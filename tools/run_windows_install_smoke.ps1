# Silent per-user install, headless OCR, then uninstall.
# setup.exe is already at dist/ArchiveDesk-setup.exe and contains only the generated fixture template.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$setup = Join-Path $root "dist\ArchiveDesk-setup.exe"
if (-not (Test-Path $setup)) { throw "setup.exe is missing" }
$log = Join-Path $root "dist\install.log"
$proc = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT","/CURRENTUSER","/NORESTART","/LOG=$log" -Wait -PassThru
Write-Output "install_exit=$($proc.ExitCode)"
if ($proc.ExitCode -ne 0) {
  if (Test-Path $log) { Get-Content $log -Tail 40 }
  throw "setup exited $($proc.ExitCode)"
}

$installDir = Join-Path $env:LOCALAPPDATA "Programs\ArchiveDesk"
$exe = Join-Path $installDir "ArchiveDesk.exe"
$template = Join-Path $installDir "templates\standard_template.xlsx"
if (-not (Test-Path $exe)) { throw "installed exe is missing: $exe" }
if (-not (Test-Path $template)) { throw "installed fixture template is missing" }
Write-Output "install_dir=$installDir"

$desktop = [Environment]::GetFolderPath("Desktop")
$desktopLnk = Join-Path $desktop "档序 ArchiveDesk.lnk"
if (-not (Test-Path -LiteralPath $desktopLnk)) { throw "desktop shortcut missing: $desktopLnk" }
$programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$menu = @(Get-ChildItem -LiteralPath $programs -Recurse -Filter "档序 ArchiveDesk.lnk" -ErrorAction SilentlyContinue)
if ($menu.Count -lt 1) { throw "start menu shortcut missing" }
Write-Output "start_menu=$($menu[0].FullName)"

$check = Start-Process -FilePath $exe -ArgumentList "--check" -Wait -PassThru -NoNewWindow
Write-Output "check_exit=$($check.ExitCode)"
if ($check.ExitCode -ne 0) { throw "ArchiveDesk.exe --check exited $($check.ExitCode)" }

& python -c "import sys; sys.path[:0]=['.', 'tests']; from tools.smoke_batch import write_pdfs; from pathlib import Path; write_pdfs(Path('dist/install-pdfs'))"
if ($LASTEXITCODE -ne 0) { throw "failed to prepare install-smoke PDFs" }
$pdfDir = Join-Path $root "dist\install-pdfs"
$outDir = Join-Path $root "dist\install-smoke-out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$report = Join-Path $root "dist\install-smoke-report.json"
$smoke = Start-Process -FilePath $exe -ArgumentList @(
  "--smoke", "--allow-elevated",
  "--pdf-dir", $pdfDir,
  "--out-dir", $outDir,
  "--report", $report,
  "--template", $template
) -Wait -PassThru -NoNewWindow
Write-Output "smoke_exit=$($smoke.ExitCode)"
if (Test-Path $report) { Get-Content $report -Raw }
if ($smoke.ExitCode -ne 0) { throw "installed exe smoke exited $($smoke.ExitCode)" }

$unins = Join-Path $installDir "unins000.exe"
if (-not (Test-Path $unins)) { throw "uninstaller is missing" }
$removed = Start-Process -FilePath $unins -ArgumentList "/VERYSILENT","/NORESTART" -Wait -PassThru
Write-Output "uninstall_exit=$($removed.ExitCode)"
if ($removed.ExitCode -ne 0) { throw "uninstall exited $($removed.ExitCode)" }
if (Test-Path $exe) { throw "ArchiveDesk.exe is still present after uninstall" }
if (Test-Path -LiteralPath $desktopLnk) { throw "desktop shortcut is still present after uninstall" }
$menuAfter = @(Get-ChildItem -LiteralPath $programs -Recurse -Filter "档序 ArchiveDesk.lnk" -ErrorAction SilentlyContinue)
if ($menuAfter.Count -gt 0) { throw "start menu shortcut is still present after uninstall" }
Write-Output "uninstall_ok=1"
