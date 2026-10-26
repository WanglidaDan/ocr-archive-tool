@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0ArchiveDesk.exe" (
  echo 找不到 ArchiveDesk.exe。
  echo 请把整个压缩包解压到一个文件夹后再双击本文件，不要只复制其中一个文件。
  echo 如果杀毒软件把 ArchiveDesk.exe 删除或隔离了，请从隔离区恢复，并把本文件夹加入白名单。
  pause
  exit /b 1
)
start "" "%~dp0ArchiveDesk.exe"
