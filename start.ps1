param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$SkipInstall,
    [switch]$SetupOnly,
    [switch]$NoBrowser,
    [switch]$StopExisting,
    [switch]$PreserveAdminPassword
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$VenvDir = Join-Path $BackendDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$DbPath = Join-Path $BackendDir "fengdiao_phm.db"
$DatabaseUrl = "sqlite+aiosqlite:///" + (($DbPath -replace "\\", "/"))
$LogsDir = Join-Path $RootDir "runtime\logs"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Quote-Ps {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Assert-ProjectRoot {
    if (-not (Test-Path $BackendDir) -or -not (Test-Path $FrontendDir)) {
        throw "start.ps1 must stay in the project root. Expected backend and frontend folders beside it."
    }
    if (-not (Test-Path $DbPath)) {
        throw "Database not found: $DbPath"
    }
}

function Assert-Command {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $Hint"
    }
}

function Get-CompatiblePython {
    Assert-Command "py" "Install Python 3.10, 3.11, or 3.12 first."

    foreach ($Version in @("3.11", "3.10", "3.12")) {
        $Executable = & py "-$Version" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $Executable) {
            return @{
                Exe = "py"
                Args = @("-$Version")
                Version = $Version
                Display = $Executable.Trim()
            }
        }
    }

    throw "No compatible Python found. Python 3.13 is intentionally skipped because this project pins older scientific packages."
}

function Test-VenvPython {
    if (-not (Test-Path $VenvPython)) {
        return $false
    }

    $Cfg = Join-Path $VenvDir "pyvenv.cfg"
    if (Test-Path $Cfg) {
        $CfgText = Get-Content -Raw -LiteralPath $Cfg
        $ExecutableLine = ($CfgText -split "`r?`n") | Where-Object { $_ -like "executable = *" } | Select-Object -First 1
        if ($ExecutableLine) {
            $ConfiguredExecutable = ($ExecutableLine -replace "^executable = ", "").Trim()
            if ($ConfiguredExecutable -and -not (Test-Path $ConfiguredExecutable)) {
                return $false
            }
        }
    }

    try {
        $Version = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    }
    catch {
        return $false
    }
    if ($LASTEXITCODE -ne 0 -or -not $Version) {
        return $false
    }

    return ($Version.Trim() -in @("3.10", "3.11", "3.12"))
}

function Remove-BrokenVenv {
    $ResolvedVenv = [System.IO.Path]::GetFullPath($VenvDir)
    $ResolvedBackend = [System.IO.Path]::GetFullPath($BackendDir)

    if (-not $ResolvedVenv.StartsWith($ResolvedBackend, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove venv outside backend: $ResolvedVenv"
    }

    if (Test-Path $VenvDir) {
        Write-Step "Removing broken backend virtual environment"
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }
}

function Get-CombinedHash {
    param([string[]]$Paths)

    $Parts = @()
    foreach ($Path in $Paths) {
        if (Test-Path $Path) {
            $Item = Get-Item -LiteralPath $Path
            $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
            $Parts += "$($Item.Name)=$Hash"
        }
    }
    return ($Parts -join ";")
}

function Ensure-BackendVenv {
    param([hashtable]$Python)

    if (-not (Test-VenvPython)) {
        Remove-BrokenVenv
        Write-Step "Creating backend virtual environment with Python $($Python.Version)"
        & $Python.Exe @($Python.Args) -m venv $VenvDir
    }

    $Version = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    Write-Info "backend venv Python: $Version"
}

function Ensure-BackendDependencies {
    if ($SkipInstall) {
        Write-Step "Skipping backend dependency install"
        return
    }

    $Requirements = Join-Path $BackendDir "requirements.txt"
    $Marker = Join-Path $VenvDir ".requirements.stamp"
    $PythonVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    $DesiredStamp = "python=$PythonVersion;requirements=$(Get-CombinedHash @($Requirements))"
    $CurrentStamp = if (Test-Path $Marker) { (Get-Content -Raw -LiteralPath $Marker).Trim() } else { "" }

    if ($CurrentStamp -eq $DesiredStamp) {
        Write-Step "Backend dependencies are already installed"
        return
    }

    Write-Step "Installing backend dependencies"
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r $Requirements -i https://pypi.tuna.tsinghua.edu.cn/simple
    Set-Content -LiteralPath $Marker -Value $DesiredStamp -Encoding ASCII
}

function Ensure-FrontendDependencies {
    Assert-Command "npm" "Install Node.js 18+ first."

    if ($SkipInstall) {
        Write-Step "Skipping frontend dependency install"
        return
    }

    $PackageJson = Join-Path $FrontendDir "package.json"
    $PackageLock = Join-Path $FrontendDir "package-lock.json"
    $NodeModules = Join-Path $FrontendDir "node_modules"
    $Marker = Join-Path $FrontendDir ".npm-install.stamp"
    $DesiredStamp = "frontend=$(Get-CombinedHash @($PackageJson, $PackageLock))"
    $CurrentStamp = if (Test-Path $Marker) { (Get-Content -Raw -LiteralPath $Marker).Trim() } else { "" }

    if ((Test-Path $NodeModules) -and $CurrentStamp -eq $DesiredStamp) {
        Write-Step "Frontend dependencies are already installed"
        return
    }

    Write-Step "Installing frontend dependencies"
    Push-Location $FrontendDir
    try {
        npm install
    }
    finally {
        Pop-Location
    }
    Set-Content -LiteralPath $Marker -Value $DesiredStamp -Encoding ASCII
}

function Invoke-BackendPython {
    param([string]$Code)

    Push-Location $BackendDir
    try {
        $env:DATABASE_URL = $DatabaseUrl
        $env:PYTHONUTF8 = "1"
        $env:PYTHONIOENCODING = "utf-8"
        $Code | & $VenvPython -
    }
    finally {
        Pop-Location
    }
}

function Ensure-AdminLogin {
    Write-Step "Ensuring demo login admin/admin123"

    $ResetExisting = if ($PreserveAdminPassword) { "0" } else { "1" }
    $env:RESET_EXISTING_ADMIN = $ResetExisting

    $Code = @'
import asyncio
import os

from sqlalchemy import select

from app.database import async_session, engine, Base
from app.main import ensure_runtime_schema
from app.models import User
from app.core.security import hash_password, verify_password


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        changed = False

        if user is None:
            user = User(
                username="admin",
                email="admin@fengdiao.com",
                password_hash=hash_password("admin123"),
                role="admin",
                is_active=True,
            )
            db.add(user)
            changed = True
            action = "created"
        else:
            action = "verified"
            if os.environ.get("RESET_EXISTING_ADMIN") == "1":
                try:
                    ok = verify_password("admin123", user.password_hash)
                except Exception:
                    ok = False
                if not ok:
                    user.password_hash = hash_password("admin123")
                    changed = True
                    action = "reset"
            if hasattr(user, "is_active"):
                user.is_active = True

        if changed:
            await db.commit()
        print(f"admin login {action}: admin/admin123")


asyncio.run(main())
'@

    Invoke-BackendPython $Code
    Remove-Item Env:\RESET_EXISTING_ADMIN -ErrorAction SilentlyContinue
}

function Get-PortProcessIds {
    param([int]$Port)
    $Connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return @($Connections | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Assert-PortAvailable {
    param([int]$Port, [string]$Name)

    $Pids = Get-PortProcessIds $Port
    if ($Pids.Count -eq 0) {
        return
    }

    if ($StopExisting) {
        Write-Step "Stopping existing process on $Name port $Port"
        foreach ($ProcessId in $Pids) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
        return
    }

    $Details = foreach ($ProcessId in $Pids) {
        Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue |
            Select-Object ProcessId, CommandLine
    }
    $Details | Format-List | Out-String | Write-Host
    throw "$Name port $Port is already in use. Close that process or run .\start.ps1 -StopExisting."
}

function Wait-Backend {
    $HealthUrl = "http://127.0.0.1:$BackendPort/api/health"
    for ($i = 1; $i -le 60; $i++) {
        try {
            $null = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 2
            return
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Backend did not become healthy at $HealthUrl. Check runtime\logs\backend.log."
}

function Test-AdminLoginViaApi {
    $LoginUrl = "http://127.0.0.1:$BackendPort/api/auth/login"
    $Body = @{ username = "admin"; password = "admin123" } | ConvertTo-Json

    try {
        $Response = Invoke-RestMethod -Uri $LoginUrl -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 10
        return [bool]$Response.access_token
    }
    catch {
        Write-Warning "Login API check failed: $($_.Exception.Message)"
        return $false
    }
}

function Start-DevServers {
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
    Assert-PortAvailable -Port $BackendPort -Name "backend"
    Assert-PortAvailable -Port $FrontendPort -Name "frontend"

    Write-Step "Starting backend"
    $BackendLog = Join-Path $LogsDir "backend.log"
    $BackendCmd = @(
        "Set-Location -LiteralPath $(Quote-Ps $BackendDir)",
        "`$env:DATABASE_URL=$(Quote-Ps $DatabaseUrl)",
        "`$env:PYTHONUTF8='1'",
        "`$env:PYTHONIOENCODING='utf-8'",
        "& $(Quote-Ps $VenvPython) -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort --reload *>&1 | Tee-Object -FilePath $(Quote-Ps $BackendLog)"
    ) -join "; "
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $BackendDir -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $BackendCmd)

    Wait-Backend
    if (-not (Test-AdminLoginViaApi)) {
        Write-Step "Repairing admin login and retrying"
        Ensure-AdminLogin
        if (-not (Test-AdminLoginViaApi)) {
            throw "Admin login still fails. This is the condition that makes the frontend show operation failed."
        }
    }

    Write-Step "Starting frontend"
    $FrontendLog = Join-Path $LogsDir "frontend.log"
    $FrontendCmd = @(
        "Set-Location -LiteralPath $(Quote-Ps $FrontendDir)",
        "`$env:VITE_API_TARGET='http://127.0.0.1:$BackendPort'",
        "npm run dev -- --host 127.0.0.1 --port $FrontendPort *>&1 | Tee-Object -FilePath $(Quote-Ps $FrontendLog)"
    ) -join "; "
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $FrontendDir -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $FrontendCmd)

    if (-not $NoBrowser) {
        Start-Sleep -Seconds 3
        Start-Process "http://127.0.0.1:$FrontendPort"
    }

    Write-Host ""
    Write-Host "Backend:  http://127.0.0.1:$BackendPort" -ForegroundColor Green
    Write-Host "API docs: http://127.0.0.1:$BackendPort/api/docs" -ForegroundColor Green
    Write-Host "Frontend: http://127.0.0.1:$FrontendPort" -ForegroundColor Green
    Write-Host "Login:    admin / admin123" -ForegroundColor Green
    Write-Host "Logs:     $LogsDir" -ForegroundColor Green
}

Assert-ProjectRoot

$Python = Get-CompatiblePython
Write-Step "Using Python $($Python.Version): $($Python.Display)"
Write-Info "database: $DbPath"

Ensure-BackendVenv -Python $Python
Ensure-BackendDependencies
Ensure-FrontendDependencies
Ensure-AdminLogin

if ($SetupOnly) {
    Write-Step "Setup complete"
    exit 0
}

Start-DevServers
