"""Turn library exceptions into short Chinese messages.

Export and recognition must not show FileDataError, BadZipFile, or Errno text.
"""

import errno
import re
import zipfile

_CJK = re.compile(r"[\u4e00-\u9fff]")


def chinese_message(error):
    """Return a Chinese description. Messages that are already Chinese stay."""
    if error is None:
        return "处理失败。"
    if isinstance(error, str):
        text = error.strip()
        return text if _CJK.search(text) else "处理失败，请检查文件后重试。"
    name = type(error).__name__
    if name == "EmptyFileError":
        return "文件是空的，无法读取。"
    if name == "FileDataError":
        return "文件已损坏，不是有效的 PDF。"
    if isinstance(error, FileNotFoundError):
        target = getattr(error, "filename", None) or ""
        if target:
            return "找不到文件：" + str(target)
        return "找不到文件。"
    if isinstance(error, zipfile.BadZipFile) or name == "BadZipFile":
        return "导出模板无法读取（文件已损坏或不是有效的 Excel）。"
    if isinstance(error, OSError):
        code = error.errno
        if code in (errno.EACCES, errno.EPERM) or isinstance(error, PermissionError):
            return "没有读取或写入权限。"
        if code == errno.ENOSPC:
            return "磁盘空间不足。"
        if code == errno.ENAMETOOLONG:
            return "路径过长，无法写入。"
        text = str(error)
        if _CJK.search(text):
            return text
        return "文件读写失败，请检查路径、权限和磁盘空间。"
    text = str(error).strip()
    if _CJK.search(text):
        return text
    return "处理失败，请检查文件后重试。"
