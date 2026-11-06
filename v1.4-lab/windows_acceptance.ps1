# Windows 11 disposable acceptance only. Does not stop services or access accounts.
[CmdletBinding()]
param([switch]$Offline, [string]$PythonExe = "")
$ErrorActionPreference = "Stop"
$exitCode = 1
try {
    $osInfo = Get-CimInstance Win32_OperatingSystem
    if ([int]$osInfo.BuildNumber -lt 22000 -or $osInfo.ProductType -ne 1) {
        throw "Dedicated Windows 11 client required; detected $($osInfo.Caption) build $($osInfo.BuildNumber)"
    }
    $labSource = $PSScriptRoot
    $driveName = (Get-Item $labSource).PSDrive.Name
    if ($driveName -notmatch '^[A-Za-z]$') { throw 'Local NTFS drive required; network path refused' }
    $volume = Get-Volume -DriveLetter $driveName
    if ($volume.FileSystem -ne 'NTFS') { throw 'This acceptance procedure requires a local NTFS volume' }
    $run = Join-Path $labSource ("acceptance-results\windows11-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $run | Out-Null
    Start-Transcript -Path (Join-Path $run "transcript.txt") | Out-Null
    $osInfo | Select-Object Caption,Version,BuildNumber,OSArchitecture | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $run "windows-host.json")
    if (-not $PythonExe) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) {
            $PythonExe = (& py -3 -c "import sys; print(sys.executable)").Trim()
            if ($LASTEXITCODE -ne 0) { throw 'Python 3 not found' }
        } else {
            $PythonExe = (Get-Command python -ErrorAction Stop).Source
        }
    }
    & $PythonExe -c "import sys; assert sys.version_info >= (3,10), 'Python >=3.10 required'"
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python' }
    $venv = Join-Path $run "venv"
    if ($Offline) {
        # No pip/network. Uses installed cryptography, imported through isolated venv.
        & $PythonExe -m venv --system-site-packages $venv
    } else {
        & $PythonExe -m venv $venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
    $python = Join-Path $venv "Scripts\python.exe"
    if (-not $Offline) {
        & $python -m pip install --disable-pip-version-check -r (Join-Path $labSource "requirements-lab.txt")
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; inspect transcript' }
    }
    & $python -c "import cryptography; print('cryptography', cryptography.__version__)"
    if ($LASTEXITCODE -ne 0) { throw 'cryptography unavailable' }
    # All temp fixtures are scoped to this new run directory, never an install path.
    $savedTemp = $env:TEMP
    $savedTmp = $env:TMP
    $env:TEMP = Join-Path $run 'temp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Path $env:TEMP | Out-Null
    try {
        & $python (Join-Path $labSource "static_security_check.py") | Tee-Object -FilePath (Join-Path $run "static-security.json")
        if ($LASTEXITCODE -ne 0) { throw 'Static checks failed' }
        & $python (Join-Path $labSource "test_release_acceptance.py") --report (Join-Path $run "acceptance.json")
        if ($LASTEXITCODE -ne 0) { throw 'Acceptance suite failed' }
        $report = Get-Content -Raw (Join-Path $run "acceptance.json") | ConvertFrom-Json
        if ($report.os_name -ne 'nt' -or $report.failures -ne 0 -or $report.errors -ne 0) { throw 'Invalid Windows report' }
        Write-Host "PASS: Windows 11 process/crash/mock tests. Physical power-loss and real business acceptance remain pending."
        Write-Host "Results: $run"
        $exitCode = 0
    } finally {
        $env:TEMP = $savedTemp
        $env:TMP = $savedTmp
    }
} catch {
    Write-Host ("FAIL/BLOCKED: " + $_.Exception.Message) -ForegroundColor Red
} finally {
    try { Stop-Transcript | Out-Null } catch {}
}
exit $exitCode
