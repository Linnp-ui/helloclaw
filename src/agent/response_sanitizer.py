"""用户可见回复清洗工具。"""

import re


_INTERNAL_HEADER_PATTERNS = [
    re.compile(r"(?im)^\s*#\s*MEMORY\.md\s*$"),
    re.compile(r"(?im)^\s*##\s*长期记忆.*$"),
    re.compile(r"(?im)^\s*##\s*你的身份信息.*$"),
    re.compile(r"(?im)^\s*##\s*用户信息.*$"),
]


def sanitize_user_facing_text(text: str) -> str:
    """清洗可能泄露给用户的内部索引格式。

    目标是移除内部记忆索引标签和标题，不改变正常业务内容。
    """
    if not text:
        return text

    cleaned = text

    # 替换可能泄露的内部名字
    cleaned = cleaned.replace("小智", "Andy")
    cleaned = cleaned.replace("[未提供]", "Andy")  # 替换占位符
    cleaned = cleaned.replace("未提供", "Andy")

    # 去掉 Q/A 包装，保留真正回答内容
    cleaned = re.sub(r"(?is)^\s*Q[：:]\s*.*?\s*A[：:]\s*", "", cleaned)
    cleaned = re.sub(r"(?im)\s*question[：:]\s*.*$", "", cleaned)

    # 去掉内部标题
    for pattern in _INTERNAL_HEADER_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    # 去掉记忆分类标签和来源标签（仅在行首或列表项处）
    cleaned = re.sub(
        r"(?im)^(\s*[-*]?\s*)\[(preference|decision|entity|fact|source)\]\s*",
        r"\1",
        cleaned,
    )

    # 去掉“(来源)”式尾部括号，避免直接暴露索引来源
    cleaned = re.sub(r"(?im)\s*\((?:source|来源)[:：]?\s*[^)]+\)\s*$", "", cleaned)

    # 去掉行尾日期索引，如 [2026-03-27] / [2026-03-27 14:20]
    cleaned = re.sub(
        r"(?im)\s*\[\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\]\s*$",
        "",
        cleaned,
    )

    # 单行回答若以列表符号开头但并非真实列表，去掉前导 "-"
    if "\n" not in cleaned:
        cleaned = re.sub(r"^\s*-\s*(\S)", r"\1", cleaned)

    # 折叠多余空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()
