@echo off
setlocal
cd /d "%~dp0.."
rem Gera dist\ObraCaixa.exe (sem dados embutidos: eles ficam em %APPDATA%\ObraCaixa)
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name ObraCaixa --paths src src\obracaixa\__main__.py
