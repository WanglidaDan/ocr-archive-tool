"""Evaluation import path for the shared 公文 rules.

The implementation lives in ``enhanced_rules`` so the app setting and this
benchmark call the same functions.
"""
from enhanced_rules import (  # noqa: F401
    ORG,
    SECRET,
    TITLE_END,
    apply_enhanced,
    extract_rules_plus,
)
