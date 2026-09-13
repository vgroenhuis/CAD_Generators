@echo off
cd /d "%~dp0"
echo Starting CAD Generators web server...
echo Once ready, open http://127.0.0.1:8000/ in your browser.
echo Press Ctrl+C to stop.
echo.
call .venv\Scripts\activate.bat
python -m uvicorn web_app.server:app --host 127.0.0.1 --port 8000
pause
