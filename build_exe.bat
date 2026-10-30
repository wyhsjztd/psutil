@echo off
chcp 65001 >nul
cd /d %~dp0

rem 在独立的干净虚拟环境中构建，避免把开发机上其他项目的巨型依赖打包进来
if not exist .venv-build (
    echo [1/3] 创建构建环境 .venv-build ...
    python -m venv .venv-build
)

echo [2/3] 安装构建依赖 ...
.venv-build\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements-build.txt

echo [3/3] 打包为单文件 exe ...
.venv-build\Scripts\python.exe -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name SysMon ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.png;assets" ^
  --exclude-module tkinter ^
  --exclude-module matplotlib ^
  --exclude-module PIL ^
  --exclude-module scipy ^
  --exclude-module pandas ^
  --exclude-module pyqtgraph.flowchart ^
  --exclude-module pyqtgraph.opengl ^
  --exclude-module pyqtgraph.examples ^
  main.py

echo.
echo 完成：dist\SysMon.exe
pause