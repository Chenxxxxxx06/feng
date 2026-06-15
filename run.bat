@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%BACKEND%\venv"
set "PY_HOME=%ROOT%runtime\python"
set "LOG=%BACKEND%\startup_check.log"

if not exist "%PY_HOME%\python.exe" (
  echo Missing bundled Python runtime:
  echo %PY_HOME%\python.exe
  pause
  exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  echo Missing backend virtual environment:
  echo %VENV%\Scripts\python.exe
  pause
  exit /b 1
)

(
  echo home = %PY_HOME%
  echo include-system-site-packages = false
  echo version = 3.13.0
  echo executable = %PY_HOME%\python.exe
  echo command = %PY_HOME%\python.exe -m venv %VENV%
) > "%VENV%\pyvenv.cfg"

set "PYTHONHOME="
set "PYTHONPATH="

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
  taskkill /PID %%a /F >nul 2>nul
)

cd /d "%BACKEND%"
"%VENV%\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy; import app.main; print('startup check ok')" > "%LOG%" 2>&1
if errorlevel 1 (
  echo Backend startup check failed.
  echo.
  type "%LOG%"
  echo.
  pause
  exit /b 1
)

start "fengdiao-pHM backend" cmd /k ""%VENV%\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
for /l %%i in (1,1,30) do (
  powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
  if not errorlevel 1 goto open_browser
  timeout /t 1 >nul
)
echo Backend did not respond within 30 seconds. Check the backend window for errors.
pause
exit /b 1

:open_browser
start http://127.0.0.1:8000
echo fengdiao-pHM is starting at http://127.0.0.1:8000
echo Keep the backend window open while using the system.
pause
