"""写入「管理类_件」的默认值。

留空表示该列导出时不填写。程序启动时用这里的值；用户在「字段与模型设置」
里的修改保存在本机项目文件中，并覆盖同名字段。下拉列必须是模板里的原文。
"""

from unit_link import unit_key

DEFAULT_SHEET = "管理类_件"

DEFAULTS = {
    "保管期限": "",
    "载体类型": "",
    "保密期限": "",
    "模版类型": "",
    "来源": "",
    "数量": "",
    "履行阶段": "",
    "框架代码": "",
    "专题标签": "",
    "职能标签": "",
}


def effective_defaults(saved=None):
    """Known fields only. A saved blank overrides the built-in value."""
    values = {field: DEFAULTS[field] for field in DEFAULTS}
    if not isinstance(saved, dict):
        return values
    for field in DEFAULTS:
        if field in saved and saved[field] is not None:
            values[field] = str(saved[field]).strip()
    return values


def _dropdown_match(value, options):
    key = unit_key(value)
    if not key or not options:
        return ""
    found = [item for item in options if unit_key(item) == key]
    if len(found) == 1:
        return found[0]
    return ""


def validate_defaults(saved, choices=None):
    """Return (values, error). error is empty when every dropdown default fits.

    Fields with no list in the current template are kept as text. A blank
    dropdown value is allowed. A non-blank value must match one list entry.
    """
    values = effective_defaults(saved)
    choices = choices or {}
    rejected = []
    for field in DEFAULTS:
        options = list(choices.get(field) or [])
        if not options or not values[field]:
            continue
        matched = _dropdown_match(values[field], options)
        if not matched:
            rejected.append(field + "「" + values[field] + "」")
        else:
            values[field] = matched
    if not rejected:
        return values, ""
    return (
        values,
        "以下默认值不在当前模板下拉项中：" + "、".join(rejected),
    )
