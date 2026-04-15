@echo off
setlocal
cd /d %~dp0\..

if not exist .venv (
    py -3.10 -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
python -m playwright install chromium

echo.
echo Instalacion completada.
echo Inicializa la base con:
echo   .\.venv\Scripts\python -m nico_trade_hub.cli init-db
echo O abre la interfaz con:
echo   scripts\launch_app.bat
endlocal