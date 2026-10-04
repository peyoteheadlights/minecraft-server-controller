# Minecraft Server Controller - setup
#
#   .\setup.ps1                 set up or repair the installation (safe to run again)
#   .\setup.ps1 --check         read-only health check; changes nothing
#   .\setup.ps1 --logon         start with Windows at login instead of at boot
#   .\setup.ps1 --skip-firewall --skip-startup --non-interactive   (for automation)
#
# If Windows says the script "is not digitally signed", run setup.cmd instead,
# or:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Both change the policy for that one process only, never for your system.
#
# Works from any folder: every path is resolved from this script's location.

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$MinMajor = 3
$MinMinor = 11

# ------------------------------------------------------------------ arguments
$Mode = 'setup'
$Pass = @()
$AdminSteps = $false
foreach ($a in $args) {
    switch -Regex ([string]$a) {
        '^(--|-|/)check$'           { $Mode = 'check' }
        '^(--|-|/)non-interactive$' { $Pass += '--non-interactive' }
        '^(--|-|/)skip-firewall$'   { $Pass += '--skip-firewall' }
        '^(--|-|/)skip-startup$'    { $Pass += '--skip-startup' }
        '^(--|-|/)skip-certs$'      { $Pass += '--skip-certs' }
        '^(--|-|/)logon$'           { $Pass += '--logon' }
        '^(--|-|/)admin-steps$'     { $AdminSteps = $true }
        '^(--|-|/)(h|help|\?)$'     {
            Get-Content -Path $MyInvocation.MyCommand.Path -TotalCount 11 | ForEach-Object { $_ -replace '^# ?', '' }
            exit 0
        }
        default {
            Write-Host "Unknown option: $a   (use --help to see the options)" -ForegroundColor Red
            exit 2
        }
    }
}
$Writing = ($Mode -eq 'setup')
$Pre = @()

function Write-Status([string]$Status, [string]$Name, [string]$Detail = '') {
    $color = @{ OK = 'Green'; WARN = 'Yellow'; FAIL = 'Red'; SKIP = 'DarkGray' }[$Status]
    $text = "[$Status] $Name"
    if ($Detail) { $text += " - $Detail" }
    Write-Host $text -ForegroundColor $color
}

function Stop-Setup([string]$What, [string]$Why, [string]$Fix, [int]$Code = 1) {
    Write-Host ''
    Write-Host $What -ForegroundColor Red
    if ($Why) { Write-Host ''; Write-Host 'Reason:'; Write-Host "  $Why" }
    if ($Fix) { Write-Host ''; Write-Host 'What to do:'; Write-Host "  $Fix" }
    exit $Code
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Write-Host ''
Write-Host '========================================'
if ($Writing) { Write-Host ' Minecraft Server Controller Setup' } else { Write-Host ' Minecraft Server Controller Health Check' }
Write-Host '========================================'
Write-Host "Project folder: $ProjectRoot"
Write-Host ''

# ------------------------------------------------------------------ 1. Windows
if ($env:OS -ne 'Windows_NT') {
    Stop-Setup 'This setup script is for Windows.' "Detected: $([Environment]::OSVersion.VersionString)" `
        'On other systems, create a virtual environment and run: python -m installer.setup_tool setup' 2
}
if (-not (Test-Path (Join-Path $ProjectRoot 'agent\main.py'))) {
    Stop-Setup 'This does not look like a complete copy of the project.' `
        "agent\main.py was not found next to setup.ps1 in $ProjectRoot" `
        'Extract the whole project zip again, into an empty folder, and run setup.ps1 from there.' 2
}

# ------------------------------------------------------------------ 2. Python
function Get-PythonVersion([string]$Exe, [string[]]$PreArgs = @()) {
    try {
        $out = & $Exe @PreArgs -c "import sys; print('%d.%d.%d|%s' % (sys.version_info[:3] + (sys.executable,)))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -match '^(\d+)\.(\d+)\.(\d+)\|(.+)$') {
            return @{ Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Text = "$($Matches[1]).$($Matches[2]).$($Matches[3])"; Path = $Matches[4].Trim() }
        }
    } catch { }
    return $null
}

$Python = $null
$Rejected = @()
if ($env:MCSC_SETUP_PYTHON) {
    $candidates = @(@{ Exe = $env:MCSC_SETUP_PYTHON; Args = @() })
} else {
    $candidates = @(@{ Exe = 'py'; Args = @('-3') }, @{ Exe = 'python'; Args = @() }, @{ Exe = 'python3'; Args = @() })
}
foreach ($c in $candidates) {
    $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    # Do not judge by where the command lives: python.org's Python install
    # manager puts its python/py commands in WindowsApps too. Run it and look
    # at the real interpreter instead (checked just below).
    $v = Get-PythonVersion $c.Exe $c.Args
    if (-not $v) { $Rejected += "$($c.Exe) (did not run)"; continue }
    if ($v.Path -like '*\WindowsApps\*') { $Rejected += "$($v.Path) (Microsoft Store build)"; continue }
    if ($v.Major -lt $MinMajor -or ($v.Major -eq $MinMajor -and $v.Minor -lt $MinMinor)) {
        $Rejected += "$($v.Path) ($($v.Text) is too old)"; continue
    }
    $Python = $v
    break
}
if (-not $Python) {
    $why = 'No suitable Python was found.'
    if ($Rejected.Count) { $why += ' Checked: ' + ($Rejected -join '; ') }
    Stop-Setup "Python $MinMajor.$MinMinor or newer is required." $why `
        'Install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run setup again.' 2
}
Write-Status 'OK' 'Python' "$($Python.Text) ($($Python.Path))"
$Pre += 'Python=OK'

# ------------------------------------------------------------------ 3. virtual environment
$Venv = Join-Path $ProjectRoot '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$venvState = 'missing'
if (Test-Path $VenvPy) {
    $vv = Get-PythonVersion $VenvPy
    if (-not $vv) { $venvState = 'broken' }
    elseif ($vv.Major -ne $Python.Major -or $vv.Minor -ne $Python.Minor) { $venvState = "built for Python $($vv.Text)" }
    else { $venvState = 'ok' }
}
if ($venvState -eq 'ok') {
    Write-Status 'OK' 'Virtual environment' $Venv
    $Pre += 'Virtual environment=OK'
} elseif (-not $Writing) {
    Write-Status 'FAIL' 'Virtual environment' "$venvState ($Venv)"
    $Pre += 'Virtual environment=FAIL'
} else {
    if ($venvState -ne 'missing') {
        # A stale environment (Python upgraded, folder moved, half-deleted) is
        # set aside rather than deleted, so nothing is lost if this was wrong.
        $aside = "$Venv.old-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Move-Item -Path $Venv -Destination $aside
        Write-Host "      The existing .venv was $venvState; moved it to $aside"
    }
    & $Python.Path -m venv $Venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) {
        Stop-Setup 'The virtual environment could not be created.' "python -m venv exited with code $LASTEXITCODE." `
            'Reinstall Python from python.org with the default options (they include venv and pip).'
    }
    Write-Status 'OK' 'Virtual environment' "created $Venv"
    $Pre += 'Virtual environment=OK'
}

# ------------------------------------------------------------------ 4. packaging tools and dependencies
if ($Writing) {
    & $VenvPy -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '      pip is missing from the virtual environment; restoring it'
        & $VenvPy -m ensurepip --upgrade *> $null
        if ($LASTEXITCODE -ne 0) {
            Stop-Setup 'pip could not be installed.' 'python -m ensurepip failed.' 'Reinstall Python from python.org, then run setup again.'
        }
    }
    & $VenvPy -m pip install --disable-pip-version-check --quiet --upgrade pip setuptools wheel
    # requirements.lock pins the exact versions (with hashes) that CI tests.
    $ReqFile = 'requirements.lock'
    $HashArgs = @('--require-hashes')
    if (-not (Test-Path (Join-Path $ProjectRoot $ReqFile))) { $ReqFile = 'requirements.txt'; $HashArgs = @() }
    & $VenvPy -m pip install --disable-pip-version-check --quiet @HashArgs -r (Join-Path $ProjectRoot $ReqFile)
    if ($LASTEXITCODE -ne 0) {
        Stop-Setup 'The dependencies could not be installed.' "pip exited with code $LASTEXITCODE. This is usually a network problem." `
            'Check the internet connection (and any proxy), then run setup again. Nothing was left half-configured.'
    }
    Write-Status 'OK' 'Dependencies' "installed from $ReqFile"
    $Pre += 'Dependencies=OK'
} elseif ($venvState -ne 'ok') {
    Write-Status 'SKIP' 'Dependencies' 'cannot be checked without a working virtual environment'
    $Pre += 'Dependencies=FAIL'
}

# ------------------------------------------------------------------ 5. everything else (Python)
if ($venvState -ne 'ok' -and -not $Writing) {
    Write-Host ''
    Write-Host 'Run .\setup.ps1 (without --check) to create the virtual environment.' -ForegroundColor Yellow
    exit 1
}
$env:MCSC_SETUP_PRE = ($Pre -join ';')
$toolArgs = @('-m', 'installer.setup_tool', $Mode) + $Pass
if ($AdminSteps) { $toolArgs += '--admin-only' }

Push-Location $ProjectRoot      # python -m needs the project folder on its path
try {
    & $VenvPy @toolArgs
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

# ------------------------------------------------------------------ 6. Administrator steps
if ($code -eq 10 -and -not $AdminSteps) {
    if (Test-Admin) { exit 1 }   # already elevated: exit 10 would mean something else went wrong
    Write-Host ''
    Write-Host 'The firewall rule and the startup task need Administrator rights.'
    $answer = 'y'
    if ($Pass -notcontains '--non-interactive') { $answer = Read-Host 'Open an Administrator window to finish? [Y/n]' }
    if ($answer -match '^(|y|yes)$') {
        # -ExecutionPolicy Bypass applies to that one elevated process only.
        $elevated = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$($MyInvocation.MyCommand.Path)`"", '--admin-steps') + $Pass
        try {
            $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $elevated -Verb RunAs -Wait -PassThru
            exit $p.ExitCode
        } catch {
            Stop-Setup 'The Administrator window was not opened.' 'Windows did not grant elevation (the prompt may have been declined).' `
                'Right-click PowerShell, choose "Run as administrator", and run setup.ps1 again.'
        }
    }
    Write-Host 'Skipped. Run setup.ps1 as Administrator later to finish.' -ForegroundColor Yellow
    exit 1
}
if ($AdminSteps -and ($Pass -notcontains '--non-interactive')) {
    Write-Host ''
    Read-Host 'Press Enter to close this window' | Out-Null   # keep the elevated window readable
}
exit $code
