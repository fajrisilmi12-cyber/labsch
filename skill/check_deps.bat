<# :
@echo off & powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ((gc '%~f0') -join \"`n\")" & goto :eof
#>
# ============================================================
#  LabSCH Dependency Checker & Auto-Installer  v1.0
#  Cek semua dependencies LabSCH Agent di Windows:
#    1. Python 3.10+ (di PATH)
#    2. pip
#    3. Paket Python: psutil, requests
#    4. msg.exe (Windows message util — untuk notify popup)
#    5. Admin privileges (untuk registry/hosts/schtasks)
#  Kalau ada yang kurang, auto-install via PowerShell.
#  Run: klik kanan -> Run as Administrator
# ============================================================

$ErrorActionPreference = "Continue"
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  LabSCH Dependency Checker & Auto-Installer" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$results = @()

function Add-Result($name, $ok, $detail) {
    $script:results += [PSCustomObject]@{
        Check = $name; Status = if ($ok) { "OK" } else { "MISSING" }; Detail = $detail
    }
    if ($ok) { Write-Host "  [OK]      $name - $detail" -ForegroundColor Green }
    else     { Write-Host "  [MISSING] $name - $detail" -ForegroundColor Red }
}

# ---------- 0. Admin ----------
Add-Result "Admin privileges" $IsAdmin $(if ($IsAdmin) { "running elevated" } else { "NOT elevated - registry/hosts/tasks install akan gagal!" })

# ---------- 1. Python ----------
$pythonCmd = $null
foreach ($c in @("python", "python3", "py")) {
    $found = Get-Command $c -ErrorAction SilentlyContinue
    if ($found) { $pythonCmd = $c; break }
}

$pyVersion = ""
if ($pythonCmd) {
    try {
        $pyVersion = (& $pythonCmd --version 2>&1).ToString()
    } catch { $pyVersion = "unknown" }
    $verOk = $pyVersion -match "Python 3\.(1[0-9]|[2-9][0-9])"
    Add-Result "Python" $verOk "$pyVersion $(if (-not $verOk) { '(butuh 3.10+)' })"
} else {
    Add-Result "Python" $false "tidak ditemukan di PATH"
}

# ---------- 2. Auto-install Python kalau tidak ada ----------
if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "  >> Python tidak ada. Mencoba auto-install..." -ForegroundColor Yellow

    $pyInstaller = "$env:TEMP\python-installer.exe"
    $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
    try {
        Write-Host "     Downloading Python 3.12.8 installer..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing

        Write-Host "     Installing (silent, Add to PATH)..."
        $proc = Start-Process -FilePath $pyInstaller `
            -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" `
            -Wait -PassThru
        if ($proc.ExitCode -eq 0) {
            Write-Host "     Python terinstall. Refresh PATH..." -ForegroundColor Green
            $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
            $userPath    = [Environment]::GetEnvironmentVariable("Path", "User")
            $env:Path = "$machinePath;$userPath"
            $pythonCmd = "python"
            Add-Result "Python (auto-installed)" $true "3.12.8"
        } else {
            Add-Result "Python (auto-install)" $false "installer exit code $($proc.ExitCode) - install manual dari python.org"
        }
        Remove-Item $pyInstaller -ErrorAction SilentlyContinue
    } catch {
        Add-Result "Python (auto-install)" $false "$($_.Exception.Message)"
        Write-Host "     Fallback: coba winget install Python.Python.3.12" -ForegroundColor Yellow
        if (-not $pythonCmd) {
            winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements 2>$null
            $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
            $pythonCmd = "python"
        }
    }
}

if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "  GAGAL: Python tetap tidak tersedia. Install manual dari python.org" -ForegroundColor Red
    Write-Host "  (centang 'Add Python to PATH'), lalu jalankan ulang script ini." -ForegroundColor Red
    & { Write-Host ""; Read-Host "Tekan Enter untuk keluar" }
    exit 1
}

# ---------- 3. pip ----------
$hasPip = $false
try {
    $null = & $pythonCmd -m pip --version 2>&1
    if ($LASTEXITCODE -eq 0) { $hasPip = $true }
} catch {}
Add-Result "pip" $hasPip $(if ($hasPip) { (& $pythonCmd -m pip --version 2>&1).ToString() } else { "pip module tidak ada" })

if (-not $hasPip) {
    Write-Host "  >> Auto-install pip (ensurepip)..."
    & $pythonCmd -m ensurepip --upgrade 2>&1 | Out-Null
    try {
        $null = & $pythonCmd -m pip --version 2>&1
        if ($LASTEXITCODE -eq 0) { $hasPip = $true; Add-Result "pip (auto-installed)" $true "ensurepip OK" }
    } catch {}
    if (-not $hasPip) {
        # fallback: download get-pip.py
        try {
            Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile "$env:TEMP\get-pip.py" -UseBasicParsing
            & $pythonCmd "$env:TEMP\get-pip.py" 2>&1 | Out-Null
            $null = & $pythonCmd -m pip --version 2>&1
            if ($LASTEXITCODE -eq 0) { $hasPip = $true; Add-Result "pip (auto-installed)" $true "get-pip.py OK" }
        } catch {
            Add-Result "pip (auto-install)" $false "$($_.Exception.Message)"
        }
    }
}

# ---------- 4. Paket Python: psutil + requests ----------
foreach ($pkg in @("psutil", "requests")) {
    $installed = & $pythonCmd -c "import $pkg" 2>$null
    $ok = ($LASTEXITCODE -eq 0)
    Add-Result "Python package: $pkg" $ok $(if ($ok) { "importable" } else { "belum terinstall" })
    if (-not $ok -and $hasPip) {
        Write-Host "  >> Auto-install $pkg..."
        if ($IsAdmin) {
            & $pythonCmd -m pip install --quiet $pkg 2>&1 | Out-Null
        } else {
            & $pythonCmd -m pip install --quiet --user $pkg 2>&1 | Out-Null
        }
        $null = & $pythonCmd -c "import $pkg" 2>$null
        Add-Result "$pkg (auto-installed)" ($LASTEXITCODE -eq 0) $(if ($LASTEXITCODE -eq 0) { "sekarang importable" } else { "pip install gagal - cek koneksi internet" })
    }
}

# ---------- 5. msg.exe (notify popup) ----------
$msgPath = "$env:SystemRoot\System32\msg.exe"
$msgOk = Test-Path $msgPath
Add-Result "msg.exe (notify popup)" $msgOk $(if ($msgOk) { "$msgPath" } else { "tidak ditemukan (fallback PowerShell MessageBox, tidak wajib)" })
if (-not $msgOk) {
    Write-Host "  >> msg.exe tidak ada (Windows Home/LTSC kadang tidak bundle)."
    Write-Host "     Notify popup akan fallback ke PowerShell MessageBox (masih bekerja,"
    Write-Host "     asal agent v0.3.1+). Tidak perlu install manual."
}

# ---------- 6. cURL (untuk test API; opsional) ----------
$curlOk = $null -ne (Get-Command curl.exe -ErrorAction SilentlyContinue)
Add-Result "curl.exe" $curlOk $(if ($curlOk) { "tersedia (opsional)" } else { "tidak ada (opsional, tidak wajib)" })

# ---------- 7. Cek file agent di folder ini ----------
$agentPy = Join-Path $PSScriptRoot "labsch_agent.py"
$agentOk = Test-Path $agentPy
Add-Result "labsch_agent.py di folder ini" $agentOk $(if ($agentOk) { "ditemukan - siap install" } else { "jalankan script ini dari folder agent hasil ekstrak zip" })

# ---------- Summary ----------
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
$missing = $results | Where-Object { $_.Status -eq "MISSING" }
if ($missing.Count -eq 0) {
    Write-Host "  SEMUA DEPENDENCIES TERPENUHI - siap install!" -ForegroundColor Green
    Write-Host "  Lanjutkan dengan: install.bat (Run as Administrator)" -ForegroundColor Green
} else {
    Write-Host "  MASIH ADA YANG KURANG ($($missing.Count)):" -ForegroundColor Yellow
    foreach ($m in $missing) {
        Write-Host "   - $($m.Check): $($m.Detail)" -ForegroundColor Yellow
    }
    if ($missing.Check -contains "Python" -or $missing.Check -contains "Admin privileges") {
        Write-Host ""
        Write-Host "  Yang ini harus dibereskan manual sebelum install." -ForegroundColor Red
    } else {
        Write-Host ""
        Write-Host "  Coba jalankan ulang script ini untuk verifikasi ulang," -ForegroundColor Yellow
        Write-Host "  lalu lanjutkan ke install.bat" -ForegroundColor Yellow
    }
}
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
& { Read-Host "Tekan Enter untuk keluar" } 2>$null | Out-Null
