@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 온살 대시보드를 시작합니다. 잠시 후 브라우저가 열립니다. (종료: 이 창을 닫기)
python -m streamlit run app.py
pause
