"""
模块拆分相关的 Prompt 模板
从 txt 文件加载，便于维护和调整
"""

import os

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_prompt(filename: str) -> str:
    """从 txt 文件加载 prompt 模板"""
    filepath = os.path.join(_CURRENT_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# 系统提示
SPLIT_SYSTEM_PROMPT = _load_prompt("split_system_prompt.txt")
# 用户提示模板
SPLIT_USER_PROMPT = _load_prompt("split_user_prompt.txt")
# PDF 文本提取提示
PDF_EXTRACT_PROMPT = _load_prompt("pdf_extract_prompt.txt")
