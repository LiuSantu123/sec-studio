@echo off
setlocal
cd /d "%~dp0"
set "PORT=%SEC_STUDIO_PORT%"
if "%PORT%"=="" set "PORT=8731"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app.py --data-dir "%~dp0.." --host 127.0.0.1 --port %PORT%
) else (
  python app.py --data-dir "%~dp0.." --host 127.0.0.1 --port %PORT%
)
if errorlevel 1 (
  echo.
  echo SEC Studio failed to start. Install Python 3 and dependencies from requirements.txt.
  pause
)
endlocal
