@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   원고 뽑기 웹서버를 시작합니다...
echo   브라우저에서 아래 주소로 접속하세요:
echo.
echo       http://localhost:8010
echo.
start "" http://localhost:8010
python web.py
if errorlevel 1 pause
