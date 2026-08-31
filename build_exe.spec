# -*- mode: python ; coding: utf-8 -*-
# 打包脚本：把 batch_proportional_image_resizer.py 打成单文件 exe。
# 构建：pyinstaller build_exe.spec --noconfirm
# 产物：dist/batch_proportional_image_resizer.exe
import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# ---- 收集 customtkinter / ttkbootstrap 的全部子模块与资源（主题、字体、png）----
customtkinter_datas, customtkinter_binaries, customtkinter_hiddenimports = collect_all("customtkinter")
ttkbootstrap_datas, ttkbootstrap_binaries, ttkbootstrap_hiddenimports = collect_all("ttkbootstrap")

a = Analysis(
    ["batch_proportional_image_resizer.py"],
    pathex=[],
    binaries=[],
    datas=[
        # UI 子集字体：由 OPPO Sans 4.0.ttf(21.7 MiB) 静态实例化到 wght=600(SemiBold)
        # + 按 GB2312 字集子集化而来，仅 1.96 MiB，墨迹与原 SemiBold 逐像素一致。
        # 生成脚本 .workbuddy-ai/build_ui_font.py（构建期工具，不进 exe）。
        ("OPPO Sans UI.ttf", "."),
        # 品牌 logo：窗口图标（任务栏/标题栏）用 Hokko.ico（256px），回退 logo.png；
        # exe 文件图标由下方 EXE(icon="Hokko.ico") 决定。
        # 冻结态会被解压到 _MEIPASS，代码按 _MEIPASS → exe 同目录 → 脚本目录 回退读取。
        ("Hokko.ico", "."),
        ("logo.png", "."),
    ] + customtkinter_datas + ttkbootstrap_datas,
    hiddenimports=[
        "PIL._tkinter_finder",
    ] + customtkinter_hiddenimports + ttkbootstrap_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a.binaries += customtkinter_binaries + ttkbootstrap_binaries

# ---- 体积裁剪：剔除运行不需要的二进制扩展 ----
# _avif  : AVIF 解码器（压缩后约 4.1 MiB），工具仅支持 jpg/png/webp/bmp/tif，不需要
# libcrypto / libssl : OpenSSL，离线 GUI 工具不 import ssl/hashlib，可安全剔除（省约 2 MiB）
# 代码已确认无 `import ssl` / `import hashlib` / `import requests` / `urllib`（grep 验证）。
_exclude_bin = ("_avif", "libcrypto", "libssl")
a.binaries = [b for b in a.binaries if not any(s in b[0] for s in _exclude_bin)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="batch_proportional_image_resizer",
    icon="Hokko.ico",                # 桌面 exe 文件图标 / 任务栏图标（目录内的 Hokko.ico，256px）
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                 # 图形界面，不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
