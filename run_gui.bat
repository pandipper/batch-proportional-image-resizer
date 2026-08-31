@echo off
REM 用 Python 3.12 启动 GUI 工具
REM 为什么需要这个 bat：双击 *.py 时 Windows 交给 py.exe（Python Launcher）
REM 挑版本，而 py.exe 的默认版本可能指向一个已卸载的解释器（本机实测默认
REM 指向 3.14，其目录已不存在），结果就是控制台一闪而过。这里显式指定 3.12。
REM 主程序首行也写了 shebang "#!/usr/bin/python3.12"，双保险。

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"

if not exist "%PY%" (
    echo [提示] 未找到 %PY%
    echo        改用 py -3.12 启动…
    py -3.12 "%~dp0batch_proportional_image_resizer.py" %*
    if errorlevel 1 pause
    exit /b
)

"%PY%" "%~dp0batch_proportional_image_resizer.py" %*
if errorlevel 1 pause
