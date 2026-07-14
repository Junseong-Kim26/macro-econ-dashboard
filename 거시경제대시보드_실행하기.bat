@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   거시경제 대시보드를 시작합니다...
echo   브라우저가 자동으로 열립니다 (localhost:8501)
echo   종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo ============================================
"C:\Users\junse\anaconda3\python.exe" -m streamlit run app.py
pause
