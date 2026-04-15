$projectRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $projectRoot "scripts\launch_app.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "NICO Trade Hub.lnk"

$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
$shortcut.Description = "Abrir NICO Trade Hub"
$shortcut.Save()

Write-Host "Acceso directo creado en: $shortcutPath"
