@echo off
chcp 65001 >nul
cd /d %~dp0

echo [1/2] 安装依赖...
python -m pip install -r requirements.txt pyinstaller -q

echo [2/2] 打包为单文件 exe...
python -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name SysMon ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.png;assets" ^
  --exclude-module tkinter ^
  --exclude-module matplotlib ^
  --exclude-module PIL ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.QtMultimedia ^
  main.py

echo.
echo 完成：dist\SysMon.exe
pause