@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" http://localhost:8011
python web.py
pause
