@echo off
echo.
echo  =========================================
echo   Marco - Italian AI Speaking Partner
echo  =========================================
echo.
echo  Starting server at http://localhost:5050
echo  Open your browser to http://localhost:5050
echo  Press Ctrl+C to stop.
echo.
cd /d "%~dp0"
python app.py
pause
