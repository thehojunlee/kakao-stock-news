@echo off
chcp 65001 > nul
cd /d "%~dp0"
python send_stock_news.py
echo.
pause
