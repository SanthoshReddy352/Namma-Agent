# Namma Agent - installer for Windows (Windows PowerShell 5.1+ / PowerShell 7+).
# Run it:  double-click "install.bat", or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File installers\install.ps1
#
# Bootstraps everything on THIS machine - and AUTO-INSTALLS Python, Git and Node.js
# if they're missing (via winget, falling back to choco) - so a beginner can just run
# it. Then: venv, dependencies, the web UI, the first AI provider + onboarding, a
# shortcut, and launch.
#
#   -NoSetup     skip the interactive first-provider / onboarding prompts (app onboards)
#   -NoLaunch    set up only, don't launch (used by the native .exe installer)
#   -NoShortcut  don't create shortcuts (the native installer manages them)
param([switch]$NoLaunch, [switch]$NoSetup, [switch]$NoShortcut)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
Set-Location $Root

Write-Host "=============================================="
Write-Host "  Namma Agent - installer"
Write-Host "  Intelligence for Everyone."
Write-Host "=============================================="

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

# Install a missing tool via winget (preferred) or choco. Returns $true if present after.
function Ensure-Tool($cmd, $wingetId, $chocoId, $label) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { return $true }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Installing $label (winget)..."
        winget install -e --id $wingetId --accept-source-agreements --accept-package-agreements --silent 2>$null | Out-Null
        Refresh-Path
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Host "  Installing $label (choco)..."
        choco install -y $chocoId 2>$null | Out-Null
        Refresh-Path
    } else {
        Write-Host "  $label is missing and neither winget nor choco is available."
    }
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Test-Py($head, $tail) {
    try {
        & $head @tail -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
function Find-Py {
    if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-Py "py" @("-3"))) { return ,@("py", @("-3")) }
    if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Py "python" @())) { return ,@("python", @()) }
    return $null
}

# 1. Python 3.10+ (auto-install if missing) ----------------------------------
Write-Host "[1/8] Ensuring Python 3.10+ ..."
$py = Find-Py
if (-not $py) {
    Ensure-Tool "python" "Python.Python.3.12" "python" "Python 3.12" | Out-Null
    $py = Find-Py
}
if (-not $py) {
    Write-Host "ERROR: could not find/install Python 3.10+. Install it then re-run:"
    Write-Host "  winget install -e --id Python.Python.3.12"
    Read-Host "Press Enter to exit"; exit 1
}
$PyHead = $py[0]; $PyTail = $py[1]
Write-Host "      Using $(& $PyHead @PyTail --version)"

# 2. Git + Node.js (auto-install if missing) ---------------------------------
Write-Host "[2/8] Ensuring Git + Node.js ..."
Ensure-Tool "git" "Git.Git" "git" "Git" | Out-Null
Ensure-Tool "npm" "OpenJS.NodeJS.LTS" "nodejs-lts" "Node.js" | Out-Null

# 3. virtual environment -----------------------------------------------------
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "[3/8] Creating .venv ..."
    & $PyHead @PyTail -m venv .venv
} else {
    Write-Host "[3/8] Reusing existing .venv"
}

# 4. dependencies ------------------------------------------------------------
Write-Host "[4/8] Installing dependencies (a few minutes on first run) ..."
& $VenvPy -m pip install --upgrade pip --no-cache-dir | Out-Null
& $VenvPy -m pip install --no-cache-dir -r namma_agent\requirements.txt

# 5. web UI ------------------------------------------------------------------
if (Test-Path "namma_agent\webui\dist\index.html") {
    Write-Host "[5/8] Web UI already built - skipping"
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "[5/8] Building the web UI ..."
    Push-Location namma_agent\webui; npm install; npm run build; Pop-Location
} else {
    Write-Host "[5/8] WARNING: web UI not built and Node/npm not found."
}

# 6. first provider + onboarding ---------------------------------------------
if ($NoSetup) {
    Write-Host "[6/8] Skipping provider/onboarding - configure it in the app."
} else {
    Write-Host "[6/8] Configuring the first AI provider + a few questions ..."
    & $VenvPy -m namma_agent --setup
    if ($LASTEXITCODE -ne 0) { Write-Host "      (setup skipped - finish it in the app)" }
}

# 7. shortcut ----------------------------------------------------------------
if ($NoShortcut) {
    Write-Host "[7/8] Skipping shortcuts (managed by the installer)."
} else {
    Write-Host "[7/8] Creating shortcuts ..."
    $PyW = Join-Path $Root ".venv\Scripts\pythonw.exe"
    $Icon = Join-Path $Root "namma_agent\assets\sparkle.ico"
    $Wsh = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath("Desktop"),
                       (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
        try {
            $lnk = $Wsh.CreateShortcut((Join-Path $dir "Namma Agent.lnk"))
            $lnk.TargetPath = $PyW
            $lnk.Arguments = "-m namma_agent"
            $lnk.WorkingDirectory = $Root
            if (Test-Path $Icon) { $lnk.IconLocation = $Icon }
            $lnk.Description = "Namma Agent - Intelligence for Everyone"
            $lnk.Save()
        } catch { Write-Host "      (could not create shortcut in $dir)" }
    }
    Write-Host "      Shortcut 'Namma Agent' added to Desktop + Start Menu."
}

# 8. launch ------------------------------------------------------------------
Write-Host "=============================================="
if ($NoLaunch) {
    Write-Host "[8/8] Setup complete. Launch from the 'Namma Agent' shortcut."
} else {
    Write-Host "[8/8] Launching Namma Agent ..."
    & $VenvPy -m namma_agent
}
