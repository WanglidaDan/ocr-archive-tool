@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 goto fail
echo Setup complete. Run Start.cmd.
pause
exit /b 0
:fail
echo Setup failed. Install Python 3.11 x64 and retry.
pause
exit /b 1
