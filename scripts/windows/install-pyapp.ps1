$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetDir = Join-Path $env:LOCALAPPDATA "VideoNotes\bin"
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Target = Join-Path $TargetDir "videonotes.exe"

New-Item -ItemType Directory -Force $TargetDir, $StartMenu | Out-Null
Copy-Item "$SourceDir\videonotes.exe" $Target -Force

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut((Join-Path $StartMenu "VideoNotes.lnk"))
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $TargetDir
$Shortcut.Save()

Write-Host "VideoNotes установлен: $Target"
Write-Host "Запускайте из меню Пуск или командой: $Target"
