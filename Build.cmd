@echo off
setlocal
cd /d "%~dp0"
if not exist "templates\standard_template.xlsx" (
  echo 无法打包：缺少标准模板 templates\standard_template.xlsx
  echo 请把本机的标准模板放到该路径后再执行打包。此文件只保存在本机，不会提交到仓库。
  pause
  exit /b 1
)
py -3.11 tools\require_template.py
if errorlevel 1 (
  pause
  exit /b 1
)
echo 标准模板检查通过。当前脚本只做打包前检查，不生成可执行文件。
exit /b 0
