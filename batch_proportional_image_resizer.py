# MIT License
# Copyright (c) 2026 pandipper
#
# 批量图片等比例缩放工具（batch-proportional-image-resizer）
# 单文件 GUI：step1 规范素材尺寸 + step2 半自动逐图裁剪，合并为同一工具。
# 依赖：Pillow（pip install pillow）。tkinter 为 Windows 官方 Python 自带标准库。
#
# 工作目录固定在 exe 同目录，自动创建两个文件夹：
#   规范素材图/    —— step1 输出 & step2 唯一输入源
#   修改后成图/    —— step2 导出目标
#   规范素材图/返工/      —— 1 键搬运「上一张」的来源
#   修改后成图/精修/      —— 3 键搬运「上一张」的结果

import os
import sys
import json
import shutil
import math
import webbrowser

from PIL import Image, ImageDraw

# ---- 重采样兼容垫片（Pillow 10+ 改用 Resampling，旧版用 Image.LANCZOS）----
try:
    _RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    _RESAMPLE = Image.LANCZOS

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

DEFAULT_TIERS = {
    "large": {"w": 2560, "h": 1440, "label": "大档"},
    "small": {"w": 1280, "h": 720,  "label": "小档"},
}

DEFAULT_CONFIG = {
    "active_tier": "large",
    "ratio_lock": True,
    "ratio": [16, 9],
    "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
}


# ===================== 主题 / 皮肤 =====================
# THEME_ON = False 时为「纯工具风」（默认），仅用 ttk.Style 染色；
#           True 时叠加参考素材库（背景图 / 裁剪框外框 / 开关皮肤）。
THEME_ON = True
ASSET_DIR = r"D:\Program Files\workbuddycn\2026-08-19-16-26-07\供参考的ui"
ASSET = {
    "bg":        os.path.join(ASSET_DIR, "ui", "button", "background.png"),   # 窗口背景（舞台/月洞门）
    "kuang":     os.path.join(ASSET_DIR, "frame", "kuang2.png"),               # 裁剪框外框（金边切角）
    "kg_on":     os.path.join(ASSET_DIR, "ui", "button", "kg_on.png"),         # 开关 on
    "kg_off":    os.path.join(ASSET_DIR, "ui", "button", "kg_off.png"),        # 开关 off
}

# 设计 Token（与 spec 第 5 节一致；ttk.Style 在 App._apply_theme 应用）
THEME = {
    "PRIMARY":   "#185FA5",
    "PRIMARY_H": "#0C447C",
    "BG":        "#FFFFFF",
    "SURFACE":   "#F4EFE6",   # 暖米色，与金边/木纹素材调子搭
    "BORDER":    "#C9BFA8",
    "TEXT":      "#2C2C2A",
    "MUTED":     "#6B665A",
    "HINT":      "#9C9785",
}


# ---------------- stdout 重定向（左下角运行日志面板）----------------
class _LogRedirector:
    """把 sys.stdout / sys.stderr 重定向到只读 Text 控件。

    注意：本类定义在模块顶层，而 `import tkinter as tk` 是 main() 内的局部变量，
    模块全局作用域里查不到 `tk`。因此这里一律用字面量 "end"（tkinter 的 END 常量
    本就等于 "end"），避免 write() 触发 NameError 被静默吞掉、导致日志面板始终为空。
    """
    def __init__(self, widget):
        self._w = widget
    def write(self, s):
        try:
            w = self._w
            w.configure(state="normal")
            w.insert("end", s)
            try:  # 限制行数（>500 行删首行），避免无限增长
                n = int(w.index("end-1c").split(".")[0])
                if n > 500:
                    w.delete("1.0", "2.0")
            except Exception:
                pass
            w.see("end")
            w.configure(state="disabled")
        except Exception:
            pass  # 控件已销毁等情况静默忽略
    def flush(self):
        pass


# ===================== 纯逻辑函数（无 tkinter 依赖，可单测）=====================


def is_image(name):
    return name.lower().endswith(IMG_EXTS)


def load_config(path):
    """读取 config.json；缺失或损坏时回退默认。"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("active_tier", "large")
            cfg.setdefault("ratio_lock", True)
            cfg.setdefault("ratio", [16, 9])
            t = cfg.get("tiers", {})
            for k in ("large", "small"):
                if k in t and "w" in t[k] and "h" in t[k]:
                    DEFAULT_TIERS[k]["w"] = int(t[k]["w"])
                    DEFAULT_TIERS[k]["h"] = int(t[k]["h"])
            if cfg.get("active_tier") not in DEFAULT_TIERS:
                cfg["active_tier"] = "large"
            return cfg
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def ensure_dirs(work_dir):
    """创建并返回四个工作文件夹路径。"""
    spec = os.path.join(work_dir, "规范素材图")
    out = os.path.join(work_dir, "修改后成图")
    spec_rework = os.path.join(spec, "返工")
    out_retouch = os.path.join(out, "精修")
    for d in (spec, out, spec_rework, out_retouch):
        os.makedirs(d, exist_ok=True)
    return {
        "spec": spec,
        "out": out,
        "spec_rework": spec_rework,
        "out_retouch": out_retouch,
    }


def list_source_images(folder):
    """列出文件夹内（顶层）所有图片文件名。"""
    try:
        return sorted(n for n in os.listdir(folder) if is_image(n))
    except OSError:
        return []


def step1_target_size(iw, ih, tiers=None, min_width=1280, max_width=2560):
    """step1 归一化（COVER 覆盖式）：把原图缩放到「覆盖 large 档 16:9 裁框」，
    保留原比例、不裁切，输出完整缩放图（溢出部分留在规范素材图里，供 step2 平移取景）。

    效果（满足「宽或高有一边与裁框贴边、最大限度保留原画面」）：
      scale = max(large.w/iw, large.h/ih)
        scale > 1：原图放大到至少 large 档（小图不会过小）
        scale < 1：原图缩小到至多 large 档（大图不会过大）
        scale == 1：原尺寸不动
      缩放后必有一边 == large 档对应边（与 16:9 裁框贴边），另一边 >=（溢出），
      因此 step2 的 16:9 裁框始终有平移/取景空间，且原画面被完整保留。
    返回 (w, h)（保持原图比例）。
    """
    if iw <= 0 or ih <= 0:
        return (max(1, iw), max(1, ih))
    large = (tiers or {}).get("large") or {"w": max_width, "h": int(max_width * 9 / 16)}
    lw, lh = large["w"], large["h"]
    scale = max(lw / iw, lh / ih)   # COVER：limiting 维度贴边 large 档，另一维溢出
    w = max(1, int(round(iw * scale)))
    h = max(1, int(round(ih * scale)))
    return (w, h)


def process_step1(source_paths, out_dir, quality=90, on_progress=None, tiers=None, min_width=1280):
    """对一组源图执行 step1，结果写入 out_dir（同名覆盖）。返回 (成功数, 跳过数)。"""
    ok = 0
    skip = 0
    total = len(source_paths)
    for i, src in enumerate(source_paths, 1):
        if on_progress:
            on_progress(i, total, src)
        if not is_image(src):
            skip += 1
            continue
        try:
            with Image.open(src) as im:
                im = im.convert("RGB")
                tgt = step1_target_size(*im.size, tiers=tiers, min_width=min_width)
                out = im.resize(tgt, _RESAMPLE)
                base = os.path.splitext(os.path.basename(src))[0] + ".jpg"
                out.save(os.path.join(out_dir, base), "JPEG", quality=quality)
            ok += 1
        except Exception:
            skip += 1
    return ok, skip


# 自动选档逻辑已移除：大档/小档改为手动单选（见 App._set_tier_active）。



def cover_scale(iw, ih, bw, bh):
    """COVER 缩放：保证缩放后两维均 >= 框。"""
    return max(bw / iw, bh / ih) if (iw > 0 and ih > 0) else 1.0


def anchor_to_box(fx, fy, iw, ih, bw, bh):
    """由锚点相对比例 (fx,fy) 在图上放置 bw×bh 的框，越界则回中心。"""
    cx, cy = fx * iw, fy * ih
    x0 = cx - bw / 2.0
    y0 = cy - bh / 2.0
    x1 = x0 + bw
    y1 = y0 + bh
    if x0 < 0 or y0 < 0 or x1 > iw or y1 > ih:
        # 回图像中心
        cx, cy = iw / 2.0, ih / 2.0
        x0 = cx - bw / 2.0
        y0 = cy - bh / 2.0
        x1 = x0 + bw
        y1 = y0 + bh
        fx, fy = 0.5, 0.5
    return (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))), (fx, fy)


def crop_for_tier(img, bw, bh, fx, fy):
    """套装开：COVER 缩放图至框，再于锚点中心裁出 bw×bh（输出恰为该尺寸）。"""
    iw, ih = img.size
    scale = cover_scale(iw, ih, bw, bh)
    sw = max(1, round(iw * scale))
    sh = max(1, round(ih * scale))
    scaled = img.resize((sw, sh), _RESAMPLE)
    cx, cy = fx * sw, fy * sh
    x0 = int(round(cx - bw / 2.0))
    y0 = int(round(cy - bh / 2.0))
    x0 = max(0, min(x0, sw - bw))
    y0 = max(0, min(y0, sh - bh))
    out = scaled.crop((x0, y0, x0 + bw, y0 + bh))
    if out.size != (bw, bh):
        out = out.resize((bw, bh), _RESAMPLE)
    return out


def crop_free(img, box):
    """套装关：自由裁切框与图的交集，不做任何判断。"""
    iw, ih = img.size
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(iw, x1)
    y1 = min(ih, y1)
    return img.crop((x0, y0, x1, y1))


# ===================== GUI（tkinter，仅在 main 内导入）=====================


def main():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from PIL import ImageTk

    APP_TITLE = "批量图片等比例缩放工具"

    class App:
        def __init__(self, root):
            self.root = root
            self.root.title(APP_TITLE)
            self.root.geometry("1200x780")

            self.work_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            self.config_path = os.path.join(self.work_dir, "config.json")
            self.cfg = load_config(self.config_path)
            self.dirs = ensure_dirs(self.work_dir)

            self.source_paths = []          # 任意位置源图（导入列表，独立于队列）
            self.queue = []                 # 规范素材图 顶层图片文件名
            self.idx = 0                    # 当前队列下标
            self.img = None                 # 当前 PIL 图（含变换）
            self.img_name = None
            self.box = (0, 0, 0, 0)         # 图像坐标裁剪框
            self.last_anchor = (0.5, 0.5)
            r = self.cfg.get("ratio", [16, 9])
            self.ratio_w = tk.IntVar(value=int(r[0]))
            self.ratio_h = tk.IntVar(value=int(r[1]))
            self.active_tier = self.cfg.get("active_tier", "large")   # 当前生效档（大档/小档，单选）
            self.ratio_lock = self.cfg.get("ratio_lock", True)        # 纵横比联动：四值保持同一比例
            self.prev_src = None            # 上一张：源文件路径
            self.prev_result = None         # 上一张：结果文件路径
            self.quality = tk.IntVar(value=100)
            self.out_format = tk.StringVar(value="JPEG")
            self.info_var = tk.StringVar(value="—")
            self.progress_var = tk.StringVar(value="")

            # 画布显示参数
            self.fit_scale = 1.0
            self.offx = 0
            self.offy = 0
            self.tk_img = None
            self.preview_tk = None

            # 步进箭头图标（像素级等大、左右镜像，避免 Unicode 字形一大一小）
            self._arrow_left = self._make_arrow("left")
            self._arrow_right = self._make_arrow("right")

            self._apply_theme()  # ttk.Style 必须在 _build_ui 之前配好
            self._build_ui()
            self._init_background()  # 背景图必须 _build_ui 之后（pack 子控件先入栈，再 lower 到最底层）
            self._refresh_queue()
            self._focus_rescan()  # 首次加载
            self.root.bind("<FocusIn>", self._on_focus_in)
            # 点击任意控件后把焦点交还画布：确保空格等快捷键可靠触发，
            # 避免焦点停在按钮上导致空格被当成「再次点击该按钮」（表现为只刷新不裁剪）
            self.root.bind("<ButtonRelease-1>", self._refocus)
            # 快捷键：焦点在输入框（Entry）时不触发，避免与数字/文字输入冲突；
            # 按钮焦点已通过 _refocus 交还画布，故此处无需排除按钮
            self.root.bind("<space>", self._kbd(self.confirm_crop))
            self.root.bind("<c>", self._kbd(self.center_box))
            self.root.bind("1", self._kbd(self.rework_prev))
            self.root.bind("3", self._kbd(self.retouch_prev))
            # 窗口映射前画布尺寸为 0/1，首次 _draw 会跳过；映射后延迟触发一次真实重绘
            self.root.after(60, self._draw)

        # ---------------- 主题 / 皮肤 ----------------
        def _make_arrow(self, direction, size=14):
            """生成与滚动条箭头风格一致的「等大三角形」图标（透明背景 RGBA）。

            用 PIL 画像素级等大的实心三角形，左右/上下仅互为镜像 —— 彻底规避
            Unicode 字符 ◀▶ / ▲▼ 在不同字体下字形大小/视觉重量不一致导致的「一大一小」。
            direction: "left" / "right"。color 默认取主题 TEXT 色。
            """
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            fg = THEME["TEXT"]
            r, g, b = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
            m = 3  # 边距，避免顶到按钮边缘
            c = (size - 1) // 2  # 中轴
            if direction == "left":
                pts = [(size - 1 - m, m), (size - 1 - m, size - 1 - m), (m, c)]
            elif direction == "right":
                pts = [(m, m), (m, size - 1 - m), (size - 1 - m, c)]
            else:
                raise ValueError(direction)
            d.polygon(pts, fill=(r, g, b, 255))
            return ImageTk.PhotoImage(img)

        def _apply_theme(self):
            """ttk.Style 套用 Token（必须在 _build_ui 之前调用）。"""
            try:
                style = ttk.Style(self.root)
                try:
                    style.theme_use("clam")  # 跨平台可预测的样式基底
                except tk.TclError:
                    pass
                T = THEME
                style.configure(".", font=("Segoe UI", 10))
                style.configure("TFrame", background=T["SURFACE"])
                style.configure("Card.TFrame", background=T["BG"])
                style.configure("TLabel", background=T["SURFACE"], foreground=T["TEXT"])
                style.configure("Card.TLabel", background=T["BG"], foreground=T["TEXT"])
                style.configure("Muted.TLabel", background=T["SURFACE"], foreground=T["MUTED"])
                style.configure("Hint.TLabel", background=T["SURFACE"], foreground=T["HINT"])
                # Primary：实心主色
                style.configure("Primary.TButton", background=T["PRIMARY"], foreground="white",
                                borderwidth=0, padding=(14, 6))
                style.map("Primary.TButton",
                          background=[("active", T["PRIMARY_H"]), ("hover", T["PRIMARY_H"])])
                # Secondary：描边
                style.configure("Secondary.TButton", background=T["SURFACE"], foreground=T["TEXT"],
                                borderwidth=1, padding=(8, 4))
                style.map("Secondary.TButton", background=[("active", T["BG"])])
                # Stepper：夹逼范围步进箭头（◀ ▶），无方框感，参照默认滚动条箭头
                # borderwidth=0、padding 小，只露箭头字符；hover 时给一点底色
                style.configure("Stepper.TButton",
                                background=T["SURFACE"],
                                foreground=T["TEXT"],
                                borderwidth=0,
                                relief="flat",
                                padding=(4, 2))
                style.map("Stepper.TButton",
                          background=[("active", T["BG"]), ("pressed", T["BG"])],
                          foreground=[("active", T["PRIMARY"]), ("pressed", T["PRIMARY"])])
                # Ghost：文字按钮
                style.configure("Ghost.TButton", background=T["SURFACE"], foreground=T["PRIMARY"],
                                borderwidth=0, padding=(4, 2))
                # 焦点环
                try:
                    style.configure("TButton", focuscolor=T["PRIMARY"])
                except tk.TclError:
                    pass
            except Exception:
                pass  # 主题失败不影响功能

        def _init_background(self):
            """THEME_ON 时在 root 铺一张缩放后的背景图（必须在 _build_ui 之后调用，
            使 pack 子控件先入栈，place 的背景再 lower 到最底层）。"""
            self._bg_label = None
            self._bg_image = None
            if not THEME_ON:
                return
            if not os.path.isfile(ASSET["bg"]):
                return
            try:
                from PIL import Image
                self._bg_full = Image.open(ASSET["bg"])
                self._bg_label = tk.Label(self.root, bd=0, highlightthickness=0, borderwidth=0)
                self._bg_label.place(x=0, y=0, relwidth=1, relheight=1)
                self._bg_label.lower()
                self._draw_bg()
                self._bg_label.bind("<Configure>", lambda e: self._draw_bg())
            except Exception:
                self._bg_label = None

        def _draw_bg(self):
            if not getattr(self, "_bg_label", None) or not getattr(self, "_bg_full", None):
                return
            try:
                from PIL import ImageTk
                w = max(1, self._bg_label.winfo_width())
                h = max(1, self._bg_label.winfo_height())
                if w < 2 or h < 2:
                    return
                # 保持比例 cover 缩放
                src_w, src_h = self._bg_full.size
                scale = max(w / src_w, h / src_h)
                nw, nh = max(1, int(src_w * scale)), max(1, int(src_h * scale))
                bg = self._bg_full.resize((nw, nh), _RESAMPLE)
                # 居中裁
                x0 = (nw - w) // 2
                y0 = (nh - h) // 2
                bg = bg.crop((x0, y0, x0 + w, y0 + h))
                self._bg_image = ImageTk.PhotoImage(bg)
                self._bg_label.configure(image=self._bg_image)
            except Exception:
                pass

        def _kuang_underlay(self, x0, y0, x1, y1):
            """THEME_ON 时在裁剪框底层画一张半透明 kuang2，作为装饰外框。"""
            if not THEME_ON or not os.path.isfile(ASSET["kuang"]):
                return
            try:
                from PIL import Image
                w, h = max(2, x1 - x0), max(2, y1 - y0)
                if w < 4 or h < 4:
                    return
                kuang = Image.open(ASSET["kuang"]).convert("RGBA")
                # 缩放并半透明
                kuang = kuang.resize((w, h), _RESAMPLE)
                # 降低 alpha（叠加而非遮挡）
                r, g, b, a = kuang.split()
                a = a.point(lambda p: int(p * 0.55))
                kuang = Image.merge("RGBA", (r, g, b, a))
                from PIL import ImageTk
                self._kuang_tk = ImageTk.PhotoImage(kuang)
                # 用 tag 区分，_draw 起手会 delete("all")
                self.canvas.create_image(x0, y0, image=self._kuang_tk, anchor="nw", tag="kuang")
            except Exception:
                pass

        # ---------------- 快捷键焦点感知 ----------------
        def _kbd(self, action):
            def handler(event):
                fw = self.root.focus_get()
                if isinstance(fw, (tk.Entry, ttk.Entry, ttk.Spinbox, tk.Button, ttk.Button)):
                    return  # 正在输入或按钮聚焦 → 不触发全局快捷键
                action()
            return handler

        # ---------------- 焦点管理 ----------------
        def _on_focus_in(self, event):
            # 仅在窗口本身获得焦点时（如从其他程序切回）才重扫，
            # 避免内部焦点切换（点按钮/列表）误触发重绘假象
            if event.widget is self.root:
                self._focus_rescan()

        def _refocus(self, event=None):
            # 点击按钮后把焦点交还画布，保证后续空格/1/3 快捷键可靠触发裁剪
            w = getattr(event, "widget", None) if event is not None else None
            if isinstance(w, (tk.Entry, ttk.Entry, ttk.Spinbox, tk.Listbox)):
                return  # 正在文字输入或选择列表时不抢焦点
            try:
                self.canvas.focus_set()
            except Exception:
                pass

        # ---------------- UI（新布局：顶栏动作 + 左可滚动竖列 + 中画布）----------------
        def _build_ui(self):
            # 顶部工具栏：左组=导入/规范，右组=裁剪操作
            top = ttk.Frame(self.root)
            top.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
            ttk.Button(top, text="规范素材尺寸", style="Primary.TButton", command=self.run_step1).pack(side=tk.LEFT, padx=(2, 8))
            ttk.Button(top, text="规范素材图路径", style="Secondary.TButton", command=lambda: self._open(self.dirs["spec"])).pack(side=tk.LEFT, padx=2)
            ttk.Button(top, text="导出文件夹路径", style="Secondary.TButton", command=lambda: self._open(self.dirs["out"])).pack(side=tk.LEFT, padx=2)
            ttk.Separator(top, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=10)
            ttk.Button(top, text="确认裁剪", style="Primary.TButton", command=self.confirm_crop).pack(side=tk.LEFT, padx=(2, 8))
            ttk.Button(top, text="返工", style="Secondary.TButton", command=self.rework_prev).pack(side=tk.LEFT, padx=2)
            ttk.Button(top, text="精修", style="Secondary.TButton", command=self.retouch_prev).pack(side=tk.LEFT, padx=2)

            # 中部：左可滚动竖列 + 中画布（右栏已废除）
            mid = ttk.Frame(self.root)
            mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=4)

            # ---- 左栏：整体可滚动的竖列（内容未超出高度时自动隐藏滚动条）----
            self._scroll_visible = True
            self.left_canvas = tk.Canvas(mid, width=330, bg=THEME["SURFACE"], highlightthickness=0)
            self.left_scroll = ttk.Scrollbar(mid, orient="vertical", command=self.left_canvas.yview)
            self.left_canvas.configure(yscrollcommand=self.left_scroll.set)
            self.left_canvas.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 0))
            self.left_scroll.pack(side=tk.LEFT, fill=tk.Y)
            self.left_content = ttk.Frame(self.left_canvas)
            # 让内容窗口填满画布宽度，消除右侧空白；width 随画布保持一致
            self._left_win = self.left_canvas.create_window((0, 0), window=self.left_content, anchor="nw", width=330)

            def _sync_left(e=None):
                self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))
                # 内容高度未超出画布时隐藏滚动条，避免多余的「上下滚动条」
                total = self.left_canvas.bbox("all")
                vis = bool(total) and (total[3] - total[1]) > self.left_canvas.winfo_height()
                if vis != self._scroll_visible:
                    self._scroll_visible = vis
                    if vis:
                        self.left_scroll.pack(side=tk.LEFT, fill=tk.Y)
                    else:
                        self.left_scroll.pack_forget()

            self.left_content.bind("<Configure>", _sync_left)
            self.left_canvas.bind("<Configure>", _sync_left)
            self.left_canvas.bind("<MouseWheel>", lambda e: self.left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

            # 导入 / 规范
            imp = ttk.LabelFrame(self.left_content, text="导入 / 规范素材")
            imp.pack(fill=tk.X, pady=(2, 6))
            ib = ttk.Frame(imp)
            ib.pack(fill=tk.X, padx=4, pady=2)
            ttk.Button(ib, text="导入文件夹", style="Primary.TButton", command=self.import_folder).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
            ttk.Button(ib, text="导入文件", style="Secondary.TButton", command=self.import_files).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

            # 素材队列
            ttk.Label(self.left_content, text="素材队列", anchor="w").pack(fill=tk.X, pady=(2, 3))
            # 素材队列：Listbox + 专用 Scrollbar（项数 > height 时始终可见）
            qf = ttk.Frame(self.left_content)
            qf.pack(fill=tk.X, pady=(0, 3))
            self.queue_list = tk.Listbox(qf, exportselection=False, height=8)
            self.queue_sb = ttk.Scrollbar(qf, orient="vertical", command=self.queue_list.yview)
            self.queue_list.configure(yscrollcommand=self.queue_sb.set)
            self.queue_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.queue_sb.pack(side=tk.LEFT, fill=tk.Y)
            self.queue_list.bind("<<ListboxSelect>>", self._on_queue_select)
            obtn = ttk.Frame(self.left_content)
            obtn.pack(fill=tk.X, pady=2)
            ttk.Button(obtn, text="↑", style="Secondary.TButton", width=2, command=self.move_up).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
            ttk.Button(obtn, text="↓", style="Secondary.TButton", width=2, command=self.move_down).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

            # 预览（固定高度窗口：图 fit/letterbox 进窗口，下方控件不再随图高抖动）
            ttk.Label(self.left_content, text="预览", anchor="w").pack(fill=tk.X, pady=(6, 2))
            self.preview_box = tk.Frame(self.left_content, width=300, height=150,
                                        bg=THEME["BG"], relief="groove", borderwidth=1)
            self.preview_box.pack(pady=2)
            self.preview_box.pack_propagate(False)  # 关键：禁止子 Label 撑大父框架 → 预览区高度恒定
            self.preview = ttk.Label(self.preview_box)
            self.preview.place(relx=0.5, rely=0.5, anchor="center")  # 图居中 letterbox 显示

            # 夹逼范围（分组标题，无开关）→ 纵横比 / 大档 / 小档 三行
            ttk.Label(self.left_content, text="夹逼范围", anchor="w", style="Muted.TLabel").pack(fill=tk.X, pady=(6, 2))
            self._build_ratio_tier_controls()

            # 旋转（单行图标按钮，无中文，仅此行为横排图标）
            grid = ttk.Frame(self.left_content)
            grid.pack(fill=tk.X, pady=(8, 3))
            for i, (glyph, cmd) in enumerate((
                ("↺", lambda: self.rotate(90)),
                ("⇋", self.mirror),
                ("⊙", self.center_box),
                ("↻", lambda: self.rotate(-90)),
            )):
                ttk.Button(grid, text=glyph, style="Secondary.TButton", width=3, command=cmd).grid(row=0, column=i, sticky="nsew", padx=2)
                grid.columnconfigure(i, weight=1)

            # 格式 / 质量
            fmt = ttk.Frame(self.left_content)
            fmt.pack(fill=tk.X, pady=(8, 3))
            ttk.Label(fmt, text="格式").pack(side=tk.LEFT)
            ttk.OptionMenu(fmt, self.out_format, "JPEG", "JPEG", "PNG").pack(side=tk.LEFT, padx=2)
            ttk.Label(fmt, text="质量").pack(side=tk.LEFT, padx=(8, 0))
            qf = ttk.Frame(fmt)
            qf.pack(side=tk.LEFT, padx=2)
            ttk.Button(qf, image=self._arrow_left, style="Stepper.TButton", command=lambda: self._step_quality(-1)).pack(side=tk.LEFT)
            ttk.Label(qf, textvariable=self.quality, width=3, anchor="center").pack(side=tk.LEFT, padx=2)
            ttk.Button(qf, image=self._arrow_right, style="Stepper.TButton", command=lambda: self._step_quality(1)).pack(side=tk.LEFT)

            # ---- 运行日志面板（左下角空位）----
            log_frame = ttk.LabelFrame(self.left_content, text="运行日志")
            log_frame.pack(fill=tk.X, padx=4, pady=(8, 4))
            log_row = ttk.Frame(log_frame)
            log_row.pack(fill=tk.X, padx=3, pady=3)
            self.log_text = tk.Text(log_row, height=6, wrap="word", state="disabled",
                                    font=("Consolas", 9), bg=THEME["BG"], fg=THEME["TEXT"],
                                    relief="flat", borderwidth=1, highlightthickness=0)
            self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            log_sb = ttk.Scrollbar(log_row, orient="vertical", command=self.log_text.yview)
            log_sb.pack(side=tk.LEFT, fill=tk.Y)
            self.log_text.configure(yscrollcommand=log_sb.set)
            ttk.Button(log_row, text="清空", style="Stepper.TButton",
                       command=self._clear_log).pack(side=tk.LEFT, padx=(2, 0))
            # 接管 stdout / stderr → 运行日志面板
            sys.stdout = _LogRedirector(self.log_text)
            sys.stderr = _LogRedirector(self.log_text)

            # ---- 中栏：画布（满宽）----
            center = ttk.Frame(mid)
            center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.canvas = tk.Canvas(center, bg="#e8e8e8", cursor="cross", takefocus=1, highlightthickness=0)
            self.canvas.pack(fill=tk.BOTH, expand=True)
            self.canvas.bind("<ButtonPress-1>", self.on_down)
            self.canvas.bind("<B1-Motion>", self.on_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_up)
            self.canvas.bind("<Configure>", self._on_canvas_configure)
            self._pending_draw = None

            # 底部：薄状态栏（无数字计数）
            bottom = ttk.Frame(self.root)
            bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=4)
            self.progress = ttk.Label(bottom, textvariable=self.progress_var, anchor="w")
            self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        # ---------------- 导入 ----------------
        def _update_import_status(self):
            """常驻计数已废弃：此调用保留为 no-op，避免改动多处调用点。"""
            return

        def import_folder(self):
            d = filedialog.askdirectory(title="选择源图片文件夹")
            if d:
                self.source_paths = [os.path.join(d, n) for n in list_source_images(d)]
                self._update_import_status()
                self.progress_var.set(f"已导入文件夹：{len(self.source_paths)} 张（源图保留在原位置）。点「规范素材尺寸」生成规范素材图。")
            if not self.queue:
                self._show_import_preview()

        def import_files(self):
            fs = filedialog.askopenfilenames(title="选择图片文件", filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp")])
            if fs:
                self.source_paths = list(fs)  # 替换当前源
                self._update_import_status()
                self.progress_var.set(f"已导入文件：{len(self.source_paths)} 张。点「规范素材尺寸」生成规范素材图。")
            if not self.queue:
                self._show_import_preview()
        def move_up(self):
            self._reorder(-1)

        def move_down(self):
            self._reorder(1)

        def _reorder(self, delta):
            lst = self.queue
            if not lst:
                return
            sel = self.queue_list.curselection()
            if not sel:
                return
            i = sel[0]
            j = i + delta
            if j < 0 or j >= len(lst):
                return
            lst[i], lst[j] = lst[j], lst[i]
            self.idx = j
            self._fill_listbox()
            try:
                self.queue_list.selection_set(j)
                self.queue_list.see(j)
            except Exception:
                pass
            self._load_current()  # 同步画布到新选中的图

        # ---------------- step1 ----------------
        def _resolve_step1_sources(self):
            """确定 step1 要处理的源图，按优先级回退，避免『点了没反应』。

            1) 已导入的源队列（self.source_paths）
            2) 素材图/ 文件夹（原图素材，按设计不改动）
            3) 规范素材图/ 自身（二次归一化，原地覆盖）
            返回 (sources_list, 来源说明文字)
            """
            if self.source_paths:
                return list(self.source_paths), "导入队列"
            cand = [os.path.join(self.dirs["spec"], n) for n in list_source_images(self.dirs["spec"])]
            if cand:
                return cand, "规范素材图（重新归一化）"
            return [], ""

        def run_step1(self):
            sources, label = self._resolve_step1_sources()
            if not sources:
                messagebox.showinfo(
                    "提示",
                    "没有可处理的图片。\n"
                    "请先点左侧「导入文件夹 / 导入文件」把图片加入导入队列，再点此按钮。")
                return
            self._step1_label = label
            self.progress_var.set(f"规范素材尺寸：处理「{label}」共 {len(sources)} 张…")
            self.root.config(cursor="watch")
            import threading

            def worker():
                def cb(i, total, src):
                    self.root.after(0, lambda: self.progress_var.set(f"规范素材尺寸 {i}/{total}（来源：{label}）"))
                try:
                    ok, skip = process_step1(
                        sources, self.dirs["spec"],
                        quality=self.quality.get(), on_progress=cb,
                        tiers=self.cfg["tiers"])
                    lw = self.cfg["tiers"]["large"]
                    self.root.after(0, lambda: self.progress_var.set(
                        f"规范素材尺寸完成：成功 {ok}，跳过 {skip}；"
                        f"按 large 档 {lw['w']}x{lw['h']} 覆盖缩放（一边贴边、溢出供取景），原比例不变"))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
                finally:
                    self.root.after(0, self._after_step1)

            threading.Thread(target=worker, daemon=True).start()

        def _after_step1(self):
            self.root.config(cursor="")
            # 这批导入源已处理为规范素材图，清空导入列表并刷新状态
            self.source_paths = []
            self._update_import_status()
            self._refresh_queue()
            self.idx = 0
            self._load_current()

        # ---------------- 队列 / 刷新 ----------------
        def _refresh_queue(self):
            # 队列显示规范素材图下所有图片（包括已导出过的），方便随时回头取景再裁。
            # （原版排除 out/ 已导出项，结果全部已裁完后队列变空、画布卡灰，用户体验差）
            files = list_source_images(self.dirs["spec"])
            self.queue = list(files)
            self._fill_listbox()

        def _fill_listbox(self):
            if not hasattr(self, "queue_list"):
                return
            self.queue_list.delete(0, tk.END)
            self._update_import_status()  # 刷新单行状态（队列 X/Y）
            for f in self.queue:
                self.queue_list.insert(tk.END, f)

        def _on_queue_select(self, event):
            sel = self.queue_list.curselection()
            if not sel:
                return
            i = sel[0]
            if i == self.idx and self.img is not None:
                return
            self.idx = i
            self._load_current()

        def _clear_log(self):
            """清空运行日志面板。"""
            try:
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", tk.END)
                self.log_text.configure(state="disabled")
            except Exception:
                pass

        def _focus_rescan(self):
            prev_name = self.img_name
            self._refresh_queue()
            if not self.queue:
                self.img = None
                self.img_name = None
                self._clear_canvas()
                self.info_var.set("队列为空：请先「规范素材尺寸」或导入图片。")
                return
            # 若当前图仍在队列，保持；否则回到队首
            if prev_name in self.queue:
                self.idx = self.queue.index(prev_name)
            else:
                self.idx = 0
            self._load_current()

        # ---------------- 加载/绘制 ----------------
        def _load_current(self):
            if not self.queue:
                self._clear_canvas()
                self.info_var.set("素材队列为空：请先导入图片并点「规范素材尺寸」生成规范素材图，或在下方队列出现后再裁剪。")
                return
            self.idx = max(0, min(self.idx, len(self.queue) - 1))
            name = self.queue[self.idx]
            path = os.path.join(self.dirs["spec"], name)
            try:
                with Image.open(path) as im:
                    self.img = im.convert("RGB")
            except Exception as e:
                messagebox.showerror("无法打开", f"{name}\n{e}")
                return
            self.img_name = name
            self._place_box_default()
            self._draw()
            self._render_preview()
            # 布局可能尚未完成（如 step1 后台线程刚回主线程），延迟再重绘一次确保画布不卡灰色
            self.root.after(40, self._draw)
            self.info_var.set(f"[{self.idx+1}/{len(self.queue)}] {name}  {self.img.size[0]}×{self.img.size[1]}")
            # 同步队列列表高亮
            if hasattr(self, "queue_list"):
                try:
                    self.queue_list.selection_clear(0, tk.END)
                    self.queue_list.selection_set(self.idx)
                    self.queue_list.see(self.idx)
                except Exception:
                    pass

        def _show_import_preview(self):
            """导入后队列（规范素材图）为空时，画布只读预览第一张导入源图。"""
            if not self.source_paths:
                return
            path = self.source_paths[0]
            name = os.path.basename(path)
            try:
                with Image.open(path) as im:
                    self.img = im.convert("RGB")
            except Exception as e:
                messagebox.showerror("无法打开", f"{name}\n{e}")
                return
            self.img_name = name
            self._place_box_default()
            self._draw()
            self._render_preview()
            self.info_var.set(
                f"导入预览 {name}  {self.img.size[0]}×{self.img.size[1]}  —— 点「规范素材尺寸」生成规范素材图后再裁剪")

        def _current_box_size(self):
            """当前生效档（大档/小档，手动单选）的裁剪框尺寸。"""
            t = self.cfg["tiers"][self.active_tier]
            return t["w"], t["h"]

        def _place_box_default(self):
            if self.img is None:
                return
            bw, bh = self._current_box_size()
            iw, ih = self.img.size
            # 先按锚点放置（默认居中）；素材比档位小时，夹为图像内「贴边的夹逼框」
            # （与图像同比例、居中内接），避免裁剪框超出图片范围
            box, anchor = anchor_to_box(
                self.last_anchor[0], self.last_anchor[1], iw, ih, bw, bh)
            box = self._clamp_box(box, iw, ih)
            self.box, self.last_anchor = box, anchor

        def _on_canvas_configure(self, event=None):
            """画布尺寸变化时防抖重绘，让 fit-to-window 始终填满可用空间。"""
            if self._pending_draw:
                self.root.after_cancel(self._pending_draw)
            self._pending_draw = self.root.after(120, self._draw)

        def _draw(self):
            self._pending_draw = None
            if self.img is None:
                self._clear_canvas()
                # 空态提示：让「空」变成「在等导入」，而非「坏没坏」
                try:
                    cw = self.canvas.winfo_width() or 800
                    ch = self.canvas.winfo_height() or 600
                    if cw > 2 and ch > 2:
                        self.canvas.create_text(cw // 2, ch // 2,
                                                text="导入图片后在此裁剪 · 或从资源管理器拖入",
                                                fill=THEME["HINT"], font=("Segoe UI", 13), tag="hint")
                except Exception:
                    pass
                return
            cw = self.canvas.winfo_width() or 800
            ch = self.canvas.winfo_height() or 600
            iw, ih = self.img.size
            self.fit_scale = min(cw / iw, ch / ih, 1.0) if (iw and ih) else 1.0
            dw, dh = int(iw * self.fit_scale), int(ih * self.fit_scale)
            if dw < 1 or dh < 1:
                # 画布尚未完成布局（窗口未映射/被遮挡时 winfo 尺寸为 0/1），
                # 此时无法正确缩放；延迟重试，待布局完成后再真实重绘，
                # 既避免 PIL resize 收到 0 尺寸抛 ValueError，也避免画布卡在灰色
                self.root.after(80, self._draw)
                return
            self.offx = (cw - dw) // 2
            self.offy = (ch - dh) // 2
            disp = self.img.resize((dw, dh), _RESAMPLE)
            self.tk_img = ImageTk.PhotoImage(disp)
            self.canvas.delete("all")
            self.canvas.create_image(self.offx, self.offy, image=self.tk_img, anchor="nw")
            # 裁剪框 + 九宫格（红框）
            x0 = self.offx + self.box[0] * self.fit_scale
            y0 = self.offy + self.box[1] * self.fit_scale
            x1 = self.offx + self.box[2] * self.fit_scale
            y1 = self.offy + self.box[3] * self.fit_scale
            self._kuang_underlay(x0, y0, x1, y1)  # THEME_ON 时底层金边外框
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ff3b30", width=2, tag="ui")
            for fx in (1/3, 2/3):
                self.canvas.create_line(x0 + (x1-x0)*fx, y0, x0 + (x1-x0)*fx, y1, fill="#ff3b30", width=1, dash=(4, 3), tag="ui")
            for fy in (1/3, 2/3):
                self.canvas.create_line(x0, y0 + (y1-y0)*fy, x1, y0 + (y1-y0)*fy, fill="#ff3b30", width=1, dash=(4, 3), tag="ui")
            # 角柄
            for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                self.canvas.create_rectangle(px-4, py-4, px+4, py+4, fill="#ff3b30", tag="ui")

        def _clear_canvas(self):
            self.canvas.delete("all")
            self.tk_img = None

        def _render_preview(self):
            if self.img is None:
                self.preview.configure(image="")
                return
            bw, bh = self._current_box_size()
            fx, fy = self._box_anchor()
            out = crop_for_tier(self.img, bw, bh, fx, fy)
            pw, ph = 290, 140   # 匹配预览窗口内尺寸（300x150 减去描边），恒定不变
            out.thumbnail((pw, ph), _RESAMPLE)
            self.preview_tk = ImageTk.PhotoImage(out)
            self.preview.configure(image=self.preview_tk)

        def _box_anchor(self):
            if not self.img:
                return 0.5, 0.5
            iw, ih = self.img.size
            cx = (self.box[0] + self.box[2]) / 2.0
            cy = (self.box[1] + self.box[3]) / 2.0
            return (cx / iw) if iw else 0.5, (cy / ih) if ih else 0.5

        # ---------------- 鼠标交互 ----------------
        def _to_img(self, ex, ey):
            return (ex - self.offx) / self.fit_scale, (ey - self.offy) / self.fit_scale

        def on_down(self, event):
            if self.img is None:
                return
            ix, iy = self._to_img(event.x, event.y)
            self.drag = {"mode": None, "sx": ix, "sy": iy, "box0": self.box}
            x0, y0, x1, y1 = self.box
            # 命中角柄？
            for (px, py, corner) in ((x0, y0, "nw"), (x1, y0, "ne"), (x0, y1, "sw"), (x1, y1, "se")):
                if abs(ix - px) < 20 / self.fit_scale and abs(iy - py) < 20 / self.fit_scale:
                    self.drag["mode"] = "resize_" + corner
                    return
            if x0 <= ix <= x1 and y0 <= iy <= y1:
                self.drag["mode"] = "move"
            else:
                self.drag["mode"] = "recenter"  # 点击框外 → 以点击点为中心放置

        def on_drag(self, event):
            if not hasattr(self, "drag") or self.img is None:
                return
            ix, iy = self._to_img(event.x, event.y)
            iw, ih = self.img.size
            mode = self.drag["mode"]
            if mode == "move":
                dx = ix - self.drag["sx"]
                dy = iy - self.drag["sy"]
                x0, y0, x1, y1 = self.drag["box0"]
                w, h = x1 - x0, y1 - y0
                nx0 = x0 + dx
                ny0 = y0 + dy
                nx0 = max(0, min(nx0, iw - w))
                ny0 = max(0, min(ny0, ih - h))
                self.box = (int(nx0), int(ny0), int(nx0 + w), int(ny0 + h))
            elif mode == "recenter":
                bw, bh = self._current_box_size()
                cx, cy = max(bw/2, min(ix, iw - bw/2)), max(bh/2, min(iy, ih - bh/2))
                self.box = (int(cx - bw/2), int(cy - bh/2), int(cx + bw/2), int(cy + bh/2))
                self.last_anchor = (cx / iw, cy / ih)
            elif mode.startswith("resize"):
                bw, bh = self._current_box_size()
                # 16:9 锁定：以对角为锚，按鼠标决定宽
                x0, y0, x1, y1 = self.drag["box0"]
                if mode in ("resize_nw", "resize_se"):
                    anchor_x, anchor_y = (x1, y1) if mode == "resize_nw" else (x0, y0)
                else:
                    anchor_x, anchor_y = (x1, y0) if mode == "resize_sw" else (x0, y1)
                new_w = max(20, abs(ix - anchor_x))
                new_h = new_w * bh / bw  # 锁 16:9
                if mode in ("resize_nw", "resize_sw"):
                    nx0, ny0 = anchor_x - new_w, anchor_y - new_h
                    self.box = (int(nx0), int(ny0), int(anchor_x), int(anchor_y))
                else:
                    self.box = (int(anchor_x), int(anchor_y), int(anchor_x + new_w), int(anchor_y + new_h))
                # 越界夹边（保持尺寸）
                self.box = self._clamp_box(self.box, iw, ih)
                self.last_anchor = self._box_anchor()
            self._draw()
            self._render_preview()

        def on_up(self, event):
            self.drag = None

        def _clamp_box(self, box, iw, ih):
            x0, y0, x1, y1 = box
            w, h = x1 - x0, y1 - y0
            if w <= 0 or h <= 0:
                return (0, 0, 0, 0)
            # 严格保持固定比例：框超过图像时任选「内接」方式等比缩小，
            # 绝不分别夹宽高（否则会破坏 16:9 比例、变成覆盖全图的非 16:9 框）
            if w > iw or h > ih:
                s = min(iw / w, ih / h)          # 缩小到恰好内接于图像
                # 框比图还大时，用户意图是「拉到最大」；居中内接为图内最大 16:9 框，
                # 不再沿用原框中心（否则会贴边、出现亚像素偏移），保证拖到最大即规整覆盖全图
                cx, cy = iw / 2.0, ih / 2.0
                w, h = w * s, h * s
                x0, y0 = cx - w / 2.0, cy - h / 2.0
                x1, y1 = cx + w / 2.0, cy + h / 2.0
            x0 = max(0, min(x0, iw - w))
            y0 = max(0, min(y0, ih - h))
            return (int(round(x0)), int(round(y0)), int(round(x0 + w)), int(round(y0 + h)))

        # ---------------- 操作 ----------------
        def center_box(self):
            self.last_anchor = (0.5, 0.5)
            self._place_box_default()
            self._draw()
            self._render_preview()

        def rotate(self, deg):
            if self.img is None:
                return
            self.img = self.img.rotate(deg, expand=True, resample=_RESAMPLE)
            self.last_anchor = (0.5, 0.5)
            self._place_box_default()
            self._draw()
            self._render_preview()
            self.info_var.set(f"[{self.idx+1}/{len(self.queue)}] {self.img_name}  {self.img.size[0]}×{self.img.size[1]}")

        def mirror(self):
            if self.img is None:
                return
            self.img = self.img.transpose(Image.FLIP_LEFT_RIGHT)
            fx, fy = self.last_anchor
            self.last_anchor = (1 - fx, fy)
            self._place_box_default()
            self._draw()
            self._render_preview()

        def confirm_crop(self):
            if self.img is None or not self.img_name:
                return
            if self.img_name not in self.queue:
                self.progress_var.set("该图尚未进入素材队列（规范素材图），请先「规范素材尺寸」再裁剪。")
                return
            bw, bh = self._current_box_size()
            fx, fy = self._box_anchor()
            out = crop_for_tier(self.img, bw, bh, fx, fy)
            base = os.path.splitext(self.img_name)[0]
            fmt = self.out_format.get()
            if fmt == "PNG":
                dest = os.path.join(self.dirs["out"], base + ".png")
                out.save(dest, "PNG")
            else:
                dest = os.path.join(self.dirs["out"], base + ".jpg")
                out.save(dest, "JPEG", quality=self.quality.get())
            # 记录上一张（源 + 结果）
            self.prev_src = os.path.join(self.dirs["spec"], self.img_name)
            self.prev_result = dest
            # 从内存队列移除（文件保留，待 FocusIn 重扫时因已存在结果而跳过）
            if self.img_name in self.queue:
                self.queue.remove(self.img_name)
                try:
                    self.queue_list.delete(self.idx)
                except Exception:
                    pass
            if self.queue:
                self.idx = 0
                self._load_current()
            else:
                self.img = None
                self.img_name = None
                self._clear_canvas()
                self.info_var.set("队列已全部处理完成。")
            self.progress_var.set(f"已导出：{os.path.basename(dest)}")

        def rework_prev(self):
            if not self.prev_src or not os.path.exists(self.prev_src):
                self.progress_var.set("无上一张可返工。")
                return
            dest = os.path.join(self.dirs["spec_rework"], os.path.basename(self.prev_src))
            try:
                shutil.move(self.prev_src, dest)
                self.progress_var.set(f"已返工：{os.path.basename(dest)}（移至 规范素材图/返工）")
                self.prev_src = None
            except Exception as e:
                messagebox.showerror("返工失败", str(e))

        def retouch_prev(self):
            if not self.prev_result or not os.path.exists(self.prev_result):
                self.progress_var.set("无上一张可精修。")
                return
            dest = os.path.join(self.dirs["out_retouch"], os.path.basename(self.prev_result))
            try:
                shutil.move(self.prev_result, dest)
                self.progress_var.set(f"已精修：{os.path.basename(dest)}（移至 修改后成图/精修）")
                self.prev_result = None
            except Exception as e:
                messagebox.showerror("精修失败", str(e))

        # ---------------- 纵横比 / 档位（夹逼范围）----------------
        def _build_ratio_tier_controls(self):
            lc = self.left_content
            # 纵横比（行首开关 + 宽:高 步进）
            rrow = ttk.Frame(lc)
            rrow.pack(fill=tk.X, pady=3)
            self.ratio_btn = self._make_header_btn(rrow, "纵横比", self.toggle_ratio_lock, self._is_ratio_on)
            self.ratio_btn.pack(side=tk.LEFT)
            self._ratio_steppers = ttk.Frame(rrow)
            self._ratio_steppers.pack(side=tk.LEFT, padx=(4, 0))
            wf = self._make_stepper(self._ratio_steppers, self.ratio_w, 1, 3, self._on_ratio_changed)
            wf.pack(side=tk.LEFT)
            ttk.Label(self._ratio_steppers, text=":").pack(side=tk.LEFT, padx=1)
            hf = self._make_stepper(self._ratio_steppers, self.ratio_h, 1, 3, self._on_ratio_changed)
            hf.pack(side=tk.LEFT)
            self.ratio_entries = [wf._entry, hf._entry]

            # 大档 / 小档（行首单选 + 宽×高 步进）
            self.tier_vars = {}
            self.tier_btns = {}
            self.tier_h_entries = {}
            for key in ("large", "small"):
                t = self.cfg["tiers"][key]
                row = ttk.Frame(lc)
                row.pack(fill=tk.X, pady=3)
                btn = self._make_header_btn(row, t["label"], lambda k=key: self._set_tier_active(k), lambda k=key: self.active_tier == k)
                btn.pack(side=tk.LEFT)
                self.tier_btns[key] = btn
                svars = {}
                wf = self._make_stepper(row, tk.IntVar(value=t["w"]), 1, 4, (lambda k=key: self._on_tier_changed(k, "w")))
                wf.pack(side=tk.LEFT, padx=(4, 0))
                svars["w"] = wf._var
                ttk.Label(row, text="×").pack(side=tk.LEFT, padx=1)
                hf = self._make_stepper(row, tk.IntVar(value=t["h"]), 1, 4, (lambda k=key: self._on_tier_changed(k, "h")))
                hf.pack(side=tk.LEFT, padx=(1, 0))
                svars["h"] = hf._var
                self.tier_vars[key] = svars
                self.tier_h_entries[key] = hf._entry
            self._refresh_headers()

        def _make_header_btn(self, parent, text, command, state_getter):
            """行首开关按钮：点击切换状态（纵横比=开/关，档位=选中/未选）。"""
            b = ttk.Button(parent, text=text, style="Secondary.TButton", command=command)
            b._base = text
            b._state_getter = state_getter
            return b

        def _is_ratio_on(self):
            return self.ratio_lock

        def _make_stepper(self, parent, var, step, width, on_step=None):
            """[-][Entry][+] 步进器：单次 ±step，可连点；Entry 可手填。"""
            f = ttk.Frame(parent)
            f._var = var
            ttk.Button(f, image=self._arrow_left, style="Stepper.TButton",
                       command=lambda: self._step_var(var, -step, on_step)).pack(side=tk.LEFT)
            e = ttk.Entry(f, textvariable=var, width=width, justify="center")
            e.pack(side=tk.LEFT, padx=1)
            ttk.Button(f, image=self._arrow_right, style="Stepper.TButton",
                       command=lambda: self._step_var(var, step, on_step)).pack(side=tk.LEFT)
            f._entry = e
            if on_step:
                e.bind("<KeyRelease>", lambda ev: on_step())
                e.bind("<FocusOut>", lambda ev: on_step())
            return f

        def _step_var(self, var, delta, on_step):
            try:
                v = max(1, int(var.get()) + delta)
                var.set(v)
            except Exception:
                pass
            if on_step:
                on_step()

        def _step_quality(self, d):
            self.quality.set(max(10, min(100, self.quality.get() + d)))

        def _on_ratio_changed(self):
            """纵横比 宽:高 改变 → 以宽为准，两档 h = round(w/ratio) 保持同比例。"""
            try:
                rw = max(1, int(self.ratio_w.get()))
                rh = max(1, int(self.ratio_h.get()))
            except Exception:
                return
            ratio = rw / rh
            for k in ("large", "small"):
                w = int(self.tier_vars[k]["w"].get())
                h = max(1, round(w / ratio))
                self.tier_vars[k]["h"].set(h)
                self.cfg["tiers"][k]["w"] = w
                self.cfg["tiers"][k]["h"] = h
            self.cfg["ratio"] = [rw, rh]
            self._save_cfg()
            if self.img is None:
                return
            self._place_box_default()
            self._draw()
            self._render_preview()

        def _on_tier_changed(self, key, dim):
            """某档宽或高被改：写回配置；锁定时改宽联动 h；当前档实时刷新裁剪框。"""
            try:
                v = max(1, int(self.tier_vars[key][dim].get()))
            except Exception:
                return
            self.cfg["tiers"][key][dim] = v
            if self.ratio_lock and dim == "w":
                ratio = int(self.ratio_w.get()) / max(1, int(self.ratio_h.get()))
                h = max(1, round(v / ratio))
                self.tier_vars[key]["h"].set(h)
                self.cfg["tiers"][key]["h"] = h
            self._save_cfg()
            if key == self.active_tier and self.img is not None:
                self._place_box_default()
                self._draw()
                self._render_preview()

        def _set_tier_active(self, key):
            """单选生效档：点大档/小档之一即生效，裁剪框立即用该档尺寸。"""
            if key not in self.cfg["tiers"]:
                return
            self.active_tier = key
            self._save_cfg()
            self._refresh_headers()
            if self.img is not None:
                self._place_box_default()
                self._draw()
                self._render_preview()

        def toggle_ratio_lock(self):
            """纵横比开关：开→按 ratio 对齐两档 h；关→保持当前数值不动。"""
            self.ratio_lock = not self.ratio_lock
            self._save_cfg()
            self._refresh_headers()
            if self.ratio_lock:
                self._on_ratio_changed()
            else:
                if self.img is not None:
                    self._place_box_default()
                    self._draw()
                    self._render_preview()

        def _style_header(self, btn, on):
            try:
                btn.configure(style="Primary.TButton" if on else "Secondary.TButton",
                              text=("● " + btn._base) if on else btn._base)
            except Exception:
                pass

        def _refresh_headers(self):
            """刷新三个行首按钮视觉态；锁定时禁用 h 输入框与纵横比输入框。"""
            self._style_header(self.ratio_btn, self.ratio_lock)
            for e in self.ratio_entries:
                try:
                    e.configure(state="disabled" if not self.ratio_lock else "normal")
                except Exception:
                    pass
            for key, btn in self.tier_btns.items():
                self._style_header(btn, self.active_tier == key)
                try:
                    self.tier_h_entries[key].configure(state="disabled" if self.ratio_lock else "normal")
                except Exception:
                    pass

        def _save_cfg(self):
            self.cfg["active_tier"] = self.active_tier
            self.cfg["ratio_lock"] = self.ratio_lock
            self.cfg["ratio"] = [int(self.ratio_w.get()), int(self.ratio_h.get())]
            for k in ("large", "small"):
                try:
                    self.cfg["tiers"][k]["w"] = int(self.tier_vars[k]["w"].get())
                    self.cfg["tiers"][k]["h"] = int(self.tier_vars[k]["h"].get())
                except Exception:
                    pass
            save_config(self.config_path, self.cfg)

        def _open(self, path):
            try:
                webbrowser.open(os.path.abspath(path))
            except Exception:
                pass

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 启动异常不再「闪退」：写 crash.log 并弹出可读错误，便于定位
        import traceback as _tb, os as _os
        try:
            _log = _os.path.join(
                _os.path.dirname(_os.path.abspath(sys.argv[0] or ".")), "crash.log")
            with open(_log, "w", encoding="utf-8") as _f:
                _tb.print_exc(file=_f)
        except Exception:
            _log = None
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            _mb.showerror("启动失败", "启动失败，详见同目录 crash.log"
                          + (f"：\n{_log}" if _log else ""))
        except Exception:
            # tkinter 也不可用（运行环境缺 tkinter）→ 用 ctypes 弹系统消息框
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "启动失败：运行环境缺少 tkinter（请用带 tkinter 的 Python 运行，或打包为 exe）。\n详见同目录 crash.log",
                    "启动失败", 0x10)
            except Exception:
                pass
        # 防止控制台一闪而过：等待回车（从控制台启动时有效；双击无控制台则忽略）
        try:
            input("按回车退出…")
        except Exception:
            pass
