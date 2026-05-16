$ErrorActionPreference = "Stop"

$desktop = [Environment]::GetFolderPath("Desktop")
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetBat = Join-Path $scriptDir "launch_batch_clone_ui.bat"
$shortcutPath = Join-Path $desktop "VoxCPM Batch Cloning.lnk"

if (-not (Test-Path -LiteralPath $targetBat)) {
    throw "Launcher batch file not found: $targetBat"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetBat
$shortcut.WorkingDirectory = $scriptDir
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,137"
$shortcut.Description = "Launch VoxCPM Batch Cloning UI"
$shortcut.Save()

Write-Output "Desktop shortcut created: $shortcutPath"
