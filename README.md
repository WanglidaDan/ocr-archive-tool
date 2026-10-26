# OCR档案应用工具 · 档序 ArchiveDesk 0.3

Windows 开源源码版。

本地扫描文件 OCR 与档案目录录入工具。基于 Windows 0.3 版源码整理，界面和识别、批量导出逻辑保持一致。

## 功能

- PDF/图片识别，保留 OCR 原文及字段证据，支持人工核对。
- 按每份文件的页眉提取密级，未识别或有冲突时留空提示。
- 正本数量默认 1，明确识别到的数量优先，可人工修改。
- 归档单位与责任者精确匹配联动，可关闭联动。
- 批量处理，每个输入文件输出独立 Excel。
- 使用自行选择的原 XLSX 模板，按单元格写入数据，保留其余 OOXML 部件及格式。

## Windows 启动

1. 安装 Python 3.11 64 位（包含 Python Launcher）。
2. 完整解压源码，在联网环境运行 `Setup.cmd` 安装依赖。
3. 运行 `Start.cmd`。
4. 在设置中选择你自己的原 Excel 模板及工作表，再导入扫描文件。

安装依赖后 OCR 可本地离线运行。可选 Ollama 只连接本机。项目数据保存在 `%LOCALAPPDATA%/ArchiveDesk/project.json`，为未加密 JSON。

开源包不含原业务模板、真实扫描件、提取结果、历史项目数据、第三方运行时和模型二进制。模板由用户自行提供，不会因开源而改变。

## 验证与限制

原 0.3 版本曾完成 Linux 环境单元测试、模拟扫描及模板格式验证。本次发布不表示已通过真实 Windows 设备验收；OCR 结果仍需核对，档案系统实际导入应另行测试。

测试不依赖未公开的业务模板或真实扫描件。示例模板由测试代码按「管理类_件 / 卷 / 卷内件」结构生成，下拉单位使用「示例单位A」这类占位名；扫描图由 Pillow 按本机中文字体绘制。Windows 上可运行全部测试：

```bat
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Linux 需要中文字体（例如 `fonts-wqy-microhei`）以及 Qt offscreen 平台库。GitHub Actions 在 Python 3.11 上执行同一套测试。

`templates/standard_template.xlsx` 是本机私有模板，已写入 `.gitignore`，不要提交。程序在该文件存在时默认用它，缺失或损坏时改为自定义核对模式。打包前运行 `Build.cmd`，缺少该文件会直接停止。公开测试使用代码生成的假模板。汇总导出把多份扫描写入同一工作簿的「管理类_件」；`python tools/compare_template.py <模板> <导出文件>` 检查除数据单元格外是否与模板一致。固定默认值在 `catalog_defaults.py`，目前全部留空。

## 许可证

本项目原创代码按 MIT 许可证提供，见 LICENSE。第三方依赖不在本许可证授权范围内，见 THIRD_PARTY_NOTICES.md；打包和分发依赖时需遵守各自条款。
