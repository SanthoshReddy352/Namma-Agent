# Namma Agent - uninstaller (Windows).
#
# Launched either by the in-app "Uninstall" button (Settings -> About -> Danger zone)
# or by the Windows "Add or remove programs" entry (its UninstallString points here).
#
#   -InstallDir <path>   the app folder to remove (defaults to this script's parent's parent)
#   -Scope all|keep-data 'all' wipes everything; 'keep-data' backs up chats/config first
#   -Relaunched          internal: set when re-launched from %TEMP% (so we can delete InstallDir)
#
# Why re-launch from %TEMP%: this script lives inside the folder it deletes, and the
# running app holds files open. We copy ourselves to TEMP, then from there wait for the
# app to exit, kill any stragglers, remove shortcuts + the registry entry, and delete
# the install folder.
param(
    [string]$InstallDir = "",
    [ValidateSet("all", "keep-data")] [string]$Scope = "all",
    [switch]$Relaunched
)
$ErrorActionPreference = "SilentlyContinue"

if (-not $InstallDir) {
    $InstallDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}

# ── stage 1: re-launch a copy from %TEMP% so we can delete InstallDir (incl. this file)
if (-not $Relaunched) {
    $tmp = Join-Path $env:TEMP "namma-uninstall.ps1"
    Copy-Item -LiteralPath $PSCommandPath -Destination $tmp -Force
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
              "-File", $tmp, "-InstallDir", $InstallDir, "-Scope", $Scope, "-Relaunched")
    Start-Process powershell -WindowStyle Hidden -ArgumentList $args
    return
}

# ── stage 2 (running from %TEMP%): do the removal
Start-Sleep -Seconds 1

# 1. Stop the running app — match python/pythonw running `-m namma_agent` from THIS install
#    (works despite the bare process name). Then give the OS a moment to release handles.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*namma_agent*" -and $_.CommandLine -like "*$InstallDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2

# 2. Keep-data: copy chats + config to %LOCALAPPDATA%\NammaAgent\backup before deleting.
if ($Scope -eq "keep-data") {
    $backup = Join-Path $env:LOCALAPPDATA "NammaAgent\backup"
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach ($rel in @("data", ".env", "namma_agent\config.local.yaml")) {
        $src = Join-Path $InstallDir $rel
        if (Test-Path $src) {
            $dst = Join-Path $backup $rel
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
        }
    }
}

# 3. Remove Desktop + Start-Menu shortcuts.
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
Remove-Item (Join-Path $desktop "Namma Agent.lnk") -Force
Remove-Item (Join-Path $startMenu "Namma Agent.lnk") -Force

# 4. Remove the Add/Remove-Programs registry entry.
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NammaAgent" -Recurse -Force

# 4b. Strip the `namma` launcher dir (<InstallDir>\bin) from the user PATH.
$binDir = Join-Path $InstallDir "bin"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $kept = ($userPath -split ';' | Where-Object { $_ -and $_ -ne $binDir }) -join ';'
    if ($kept -ne $userPath) {
        [Environment]::SetEnvironmentVariable("Path", $kept, "User")
    }
}

# 5. Remove the install folder.
Remove-Item -LiteralPath $InstallDir -Recurse -Force

# 6. 'all' also wipes the per-user data dir.
if ($Scope -eq "all") {
    Remove-Item -LiteralPath (Join-Path $env:USERPROFILE ".namma_agent") -Recurse -Force
}

# 7. Refresh the icon cache so the stale (cached) icon disappears, then confirm.
ie4uinit.exe -show
Add-Type -AssemblyName System.Windows.Forms
$msg = if ($Scope -eq "keep-data") {
    "Namma Agent has been uninstalled. Your chats and settings were saved to`n$env:LOCALAPPDATA\NammaAgent\backup"
} else {
    "Namma Agent has been completely uninstalled."
}
[System.Windows.Forms.MessageBox]::Show($msg, "Namma Agent") | Out-Null
