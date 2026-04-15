@echo off
echo 正在安装依赖...
pip install telethon plyer customtkinter pyinstaller

echo.
echo 正在打包为 exe...
pyinstaller --onefile --windowed --name "TG多功能工具" main.py

echo.
echo 打包完成！exe 文件在 dist\ 文件夹中
pause
