@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================================
REM  风调预顺 PHM 便携版 — 一键启动
REM  西北工业大学 · 软件架构设计 · 第15小组
REM ============================================================================
REM  解压后双击此文件即可, 无需安装 Python / Node.js / 任何环境
REM  自动启动后端 + 数据库 + 前端, 浏览器打开 http://127.0.0.1:8000
REM ============================================================================

title 风调预顺 PHM — 启动中...

set "ROOT=%~dp0"
set "RUNTIME=%ROOT%runtime\python"
set "BACKEND=%ROOT%backend"
set "DIST=%ROOT%frontend\dist"
set "DB=%BACKEND%\fengdiao_phm.db"
set "LAUNCHER=%BACKEND%\launcher.py"
set "PORT=8000"

echo.
echo   ================================================================
echo       风调预顺 PHM 预测性运维系统 — 便携版
echo       西北工业大学 · 软件架构设计 · 第15小组
echo   ================================================================
echo.

REM ============================================================
REM  第1步: 完整性检查
REM ============================================================
echo   [1/5] 检查运行环境...

set "MISSING="

if not exist "%RUNTIME%\python.exe" (
    echo         [FAIL] 缺少: runtime\python\python.exe
    set "MISSING=1"
)
if not exist "%LAUNCHER%" (
    echo         [FAIL] 缺少: backend\launcher.py
    set "MISSING=1"
)
if not exist "%DB%" (
    echo         [FAIL] 缺少: backend\fengdiao_phm.db
    set "MISSING=1"
)
if not exist "%DIST%\index.html" (
    echo         [FAIL] 缺少: frontend\dist\index.html
    set "MISSING=1"
)

if defined MISSING (
    echo.
    echo   请确认压缩包已完整解压, 所有文件与启动器在同一目录
    goto :error
)

echo         [OK] Python 3.11 嵌入式运行时
echo         [OK] 数据库 (backend\fengdiao_phm.db)
echo         [OK] 前端页面 (frontend\dist\)
echo         [OK] 启动器 (backend\launcher.py)

REM ============================================================
REM  第2步: 快速导入检查
REM ============================================================
echo   [2/5] 检查 Python 依赖...
"%RUNTIME%\python.exe" -c "import fastapi,uvicorn,sqlalchemy;print('OK')" >nul 2>nul
if errorlevel 1 (
    echo         [FAIL] Python 依赖不完整
    echo         runtime\python 可能损坏, 请重新解压
    goto :error
)
echo         [OK] 核心依赖完整

REM ============================================================
REM  第3步: 释放端口
REM ============================================================
echo   [3/5] 检查端口 %PORT%...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo         端口被 PID=%%a 占用, 释放中...
    taskkill /PID %%a /F >nul 2>nul
    timeout /t 2 >nul
)
echo         [OK] 端口 %PORT% 已就绪

REM ============================================================
REM  第4步: 启动服务
REM ============================================================
echo   [4/5] 启动服务...

set "PYTHONHOME="
set "PYTHONPATH="

REM 用 /K 保持窗口打开 (方便查看日志和错误)
start "风调预顺-PHM" cmd /k "cd /d "%BACKEND%" && "%RUNTIME%\python.exe" "%LAUNCHER%""

REM ============================================================
REM  第5步: 等待就绪
REM ============================================================
echo   [5/5] 等待服务就绪...

for /l %%i in (1,1,60) do (
    powershell -NoProfile -Command "try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%PORT%/api/health' -TimeoutSec 2;if($r.StatusCode -eq 200){exit 0}else{exit 1}}catch{exit 1}" >nul 2>nul
    if not errorlevel 1 goto :ready
    if %%i==1 <nul set /p ="        等待中."
    if %%i gtr 1 <nul set /p ="."
    timeout /t 1 >nul
)

REM 超时
echo.
echo.
echo   [FAIL] 服务在 60 秒内未响应
echo.
echo   请检查 "风调预顺-PHM" 窗口中的错误信息
echo   常见原因: 杀毒软件拦截、数据库损坏、端口冲突
echo   手动测试: runtime\python\python.exe backend\launcher.py
goto :error

:ready
echo.
echo         [OK] 服务就绪!

REM ============================================================
REM  启动成功
REM ============================================================
echo.
echo   ================================================================
echo                        启动成功!
echo   ================================================================
echo     前端页面 : http://127.0.0.1:%PORT%
echo     API 文档 : http://127.0.0.1:%PORT%/api/docs
echo     登录账号 : admin / admin123
echo   ================================================================
echo     后端窗口 : 风调预顺-PHM (请勿关闭)
echo     停止服务 : 关闭后端窗口即可
echo   ================================================================
echo.

start http://127.0.0.1:%PORT%

echo   浏览器已打开。如未弹出请手动访问 http://127.0.0.1:%PORT%
echo.
echo   按任意键关闭此窗口 (不影响服务运行)...
pause >nul
exit /b 0

REM ============================================================
REM  启动失败
REM ============================================================
:error
echo.
echo   ================================================================
echo                        启动失败
echo   ================================================================
echo   可能原因:
echo     1. 压缩包未完整解压 — 请重新解压
echo     2. 杀毒软件拦截 — 将项目目录加入白名单
echo     3. 文件路径含中文/空格 — 移到纯英文路径
echo     4. 360/腾讯安全管家 — 退出后重试
echo   ================================================================
echo.
echo   按任意键退出...
pause >nul
exit /b 1
