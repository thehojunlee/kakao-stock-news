@echo off
chcp 65001 > nul
cd /d "%~dp0"
python get_kakao_token.py
echo.
pause

