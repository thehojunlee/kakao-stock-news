@echo off
chcp 65001 > nul
cd /d "%~dp0"
python send_stock_news.py --dry-run
echo.
pause

