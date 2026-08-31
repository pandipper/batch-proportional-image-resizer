@echo off
REM 一键打包：把 batch_proportional_image_resizer.py 打成单文件 exe
REM 前置（一次性）：
REM   pip install -r requirements.txt
REM   pip install pyinstaller
REM 注：显式用用户机上的 Python 3.12（与 run_gui.bat 同款，避免被损坏的 3.13 关联拖累）。
"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller build_exe.spec --noconfirm
if errorlevel 1 pause
echo 完成：dist\batch_proportional_image_resizer.exe
