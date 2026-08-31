@echo off
REM 用 Python 3.12 启动 GUI 工具
REM （双击 *.py 会被关联到已损坏的 Python 3.13，故显式指定 3.12 解释器）
"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" "%~dp0batch_proportional_image_resizer.py" %*
if errorlevel 1 pause
