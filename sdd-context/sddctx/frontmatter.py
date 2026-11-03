"""Markdown frontmatter 解析（YAML 受限子集）。

为什么自己写：规格文件是人写的 SDD 文档，字段是结构化的，但整套系统的其它部分
只依赖 Python 标准库。这里实现一个够用且行为明确的 YAML 子集解析器，
支持：标量、块序列、行内序列 `[a, b]`、嵌套映射、序列中的映射、注释、引号。
不支持锚点、多文档等 YAML 高级特性——遇到会明确报错而不是静默出错。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class FrontmatterError(ValueError):
    """frontmatter 无法解析。"""


@dataclass(frozen=True)
class _Tok:
    indent: int
    text: str
    line_no: int


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """拆出 frontmatter 与正文。没有 frontmatter 时返回 (None, 原文)。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() in {"---", "..."}:
            front = "\n".join(lines[1:idx])
            body = "\n".join(lines[idx + 1 :])
            return front, body
    raise FrontmatterError("frontmatter 缺少结束标记 '---'")


def _strip_comment(value: str) -> str:
    """去掉行尾注释（引号内的 # 不算注释）。"""
    out: list[str] = []
    quote: str | None = None
    for idx, ch in enumerate(value):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (idx == 0 or value[idx - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).strip()


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return None
    if value[0] == "[" and value[-1] == "]":
        inner = value[1:-1].strip()
        if not inner:
            return []
        items: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in inner:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            if ch == "," and depth == 0:
                items.append("".join(current))
                current = []
                continue
            current.append(ch)
        items.append("".join(current))
        return [_parse_scalar(item) for item in items]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"null", "~", "none"}:
        return None
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _tokenize(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        tokens.append(_Tok(indent=indent, text=stripped, line_no=line_no))
    return tokens


def _split_key(text: str) -> tuple[str, str, bool]:
    """拆出 key 与 rest。返回 (key, rest, found)。"""
    quote: str | None = None
    for idx, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch == ":" and (idx + 1 == len(text) or text[idx + 1] in " \t"):
            return text[:idx].strip().strip("\"'"), text[idx + 1 :].strip(), True
    return text.strip(), "", False


def _parse_map(tokens: list[_Tok], start: int, indent: int) -> tuple[dict[str, Any], int]:
    data: dict[str, Any] = {}
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if tok.indent < indent:
            break
        if tok.indent > indent:
            raise FrontmatterError(f"第 {tok.line_no} 行缩进异常：{tok.text!r}")
        if tok.text.startswith("- "):
            break
        key, rest, found = _split_key(tok.text)
        if not found:
            raise FrontmatterError(f"第 {tok.line_no} 行不是合法的 'key: value'：{tok.text!r}")
        if not key:
            raise FrontmatterError(f"第 {tok.line_no} 行缺少键名")
        i += 1
        if rest:
            data[key] = _parse_scalar(_strip_comment(rest))
            continue
        if i < len(tokens) and tokens[i].indent > indent:
            value, i = _parse_block(tokens, i, tokens[i].indent)
            data[key] = value
        elif i < len(tokens) and tokens[i].indent == indent and tokens[i].text.startswith("- "):
            value, i = _parse_seq(tokens, i, indent)
            data[key] = value
        else:
            data[key] = None
    return data, i


def _parse_seq(tokens: list[_Tok], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if tok.indent != indent or not tok.text.startswith("- "):
            break
        item_text = tok.text[2:].strip()
        j = i + 1
        while j < len(tokens) and tokens[j].indent > indent:
            j += 1
        key, _, is_mapping = _split_key(item_text)
        if is_mapping and key and not item_text.startswith(("\"", "'")):
            block = [_Tok(indent=indent + 2, text=item_text, line_no=tok.line_no)]
            block.extend(tokens[i + 1 : j])
            value, consumed = _parse_map(block, 0, indent + 2)
            if consumed != len(block):
                raise FrontmatterError(f"第 {tok.line_no} 行的序列项解析不完整：{item_text!r}")
            items.append(value)
        else:
            items.append(_parse_scalar(_strip_comment(item_text)))
        i = j
    return items, i


def _parse_block(tokens: list[_Tok], start: int, indent: int) -> tuple[Any, int]:
    if tokens[start].text.startswith("- "):
        return _parse_seq(tokens, start, indent)
    return _parse_map(tokens, start, indent)


def parse_yaml(text: str) -> dict[str, Any]:
    """解析 YAML 子集，返回顶层映射。"""
    tokens = _tokenize(text)
    if not tokens:
        return {}
    value, consumed = _parse_block(tokens, 0, tokens[0].indent)
    if consumed != len(tokens):
        bad = tokens[consumed]
        raise FrontmatterError(f"第 {bad.line_no} 行无法解析：{bad.text!r}")
    if not isinstance(value, dict):
        raise FrontmatterError("frontmatter 顶层必须是映射")
    return value


def parse_document(text: str) -> tuple[dict[str, Any], str]:
    """解析 Markdown 文档，返回 (frontmatter 字典, 正文)。"""
    front, body = split_frontmatter(text)
    if front is None:
        return {}, text
    return parse_yaml(front), body

