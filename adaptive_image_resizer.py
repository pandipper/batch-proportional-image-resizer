#!/usr/bin/env python3
# MIT License
# Copyright (c) 2026 pandipper
"""
adaptive_image_resizer.py — 等比例批量缩放（不裁剪 / 不拉伸 / 不填充）

按源图宽度自动分档，把每张图归一化到 大(2560) / 中(1920) / 小(1280) 三档之一，
并对高度低于 720 的图做兜底放大到高 720。全程保持原始宽高比、画面完整，
供后续人工裁剪成 16:9 使用。

分档规则（仅缩小，不为了凑档而放大）：
    w > 2560            -> 目标宽 2560   （大档）
    1920 <= w <= 2560   -> 目标宽 1920   （中档）
    1280 <= w < 1920    -> 目标宽 1280   （小档）
    w < 1280 且 h >= 720 -> 保持原尺寸   （不放大，发虚比凑档更糟）
    w < 1280 且 h < 720  -> 高=720 兜底放大
    任意档算出的高 < 720  -> 覆盖为高 720，重算宽（高度兜底优先于宽度封顶，允许宽 > 2560）

用法:
    python adaptive_image_resizer.py --input <图片目录> [--output <输出目录>]
                                     [--quality 100] [--sort] [--recursive]

示例:
    python adaptive_image_resizer.py --input ./photos --sort
    python adaptive_image_resizer.py --input ./photos --output ./out --recursive

依赖:
    pip install pillow            # 任意较新版本均可（9 / 10 / 11 / 12），无需锁 12.3.0
    或: pip install -r requirements.txt
"""
import argparse
import os
import sys

from PIL import Image

# 重采样常量在不同 Pillow 版本名称不同：>=9.1 用 Image.Resampling.LANCZOS，
# 更早版本用 Image.LANCZOS。统一成 _LANCZOS 以兼容各种版本（无需锁死 12.3.0）。
try:
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    _LANCZOS = Image.LANCZOS

SUPPORTED = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def choose_target(w, h):
    """返回 (target_w, target_h)，等比、不裁。"""
    if w > 2560:
        tw = 2560
    elif w >= 1920:
        tw = 1920
    elif w >= 1280:
        tw = 1280
    else:  # w < 1280
        if h >= 720:
            return (w, h)                      # 保持原尺寸，不放大
        return (round(720 * w / h), 720)       # 仅按高兜底放大
    th = round(h * tw / w)
    if th < 720:                              # 高度兜底优先于宽度封顶
        th = 720
        tw = round(720 * w / h)
    return (tw, th)


def tier_name(tw):
    if tw >= 2560:
        return "large"
    if tw >= 1920:
        return "medium"
    if tw >= 1280:
        return "small"
    return "kept"


def process_file(src_path, out_dir, quality, do_sort):
    try:
        with Image.open(src_path) as img:
            w, h = img.size
            tw, th = choose_target(w, h)
            if (tw, th) == (w, h):
                return ("skip", src_path, (w, h), (tw, th))
            # 按需求不处理 EXIF 方向：直接以原始像素缩放（如后续需要可加
            # from PIL import ImageOps; img = ImageOps.exif_transpose(img)）
            rgb = img.convert("RGB")
            resized = rgb.resize((tw, th), _LANCZOS)
            base = os.path.splitext(os.path.basename(src_path))[0]
            ext = os.path.splitext(src_path)[1].lower()
            out_ext = ext if ext in SUPPORTED else ".jpg"
            save_dir = os.path.join(out_dir, tier_name(tw)) if do_sort else out_dir
            os.makedirs(save_dir, exist_ok=True)
            out_path = os.path.join(save_dir, base + out_ext)
            save_kwargs = {"optimize": True}
            if out_ext in (".jpg", ".jpeg", ".webp"):
                save_kwargs["quality"] = quality
            resized.save(out_path, **save_kwargs)
            return ("ok", src_path, (w, h), (tw, th))
    except Exception as e:  # noqa: BLE001 - 单文件失败不影响整批
        return ("error", src_path, None, str(e))


def collect_files(in_dir, out_dir, recursive):
    files = []
    out_abs = os.path.abspath(out_dir)
    if recursive:
        for root, _, names in os.walk(in_dir):
            if os.path.abspath(root) == out_abs:
                continue
            for n in names:
                if n.lower().endswith(SUPPORTED):
                    files.append(os.path.join(root, n))
    else:
        for n in os.listdir(in_dir):
            if n.lower().endswith(SUPPORTED):
                files.append(os.path.join(in_dir, n))
    return files


def main():
    ap = argparse.ArgumentParser(description="等比例批量缩放（自适应分档，不裁剪）")
    ap.add_argument("--input", required=True, help="图片所在目录")
    ap.add_argument("--output", default=None, help="输出目录（默认 <input>/adaptive_output）")
    ap.add_argument("--quality", type=int, default=100, help="JPG/WEBP 质量 1-100，默认 100（与 GUI 版一致，无损优先）")
    ap.add_argument("--sort", action="store_true", help="按 large/medium/small/kept 分目录")
    ap.add_argument("--recursive", action="store_true", help="递归处理子目录")
    args = ap.parse_args()

    in_dir = args.input
    out_dir = args.output or os.path.join(in_dir, "adaptive_output")
    if not os.path.isdir(in_dir):
        print(f"目录不存在: {in_dir}", file=sys.stderr)
        sys.exit(1)

    files = collect_files(in_dir, out_dir, args.recursive)
    if not files:
        print("未发现支持的图片文件。")
        return

    counts = {"ok": 0, "skip": 0, "error": 0}
    for f in files:
        status, path, src, tgt = process_file(f, out_dir, args.quality, args.sort)
        name = os.path.basename(path)
        if status == "ok":
            counts["ok"] += 1
            print(f"[缩放] {name}  {src} -> {tgt}")
        elif status == "skip":
            counts["skip"] += 1
            print(f"[跳过] {name}  {src} (已满足，不放大)")
        else:
            counts["error"] += 1
            print(f"[错误] {name}  {tgt}", file=sys.stderr)
    print(f"\n完成: 缩放 {counts['ok']} / 跳过 {counts['skip']} / 失败 {counts['error']}")
    print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
