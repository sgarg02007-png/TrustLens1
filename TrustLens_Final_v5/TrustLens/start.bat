@echo off
title TrustLens server
cd /d "%~dp0backend"
set PY=
py --version >nul 2>nul && set PY=py
if not defined PY python --version >nul 2>nul && set PY=python
if not defined PY (
  echo.
  echo  Python was not found. Install it from https://www.python.org/downloads/
  echo  and tick "Add Python to PATH" on the first screen, then run this again.
  echo.
  pause
  exit /b 1
)
echo Using %PY%
if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  %PY% -m venv venv
)
if not exist venv\Scripts\python.exe (
  echo Could not create the virtual environment.
  pause
  exit /b 1
)
call venv\Scripts\activate
echo Installing packages. The first time can take 1 to 3 minutes, please wait...
python -m pip install --prefer-binary -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Install failed. Check your internet connection and run this again.
  pause
  exit /b 1
)
echo.
echo  TrustLens is starting. The browser will open in a few seconds.
echo  Keep this window open while you use the app.
echo.
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8000"
python -m uvicorn main:app --port 8000
echo.
echo Server stopped. Read any error above.
pause
