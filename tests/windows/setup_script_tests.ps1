# Tests for setup.ps1 on Windows PowerShell 5.1. Run by the GitHub Actions
# workflow on a disposable runner. Exits non-zero if any check fails.
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$script = Join-Path $root 'setup.ps1'
$temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$failures = 0
$password = 'ci setup password 4417'

function Check([bool]$ok, [string]$name) {
    if ($ok) { Write-Host "PASS  $name" -ForegroundColor Green }
    else { Write-Host "FAIL  $name" -ForegroundColor Red; $script:failures++ }
}
function Invoke-Setup([string[]]$SetupArgs, [string]$From = $root) {
    Push-Location $From
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script @SetupArgs 2>&1 | Out-String
        return @{ Code = $LASTEXITCODE; Out = $out }
    } finally { Pop-Location }
}

$server = Join-Path $temp 'MC Test Server'
New-Item -ItemType Directory -Force -Path $server | Out-Null
Set-Content -Path (Join-Path $server 'fabric-server-launch.jar') -Value 'jar'
$skip = @('--skip-firewall', '--skip-startup')

# 1. --check on an unconfigured copy, launched from another directory: read-only
$r = Invoke-Setup (@('--check') + $skip) $temp
Check ($r.Code -ne 0) 'check reports problems on an unconfigured copy'
Check (-not (Test-Path "$root\.venv")) 'check created no virtual environment'
Check (-not (Test-Path "$root\config\config.yaml")) 'check created no configuration'
Check ($r.Out -match 'Health Check') 'check prints its header'

# 2. missing Python gives a clear error
$env:MCSC_SETUP_PYTHON = 'C:\no\such\python.exe'
$r = Invoke-Setup @('--non-interactive')
Remove-Item Env:\MCSC_SETUP_PYTHON
Check ($r.Code -eq 2) 'missing Python exits with code 2'
Check ($r.Out -match 'python.org') 'missing Python explains where to get it'

# 3. full setup from another directory, non-interactive
$env:MCSC_SETUP_SERVER_DIR = $server
$env:MCSC_SETUP_PASSWORD = $password
$r = Invoke-Setup (@('--non-interactive') + $skip) $temp
Check ($r.Code -eq 0) "setup from another directory succeeds (exit $($r.Code))"
if ($r.Code -ne 0) { Write-Host $r.Out }
Check (Test-Path "$root\.venv\Scripts\python.exe") 'setup created the virtual environment'
Check ((Get-Content "$root\config\config.yaml" -Raw) -match [regex]::Escape($server)) 'server folder written to config.yaml'
Check ($r.Out -notmatch [regex]::Escape($password)) 'the password is never printed'
Check ((Get-Content "$root\.env" -Raw) -notmatch [regex]::Escape($password)) 'the password is not stored in plain text'
$envHash = (Get-FileHash "$root\.env").Hash
$cfgHash = (Get-FileHash "$root\config\config.yaml").Hash

# 4. repeating setup is safe and reuses what exists
$r = Invoke-Setup (@('--non-interactive') + $skip)
Check ($r.Code -eq 0) 'repeated setup succeeds'
Check ((Get-FileHash "$root\.env").Hash -eq $envHash) 'repeated setup keeps the existing .env'
Check ((Get-FileHash "$root\config\config.yaml").Hash -eq $cfgHash) 'repeated setup keeps config.yaml'
Check ($r.Out -match 'existing password kept') 'repeated setup says it reused the password'

# 5. --check passes on the configured installation, and writes nothing
$r = Invoke-Setup (@('--check') + $skip) $temp
Check ($r.Code -eq 0) "check passes after setup (exit $($r.Code))"
if ($r.Code -ne 0) { Write-Host $r.Out }
Check ((Get-FileHash "$root\.env").Hash -eq $envHash) 'check left .env untouched'

# 6. a missing dependency is detected, then repaired by setup
& "$root\.venv\Scripts\python.exe" -m pip uninstall -y psutil | Out-Null
$r = Invoke-Setup (@('--check') + $skip)
Check ($r.Code -ne 0 -and $r.Out -match 'psutil') 'check names the missing dependency'
$r = Invoke-Setup (@('--non-interactive') + $skip)
Check ($r.Code -eq 0) 'setup repairs the missing dependency'

# 7. the setup.cmd wrapper works without changing the execution policy
$policyBefore = Get-ExecutionPolicy -Scope CurrentUser
& cmd.exe /c "`"$root\setup.cmd`" --check --skip-firewall --skip-startup" | Out-Null
Check ($LASTEXITCODE -eq 0) 'setup.cmd runs the health check'
Check ((Get-ExecutionPolicy -Scope CurrentUser) -eq $policyBefore) 'the execution policy was not changed'

# 8. an unknown option is refused
$r = Invoke-Setup @('--frobnicate')
Check ($r.Code -eq 2) 'an unknown option is refused'

Write-Host ''
if ($failures) { Write-Host "$failures check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host 'All setup checks passed.' -ForegroundColor Green

# Exit explicitly. Without this, GitHub's step wrapper ends with the exit code of
# the last program run above - the deliberate "unknown option" check, where
# setup.ps1 correctly exits 2 - and marks a fully passing run as failed.
exit 0
