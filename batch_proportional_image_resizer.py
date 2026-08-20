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
#   规范素材图/返工/      —— q 键搬运「上一张」的来源
#   修改后成图/精修/      —— E 键搬运「上一张」的结果

import os
import sys
import json
import shutil
import math
import webbrowser

from PIL import Image

# ---- 重采样兼容垫片（Pillow 10+ 改用 Resampling，旧版用 Image.LANCZOS）----
try:
    _RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    _RESAMPLE = Image.LANCZOS

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

DEFAULT_TIERS = {
    "large":  {"w": 2560, "h": 1440, "label": "大"},
    "medium": {"w": 1920, "h": 1080, "label": "中"},
    "small":  {"w": 1280, "h": 720,  "label": "小"},
}

DEFAULT_CONFIG = {
    "suite_on": True,
    "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
}


# ===================== 纯逻辑函数（无 tkinter 依赖，可单测）=====================


def is_image(name):
    return name.lower().endswith(IMG_EXTS)


def load_config(path):
    """读取 config.json；缺失或损坏时回退默认。"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("suite_on", True)
            t = cfg.get("tiers", {})
            for k in ("large", "medium", "small"):
                if k in t and "w" in t[k] and "h" in t[k]:
                    DEFAULT_TIERS[k]["w"] = int(t[k]["w"])
                    DEFAULT_TIERS[k]["h"] = int(t[k]["h"])
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


def step1_target_size(iw, ih):
    """依源图尺寸计算 step1 归一化目标尺寸（返回 (w, h) 或 None 表示保持原图）。

    规则（与原始 adaptive_image_resizer 一致）：
      按源宽分档：>2560→2560；1920–2560→1920；1280–1920→1280
      高度兜底：计算高 <720 时强制高=720、宽按比例重算（优先于宽封顶，允许宽>2560）
      不放大保护：w<1280 且 h>=720 时保持原尺寸（返回 None）
    """
    w = iw
    if iw > 2560:
        w = 2560
    elif iw >= 1920:
        w = 1920
    elif iw >= 1280:
        w = 1280
    else:
        w = iw  # <1280，后面再判断不放大

    # 等比缩放
    if iw > 0:
        h = round(ih * (w / iw))
    else:
        h = ih

    # 高度兜底
    if h < 720:
        h = 720
        if h > 0:
            w = round(iw * (h / ih)) if ih > 0 else w

    # 不放大保护
    if iw < 1280 and ih >= 720:
        return None

    return (w, h)


def process_step1(source_paths, out_dir, quality=90, on_progress=None):
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
                tgt = step1_target_size(*im.size)
                if tgt is None:
                    out = im  # 保持原尺寸
                else:
                    out = im.resize(tgt, _RESAMPLE)
                base = os.path.splitext(os.path.basename(src))[0] + ".jpg"
                out.save(os.path.join(out_dir, base), "JPEG", quality=quality)
            ok += 1
        except Exception:
            skip += 1
    return ok, skip


def pick_tier_by_height(h, tiers):
    """套装开时按图高就近选档（绝对差最小）。"""
    best = None
    best_diff = None
    for k, v in tiers.items():
        d = abs(h - v["h"])
        if best_diff is None or d < best_diff:
            best_diff = d
            best = k
    return best


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
            self.root.geometry("1180x760")

            self.work_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            self.config_path = os.path.join(self.work_dir, "config.json")
            self.cfg = load_config(self.config_path)
            self.dirs = ensure_dirs(self.work_dir)

            self.source_paths = []          # 任意位置源图
            self.queue = []                 # 规范素材图 顶层图片文件名
            self.idx = 0                    # 当前队列下标
            self.img = None                 # 当前 PIL 图（含变换）
            self.img_name = None
            self.box = (0, 0, 0, 0)         # 图像坐标裁剪框
            self.last_anchor = (0.5, 0.5)
            self.manual_tier = None         # 用户点击预设后的覆盖档
            self.custom = {"w": 1920, "h": 1080}
            self.prev_src = None            # 上一张：源文件路径
            self.prev_result = None         # 上一张：结果文件路径
            self.quality = tk.IntVar(value=90)
            self.out_format = tk.StringVar(value="JPEG")
            self.progress_var = tk.StringVar(value="")

            # 画布显示参数
            self.fit_scale = 1.0
            self.offx = 0
            self.offy = 0
            self.tk_img = None
            self.preview_tk = None

            self._build_ui()
            self._refresh_queue()
            self._focus_rescan()  # 首次加载
            self.root.bind("<FocusIn>", lambda e: self._focus_rescan())
            self.root.bind("<space>", lambda e: self.confirm_crop())
            self.root.bind("<c>", lambda e: self.center_box())
            self.root.bind("<q>", lambda e: self.rework_prev())
            self.root.bind("<e>", lambda e: self.retouch_prev())

        # ---------------- UI ----------------
        def _build_ui(self):
            # 顶部工具栏
            top = ttk.Frame(self.root)
            top.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
            ttk.Button(top, text="导入文件夹", command=self.import_folder).pack(side=tk.LEFT, padx=2)
            ttk.Button(top, text="导入文件", command=self.import_files).pack(side=tk.LEFT, padx=2)
            ttk.Button(top, text="规范素材尺寸", command=self.run_step1).pack(side=tk.LEFT, padx=2)
            ttk.Button(top, text="规范素材图路径", command=lambda: self._open(self.dirs["spec"])).pack(side=tk.LEFT, padx=2)
            ttk.Button(top, text="导出文件夹路径", command=lambda: self._open(self.dirs["out"])).pack(side=tk.LEFT, padx=2)

            # 中部：左画布 + 右面板
            mid = ttk.Frame(self.root)
            mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=4)

            left = ttk.Frame(mid)
            left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.canvas = tk.Canvas(left, bg="#1e1e1e", cursor="cross")
            self.canvas.pack(fill=tk.BOTH, expand=True)
            self.canvas.bind("<ButtonPress-1>", self.on_down)
            self.canvas.bind("<B1-Motion>", self.on_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_up)

            right = ttk.Frame(mid, width=320)
            right.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
            right.pack_propagate(False)

            ttk.Label(right, text="结果预览", anchor="w").pack(fill=tk.X, pady=(4, 0))
            self.preview = ttk.Label(right)
            self.preview.pack(pady=2)
            self.info_var = tk.StringVar(value="—")
            ttk.Label(right, textvariable=self.info_var, anchor="w", wraplength=300).pack(fill=tk.X)

            # 套装开关 + 三档编辑
            self.suite_btn = ttk.Button(right, text="", command=self.toggle_suite)
            self.suite_btn.pack(fill=tk.X, pady=(8, 2))
            self._sync_suite_btn()

            ttk.Separator(right).pack(fill=tk.X, pady=4)
            ttk.Label(right, text="尺寸套装（可编辑）", anchor="w").pack(fill=tk.X)
            self.tier_entries = {}
            for k in ("large", "medium", "small"):
                row = ttk.Frame(right)
                row.pack(fill=tk.X, pady=1)
                t = self.cfg["tiers"][k]
                ttk.Label(row, text=t.get("label", k), width=4).pack(side=tk.LEFT)
                ew = ttk.Entry(row, width=7)
                eh = ttk.Entry(row, width=7)
                ew.insert(0, str(t["w"]))
                eh.insert(0, str(t["h"]))
                ew.pack(side=tk.LEFT, padx=2)
                eh.pack(side=tk.LEFT, padx=2)
                self.tier_entries[k] = (ew, eh)
                ttk.Button(row, text=f"用{k}", command=lambda kk=k: self.set_tier(kk)).pack(side=tk.LEFT, padx=2)

            ttk.Separator(right).pack(fill=tk.X, pady=4)
            ttk.Label(right, text="自定义尺寸（套装关时生效）", anchor="w").pack(fill=tk.X)
            crow = ttk.Frame(right)
            crow.pack(fill=tk.X, pady=1)
            self.cw = ttk.Entry(crow, width=7)
            self.ch = ttk.Entry(crow, width=7)
            self.cw.insert(0, "1920")
            self.ch.insert(0, "1080")
            self.cw.pack(side=tk.LEFT, padx=2)
            self.ch.pack(side=tk.LEFT, padx=2)
            ttk.Button(crow, text="设为框", command=self.apply_custom).pack(side=tk.LEFT, padx=2)

            # 变换 + 操作
            ttk.Separator(right).pack(fill=tk.X, pady=4)
            ttk.Button(right, text="↺ 左转90°", command=lambda: self.rotate(90)).pack(fill=tk.X, pady=1)
            ttk.Button(right, text="↻ 右转90°", command=lambda: self.rotate(-90)).pack(fill=tk.X, pady=1)
            ttk.Button(right, text="⇋ 镜像", command=self.mirror).pack(fill=tk.X, pady=1)
            ttk.Button(right, text="居中 (C)", command=self.center_box).pack(fill=tk.X, pady=1)

            fmt = ttk.Frame(right)
            fmt.pack(fill=tk.X, pady=(6, 0))
            ttk.Label(fmt, text="格式").pack(side=tk.LEFT)
            ttk.OptionMenu(fmt, self.out_format, "JPEG", "JPEG", "PNG").pack(side=tk.LEFT, padx=2)
            ttk.Label(fmt, text="质量").pack(side=tk.LEFT, padx=(6, 0))
            ttk.Spinbox(fmt, from_=10, to=100, textvariable=self.quality, width=5).pack(side=tk.LEFT, padx=2)

            # 底部状态栏 + 操作按钮
            bottom = ttk.Frame(self.root)
            bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=4)
            ttk.Button(bottom, text="确认裁剪 (空格)", command=self.confirm_crop).pack(side=tk.LEFT, padx=2)
            ttk.Button(bottom, text="返工 (q)", command=self.rework_prev).pack(side=tk.LEFT, padx=2)
            ttk.Button(bottom, text="精修 (E)", command=self.retouch_prev).pack(side=tk.LEFT, padx=2)
            self.progress = ttk.Label(bottom, textvariable=self.progress_var, anchor="w")
            self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        # ---------------- 导入 ----------------
        def import_folder(self):
            d = filedialog.askdirectory(title="选择源图片文件夹")
            if d:
                self.source_paths = [os.path.join(d, n) for n in list_source_images(d)]
                self.progress_var.set(f"已导入文件夹：{len(self.source_paths)} 张（源图保留在原位置）")

        def import_files(self):
            fs = filedialog.askopenfilenames(title="选择图片文件", filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp")])
            if fs:
                self.source_paths = list(fs)  # 替换当前源
                self.progress_var.set(f"已导入文件：{len(self.source_paths)} 张")

        # ---------------- step1 ----------------
        def run_step1(self):
            if not self.source_paths:
                messagebox.showinfo("提示", "请先导入图片（文件夹或文件）。")
                return
            self.progress_var.set("规范素材尺寸：准备中…")
            self.root.config(cursor="watch")
            import threading

            def worker():
                def cb(i, total, src):
                    self.root.after(0, lambda: self.progress_var.set(f"规范素材尺寸 {i}/{total}"))
                try:
                    ok, skip = process_step1(self.source_paths, self.dirs["spec"], quality=self.quality.get(), on_progress=cb)
                    self.root.after(0, lambda: self.progress_var.set(f"规范素材尺寸完成：成功 {ok}，跳过 {skip}"))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
                finally:
                    self.root.after(0, self._after_step1)

            threading.Thread(target=worker, daemon=True).start()

        def _after_step1(self):
            self.root.config(cursor="")
            self._refresh_queue()
            self.idx = 0
            self._load_current()

        # ---------------- 队列 / 刷新 ----------------
        def _refresh_queue(self):
            done = set(os.listdir(self.dirs["out"])) if os.path.isdir(self.dirs["out"]) else set()
            files = list_source_images(self.dirs["spec"])
            # 排除 返工 子文件夹（list_source_images 只列顶层，已天然排除）
            self.queue = [f for f in files if f not in done]

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
            self.manual_tier = None
            self._place_box_default()
            self._draw()
            self._render_preview()
            self.info_var.set(f"[{self.idx+1}/{len(self.queue)}] {name}  {self.img.size[0]}×{self.img.size[1]}")

        def _current_box_size(self):
            if self.cfg["suite_on"]:
                if self.manual_tier:
                    t = self.cfg["tiers"][self.manual_tier]
                else:
                    t = self.cfg["tiers"][pick_tier_by_height(self.img.size[1], self.cfg["tiers"])]
                return t["w"], t["h"]
            else:
                try:
                    return max(1, int(self.cw.get())), max(1, int(self.ch.get()))
                except ValueError:
                    return 1920, 1080

        def _place_box_default(self):
            bw, bh = self._current_box_size()
            self.box, self.last_anchor = anchor_to_box(
                self.last_anchor[0], self.last_anchor[1],
                self.img.size[0], self.img.size[1], bw, bh)

        def _draw(self):
            if self.img is None:
                self._clear_canvas()
                return
            cw = self.canvas.winfo_width() or 800
            ch = self.canvas.winfo_height() or 600
            iw, ih = self.img.size
            self.fit_scale = min(cw / iw, ch / ih, 1.0) if (iw and ih) else 1.0
            dw, dh = int(iw * self.fit_scale), int(ih * self.fit_scale)
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
            if self.cfg["suite_on"]:
                out = crop_for_tier(self.img, bw, bh, fx, fy)
            else:
                out = crop_free(self.img, self.box)
            pw, ph = 240, 135
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
            if w > iw:
                w = iw
            if h > ih:
                h = ih
            x0 = max(0, min(x0, iw - w))
            y0 = max(0, min(y0, ih - h))
            return (int(x0), int(y0), int(x0 + w), int(y0 + h))

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
            self.box = (self.box[0], self.box[1], self.box[2], self.box[3])  # 重算锚点
            self._place_box_default()
            self._draw()
            self._render_preview()

        def confirm_crop(self):
            if self.img is None or not self.img_name:
                return
            bw, bh = self._current_box_size()
            fx, fy = self._box_anchor()
            if self.cfg["suite_on"]:
                out = crop_for_tier(self.img, bw, bh, fx, fy)
            else:
                out = crop_free(self.img, self.box)
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

        # ---------------- 套装 / 预设 ----------------
        def toggle_suite(self):
            self.cfg["suite_on"] = not self.cfg["suite_on"]
            self._sync_suite_btn()
            self._save_cfg()
            if self.img is not None:
                self._place_box_default()
                self._draw()
                self._render_preview()

        def _sync_suite_btn(self):
            self.suite_btn.configure(text="● 套装：开（自动选档）" if self.cfg["suite_on"] else "○ 套装：关（自由自定义）")

        def set_tier(self, key):
            self.manual_tier = key
            self._save_cfg()
            if self.img is not None:
                self._place_box_default()
                self._draw()
                self._render_preview()

        def apply_custom(self):
            try:
                self.custom = {"w": int(self.cw.get()), "h": int(self.ch.get())}
            except ValueError:
                pass
            self._save_cfg()
            if not self.cfg["suite_on"] and self.img is not None:
                self._place_box_default()
                self._draw()
                self._render_preview()

        def _save_cfg(self):
            # 同步三档编辑框到 config
            for k, (ew, eh) in self.tier_entries.items():
                try:
                    self.cfg["tiers"][k]["w"] = int(ew.get())
                    self.cfg["tiers"][k]["h"] = int(eh.get())
                except ValueError:
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
    main()
