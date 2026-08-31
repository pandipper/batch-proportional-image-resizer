#!/usr/bin/python3.12
# ↑ shebang 是给 Windows 的 Python Launcher（py.exe）看的。双击 .py 时
#   Windows 走的是 py.exe，而 py.exe 的「默认版本」未必是你装依赖的那个
#   Python——实测本机 py.exe 默认指向 3.14，而 3.14 的解释器早已被卸载
#   （C:\Users\...\AppData\Local\Python\pythoncore-3.14-64 不存在），
#   于是 py.exe 直接报 "Unable to create process" 后退出，表现为双击闪退。
#   写上这一行，py.exe 就会改用 3.12（依赖都装在这里）。
#   注意别写成 #!/usr/bin/env python3.12 —— 那种写法走 PATH 查找，
#   本机 PATH 里 3.12 排在 uv 的 3.12.13 之后，会命中没装依赖的那个。
#   PyInstaller 打包时这一行只是注释，不影响 exe。

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

# ───── 双击 .py 闪退兜底 ─────
# 双击启动时 Windows 用的是控制台 python.exe，一旦中途抛异常，控制台会
# 在你看清之前就关掉（表现为「闪退」）。这里捕获所有未处理异常，改成弹窗
# 把错误留下来；同时单独捕获 ImportError，给出「装依赖 / 换解释器」的指引。
from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

def _show_error(title, msg):
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb
        r = _tk.Tk(); r.withdraw()
        _mb.showerror(title, msg)
        r.destroy()
    except Exception:
        print(f"[{title}] {msg}", file=sys.stderr)

def _excepthook(exc_type, exc, tb):
    msg = "".join(traceback.format_exception(exc_type, exc, tb))
    _show_error("程序启动失败", msg)

sys.excepthook = _excepthook

# 关键依赖缺失检测（放在最前面，避免后续 import 链式崩溃）
try:
    import ttkbootstrap  # noqa
    import customtkinter as ctk  # noqa
except ImportError as _e:
    _show_error(
        "缺少依赖库",
        f"当前 Python 解释器缺少：{_e.name}\n\n"
        f"正在使用的解释器：\n  {sys.executable}\n\n"
        "双击 .py 时 Windows 会交给 py.exe（Python Launcher）挑一个版本，\n"
        "它挑中的那个未必装了本工具的依赖。\n\n"
        "解决方法（任选其一）：\n"
        "  ① 双击 run_gui.bat 启动（显式指定 Python 3.12）\n"
        "  ② 给当前解释器补装依赖：\n"
        f'     "{sys.executable}" -m pip install ttkbootstrap customtkinter pillow\n'
        "  ③ 若上面报的是 3.14/3.13 之类你没装过的版本，说明 py.exe 的默认\n"
        "     版本指向了一个已卸载的解释器，改用 run_gui.bat 即可绕开。",
    )
    sys.exit(1)

import json
import shutil
import webbrowser
import ctypes
import glob
import atexit

from PIL import Image

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk
    import customtkinter as ctk
    from PIL import ImageTk

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
    "font_size": 12,
    "theme": "minty",
    "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
}


# ===================== 主题 / 皮肤 =====================
# 仅用 ttkbootstrap 主题 + CustomTkinter（THEME_ON / 本地 PNG 皮肤素材方案已废弃）

# 设计 Token（与 spec 第 5 节一致；ttk.Style 在 App._apply_theme 应用）
# 唯一真相源：运行时由 _ttk_theme_colors(style.colors) 覆盖（见 App._apply_theme 段 1）。
# 此处 THEME 仅是「主题加载失败时的兜底」，改运行期颜色请改 _ttk_theme_colors，改这里无效。
# 分隔线用固定中性色（不随主题），单独抽成常量避免两处字面量漂移：
THEME_DIVIDER = "#9e988c"
THEME = {
    "PRIMARY":    "#609b8a",  "PRIMARY_H":    "#436c61",
    "BG":         "#eceeed",  "SURFACE":      "#ffffff",
    "BORDER":     "#d6d6d6",  "TEXT":         "#5a5a5a",
    "MUTED":      "#c2787b",  "HINT":         "#c2787b",
    "SUCCESS":    "#45a37e",  "SUCCESS_H":    "#307258",
    "WARNING":    "#ffce67",  "WARNING_H":    "#cca552",
    "SECONDARY":  "#c2787b",  "SECONDARY_H":  "#9b6062",
    "DANGER":     "#cc6041",  "DANGER_H":     "#8f432e",
    "DIVIDER":    "#9e988c",  "HOVER_LIGHT":  "#eceeed",
}

# 仅保留亮色主题（暗色主题已废弃）。可选 4 个主题：1 个默认 + 3 个 ttkbootstrap 内置官方主题。
APP_TITLE = "批量图片等比例缩放工具"
APP_VERSION = "1.0.2"          # 显示在窗口标题，用于发布后可追溯版本
THEME_CHOICES = ["minty", "everforest-light", "tokyo-night-light", "solarized-light"]

# 全站字体：注册成功后 Tk 按此名取用；注册失败则回退系统字体（见 _register_fonts）
#
# 2026-08-29 起改用 `OPPO Sans UI.ttf`（1.96 MiB）。它由 `OPPO Sans 4.0.ttf`
# （21.7 MiB 可变字体）静态实例化到 wght=600(SemiBold)、再按 GB2312 字集子集化
# 而来，省 91%。墨迹实测与原来的 SemiBold **逐像素一致**（拉丁串 2617 vs 2617，
# 差异 0.00%），四条真实界面文案的中文渲染也 100% 一致。
# 生成脚本 `.workbuddy-ai/build_ui_font.py`，验证脚本 `verify_ui_font.py`。
# 体积从哪省下来的：gvar（可变字重插值数据）占原文件 54.9%，而我们只用 SemiBold
# 一个字重——等于原先花 12.5 MiB 买了 4 个用不到的字重。
#
# 三个必须知道的约束：
#   1. 族名必须独立于 `OPPO Sans 4.0`。后者已装入 C:\Windows\Fonts，若同名，
#      GDI 会枚举出两个同族字体，取哪个不确定。
#   2. 静态化后**只有一个字重**，所以 FONT_BOLD 只能是「小 2 号」而非更粗
#      （这与改名之前完全一样，不是新引入的限制）。
#   3. `weight="bold"` 对本字体无效（无 Bold 实例），要加粗只能换 family 名。
FONT_NAME = "OPPO Sans UI"
FONT = (FONT_NAME, 12)
FONT_BOLD = (FONT_NAME, 10)    # 单字重字体：仅比正文小 2 号，不是「更粗」
FONT_HINT = (FONT_NAME, 13)    # 画布空态 / 预览关闭提示专用，随字号设置一起刷新


# ---------------- OPPO Sans 字体注册（Windows GDI）----------------
# 原型全站用 "OPPO Sans 4.0"；运行时注册后 Tk 才能按字体名取用，否则回退 Segoe UI。
_FONT_PATHS = []

def _register_fonts():
    """注册项目根目录（含子目录）下的 OPPO Sans*.ttf。仅 Windows 生效，失败打印原因。"""
    global _FONT_PATHS
    _FONT_REGISTERED = False
    # 搜索目录：开发态用脚本所在目录；冻结（PyInstaller exe）时额外查
    # _MEIPASS（打包进 exe 的资源解压目录）与 exe 同目录（便于随身附带字体）。
    search_dirs = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            search_dirs.append(sys._MEIPASS)
        search_dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
    try:
        search_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        search_dirs.append(os.getcwd())
    # 优先精确匹配 UI 子集字体（1.96 MiB）。只有它缺失时才回退通配——
    # 通配会命中完整的 `OPPO Sans 4.0.ttf`（21.7 MiB），虽然注册本身只要 0.02 ms，
    # 但会白占一份打包体积。想回退到完整字体，删掉 UI 子集字体即可。
    found = []
    for _d in search_dirs:
        found += glob.glob(os.path.join(_d, "**", "OPPO Sans UI.ttf"), recursive=True)
    if not found:
        for _d in search_dirs:
            found += glob.glob(os.path.join(_d, "**", "OPPO Sans*.ttf"), recursive=True)
    # 去重（保持首次出现顺序）：同一目录可能被多个 search_dirs 命中
    _seen = set()
    found = [p for p in found if not (p in _seen or _seen.add(p))]
    for p in found:
        try:
            n = ctypes.windll.gdi32.AddFontResourceW(p)
            if n and n > 0:
                _FONT_PATHS.append(p)
                _FONT_REGISTERED = True
                print(f"[font] registered: {os.path.basename(p)} (n={n})")
            else:
                err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else ctypes.GetLastError()
                print(f"[font] AddFontResourceW FAILED for {p}: GetLastError={err}")
        except Exception as e:
            print(f"[font] exception for {p}: {e}")
    if _FONT_REGISTERED:
        # 通知系统字体缓存已变更（让其它进程也能识别）。
        # 必须用 PostMessageW（异步、投递即返回），绝不能用 SendMessageW——
        # 后者向 HWND_BROADCAST 同步广播，会被系统中任一卡住的窗口拖死、导致整个程序挂起。
        try:
            ctypes.windll.user32.PostMessageW(0xFFFF, 0x001D, 0, 0)
        except Exception:
            pass
        atexit.register(_unregister_fonts)


def _unregister_fonts():
    for p in _FONT_PATHS:
        try:
            ctypes.windll.gdi32.RemoveFontResourceW(p)
        except Exception:
            pass


# ---------------- stdout 重定向（左下角运行日志面板）----------------
class _LogRedirector:
    """把 sys.stdout / sys.stderr 重定向到只读 Text 控件。

    注意：本类定义在模块顶层，而 `import tkinter as tk` 是 main() 内的局部变量，
    模块全局作用域里查不到 `tk`。因此这里一律用字面量 "end"（tkinter 的 END 常量
    本就等于 "end"），避免 write() 触发 NameError 被静默吞掉、导致日志面板始终为空。
    """
    def __init__(self, widget: Any) -> None:
        self._w = widget
    def write(self, s: str) -> None:
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
    def flush(self) -> None:
        pass


# ===================== 纯逻辑函数（无 tkinter 依赖，可单测）=====================


def is_image(name: str) -> bool:
    return name.lower().endswith(IMG_EXTS)


def _open_rgb(path: str) -> "Image.Image":
    """以 RGB 模式打开任意图片，返回 PIL Image（调用方负责持有）。

    抽成模块级函数是为了避免在 App 方法里直接引用 ``Image.open`` 时，
    因闭包解析问题偶发 ``free variable 'Image'`` 异常（用户 v1.0.1 实测遇到过）。
    模块级 import 的 ``Image`` 是明确的全局，不会被内部作用域阴影。
    """
    from PIL import Image  # 冗余但防御性：即使模块级 import 被干扰也能工作
    with Image.open(path) as im:
        return im.convert("RGB")


# ---------- 主题 / 字体：从 App._apply_theme 抽出的可单测纯逻辑 ----------
# 这三个函数原本内联在 _apply_theme 的 75 行巨型 try 里。内联 + `except: pass`
# 的后果是：任何一处抛异常，后面所有样式都会静默失效且不留任何线索（历史 bug：
# `T = THEME` 的 NameError 曾让整个自定义样式块连续数轮未生效而无人察觉）。
# 抽出后由调用方「按段」捕获并记录，异常不再被吞。


def _ttk_theme_colors(style: Any) -> Dict[str, str]:
    """从 ttkbootstrap Style 提取本工具用到的色表（含 hover 派生色）。

    返回的键与模块级 THEME 完全一致，供 `THEME.update()` 覆盖硬编码 fallback。
    异常一律向上抛给调用方按段记录——这里不要吞。
    """
    c = style.colors

    def _hover(label, step=100):
        """用 ttkbootstrap 的 ramp 取比 base 深一档的色，作为 hover。"""
        r = c.ramp(label)
        key = max(min(500 + step, 950), 50)
        if key not in r:
            key = min(r.keys(), key=lambda k: abs(k - key))
        return r[key]

    return {
        "PRIMARY":    c.primary,    "PRIMARY_H":    _hover("primary"),
        "SUCCESS":    c.success,    "SUCCESS_H":    _hover("success"),
        "WARNING":    c.warning,    "WARNING_H":    _hover("warning"),
        "DANGER":     c.danger,     "DANGER_H":     _hover("danger"),
        "SECONDARY":  c.secondary,  "SECONDARY_H":  _hover("secondary"),
        "BG":         c.light,
        "SURFACE":    c.bg,
        "BORDER":     c.border,
        "TEXT":       c.fg,
        "MUTED":      c.secondary,
        "HINT":       c.secondary,
        "DIVIDER":    THEME_DIVIDER,    # 刻意不随主题变化：分隔线固定中性色
        "HOVER_LIGHT": c.light,
    }


def _resolve_ui_family() -> str:
    """探测可用字体族：优先 OPPO Sans UI，缺失时逐级回退到系统字体。

    两个坑（都是实测出来的，改候选名单前务必读完）：

    1. **Tk 的 families() 在中文 Windows 上返回本地化名**。`微软雅黑`、`等线`
       查得到，而 `Microsoft YaHei`、`DengXian`、`SimSun`、`SimHei` **一律查不到**
       （`Microsoft YaHei UI` 是例外，它有英文名）。这里靠 `in families` 精确匹配，
       候选里写英文名会被静默判为不存在——不报错，只是悄悄回退，极难排查。
    2. **不要把 `Segoe UI` 排在中文候选之前**。它是纯拉丁字体，遇到中文要逐个走
       fallback 查找，实测 measure() 单次 0.914 ms，比中文字体慢 6~8 倍
       （雅黑 0.147 / 静态 OPPO Sans 0.114）。放在最后兜底即可。
    """
    from tkinter import font as tkfont
    families = set(tkfont.families())
    for name in (FONT_NAME, "OPPO Sans 4.0", "OPPO Sans", "微软雅黑", "等线"):
        if name in families:
            return name
    return "Segoe UI"


def _ui_font_tuple(font_size: Any) -> Tuple[str, int, int, int]:
    """返回 (family, size, bold_size, hint_size)；size 已夹到 [8, 24]。

    bold 比正文小 2 号（单字重字体无法更粗）；hint 是画布提示文字，比正文大 1 号。
    """
    size = max(8, min(24, int(font_size)))
    try:
        family = _resolve_ui_family()
    except Exception:
        family = FONT_NAME
    return family, size, max(8, size - 2), min(24, size + 1)


def _sync_tk_named_fonts(family: str, size: int) -> None:
    """同步 tk 全局具名字体，让之后新建的 tk 控件也继承同一字体。

    单个字体名不存在属于可容忍情况（跳过即可），不向上抛。
    """
    from tkinter import font as tkfont
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(name).configure(family=family, size=size)
        except Exception:
            pass


def load_config(path: str) -> Dict[str, Any]:
    """读取 config.json；缺失或损坏时回退默认。"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("active_tier", "large")
            cfg.setdefault("ratio_lock", True)
            cfg.setdefault("ratio", [16, 9])
            cfg.setdefault("font_size", 12)
            cfg.setdefault("theme", "minty")
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


def save_config(path: str, cfg: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def ensure_dirs(work_dir: str) -> Dict[str, str]:
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


def list_source_images(folder: str) -> List[str]:
    """列出文件夹内（顶层）所有图片文件名。"""
    try:
        return sorted(n for n in os.listdir(folder) if is_image(n))
    except OSError:
        return []


def step1_target_size(iw: int, ih: int, tiers: Optional[Dict[str, Any]] = None, min_width: int = 1280, max_width: int = 2560) -> Tuple[int, int]:
    """step1 归一化：以「短边」为基准夹逼到 [720, 1440]，最大限度保留画面。

    规则（大小档 small=1280x720、large=2560x1440，其短边即高 720/1440）：
      short = min(iw, ih)
      720 <= short <= 1440  -> 不缩放，原尺寸保留
      short < 720           -> 等比放大，使短边 = 720
      short > 1440          -> 等比缩小，使短边 = 1440
    始终保留原纵横比，不裁切、不拉伸；长边允许溢出（留待 step2 取景裁剪）。
    短边上下限取自档位（small/large 的短边即其高），改 settings 档位时自动跟随。
    返回 (w, h)（保持原图比例）。
    """
    if iw <= 0 or ih <= 0:
        return (max(1, iw), max(1, ih))
    t = tiers or {}
    sm = t.get("small") or {"w": min_width, "h": 720}
    lg = t.get("large") or {"w": max_width, "h": int(max_width * 9 / 16)}
    short_min = min(sm["w"], sm["h"])   # 720
    short_max = min(lg["w"], lg["h"])   # 1440
    short = min(iw, ih)
    if short < short_min:
        scale = short_min / short          # 短边不足 -> 放大到 720
    elif short > short_max:
        scale = short_max / short          # 短边过大 -> 缩小到 1440
    else:
        scale = 1.0                        # 短边在范围内 -> 不动
    w = max(1, int(round(iw * scale)))
    h = max(1, int(round(ih * scale)))
    return (w, h)


def process_step1(source_paths: Sequence[str], out_dir: str, quality: int = 100, on_progress: Optional[Callable[[int, int, str], bool]] = None, tiers: Optional[Dict[str, Any]] = None, min_width: int = 1280) -> Tuple[int, int]:
    """对一组源图执行 step1，结果写入 out_dir（同名覆盖）。返回 (成功数, 跳过数)。

    `on_progress(i, total, src)` 在每张处理前调用，**返回 False 即中止**本轮
    （供 GUI 的「取消」使用）：已写入的图片保留，函数立即返回已累计的 (ok, skip)。
    """
    ok = 0
    skip = 0
    total = len(source_paths)
    for i, src in enumerate(source_paths, 1):
        if on_progress and on_progress(i, total, src) is False:
            print(f"[step1] 已取消：处理到第 {i}/{total} 张时中止")
            break
        if not is_image(src):
            skip += 1
            continue
        try:
            im = _open_rgb(src)
            tgt = step1_target_size(*im.size, tiers=tiers, min_width=min_width)
            out = im.resize(tgt, _RESAMPLE)
            base = os.path.splitext(os.path.basename(src))[0] + ".jpg"
            out.save(os.path.join(out_dir, base), "JPEG", quality=quality)
            ok += 1
        except Exception as e:
            skip += 1
            print(f"[step1] 跳过 {os.path.basename(src)}：{type(e).__name__}: {e}")
    return ok, skip


def cover_scale(iw: int, ih: int, bw: int, bh: int) -> float:
    """COVER 缩放：保证缩放后两维均 >= 框。"""
    return max(bw / iw, bh / ih) if (iw > 0 and ih > 0) else 1.0


def anchor_to_box(fx: float, fy: float, iw: int, ih: int, bw: int, bh: int) -> Tuple[Tuple[int, int, int, int], Tuple[float, float]]:
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


def crop_for_tier(img: Image.Image, bw: int, bh: int, fx: float, fy: float) -> Image.Image:
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


# ===================== GUI（tkinter，仅在 main 内导入）=====================


def main():
    import tkinter as tk
    from tkinter import filedialog
    import ttkbootstrap as ttkb
    # 美化版消息框（跟随 minty 主题）：替代 tkinter 原生 messagebox。
    # buttons 支持 "文案:bootstyle" 写法，localize=False 避免中文按钮被再翻译。
    from ttkbootstrap.dialogs import Messagebox
    # ttkbootstrap 2.x 顶层直接导出各控件（ttkb.Frame/Button/Spinbox...），
    # 没有独立的 ttk 子模块；用别名 ttk 让既有调用点 ttk.X 落到 ttkb 顶层。
    ttk = ttkb
    from PIL import ImageTk
    # CustomTkinter 初始化（创建任何 CTk 控件前必须先设置）
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")  # 接近 minty 主色
    # ───────── Bootstrap-Icons 桥接（渲染为 CTkButton / 图标组）─────────
    _BS_GLYPHMAP = {}
    _BS_FONT_PATH = ""
    _PIL_ICON_CACHE = {}   # 缓存 PIL 图（供 _make_icon 复用，避免重复渲染）
    _ICON_CACHE = {}       # 缓存 CTkImage（CTk 控件用）
    _CTK_REGISTRY = []     # 已建 CTk 控件登记表，供主题切换时批量重新着色

    def _init_bootstrap_icons():
        """加载 ttkbootstrap 自带的 bootstrap.ttf + glyphmap.json，仅执行一次。"""
        nonlocal _BS_GLYPHMAP, _BS_FONT_PATH
        if _BS_GLYPHMAP:
            return
        import ttkbootstrap as _ttkb
        base = os.path.dirname(_ttkb.__file__)
        _BS_FONT_PATH = os.path.join(base, "assets", "icons", "bootstrap.ttf")
        with open(os.path.join(base, "assets", "icons", "glyphmap.json"), encoding="utf-8") as f:
            _BS_GLYPHMAP = json.load(f)

    def _make_icon_pil(name, size=14, color="#ffffff"):
        """把 Bootstrap-Icons 名称渲染成 PIL.Image（RGBA），供 CTkImage / ImageTk 复用。"""
        if not name:
            return None
        _init_bootstrap_icons()
        glyph = _BS_GLYPHMAP.get(name)
        if glyph is None:
            return None
        key = (name, size, color)
        if key in _PIL_ICON_CACHE:
            return _PIL_ICON_CACHE[key]
        from PIL import Image, ImageDraw, ImageFont
        code = chr(int(glyph))  # glyphmap.json 里直接是 10 进制 int
        # 渲染字号回到 2.6×（常规 2.5×），不再叠加偏移 → 字重还原轻盈（框3/框4：字重过重）
        f = ImageFont.truetype(_BS_FONT_PATH, int(size * 2.6))
        bbox = f.getbbox(code)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        # 单遍绘制，移除 3×3 偏移加粗 → 图标不过粗
        d = ImageDraw.Draw(img)
        d.text((-bbox[0], -bbox[1]), code, font=f, fill=color)
        _PIL_ICON_CACHE[key] = img
        return img

    def _make_icon(name, size=14, color="#ffffff"):
        """把 Bootstrap-Icons 名称渲染成 CTkImage（CustomTkinter 控件用，带缓存）。"""
        if not name:
            return None
        key = (name, size, color)
        if key in _ICON_CACHE:
            return _ICON_CACHE[key]
        img = _make_icon_pil(name, size, color)
        if img is None:
            return None
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
        _ICON_CACHE[key] = ctk_img
        return ctk_img

    def _text_on(bg):
        """按背景亮度返回可读文字/图标色：深底白字，浅底（如 warning 黄）用主题文字色。"""
        try:
            r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            L = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            return "#ffffff" if L < 0.55 else THEME.get("TEXT", "#2C2C2A")
        except Exception:
            return "#ffffff"

    def _icon_color(bootstyle):
        """图标字形颜色：实心按钮用与文字一致的对比色，outline/link 用描边色。全部取自 THEME。"""
        s = bootstyle or "primary"
        is_outline = "-outline" in s or "-link" in s
        base = s.replace("-outline", "").replace("-link", "")
        fg = THEME.get(base.upper(), THEME["PRIMARY"])
        return fg if is_outline else _text_on(fg)

    def _ctk_colors(bootstyle):
        """把 ttkbootstrap bootstyle 映射到 CustomTkinter 的 fg/hover/text/border 色。
        全部取自 THEME（运行时由 style.colors / ramp 派生），不再写死 hex。"""
        s = bootstyle or "primary"
        is_outline = "-outline" in s
        is_link = "-link" in s
        base = s.replace("-outline", "").replace("-link", "")
        key = base.upper()
        fg = THEME.get(key, THEME["PRIMARY"])
        hover = THEME.get(key + "_H", fg)
        if is_outline or is_link:
            return ("transparent", THEME["HOVER_LIGHT"], fg, "transparent" if is_link else fg)
        return (fg, hover, _text_on(fg), "transparent")

    def mk_btn(parent, text="", icon=None, bootstyle="primary", command=None, **kwargs):
        """CustomTkinter 圆角按钮工厂（文字按钮）。

        图标走 _make_icon 渲染成 CTkImage；带文字的图标在左；
        圆角 8、高 36，与此前 ttkbootstrap 外观接近但圆角更干净。
        """
        is_icon_only = bool(icon) and not text
        # icon-only 按钮走 _make_icon_group，不在这里构造（CTkButton 的 text/image
        # 混排在用户环境下会丢图标）。
        if is_icon_only:
            raise ValueError("icon-only 按钮请用 _make_icon_group")
        icon_size = 16
        img = _make_icon(icon, size=icon_size, color=_icon_color(bootstyle)) if icon else None
        fg, hover, text_color, border_color = _ctk_colors(bootstyle)
        btn_kwargs = dict(
            text=text, image=img, command=command, compound="left",
            corner_radius=8, height=36, font=FONT,
            fg_color=fg, hover_color=hover, text_color=text_color,
        )
        if border_color != "transparent":
            btn_kwargs["border_color"] = border_color
            btn_kwargs["border_width"] = 1
        else:
            btn_kwargs["border_width"] = 0
        btn = ctk.CTkButton(parent, **btn_kwargs, **kwargs)
        btn._keep = img  # 防止 CTkImage 被 GC 回收导致图标消失
        _CTK_REGISTRY.append(("btn", btn, bootstyle, icon))
        return btn

    def _make_icon_group(parent, items, bootstyle="primary", icon_size=18):
        """连续圆角图标按钮组：单个 CTkFrame 外壳 + 内部图标格 + 短灰分割线。

        每个图标放在内层圆角格子（CTkFrame, corner_radius=6）中，正常态透明、
        hover 态底色变为与其他按钮一致的 hover 色（与 mk_btn 的 CTkButton 悬停
        行为相同）；格四周留 2px 余量让外壳圆角露出，避免直角覆盖外壳圆角。
        点击执行命令。items: [(icon_name, command, tooltip), ...]
        """
        fg, hover, text_color, _border = _ctk_colors(bootstyle)
        n = max(1, len(items))
        frame = ctk.CTkFrame(
            parent, fg_color=fg, corner_radius=8, border_width=0, height=36,
        )
        # grid + weight 稳定均分宽度；pack 的 expand 在 CTkFrame 上易分配不均。
        frame.grid_propagate(False)
        col = 0
        cells = []   # 登记每个图标的 (cell, lbl, icon)，供主题切换时重新着色
        for i, (icon, cmd, _tip) in enumerate(items):
            img = _make_icon(icon, size=icon_size, color=text_color)
            # 内层圆角格：hover 时整格底色变深，与 CTkButton 悬停一致
            cell = ctk.CTkFrame(frame, corner_radius=6, fg_color="transparent",
                               border_width=0)
            cell._hover = hover   # 主题切换后需更新，故用可变属性而非闭包捕获
            cell.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
            lbl = ctk.CTkLabel(cell, text="", image=img, fg_color="transparent")
            lbl._keep = img  # 防 GC
            lbl.place(relx=0.5, rely=0.5, anchor="center")
            # 事件绑在图标上，handler 切换整格底色（避免子控件覆盖导致的闪烁）
            lbl.bind("<Button-1>", lambda _e, c=cmd: c())
            lbl.bind("<Enter>", lambda _e, c=cell: c.configure(fg_color=c._hover))
            lbl.bind("<Leave>", lambda _e, c=cell: c.configure(fg_color="transparent"))
            frame.columnconfigure(col, weight=1, minsize=icon_size + 8)
            col += 1
            cells.append((cell, lbl, icon))
            # 图标之间：短灰分割线（高度 14、非通高，仿分段控件分隔）
            if i < n - 1:
                div = tk.Frame(frame, width=2, height=14,
                               bg=THEME["DIVIDER"], highlightthickness=0)
                div.grid(row=0, column=col, sticky="", padx=0)
                frame.columnconfigure(col, weight=0, minsize=2)
                col += 1
        frame.rowconfigure(0, weight=1)
        _CTK_REGISTRY.append(("group", frame, bootstyle, items, icon_size, cells))
        return frame

    from ttkbootstrap.dialogs.message import MessageDialog

    class _RichLine:
        __slots__ = ("text", "style", "indent", "pady")
        def __init__(self, text="", style=None, indent=0, pady=None):
            self.text = text
            self.style = style
            self.indent = indent
            self.pady = pady

    class _RichMessageDialog(MessageDialog):
        """ttkbootstrap MessageDialog 的富文本变体。

        正文拆成多行，每行可独立指定 ``bootstyle``（primary / success / warning /
        danger / info / secondary / dark），从而把「短边下限 720」「上限 1440」
        这类对用户最重要的变化值用醒目颜色标出来。图标、按钮、居中、模态、
        Esc 关闭等行为完全继承自官方 MessageDialog， visually 与原生
        Messagebox 保持一致。
        """
        def __init__(self, lines, title=" ", buttons=None, parent=None,
                     alert=False, default=None, icon=None, **kwargs):
            self._lines = lines
            # 富文本由调用方自己控制换行，message 留空，不再走父类的 textwrap
            super().__init__(message="", title=title, buttons=buttons or ["OK:primary"],
                             parent=parent, alert=alert, default=default, icon=icon,
                             width=1, **kwargs)

        def create_body(self, master):
            from ttkbootstrap.dialogs.message import _alert_icon
            container = ttk.Frame(master, padding=self._padding)
            if self._icon:
                icon_lbl = self._create_icon_label(container)
                if icon_lbl is not None:
                    icon_lbl.pack(side="left", anchor="center", padx=(0, 10))
            msg_frame = ttk.Frame(container)
            for line in self._lines:
                if line.text == "" or line.text is None:
                    ttk.Frame(msg_frame, height=8).pack(fill="x")
                    continue
                kw = {}
                if line.style:
                    kw["bootstyle"] = line.style
                pady = line.pady if line.pady is not None else (0, 3)
                # 约 8px/字符，60 字符对应 480px；超出自动折行
                ttk.Label(msg_frame, text=line.text, anchor="w", justify="left",
                          wraplength=480, **kw).pack(
                    fill="x", anchor="n", pady=pady, padx=(line.indent, 0))
            msg_frame.pack(side="left", fill="x", expand=True, anchor="center")
            container.pack(fill="x", expand=True)

    class App:
        def __init__(self, root):
            self.root = root
            self.root.title(f"{APP_TITLE}  v{APP_VERSION}")
            self.root.geometry("1200x780")

            self.work_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            self.config_path = os.path.join(self.work_dir, "config.json")
            self.cfg = load_config(self.config_path)
            self.dirs = ensure_dirs(self.work_dir)
            self._settings_menu = None   # 设置按钮弹出的二级菜单（懒加载）
            # 窗口预览默认开启（2026-08-29 改为 True）。
            # 原先默认 False 是为了规避拖动/滚动卡顿，但代价是启动后画布一片空白、
            # 必须手动去设置里打开，观感像"坏了"。现在改回默认开启，卡顿改由
            # `_draw` 的增量更新（只 coords 移动已有图元，不再 delete+重建）来治本。
            # 仍然保留设置菜单开关：处理超大图时手动关掉可以彻底零开销。
            self._preview_on = True

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
            self._theme_errors = []  # 首屏主题各段失败的缓存，_build_ui 末尾补写进日志面板

            # 主题：固定 minty 亮色（暗色主题已废弃）

            # 画布显示参数
            self.fit_scale = 1.0
            self.offx = 0
            self.offy = 0
            self.tk_img = None
            self.preview_tk = None
            self._pv_key = None      # 预览底图缓存键：(id(self.img), bw, bh)
            self._pv_base = None     # 缩到 ~320px 量级的底图，拖动时在其上裁窗
            self._pv_scale = 1.0     # 底图相对 COVER 尺寸的缩放系数（框也按此系数同步缩放）
            self._pending_pv = None  # 预览重绘的合并定时器

            self._apply_theme()  # ttk.Style 必须在 _build_ui 之前配好
            self._build_ui()
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
            # Esc：中止正在进行的「规范素材尺寸」。设置面板是独立 Toplevel，
            # 有自己的 Esc 关闭绑定，两者不会互相干扰（Toplevel 不在 root 的绑定链上）。
            self.root.bind("<Escape>", self.cancel_step1)
            # 窗口映射前画布尺寸为 0/1，首次 _draw 会跳过；映射后延迟触发一次真实重绘
            self.root.after(60, self._draw)

        # ---------------- 主题 / 皮肤 ----------------
        def _apply_theme(self):
            """ttkbootstrap 主题（默认 minty，可切换为其它亮色主题）+ 命名样式，必须在 _build_ui 之前调用。

            按 4 段各自 try：任一段失败只影响该段，且会把异常写进日志面板。
            这里早期整段包在一个 `try: ... except Exception: pass` 里——任何一处异常
            都会让后面所有样式静默失效且毫无线索（`T = THEME` 的 NameError 曾让整个
            自定义样式块连续数轮未生效而无人察觉）。现在失败至少是可见的。
            """
            T = THEME
            style = None
            # 段 1：切换 ttkbootstrap 主题并刷新色表
            try:
                style = ttkb.Style()
                style.theme_use(self.cfg.get("theme", "minty"))
                THEME.update(_ttk_theme_colors(style))
            except Exception as e:
                self._theme_err("切换主题/刷新色表", e)
            # 段 2：字体（探测字族 → 写回全局 FONT/FONT_BOLD/FONT_HINT → 同步 tk 具名字体）
            try:
                global FONT, FONT_BOLD, FONT_HINT
                family, size, bold_size, hint_size = _ui_font_tuple(
                    self.cfg.get("font_size", 12))
                FONT = (family, size)
                FONT_BOLD = (family, bold_size)
                FONT_HINT = (family, hint_size)
                _sync_tk_named_fonts(family, size)
                self._FONT = FONT
                self._FONT_BOLD = FONT_BOLD
                self._FONT_HINT = FONT_HINT
            except Exception as e:
                self._theme_err("字体解析", e)
            # 段 3：ttk 命名样式（复用段 1 的 style；重复 new Style() 会重置主题）
            try:
                if style is None:
                    style = ttkb.Style()
                for cls in ("TButton", "TLabel", "TSpinbox", "TCombobox", "TEntry"):
                    style.configure(cls, font=FONT)
                style.configure("TLabelframe.Label", font=FONT_BOLD)
                style.configure("TFrame", background=T["SURFACE"])
                style.configure("Card.TFrame", background=T["BG"])
                style.configure("TLabel", background=T["SURFACE"], foreground=T["TEXT"])
                style.configure("Card.TLabel", background=T["BG"], foreground=T["TEXT"])
                style.configure("Muted.TLabel", background=T["SURFACE"], foreground=T["MUTED"])
                style.configure("Hint.TLabel", background=T["SURFACE"], foreground=T["HINT"])
            except Exception as e:
                self._theme_err("ttk 命名样式", e)
            # 段 4：根窗口背景（避免控件未填满处露出硬白框）
            try:
                self.root.configure(bg=T["SURFACE"])
            except Exception as e:
                self._theme_err("根窗口背景", e)

        def _theme_err(self, stage, exc):
            """记录主题某一阶段失败。

            首屏 _apply_theme 早于日志面板创建（sys.stdout 重定向在 _build_ui 里才装），
            此时 print 只能到控制台；故同时缓存一份，待 _build_ui 末尾再补写进面板。
            """
            msg = f"[主题] {stage} 失败：{type(exc).__name__}: {exc}"
            errors = getattr(self, "_theme_errors", None)
            if errors is None:
                errors = self._theme_errors = []
            errors.append(msg)
            print(msg)

        def _flush_theme_errors(self):
            """日志面板就绪后，把首屏缓存的主题错误补写进面板（仅此一次）。"""
            for msg in getattr(self, "_theme_errors", None) or []:
                print(msg)
            self._theme_errors = []

        def _apply_ctk_visuals(self):
            """主题/字号切换后，把已建的 CustomTkinter 控件按新 THEME / FONT 重新着色、重新设字体。

            CustomTkinter 的**颜色和字体都是构建时捕获的**，既不随 style.colors 自动刷新，
            也不随 ttk 的 style.configure(font=...) 刷新。所以必须遍历 _CTK_REGISTRY
            逐个重新 configure；同时刷新行首开关按钮的激活态。
            """
            try:
                for entry in _CTK_REGISTRY:
                    kind = entry[0]
                    if kind == "btn":
                        _, btn, bootstyle, icon = entry
                        if not btn.winfo_exists():
                            continue
                        fg, hover, text_color, border_color = _ctk_colors(bootstyle)
                        # font 一并刷新：注册表里的按钮均由 mk_btn 创建、用的是全局 FONT，
                        # 改字号后不重刷就会出现「ttk 控件变了、CTk 按钮没变」的割裂
                        kw = dict(fg_color=fg, hover_color=hover, text_color=text_color,
                                  font=FONT)
                        if border_color != "transparent":
                            kw["border_color"] = border_color
                            kw["border_width"] = 1
                        else:
                            kw["border_width"] = 0
                        btn.configure(**kw)
                        if icon:
                            new_img = _make_icon(icon, size=16, color=text_color)
                            btn.configure(image=new_img)
                            btn._keep = new_img
                    elif kind == "group":
                        _, frame, bootstyle, _items, icon_size, cells = entry
                        if not frame.winfo_exists():
                            continue
                        fg, hover, text_color, _border = _ctk_colors(bootstyle)
                        frame.configure(fg_color=fg)
                        for (cell, lbl, icon) in cells:
                            if not cell.winfo_exists() or not lbl.winfo_exists():
                                continue
                            cell._hover = hover
                            new_img = _make_icon(icon, size=icon_size, color=text_color)
                            lbl.configure(image=new_img)
                            lbl._keep = new_img
            except Exception:
                pass
            try:
                self._refresh_headers()
            except Exception:
                pass
            # 处理区画布底色锁定为 E8E8E8，主题切换后强制重设，避免与父框背景混色而“消失”
            try:
                if getattr(self, "canvas", None) is not None and self.canvas.winfo_exists():
                    self.canvas.configure(bg="#e8e8e8")
            except Exception:
                pass
            # 工具栏竖向分隔线是经典 tk.Frame，背景色在构建时写死、不随主题引擎刷新，
            # 故切主题后必须手动重染，否则分隔线会一直停留在旧主题的配色上
            try:
                for d in getattr(self, "_dividers", []):
                    if d is not None and d.winfo_exists():
                        d.configure(bg=THEME["DIVIDER"])
            except Exception:
                pass
            # 署名 @pandipper：颜色跟随当前 PRIMARY 主色调（点击切主题时同步刷新）
            try:
                sig = getattr(self, "signature", None)
                if sig is not None and sig.winfo_exists():
                    sig.configure(foreground=THEME["PRIMARY"])
            except Exception:
                pass

        # ---------------- 快捷键焦点感知 ----------------
        # ---------------- 快捷键焦点感知 ----------------
        def _kbd(self, action):
            def handler(event):
                fw = self.root.focus_get()
                if isinstance(fw, (tk.Entry, ttk.Entry, ttk.Spinbox, tk.Button, ttk.Button,
                                   ctk.CTkButton, ctk.CTkEntry)):
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
            if isinstance(w, (tk.Entry, ttk.Entry, ttk.Spinbox, tk.Listbox,
                              ctk.CTkEntry)):
                return  # 正在文字输入或选择列表/CTkEntry 时不抢焦点
            try:
                self.canvas.focus_set()
            except Exception:
                pass

        # ---------------- 图标：使用 Bootstrap-Icons 字体渲染为 CTkImage ----------------
        # 文字按钮用 CTkButton（圆角）；icon-only 按钮用 _make_icon_group（连续圆角 CTkFrame）。
        # 见下方 _build_ui 中旋转行与队列上下移按钮组的定义。

        def _make_placeholder_img(self):
            """预览空态占位图：160×90 绿调渐变（对应 HTML 原型 .preview .ph），无图时显示。"""
            from PIL import Image, ImageDraw
            w, h = 160, 90
            img = Image.new("RGB", (w, h))
            d = ImageDraw.Draw(img)
            c1, c2 = (207, 217, 210), (174, 191, 180)  # #cfd9d2 → #aebfb4
            for y in range(h):
                t = y / (h - 1)
                d.line([(0, y), (w, y)], fill=(
                    int(c1[0] + (c2[0] - c1[0]) * t),
                    int(c1[1] + (c2[1] - c1[1]) * t),
                    int(c1[2] + (c2[2] - c1[2]) * t),
                ))
            return ImageTk.PhotoImage(img)

        # ---------------- UI（新布局：顶栏动作 + 左可滚动竖列 + 中画布）----------------
        def _build_ui(self):
            # 顶部工具栏：左组=规范/导入/导出；中组=确认裁剪/返工/精修；右组(最右)=移除/设置
            top = ttk.Frame(self.root)
            top.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
            self._dividers = []   # 工具栏竖向分隔线（经典 tk.Frame），固定配色
            # 左组：规范 / 导入 / 导出
            mk_btn(top, text="规范素材尺寸", icon="rulers", bootstyle="primary", command=self.run_step1).pack(side=tk.LEFT, padx=4)
            b_spec = mk_btn(top, text="规范素材图路径", icon="folder2-open", bootstyle="success", command=lambda: self._open(self.dirs["spec"]))
            b_spec.pack(side=tk.LEFT, padx=4); self._set_tip(b_spec, self.dirs["spec"])
            b_out = mk_btn(top, text="导出文件夹路径", icon="folder2-open", bootstyle="success", command=lambda: self._open(self.dirs["out"]))
            b_out.pack(side=tk.LEFT, padx=4); self._set_tip(b_out, self.dirs["out"])

            # 左 / 中 之间的竖向分隔线
            d1 = tk.Frame(top, width=2, bg=THEME["DIVIDER"]); d1.pack(side=tk.LEFT, fill=tk.Y, padx=10)
            self._dividers.append(d1)

            # 中组：画布操作（确认裁剪 / 返工 / 精修）
            mg = ttk.Frame(top)
            mk_btn(mg, text="确认裁剪", icon="crop", bootstyle="primary", command=self.confirm_crop).pack(side=tk.LEFT, padx=4)
            b_rw = mk_btn(mg, text="返工路径", icon="folder2-open", bootstyle="success", command=lambda: self._open(self.dirs["spec_rework"]))
            b_rw.pack(side=tk.LEFT, padx=4); self._set_tip(b_rw, self.dirs["spec_rework"])
            b_rt = mk_btn(mg, text="精修路径", icon="folder2-open", bootstyle="success", command=lambda: self._open(self.dirs["out_retouch"]))
            b_rt.pack(side=tk.LEFT, padx=4); self._set_tip(b_rt, self.dirs["out_retouch"])
            mg.pack(side=tk.LEFT)

            # 中 / 右 之间的竖向分隔线
            d2 = tk.Frame(top, width=2, bg=THEME["DIVIDER"]); d2.pack(side=tk.LEFT, fill=tk.Y, padx=10)
            self._dividers.append(d2)

            # 右组（最右侧）：移除 + 设置
            rg = ttk.Frame(top)
            b_del = mk_btn(rg, text="移除", icon="trash", bootstyle="warning", command=self._remove_selected)
            b_del.pack(side=tk.LEFT, padx=2); self._set_tip(b_del, "移除素材队列里被选中的项目")
            settings_btn = mk_btn(rg, text="设置", icon="gear-fill", bootstyle="secondary")
            settings_btn.configure(command=lambda w=settings_btn: self._open_settings_menu(w))
            settings_btn.pack(side=tk.LEFT, padx=2); self._set_tip(settings_btn, "设置")
            rg.pack(side=tk.RIGHT)  # 移除 + 设置 固定到工具栏最右侧

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

            self._pending_sync = None

            def _do_sync_left():
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

            def _sync_left(e=None):
                # 防抖：窗口拖动时 <Configure> 高频触发，合并到 120ms 后只算一次滚动区域
                if self._pending_sync:
                    self.root.after_cancel(self._pending_sync)
                self._pending_sync = self.root.after(120, _do_sync_left)

            self.left_content.bind("<Configure>", _sync_left)
            self.left_canvas.bind("<Configure>", _sync_left)
            self.left_canvas.bind("<MouseWheel>", lambda e: self.left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

            # 导入 / 规范
            imp = ttk.LabelFrame(self.left_content, text="导入 / 规范素材")
            imp.pack(fill=tk.X, pady=(2, 6))
            ib = ttk.Frame(imp)
            ib.pack(fill=tk.X, padx=4, pady=2)
            mk_btn(ib, text="导入文件夹", icon="folder2-open", bootstyle="primary", command=self.import_folder).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
            mk_btn(ib, text="导入文件", icon="file-earmark-image", bootstyle="secondary-outline", command=self.import_files).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

            # 素材队列
            ttk.Label(self.left_content, text="素材队列", anchor="w", font=FONT_BOLD).pack(fill=tk.X, pady=(2, 3))
            # 素材队列：Listbox + 专用 Scrollbar（项数 > height 时始终可见）
            qf = ttk.Frame(self.left_content)
            qf.pack(fill=tk.X, pady=(0, 3))
            self.queue_list = tk.Listbox(qf, exportselection=False, height=8,
                                         font=FONT,
                                         selectbackground=THEME["PRIMARY"], selectforeground="#ffffff")
            self.queue_sb = ttk.Scrollbar(qf, orient="vertical", command=self.queue_list.yview)
            self.queue_list.configure(yscrollcommand=self.queue_sb.set)
            self.queue_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.queue_sb.pack(side=tk.LEFT, fill=tk.Y)
            self.queue_list.bind("<<ListboxSelect>>", self._on_queue_select)
            obtn = ttk.Frame(self.left_content)
            obtn.pack(fill=tk.X, pady=2)
            # 用 grid 让按钮均分布满整行（与夹逼范围、旋转行同宽对齐）
            # 列宽：↑↓ 列略宽（视觉更稳），返工/精修 列略窄；四列均填满整行 → 左右边缘列对齐
            # 注意：tkinter grid weight 只接受整数，1.15 会 TclError，故用 3/4/4/3（↑↓ 约 1.33×）
            obtn.columnconfigure(0, weight=3)
            obtn.columnconfigure(1, weight=4)
            obtn.columnconfigure(2, weight=4)
            obtn.columnconfigure(3, weight=3)
            mk_btn(obtn, text="返工", icon="arrow-return-left", bootstyle="success", command=self._rework_selected).grid(row=0, column=0, sticky="nsew", padx=(0, 2))
            # ↑↓ 合成一个连续圆角图标组（避免两个独立圆角按钮接缝毛边）
            updown = _make_icon_group(obtn, [
                ("arrow-up", self.move_up, "上移选中项"),
                ("arrow-down", self.move_down, "下移选中项"),
            ], bootstyle="primary")
            updown.grid(row=0, column=1, columnspan=2, sticky="nsew", padx=2)
            self._set_tip(updown, "上移 / 下移选中项")
            mk_btn(obtn, text="精修", icon="pencil", bootstyle="success", command=self._retouch_selected).grid(row=0, column=3, sticky="nsew", padx=(2, 0))

            # 预览（固定高度窗口：图 fit/letterbox 进窗口，下方控件不再随图高抖动）
            ttk.Label(self.left_content, text="预览", anchor="w", style="Muted.TLabel", font=FONT_BOLD).pack(fill=tk.X, pady=(6, 2))
            self.preview_box = tk.Frame(self.left_content, width=300, height=150,
                                        bg=THEME["BG"], highlightthickness=1,
                                        highlightbackground=THEME["BORDER"])
            self.preview_box.pack(pady=2, ipady=4)
            self.preview_box.pack_propagate(False)  # 关键：禁止子 Label 撑大父框架 → 预览区高度恒定
            self.preview = ttk.Label(self.preview_box)
            self.preview.place(relx=0.5, rely=0.5, anchor="center")  # 图居中 letterbox 显示
            # 预览空态占位：160×90 渐变绿块（对应 HTML 原型 .preview .ph），无图时显示
            self.preview_ph_img = self._make_placeholder_img()
            self.preview_ph = tk.Label(self.preview_box, image=self.preview_ph_img, bg=THEME["BG"])
            self.preview_ph.place(relx=0.5, rely=0.5, anchor="center")

            # 夹逼范围（分组标题，无开关）→ 纵横比 / 大档 / 小档 三行
            ttk.Label(self.left_content, text="夹逼范围", anchor="w", style="Muted.TLabel", font=FONT_BOLD).pack(fill=tk.X, pady=(6, 2))
            self._build_ratio_tier_controls()

            # 旋转（单行图标按钮，无中文，仅此行为横排图标）
            grid = ttk.Frame(self.left_content)
            grid.pack(fill=tk.X, pady=(8, 3))
            rot_group = _make_icon_group(grid, [
                ("arrow-counterclockwise", lambda: self.rotate(90), "逆时针旋转 90°"),
                ("arrow-left-right", self.mirror, "水平镜像"),
                ("record-circle", self.center_box, "居中"),
                ("arrow-clockwise", lambda: self.rotate(-90), "顺时针旋转 90°"),
            ], bootstyle="primary")
            rot_group.pack(fill=tk.X, expand=True, padx=2)
            self._set_tip(rot_group, "旋转 / 镜像 / 居中")

            # 格式 / 质量
            fmt = ttk.Frame(self.left_content)
            fmt.pack(fill=tk.X, pady=(8, 3))
            ttk.Label(fmt, text="格式").pack(side=tk.LEFT)
            # 原生 ttkbootstrap 写法：ttk.Combobox(secondary) 直接出白底描边下拉，
            # 圆角与箭头由 ttkbootstrap 主题提供，无需自定义 TButton 样式
            self._fmt_combo = ttk.Combobox(fmt,
                                           textvariable=self.out_format,
                                           values=("JPEG", "PNG"),
                                           state="readonly",
                                           bootstyle="secondary",
                                           width=6)
            self._fmt_combo.pack(side=tk.LEFT, padx=(2, 0))
            ttk.Label(fmt, text="质量").pack(side=tk.LEFT, padx=(8, 0))
            ttk.Spinbox(fmt, textvariable=self.quality, from_=10, to=100,
                        increment=1, width=4, justify="center").pack(side=tk.LEFT, padx=2)

            # ---- 运行日志面板（左下角空位）----
            # 标题改为「保存日志」且可点击触发保存；面板内不再另置按钮。
            log_head = ttk.Frame(self.left_content)
            ttk.Button(log_head, text="保存日志", bootstyle="link",
                       command=self._save_log).pack(side=tk.LEFT)
            log_frame = ttk.LabelFrame(self.left_content, labelwidget=log_head)
            log_frame.pack(fill=tk.X, padx=4, pady=(8, 4))
            log_row = ttk.Frame(log_frame)
            log_row.pack(fill=tk.X, padx=3, pady=3)
            self.log_text = tk.Text(log_row, height=6, wrap="word", state="disabled",
                                    font=(FONT[0], max(8, FONT[1] - 3)), bg=THEME["BG"], fg=THEME["TEXT"],
                                    relief="flat", borderwidth=1, highlightthickness=0)
            self.log_text.pack(fill=tk.BOTH, expand=True)
            # 接管 stdout / stderr → 运行日志面板
            sys.stdout = _LogRedirector(self.log_text)
            sys.stderr = _LogRedirector(self.log_text)

            # ---- 中栏：画布（满宽，内缩 6px 留出空隙，避免拥挤）----
            center = ttk.Frame(mid)
            center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
            self.canvas = tk.Canvas(center, bg="#e8e8e8", cursor="cross", takefocus=1,
                                     highlightthickness=1, highlightbackground="#c4c4c4")
            self.canvas.pack(fill=tk.BOTH, expand=True)
            self.canvas.bind("<ButtonPress-1>", self.on_down)
            self.canvas.bind("<B1-Motion>", self.on_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_up)
            self.canvas.bind("<Configure>", self._on_canvas_configure)
            self._pending_draw = None

            # 底部：薄状态栏，与根背景同色，不留硬白边
            # 左下角（progress_var）= 操作结果文案（导入完成、导出成功、错误提示等）
            # 右下角（info_var）   = 计数主导的当前状态：
            #                        step1 阶段显示「已导入 N 张 · 请点击规范素材尺寸」
            #                        step2 阶段显示「[x/N] 文件名 宽×高」
            bottom = ttk.Frame(self.root)
            bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=0, pady=0)
            # 署名：点击切换主题，文字色在 _apply_ctk_visuals 里跟随当前 PRIMARY 重染
            self.signature = ttk.Label(bottom, text="@pandipper", foreground=THEME["PRIMARY"],
                                       cursor="hand2", font=FONT_HINT)
            self.signature.pack(side=tk.LEFT, padx=(8, 6), pady=4)
            self.signature.bind("<Button-1>", lambda _e: self._cycle_theme())
            self._set_tip(self.signature, "点击切换主题")
            # info 先 pack：Tk 按 pack 顺序分配空腔，先登记者优先拿满自身所需宽度，
            # 保证「[i/N] 文件名 宽×高」这类常驻状态不会被偏长的操作提示挤掉
            self.info = ttk.Label(bottom, textvariable=self.info_var, anchor="e")
            self.info.pack(side=tk.RIGHT, padx=(4, 8), pady=4)
            self.progress = ttk.Label(bottom, textvariable=self.progress_var, anchor="w")
            self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4), pady=4)

            # 日志面板已就绪（stdout 重定向在本方法内装好），补写首屏缓存的主题错误
            self._flush_theme_errors()

        def _open_settings_menu(self, widget):
            """设置按钮：弹出式二级菜单面板（窗口预览 / 字号调节 / 打开配置 / 清空日志）。"""
            try:
                if self._settings_menu:
                    self._settings_menu.destroy()
            except Exception:
                pass
            popup = tk.Toplevel(self.root)
            popup.wm_overrideredirect(True)
            popup.configure(bg=THEME["SURFACE"])
            popup.attributes("-topmost", True)
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            popup.geometry(f"+{x}+{y}")

            # 关闭菜单的辅助函数
            def _close():
                try:
                    popup.destroy()
                except Exception:
                    pass
                self._settings_menu = None

            # 1. 窗口预览开关
            state = "✓ 开" if self._preview_on else "✗ 关"
            ctk.CTkButton(
                popup, text=f"窗口预览：{state}",
                command=lambda: [self._toggle_preview(), self._open_settings_menu(widget)],
                fg_color="transparent", hover_color=THEME["SURFACE"],
                text_color=THEME["TEXT"], anchor="w", height=32,
                font=FONT,
            ).pack(fill=tk.X, padx=4, pady=2)

            # 2. 字号调节：左/右小三角（chevron）逐 1 级调整
            font_row = ctk.CTkFrame(popup, fg_color="transparent", height=34)
            font_row.pack(fill=tk.X, padx=4, pady=2)
            font_row.pack_propagate(False)
            ctk.CTkLabel(font_row, text="字号", font=FONT, text_color=THEME["TEXT"]).pack(side=tk.LEFT, padx=(4, 8))

            def _change_font(delta):
                new_size = max(8, min(24, self.cfg.get("font_size", 12) + delta))
                if new_size != self.cfg.get("font_size", 12):
                    self.cfg["font_size"] = new_size
                    self._save_cfg()
                    self._apply_theme()
                    # CustomTkinter 的字体是构建时捕获的，不随 ttk style 刷新，
                    # 不重刷就会出现「ttk 控件字号变了、CTk 按钮还是旧的」的割裂
                    self._apply_ctk_visuals()
                    # 重建本菜单，让面板自身也用上新字号（与「窗口预览」开关同一套路）
                    self._open_settings_menu(widget)

            left_img = _make_icon("chevron-left", 14, THEME["TEXT"])
            right_img = _make_icon("chevron-right", 14, THEME["TEXT"])
            ctk.CTkButton(font_row, text="", image=left_img, width=28, height=28,
                          fg_color=THEME["BG"], hover_color=THEME["PRIMARY"],
                          text_color=THEME["TEXT"], command=lambda: _change_font(-1)).pack(side=tk.LEFT, padx=2)
            self._font_size_lbl = ctk.CTkLabel(font_row, text=str(self.cfg.get("font_size", 12)),
                                               font=FONT, width=30, text_color=THEME["TEXT"])
            self._font_size_lbl.pack(side=tk.LEFT, padx=4)
            ctk.CTkButton(font_row, text="", image=right_img, width=28, height=28,
                          fg_color=THEME["BG"], hover_color=THEME["PRIMARY"],
                          text_color=THEME["TEXT"], command=lambda: _change_font(1)).pack(side=tk.LEFT, padx=2)

            # 2.5 主题切换（点击直接切到字母顺序的下一个主题，循环）
            ctk.CTkButton(
                popup, text="主题",
                command=lambda: [self._cycle_theme(), _close()],
                fg_color="transparent", hover_color=THEME["SURFACE"],
                text_color=THEME["TEXT"], anchor="w", height=32,
                font=FONT,
            ).pack(fill=tk.X, padx=4, pady=2)

            # 3. 打开配置 / 清空日志
            ctk.CTkButton(
                popup, text="打开配置文件 (config.json)",
                command=lambda: [self._open(self.config_path), _close()],
                fg_color="transparent", hover_color=THEME["SURFACE"],
                text_color=THEME["TEXT"], anchor="w", height=32,
                font=FONT,
            ).pack(fill=tk.X, padx=4, pady=2)
            ctk.CTkButton(
                popup, text="清空运行日志",
                command=lambda: [self._clear_log(), _close()],
                fg_color="transparent", hover_color=THEME["SURFACE"],
                text_color=THEME["TEXT"], anchor="w", height=32,
                font=FONT,
            ).pack(fill=tk.X, padx=4, pady=2)

            self._settings_menu = popup
            # 点击菜单外部或按 Esc 关闭
            popup.bind("<Escape>", lambda _e: _close())
            popup.bind("<FocusOut>", lambda _e: _close())
            popup.focus_set()

        def _cycle_theme(self):
            """设置 → 主题：点击直接切到字母顺序的下一个主题（循环），并持久化。"""
            choices = sorted(THEME_CHOICES)
            current = self.cfg.get("theme", "minty")
            idx = choices.index(current) if current in choices else 0
            next_theme = choices[(idx + 1) % len(choices)]
            self.cfg["theme"] = next_theme
            self._save_cfg()
            self._apply_theme()
            self._apply_ctk_visuals()

        def _toggle_preview(self):
            """切换窗口预览：开启后重绘当前图，关闭后清屏（拖动/滚动不再卡顿）。"""
            self._preview_on = not self._preview_on
            if self._preview_on:
                self._on_canvas_configure()   # 触发一次防抖重绘
            else:
                self._draw()                  # 关闭时立即清屏并显示提示

        # ---------------- 美化版消息框 ----------------
        # 统一走 ttkbootstrap 的 Messagebox，样式跟随当前主题；按钮文案用中文，
        # localize=False 防止 MessageCatalog 再翻译一遍。
        def _msg_info(self, title: str, message: str) -> None:
            Messagebox.show_info(message=message, title=title, parent=self.root,
                                 buttons=["确定:primary"], localize=False, width=60)

        def _msg_error(self, title: str, message: str) -> None:
            Messagebox.show_error(message=message, title=title, parent=self.root,
                                  buttons=["确定:danger"], localize=False, width=60)

        def _msg_yesno(self, title: str, message: str) -> bool:
            """返回 True = 用户点了「是」。Esc / 关闭窗口都算取消。"""
            ans = Messagebox.yesno(message=message, title=title, parent=self.root,
                                   buttons=["否:secondary", "是:primary"],
                                   localize=False, width=64)
            return ans == "是"

        def _msg_yesno_rich(self, title: str, lines) -> bool:
            """富文本确认框：每行可独立 bootstyle 颜色。返回 True = 用户点「是"。"""
            from ttkbootstrap.dialogs.message import _alert_icon
            dialog = _RichMessageDialog(
                lines=lines, title=title, parent=self.root,
                buttons=["否:secondary", "是:primary"],
                icon=_alert_icon("question"), alert=False, localize=False)
            dialog.show()
            return dialog.result == "是"

        # ---------------- 导入 ----------------
        def import_folder(self):
            d = filedialog.askdirectory(title="选择源图片文件夹")
            if d:
                self.source_paths = [os.path.join(d, n) for n in list_source_images(d)]
                # 右下角 = 计数/当前状态；左下角 = 操作结果
                self.info_var.set(
                    f"已导入 {len(self.source_paths)} 张源图（原图保留在原位置）"
                    f" —— 请点击顶部「规范素材尺寸」按钮生成规范素材图。")
                self.progress_var.set("")
            if not self.queue:
                self._show_import_preview()

        def import_files(self):
            fs = filedialog.askopenfilenames(title="选择图片文件", filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp")])
            if fs:
                self.source_paths = list(fs)  # 替换当前源
                self.info_var.set(
                    f"已导入 {len(self.source_paths)} 张源图（原图保留在原位置）"
                    f" —— 请点击顶部「规范素材尺寸」按钮生成规范素材图。")
                self.progress_var.set("")
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

        def _clamp_range(self):
            """当前档位推算出的短边夹逼区间 [下限, 上限]。

            档位在右栏可随时改，所以所有面向用户的文案都必须现算，不能写死 720/1440，
            否则用户把大档改成 2000×1200 后弹窗还在说 1440，就成了假信息。
            """
            t = self.cfg.get("tiers") or {}
            sm = t.get("small") or {"w": 1280, "h": 720}
            lg = t.get("large") or {"w": 2560, "h": 1440}
            return (min(int(sm["w"]), int(sm["h"])),
                    min(int(lg["w"]), int(lg["h"])))

        def _confirm_step1(self, sources, label) -> bool:
            """step1 执行前的确认弹窗：按**当前档位**实时列出处理效果。

            用富文本对话框把「处理张数」「档位尺寸」「短边夹逼上下限」等着重
            颜色标注，帮助用户一眼抓住变化值。
            """
            t = self.cfg.get("tiers") or {}
            sm = t.get("small") or {"w": 1280, "h": 720}
            lg = t.get("large") or {"w": 2560, "h": 1440}
            lo, hi = self._clamp_range()
            n = len(sources)
            lines = [
                _RichLine(f"即将处理 {n} 张图片（来源：{label}）", style="dark"),
                _RichLine(""),
                _RichLine("当前档位设置", style="secondary"),
                _RichLine(f"        小档    {sm['w']} × {sm['h']}", style="primary"),
                _RichLine(f"        大档    {lg['w']} × {lg['h']}", style="primary"),
                _RichLine(""),
                _RichLine(f"step1 会把每张图按「短边」夹逼到 {lo} ~ {hi}：",
                          style="dark"),
                _RichLine(f"        ●  短边 < {lo}", style="secondary"),
                _RichLine(f"           等比放大，短边拉到 {lo}", style="danger"),
                _RichLine(f"        ●  {lo} ≤ 短边 ≤ {hi}", style="secondary"),
                _RichLine("           保持原尺寸，不做任何缩放", style="secondary"),
                _RichLine(f"        ●  短边 > {hi}", style="secondary"),
                _RichLine(f"           等比缩小，短边压到 {hi}", style="danger"),
                _RichLine(""),
                _RichLine("全程保持原始宽高比，不裁剪、不拉伸。", style="secondary"),
                _RichLine("源图不会被修改，结果写入「规范素材图/」文件夹。",
                          style="secondary"),
                _RichLine(""),
                _RichLine("是否继续执行？", style="dark"),
            ]
            return self._msg_yesno_rich("确认执行「规范素材尺寸」", lines)

        def run_step1(self):
            # 重入保护：连点按钮会起多个 worker 线程，同时往同一批文件名写 JPEG，
            # 轻则互相覆盖、重则半张图。这里直接挡掉，并给出可见反馈。
            if getattr(self, "_step1_busy", False):
                self._msg_info(
                    "提示",
                    "「规范素材尺寸」正在处理中，请等这一批跑完。\n"
                    "（想中止可按 Esc，已完成的图片会保留）")
                return
            sources, label = self._resolve_step1_sources()
            if not sources:
                self._msg_info(
                    "提示",
                    "没有可处理的图片。\n"
                    "请先点左侧「导入文件夹 / 导入文件」把图片加入导入队列，再点此按钮。")
                return
            # 执行前确认：把 step1 的实际效果（按当前档位算出来）摆给用户看，
            # 避免新用户不知道这一步会做什么、会不会动到源图。
            if not self._confirm_step1(sources, label):
                self.progress_var.set("已取消「规范素材尺寸」（未处理任何图片）")
                return
            self._step1_label = label
            self._step1_busy = True
            self._step1_cancel = False
            self.progress_var.set(
                f"规范素材尺寸：处理「{label}」共 {len(sources)} 张…（按 Esc 可中止）")
            self.root.config(cursor="watch")
            import threading

            def worker():
                def cb(i, total, src):
                    # 在后台线程里读取消标志，通过返回值告诉 process_step1 中止
                    if getattr(self, "_step1_cancel", False):
                        return False
                    self.root.after(0, lambda: self.progress_var.set(
                        f"规范素材尺寸 {i}/{total}（来源：{label}）"))
                    return True
                try:
                    ok, skip = process_step1(
                        sources, self.dirs["spec"],
                        quality=self.quality.get(), on_progress=cb,
                        tiers=self.cfg["tiers"])
                    if getattr(self, "_step1_cancel", False):
                        self.root.after(0, lambda: self.progress_var.set(
                            f"已中止「规范素材尺寸」：本次完成 {ok} 张，跳过 {skip} 张"))
                    else:
                        self.root.after(0, lambda: self.progress_var.set(
                            f"规范素材尺寸完成：成功 {ok}，跳过 {skip}；"
                            f"按短边夹逼到 [{self._clamp_range()[0]},{self._clamp_range()[1]}]"
                            f"（短边达标即不缩放），原比例不变"))
                except Exception as e:
                    self.root.after(0, lambda: self._msg_error("错误", str(e)))
                finally:
                    # 先清标志再回调：_after_step1 里若再触发 run_step1 不会被误挡
                    self._step1_busy = False
                    self._step1_cancel = False
                    self.root.after(0, self._after_step1)

            threading.Thread(target=worker, daemon=True).start()

        def cancel_step1(self, event=None):
            """Esc 中止正在进行的「规范素材尺寸」。已写入的图片保留。"""
            if not getattr(self, "_step1_busy", False):
                return "break"
            self._step1_cancel = True
            self.progress_var.set("正在中止「规范素材尺寸」…（已完成的图片会保留）")
            return "break"

        def _after_step1(self):
            self.root.config(cursor="")
            # 这批导入源已处理为规范素材图，清空导入列表并刷新状态
            self.source_paths = []
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

        def _save_log(self):
            """保存运行日志到程序同级目录：<年月日_时分>run.log（覆盖写）。"""
            try:
                import datetime as _dt
                stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
                path = os.path.join(self.work_dir, f"{stamp}run.log")
                self.log_text.configure(state="normal")
                text = self.log_text.get("1.0", tk.END)
                self.log_text.configure(state="disabled")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, f"\n[日志已保存] {path}\n")
                self.log_text.configure(state="disabled")
                self.log_text.see(tk.END)
            except Exception as e:
                try:
                    self.log_text.configure(state="normal")
                    self.log_text.insert(tk.END, f"\n[保存失败] {e}\n")
                    self.log_text.configure(state="disabled")
                    self.log_text.see(tk.END)
                except Exception:
                    pass

        def _queue_signature(self):
            """目录签名（文件名+size+mtime），用于 FocusIn 短路：目录自上次扫描后无变化则跳过整轮重扫。"""
            d = self.dirs.get("spec")
            if not d or not os.path.isdir(d):
                return None
            try:
                entries = []
                for fn in os.listdir(d):
                    if is_image(fn):
                        st = os.stat(os.path.join(d, fn))
                        entries.append((fn, st.st_size, int(st.st_mtime)))
                return tuple(sorted(entries))
            except OSError:
                return None

        def _focus_rescan(self):
            """窗口切回时重扫队列目录，把外部新增/删除的素材反映到列表。

            关键：只同步队列，**不重新解码当前图**。
            以前这里无条件调用 `_load_current()`，两个后果：
              1. 每次 Alt-Tab 切回都要重读磁盘 + PIL 解码一遍当前图（大图约
                 140 ms 的可见卡顿），而图根本没变；
              2. `_load_current()` 内部会 `_place_box_default()`，把用户已经
                 拖好的取景框重置回默认位置——切个窗口就丢进度，比卡顿更糟。
            先比目录签名（文件名+size+mtime）：没变就直接返回，连 listdir
            都省了；变了才继续——且只有当前图确实已不在队列（被删/被换）时才重新加载。
            """
            sig = self._queue_signature()
            if sig == getattr(self, "_queue_sig", None):
                return  # 目录自上次扫描后无变化，无需任何操作
            self._queue_sig = sig
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
                return          # 图没变，什么都不用做
            self.idx = 0
            self._load_current()

        # ---------------- 加载/绘制 ----------------
        def _load_current(self):
            if not self.queue:
                self._clear_canvas()
                self.info_var.set("素材队列为空：请先导入图片并「规范素材尺寸」。")
                return
            # 切图前取消尚未执行的预览渲染：旧图的底图缓存即将失效，
            # 留着定时器会在加载完新图后再多渲染一次无用帧
            if self._pending_pv:
                self.root.after_cancel(self._pending_pv)
                self._pending_pv = None
            self.idx = max(0, min(self.idx, len(self.queue) - 1))
            name = self.queue[self.idx]
            path = os.path.join(self.dirs["spec"], name)
            try:
                self.img = _open_rgb(path)
            except Exception as e:
                self._msg_error("无法打开", f"{name}\n{e}")
                return
            self.img_name = name
            self._place_box_default()
            self._draw()
            self._render_preview()
            # 布局可能尚未完成（如 step1 后台线程刚回主线程），延迟再重绘一次确保画布不卡灰色
            self.root.after(40, self._draw)
            # 右下角 = 计数主导的当前图状态；左下角 = 操作结果（不在此处覆盖）
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
                self.img = _open_rgb(path)
            except Exception as e:
                self._msg_error("无法打开", f"{name}\n{e}")
                return
            self.img_name = name
            self._place_box_default()
            self._draw()
            self._render_preview()
            self.info_var.set(
                f"导入预览 {name}  {self.img.size[0]}×{self.img.size[1]} —— 需先「规范素材尺寸」")

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
            if not self._preview_on:
                return  # 预览关闭时画布完全不重绘 → 拖动/滚动零开销
            if self._pending_draw:
                self.root.after_cancel(self._pending_draw)
            self._pending_draw = self.root.after(120, self._draw)

        def _show_hint(self, text):
            """画布提示态（预览关闭 / 尚未导入图片）。只维持一个 text item。"""
            try:
                cw = self.canvas.winfo_width() or 800
                ch = self.canvas.winfo_height() or 600
            except Exception:
                return
            if getattr(self, "_draw_mode", None) != "hint":
                self._clear_canvas()
                self._draw_mode = "hint"
                self._hint_item = None
            if cw <= 2 or ch <= 2:
                return
            # 存活校验：Tk 对已删除的 item id 是静默的（coords/itemconfigure 都
            # 不抛异常、只返回空），所以光靠 try/except 兜不住「item 被外部删掉」
            # 这种情况——会一直走更新分支、一直什么都不显示。必须显式问一下。
            # canvas.type() 对活着的 item 返回 'text' 等类型名，对已删的返回 None。
            if self._hint_item is not None and not self.canvas.type(self._hint_item):
                self._hint_item = None
            try:
                if self._hint_item is None:
                    self._hint_item = self.canvas.create_text(
                        cw // 2, ch // 2, text=text,
                        fill=THEME["HINT"], font=FONT_HINT, tag="hint")
                else:
                    self.canvas.coords(self._hint_item, cw // 2, ch // 2)
                    self.canvas.itemconfigure(
                        self._hint_item, text=text,
                        fill=THEME["HINT"], font=FONT_HINT)
            except Exception:
                # 图元可能已被外部清空（如切主题重建画布），重置后下一帧重建
                self._hint_item = None
                self._draw_mode = None

        def _update_ui_items(self, x0, y0, x1, y1):
            """裁剪框 + 九宫格 + 4 个角柄：首次创建，之后只移动坐标。

            原先每帧都 `delete("all")` 再重建 10 个 canvas item（1 图 + 1 外框 +
            4 条九宫格线 + 4 个角柄）。拖动时这 10 个 item 的反复创建/销毁就是
            主要的每帧开销。改为创建一次、之后只用 `coords()` 移动，
            拖动预览的每帧成本显著下降。

            item 顺序固定：img / 外框 / 竖线×2 / 横线×2 / 角柄×4
            """
            it = getattr(self, "_ui_items", None)
            # 存活校验，不能省：Tk 对已删除的 item id 全程静默 —— coords() 返回
            # []、itemconfigure() 返回 {}、都不抛异常。所以一旦画布被外部清空
            # （最典型的就是切主题时重建画布），下面那个 except 分支根本不会
            # 触发，程序会拿着失效 id 一直「成功」地画到虚空里：画布永久空白、
            # 日志一行报错都没有。canvas.type() 对活着的 item 返回类型名
            # （'image'/'rectangle'…），对已删的返回 None。
            if it is not None and not self.canvas.type(it["img"]):
                it = None
            if getattr(self, "_draw_mode", None) != "image" or not it:
                self.canvas.delete("all")
                img_item = self.canvas.create_image(
                    self.offx, self.offy, image=self.tk_img, anchor="nw")
                items = [self.canvas.create_rectangle(
                    x0, y0, x1, y1, outline="#ff3b30", width=2, tag="ui")]
                for fx in (1 / 3, 2 / 3):
                    items.append(self.canvas.create_line(
                        x0 + (x1 - x0) * fx, y0, x0 + (x1 - x0) * fx, y1,
                        fill="#ff3b30", width=1, dash=(4, 3), tag="ui"))
                for fy in (1 / 3, 2 / 3):
                    items.append(self.canvas.create_line(
                        x0, y0 + (y1 - y0) * fy, x1, y0 + (y1 - y0) * fy,
                        fill="#ff3b30", width=1, dash=(4, 3), tag="ui"))
                for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                    items.append(self.canvas.create_rectangle(
                        px - 4, py - 4, px + 4, py + 4,
                        fill="#ff3b30", tag="ui"))
                self._ui_items = {"img": img_item, "box": items}
                self._draw_mode = "image"
                self._tk_img_dirty = False
                return

            try:
                self.canvas.coords(it["img"], self.offx, self.offy)
                if getattr(self, "_tk_img_dirty", False):
                    self.canvas.itemconfigure(it["img"], image=self.tk_img)
                    self._tk_img_dirty = False
                b = it["box"]
                self.canvas.coords(b[0], x0, y0, x1, y1)
                self.canvas.coords(b[1],
                                   x0 + (x1 - x0) / 3, y0, x0 + (x1 - x0) / 3, y1)
                self.canvas.coords(b[2],
                                   x0 + (x1 - x0) * 2 / 3, y0, x0 + (x1 - x0) * 2 / 3, y1)
                self.canvas.coords(b[3],
                                   x0, y0 + (y1 - y0) / 3, x1, y0 + (y1 - y0) / 3)
                self.canvas.coords(b[4],
                                   x0, y0 + (y1 - y0) * 2 / 3, x1, y0 + (y1 - y0) * 2 / 3)
                for i, (px, py) in enumerate(
                        ((x0, y0), (x1, y0), (x0, y1), (x1, y1))):
                    self.canvas.coords(b[5 + i], px - 4, py - 4, px + 4, py + 4)
            except Exception:
                # item 已失效（切主题重建画布等）：丢弃缓存，下一帧整体重建
                self._ui_items = None
                self._draw_mode = None
                self._update_ui_items(x0, y0, x1, y1)

        def _draw(self):
            self._pending_draw = None
            if not self._preview_on:
                self._show_hint("窗口预览已关闭（设置 → 窗口预览：开）")
                return
            if self.img is None:
                # 空态提示：让「空」变成「在等导入」，而非「坏没坏」。
                # 文案要点名下一步动作（新用户最容易卡在「不知道还要点规范素材尺寸」）。
                self._show_hint("导入图片后，请先点击顶部「规范素材尺寸」按钮")
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
                if self._pending_draw:
                    self.root.after_cancel(self._pending_draw)
                self._pending_draw = self.root.after(80, self._draw)
                return
            self.offx = (cw - dw) // 2
            self.offy = (ch - dh) // 2
            # 仅当显示尺寸或源图变化时才重做昂贵的 PIL 整图缩放；
            # 拖动裁剪框 / 窗口抖动 / Focus 等尺寸不变的重绘可跳过，显著降低卡顿
            if (getattr(self, "_tk_dw", -1) != dw or getattr(self, "_tk_dh", -1) != dh
                    or getattr(self, "_tk_src", None) is not self.img):
                disp = self.img.resize((dw, dh), _RESAMPLE)
                self.tk_img = ImageTk.PhotoImage(disp)
                self._tk_dw, self._tk_dh, self._tk_src = dw, dh, self.img
                self._tk_img_dirty = True
            x0 = self.offx + self.box[0] * self.fit_scale
            y0 = self.offy + self.box[1] * self.fit_scale
            x1 = self.offx + self.box[2] * self.fit_scale
            y1 = self.offy + self.box[3] * self.fit_scale
            self._update_ui_items(x0, y0, x1, y1)

        def _clear_canvas(self):
            # 取消尚未执行的预览渲染，避免清画布后定时器仍在旧图上渲染一帧
            if self._pending_pv:
                self.root.after_cancel(self._pending_pv)
                self._pending_pv = None
            self.canvas.delete("all")
            self.tk_img = None
            self._tk_dw = self._tk_dh = -1
            self._tk_src = None
            # 增量绘制的缓存状态必须一并清空：delete("all") 之后那些 item id
            # 已不存在，下一帧若还拿去 coords()/itemconfigure() 会抛 TclError
            self._draw_mode = None
            self._ui_items = None
            self._hint_item = None
            self._tk_img_dirty = True

        def _render_preview(self):
            """右下结果预览。拖动时每帧都会调用，故做两级优化：

            1) 底图缓存：把「先全分辨率 COVER 裁切、再缩到 290px」换成
               「先把整图缩到约 320px 量级的底图，再在底图上裁窗」——两步对易，
               肉眼无差别，单帧从 15~202ms 降到约 0.2ms。
               导出（confirm_crop）仍走全分辨率 crop_for_tier，画质不受影响。
            2) 失效靠 key 自动判定：切图 / 旋转 / 镜像 → id(self.img) 变；
               改档位 / 角柄缩放取景框 → (bw, bh) 变。无需手动 invalidate。
            """
            if self.img is None:
                self.preview.configure(image="")
                self.preview_ph.place(relx=0.5, rely=0.5, anchor="center")  # 显示占位
                return
            self.preview_ph.place_forget()  # 有图则隐藏占位
            bw, bh = self._current_box_size()
            iw, ih = self.img.size
            key = (id(self.img), bw, bh)
            if self._pv_key != key or self._pv_base is None:
                cs = cover_scale(iw, ih, bw, bh)
                sw, sh = iw * cs, ih * cs
                # 系数按「取景框宽 bw」算，而不是 COVER 后的宽度 sw：
                # 全景图（如 4800×720）COVER 后 sw 可达 bw 的数倍，若按 sw 取系数会把底图
                # 缩得过小，裁出的窗口甚至小于预览窗（290×140），预览直接缩水成一小块。
                # 480px 是实测质量/成本平衡点（对比 320/480/640，最坏像素差 2.6 最优）。
                m = min(1.0, 480.0 / bw) if bw > 0 else 1.0
                # 兜底：极端长条图 COVER 后尺寸会暴涨，限制底图总像素避免单次 resize 过大
                area = (sw * m) * (sh * m)
                if area > 1_200_000:
                    m *= (1_200_000 / area) ** 0.5
                self._pv_base = self.img.resize((max(1, round(sw * m)),
                                                 max(1, round(sh * m))), _RESAMPLE)
                self._pv_scale = m
                self._pv_key = key
            m = self._pv_scale
            fx, fy = self._box_anchor()
            # 底图已是 COVER 比例，取景框按同一系数缩放后 cover_scale 恒为 1，
            # 故此结果与全分辨率 crop_for_tier 严格等价（仅分辨率更低，仅用于预览）
            out = crop_for_tier(self._pv_base, max(1, round(bw * m)), max(1, round(bh * m)), fx, fy)
            pw, ph = 290, 140   # 匹配预览窗口内尺寸（300x150 减去描边），恒定不变
            out.thumbnail((pw, ph), _RESAMPLE)
            self.preview_tk = ImageTk.PhotoImage(out)
            self.preview.configure(image=self.preview_tk)

        def _do_render_preview(self):
            """合并调度入口：由 on_drag 经 after(0) 排到下一帧，避免一帧内重复渲染。"""
            self._pending_pv = None
            self._render_preview()

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
            if getattr(self, "drag", None) is None or self.img is None:
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
            # 右下角预览节流：限制刷新频率（≤25fps），避免高频 mousemove 每次都重算预览
            if self._pending_pv is None:
                self._pending_pv = self.root.after(40, self._do_render_preview)

        def on_up(self, event):
            self.drag = None
            # 松手后强制刷新到精确终态：取消挂起的节流渲染并立即出图，
            # 避免「拖动时预览停在最后一帧节流位」的观感
            if self._pending_pv is not None:
                self.root.after_cancel(self._pending_pv)
                self._pending_pv = None
            self._render_preview()
            self._draw()

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
                # 右下角 info_var 已自动变成 [1/N] name W×H，左下角只保留操作结果
                self.progress_var.set(f"已导出：{os.path.basename(dest)}")
            else:
                self.img = None
                self.img_name = None
                self._clear_canvas()
                self.info_var.set("队列已全部处理完成。")
                self.progress_var.set("队列已全部处理完成。")

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
                self._msg_error("返工失败", str(e))

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
                self._msg_error("精修失败", str(e))

        # ---------------- 纵横比 / 档位（夹逼范围）----------------
        def _build_ratio_tier_controls(self):
            lc = self.left_content
            # v8 网格：行首开关锁 73px、两个步进器权重 1 撑开、分隔符锁 20px，
            # 整行与旋转行同宽（均 full-width），故左右边缘对齐。
            TOGGLE_W, SEP_W = 73, 20

            def _row(parent):
                f = ttk.Frame(parent)
                f.pack(fill=tk.X, pady=3)
                f.columnconfigure(0, minsize=TOGGLE_W, weight=0)
                f.columnconfigure(1, weight=1)
                f.columnconfigure(2, minsize=SEP_W, weight=0)
                f.columnconfigure(3, weight=1)
                return f

            # 纵横比（行首开关 + 宽:高 步进）
            rf = _row(lc)
            self.ratio_btn = self._make_header_btn(rf, "纵横比", self.toggle_ratio_lock)
            self.ratio_btn.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
            wf = self._make_stepper(rf, self.ratio_w, 1, 4, self._on_ratio_changed)
            wf.grid(row=0, column=1, sticky="nsew", padx=2)
            ttk.Label(rf, text=":", anchor="center", width=2).grid(row=0, column=2, sticky="nsew")
            hf = self._make_stepper(rf, self.ratio_h, 1, 4, self._on_ratio_changed)
            hf.grid(row=0, column=3, sticky="nsew", padx=(2, 0))
            self.ratio_entries = [wf, hf]

            # 大档 / 小档（行首单选 + 宽×高 步进）
            self.tier_vars = {}
            self.tier_btns = {}
            self.tier_h_entries = {}
            for key in ("large", "small"):
                t = self.cfg["tiers"][key]
                row = _row(lc)
                btn = self._make_header_btn(row, t["label"], lambda k=key: self._set_tier_active(k))
                btn.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
                self.tier_btns[key] = btn
                svars = {}
                wf = self._make_stepper(row, tk.IntVar(value=t["w"]), 1, 4, (lambda k=key: self._on_tier_changed(k, "w")))
                wf.grid(row=0, column=1, sticky="nsew", padx=2)
                svars["w"] = wf._var
                ttk.Label(row, text="×", anchor="center", width=2).grid(row=0, column=2, sticky="nsew")
                hf = self._make_stepper(row, tk.IntVar(value=t["h"]), 1, 4, (lambda k=key: self._on_tier_changed(k, "h")))
                hf.grid(row=0, column=3, sticky="nsew", padx=(2, 0))
                svars["h"] = hf._var
                self.tier_vars[key] = svars
                self.tier_h_entries[key] = hf
            self._refresh_headers()

        def _make_header_btn(self, parent, text, command, icon=None):
            """行首开关按钮：点击切换状态（纵横比=开/关，档位=选中/未选）。
            固定 width 让 纵横比/大档/小档 三行左列宽度一致。"""
            return mk_btn(parent, text=text, icon=icon, bootstyle="secondary-outline", command=command, width=85)

        def _make_stepper(self, parent, var, step, width, on_step=None):
            """Spinbox 步进器：上下箭头由主题引擎自绘（等大对称），可连点；可直接手填。"""
            sb = ttk.Spinbox(parent, textvariable=var, from_=1, to=9999,
                             increment=step, width=width, justify="center")
            sb._var = var
            if on_step:
                # 防抖：command（连点/长按上下箭头）与 KeyRelease（手输）都会高频触发，
                # 未防抖时每触发一次就全量重绘 + 写一次 config.json，长按箭头会把 UI 拖死，
                # 还会把中间值（如 w=2）逐次持久化。合并到 120ms 后执行一次。
                _t = {"id": None}

                def _fire():
                    _t["id"] = None
                    on_step()

                def _schedule():
                    if _t["id"]:
                        self.root.after_cancel(_t["id"])
                    _t["id"] = self.root.after(120, _fire)

                sb.configure(command=_schedule)
                sb.bind("<KeyRelease>", lambda ev: _schedule())
                sb.bind("<FocusOut>", lambda ev: _schedule())
            return sb

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
            # 激活态用 secondary 实心填充，未激活用 secondary-outline（透明底描边）。色取自 THEME。
            try:
                if on:
                    btn.configure(fg_color=THEME["SECONDARY"], hover_color=THEME["SECONDARY_H"], text_color="#ffffff")
                else:
                    btn.configure(fg_color="transparent", hover_color=THEME["HOVER_LIGHT"], text_color=THEME["SECONDARY"])
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

        # ---------------- 移除 / 返工 / 精修（队列选中项）----------------
        def _pop_queue_item(self, i):
            """从内存队列 + 列表框移除第 i 项，并校正当前下标 / 画布。"""
            del self.queue[i]
            self.queue_list.delete(i)
            if i < self.idx:
                self.idx -= 1
            if self.queue:
                self.idx = min(self.idx, len(self.queue) - 1)
                self._load_current()
            else:
                self.idx = 0
                self.img = None
                self.img_name = None
                self._clear_canvas()
                self.info_var.set("队列已空。")

        def _remove_selected(self):
            """移除：把选中项移出队列（文件保留到 规范素材图/已移除，不真正删除）。"""
            sel = self.queue_list.curselection()
            if not sel:
                self.progress_var.set("请先在队列中选择要移除的项目。")
                return
            i = sel[0]
            name = self.queue[i]
            src = os.path.join(self.dirs["spec"], name)
            if not os.path.exists(src):
                self._pop_queue_item(i)
                self.progress_var.set(f"已移除（文件不在磁盘）：{name}")
                return
            # 无需弹窗确认：按钮已放远、不易误触；文件仅移入「已移除」，不真正删除。
            dest_dir = os.path.join(self.dirs["spec"], "已移除")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, name)
            if os.path.exists(dest):
                base, ext = os.path.splitext(name)
                n = 1
                while os.path.exists(os.path.join(dest_dir, f"{base}_{n}{ext}")):
                    n += 1
                dest = os.path.join(dest_dir, f"{base}_{n}{ext}")
            try:
                shutil.move(src, dest)
            except Exception as e:
                self._msg_error("移除失败", str(e))
                return
            self._pop_queue_item(i)
            self.progress_var.set(f"已移除：{name}（保留于 规范素材图/已移除）")

        def _rework_selected(self):
            self.rework_prev()

        def _retouch_selected(self):
            self.retouch_prev()

        # ---------------- 主题 / 明暗 ----------------
        def _set_tip(self, widget, text):
            """轻量 tooltip（无额外依赖）：悬浮显示说明文字。"""
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry("+0+0")
            tk.Label(tip, text=text, background="#2C2C2A", foreground="#FFFFFF",
                     font=(FONT[0], 9), padx=6, pady=3,
                     relief="solid", borderwidth=1).pack()
            tip.withdraw()

            def _enter(_e):
                x = widget.winfo_rootx() + 12
                y = widget.winfo_rooty() + widget.winfo_height() + 4
                tip.wm_geometry(f"+{x}+{y}")
                tip.deiconify()

            def _leave(_e):
                tip.withdraw()

            widget.bind("<Enter>", _enter)
            widget.bind("<Leave>", _leave)

    _register_fonts()  # 注册 OPPO Sans（须在 Style/Window 之前，否则回退系统字体）
    # Windows DPI 感知：缩放 125%/150% 下，未声明 DPI 感知的进程会被位图拉伸，
    # ttkbootstrap 的圆角 PNG 元素因此看起来是直角。必须在建窗前声明。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # per-monitor v1（Win 8.1+）
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()    # 兜底（Win Vista+）
        except Exception:
            pass
    root = ttkb.Window(themename="minty")

    # 运行窗口图标（任务栏 / 标题栏）：优先用 Hokko.ico（256px，清晰），回退 logo.png。
    # 冻结态从 _MEIPASS / exe 同目录取；exe 文件图标由 build_exe.spec 的 icon= 决定。
    _icon_cands = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            _icon_cands += [os.path.join(sys._MEIPASS, "Hokko.ico"),
                            os.path.join(sys._MEIPASS, "logo.png")]
        _icon_cands += [os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "Hokko.ico"),
                        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "logo.png")]
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        _here = os.getcwd()
    _icon_cands += [os.path.join(_here, "Hokko.ico"), os.path.join(_here, "logo.png")]
    for _p in _icon_cands:
        if not os.path.isfile(_p):
            continue
        try:
            if os.path.splitext(_p)[1].lower() == ".ico":
                root.iconbitmap(_p)          # 多尺寸 ICO：任务栏/标题栏最清晰
            else:
                from PIL import Image, ImageTk
                _ic = Image.open(_p).convert("RGBA").resize((64, 64), Image.LANCZOS)
                root.iconphoto(True, ImageTk.PhotoImage(_ic))  # 同时作用于后续 Toplevel
            break
        except Exception as _e:
            print(f"[icon] 设置失败（{_p}）：{_e}")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
