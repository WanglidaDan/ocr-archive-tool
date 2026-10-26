# Run the unpacked ArchiveDesk.exe as a standard user, with outbound blocked.
# The base zip must already be at dist/ArchiveDesk-base.zip and must not contain a template.
# The injected zip is only for this smoke run. It is not uploaded.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
New-Item -ItemType Directory -Force -Path dist | Out-Null

$os = Get-CimInstance Win32_OperatingSystem
$caption = [string]$os.Caption
Write-Output "windows_product_name=$caption"

$zipJson = & python tools/verify_base_zip.py dist/ArchiveDesk-base.zip
$zipCode = $LASTEXITCODE
Set-Content -Path dist/zip-check.json -Value $zipJson -Encoding utf8
Write-Output $zipJson
if ($zipCode -ne 0) { throw "base zip failed DLL or template check" }

$zipItem = Get-Item dist/ArchiveDesk-base.zip
if (Test-Path dist/unpacked-base) { Remove-Item -Recurse -Force dist/unpacked-base }
Expand-Archive -Path dist/ArchiveDesk-base.zip -DestinationPath dist/unpacked-base -Force
$unpacked = (Get-ChildItem dist/unpacked-base -Recurse -File | Measure-Object Length -Sum).Sum
Write-Output "zip_bytes=$($zipItem.Length)"
Write-Output "unpacked_bytes=$unpacked"

& python -c "import sys; sys.path[:0]=['.', 'tests']; from tools.smoke_batch import write_pdfs; from fixtures import example_template; from pathlib import Path; write_pdfs(Path('dist/smoke-pdfs')); Path('dist/fake-template.xlsx').write_bytes(Path(example_template()).read_bytes())"
if ($LASTEXITCODE -ne 0) { throw "failed to prepare fake PDFs or template" }

& python tools/inject_template.py dist/ArchiveDesk-base.zip dist/fake-template.xlsx dist/smoke-injected.zip
if ($LASTEXITCODE -ne 0) { throw "inject_template.py refused the smoke template" }
if (Test-Path dist/smoke-app) { Remove-Item -Recurse -Force dist/smoke-app }
Expand-Archive -Path dist/smoke-injected.zip -DestinationPath dist/smoke-app -Force
$app = Join-Path $root "dist\smoke-app\ArchiveDesk"
$exe = Join-Path $app "ArchiveDesk.exe"
$template = Join-Path $app "templates\standard_template.xlsx"
if (-not (Test-Path $template)) { throw "injected template is missing" }

$check = Get-Content dist/zip-check.json -Raw | ConvertFrom-Json
$context = @{
  zip_bytes = [int64]$zipItem.Length
  unpacked_bytes = [int64]$unpacked
  required_dlls_in_zip = $check.required_dlls
  runtime_dlls_in_zip = @($check.runtime_dlls)
  firewall = "outbound-block-on-ArchiveDesk.exe"
  template_in_artifact = $false
  windows_product_name = $caption
}
$contextPath = Join-Path $app "smoke-context.json"
$context | ConvertTo-Json -Depth 4 | Set-Content -Path $contextPath -Encoding utf8
$outDir = Join-Path $app "smoke-out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$report = Join-Path $app "smoke-report.json"
$pdfDir = Join-Path $root "dist\smoke-pdfs"
$runner = Join-Path $app "smoke-run.bat"
@(
  "@echo off"
  "set TEMP=%~dp0smoke-temp"
  "set TMP=%~dp0smoke-temp"
  "mkdir `"%TEMP%`" 2>nul"
  "`"$exe`" --smoke --pdf-dir `"$pdfDir`" --out-dir `"$outDir`" --report `"$report`" --template `"$template`" --context `"$contextPath`""
  "exit /b %ERRORLEVEL%"
) | Set-Content -Path $runner -Encoding ascii

$existing = Get-NetFirewallRule -DisplayName "M2ArchiveDeskOffline" -ErrorAction SilentlyContinue
if ($existing) { Remove-NetFirewallRule -DisplayName "M2ArchiveDeskOffline" }
New-NetFirewallRule -DisplayName "M2ArchiveDeskOffline" -Direction Outbound -Action Block -Program $exe -Profile Any | Out-Null

$smokeUser = "m2smoke"
$smokePassword = "Ad-m2-Smoke-8bcf!"
& net.exe user $smokeUser $smokePassword /add | Out-Null
if ($LASTEXITCODE -ne 0) { throw "net user add failed: $LASTEXITCODE" }
& net.exe localgroup Administrators $smokeUser /delete | Out-Null
$admins = & net.exe localgroup Administrators
if ($admins -match '(?im)^\s*m2smoke\s*$') { throw "smoke user is an administrator" }

function Grant-BatchLogon([string]$Account) {
  $sid = (New-Object System.Security.Principal.NTAccount($Account)).Translate(
    [System.Security.Principal.SecurityIdentifier]).Value
  $cfg = Join-Path $env:TEMP "m2-batch-logon.cfg"
  $db = Join-Path $env:TEMP "m2-batch-logon.sdb"
  & secedit.exe /export /cfg $cfg /areas USER_RIGHTS | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "secedit export failed: $LASTEXITCODE" }
  $right = "SeBatchLogonRight"
  $lines = @(Get-Content -Path $cfg)
  $found = $false
  $updated = foreach ($line in $lines) {
    if ($line -like "$right*") {
      $found = $true
      if ($line -notlike "*$sid*") {
        $trimmed = $line.TrimEnd()
        if ($trimmed.EndsWith("=")) { "$trimmed *$sid" } else { "$trimmed,*$sid" }
      } else {
        $line
      }
    } else {
      $line
    }
  }
  if (-not $found) { $updated = @($updated) + "$right = *$sid" }
  $updated | Set-Content -Path $cfg -Encoding unicode
  & secedit.exe /configure /db $db /cfg $cfg /areas USER_RIGHTS | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "secedit configure failed: $LASTEXITCODE" }
}

Grant-BatchLogon $smokeUser
& icacls.exe $root /grant "${smokeUser}:(RX)" | Out-Null
& icacls.exe (Join-Path $root "dist") /grant "${smokeUser}:(OI)(CI)RX" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls dist failed: $LASTEXITCODE" }
& icacls.exe $app /grant "${smokeUser}:(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls app failed: $LASTEXITCODE" }

wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true | Out-Null
$action = New-ScheduledTaskAction -Execute $runner -WorkingDirectory $app
$principal = New-ScheduledTaskPrincipal -UserId $smokeUser -LogonType Password -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName "M2Smoke" -Action $action -Principal $principal -Settings $settings -Password $smokePassword -Force | Out-Null
Start-ScheduledTask -TaskName "M2Smoke"
$deadline = (Get-Date).AddMinutes(15)
do {
  Start-Sleep -Seconds 5
  $task = Get-ScheduledTask -TaskName "M2Smoke"
} while (($task.State -eq "Running" -or $task.State -eq "Queued") -and (Get-Date) -lt $deadline)
$info = Get-ScheduledTaskInfo -TaskName "M2Smoke"
Write-Output "scheduled_task_result=$($info.LastTaskResult)"
$startup = Join-Path $app "startup-error.txt"
if (Test-Path $startup) {
  Write-Output "----- startup-error.txt -----"
  Get-Content $startup -Raw
}
if (-not (Test-Path $report)) { throw "smoke report was not written" }
Get-Content $report -Raw
if ($info.LastTaskResult -ne 0) { throw "smoke process exited $($info.LastTaskResult)" }
Copy-Item $report dist/smoke-report.json -Force
