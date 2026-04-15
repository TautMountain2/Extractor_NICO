@echo off
setlocal
cd /d %~dp0\..
call .venv\Scripts\activate.bat
python -m nico_trade_hub.cli sync-banxico --metric both --flow both --start 2022-01 --end 2022-01
endlocal
