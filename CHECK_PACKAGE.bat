@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%BACKEND%\venv"
set "PY_HOME=%ROOT%runtime\python"

echo Checking fengdiao-pHM portable package...
echo Package: %ROOT%
echo.

if not exist "%PY_HOME%\python.exe" (
  echo [FAIL] Missing bundled Python: %PY_HOME%\python.exe
  goto failed
) else (
  echo [OK] Bundled Python found.
)

if not exist "%VENV%\Scripts\python.exe" (
  echo [FAIL] Missing backend venv: %VENV%\Scripts\python.exe
  goto failed
) else (
  echo [OK] Backend venv found.
)

if not exist "%BACKEND%\fengdiao_phm.db" (
  echo [FAIL] Missing database: %BACKEND%\fengdiao_phm.db
  goto failed
) else (
  echo [OK] Database found.
)

if not exist "%ROOT%frontend\dist\index.html" (
  echo [FAIL] Missing frontend build: %ROOT%frontend\dist\index.html
  goto failed
) else (
  echo [OK] Frontend build found.
)

if not exist "%BACKEND%\data\models\windblade_dtu_yolo_best.pt" (
  echo [FAIL] Missing blade YOLO model.
  goto failed
) else (
  echo [OK] Blade YOLO model found.
)

(
  echo home = %PY_HOME%
  echo include-system-site-packages = false
  echo version = 3.13.0
  echo executable = %PY_HOME%\python.exe
  echo command = %PY_HOME%\python.exe -m venv %VENV%
) > "%VENV%\pyvenv.cfg"

cd /d "%BACKEND%"
"%VENV%\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, app.main; print('[OK] Backend imports passed.')" || goto failed

echo.
echo Package check passed.
pause
exit /b 0

:failed
echo.
echo Package check failed. Please send this window screenshot to the developer.
pause
exit /b 1
