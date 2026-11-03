"""Zero-dependency pure-Python YAML 1.2 subset loader and dumper fallback.
Used automatically when PyYAML is not installed in the active Python environment.
"""

import ast
import json
import re
from typing import IO, Any


class YAMLError(Exception):
    """YAML parsing error."""


def _parse_scalar(val: str) -> Any:
    val = val.strip()
    if not val or val in ("null", "Null", "NULL", "~"):
        return None
    if val in ("true", "True", "TRUE"):
        return True
    if val in ("false", "False", "FALSE"):
        return False
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        if val.startswith("'"):
            return val[1:-1].replace("''", "'")
        try:
            return ast.literal_eval(val)
        except (ValueError, SyntaxError):
            return val[1:-1]
    if re.match(r"^-?\d+$", val):
        return int(val)
    if re.match(r"^-?\d+\.\d+$", val):
        return float(val)
    if val.startswith("[") and val.endswith("]"):
        return _parse_flow_seq(val[1:-1])
    if val.startswith("{") and val.endswith("}"):
        return _parse_flow_map(val[1:-1])
    return val


def _split_flow_items(text: str) -> list[str]:
    items: list[str] = []
    cur: list[str] = []
    depth = 0
    in_quote: str | None = None
    for ch in text:
        if in_quote:
            cur.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            cur.append(ch)
        elif ch in ("[", "{"):
            depth += 1
            cur.append(ch)
        elif ch in ("]", "}"):
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        items.append(tail)
    return items


def _parse_flow_seq(inner: str) -> list[Any]:
    if not inner.strip():
        return []
    return [_parse_scalar(item) for item in _split_flow_items(inner)]


def _parse_flow_map(inner: str) -> dict[str, Any]:
    if not inner.strip():
        return {}
    out: dict[str, Any] = {}
    for item in _split_flow_items(inner):
        if ":" in item:
            k, v = item.split(":", 1)
            out[str(_parse_scalar(k))] = _parse_scalar(v)
    return out


def _strip_comment(line: str) -> str:
    in_quote: str | None = None
    for i, ch in enumerate(line):
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line.rstrip()


def _split_key_val(text: str) -> tuple[str, str] | None:
    in_quote: str | None = None
    depth = 0
    for i, ch in enumerate(text):
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
        elif ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
        elif ch == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1].isspace()):
            return text[:i].strip(), text[i + 1 :].strip()
    return None


def safe_load(stream: str | bytes | IO[Any]) -> Any:
    """Parse YAML or JSON document into Python objects."""
    if hasattr(stream, "read"):
        raw = stream.read()
    else:
        raw = stream
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = str(raw)

    text_stripped = text.strip()
    if not text_stripped:
        return None
    if text_stripped.startswith(("{", "[")):
        try:
            return json.loads(text_stripped)
        except json.JSONDecodeError:
            pass

    raw_lines = text.splitlines()
    lines: list[tuple[int, str]] = []
    i = 0
    while i < len(raw_lines):
        raw_line = raw_lines[i]
        cleaned = _strip_comment(raw_line)
        if not cleaned.strip() or cleaned.strip() == "---":
            i += 1
            continue
        if "\t" in cleaned[: len(cleaned) - len(cleaned.lstrip())]:
            raise YAMLError("Tabs are not allowed for indentation in YAML")
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        lines.append((indent, cleaned.strip()))
        i += 1

    if not lines:
        return None

    idx = 0

    def parse_node(min_indent: int) -> Any:
        nonlocal idx
        if idx >= len(lines):
            return None
        cur_indent, cur_text = lines[idx]
        if cur_indent < min_indent:
            return None
        if cur_text.startswith("- ") or cur_text == "-":
            return parse_seq(cur_indent)
        if _split_key_val(cur_text) is not None:
            return parse_map(cur_indent)
        idx += 1
        return _parse_scalar(cur_text)

    def parse_seq(seq_indent: int) -> list[Any]:
        nonlocal idx
        arr: list[Any] = []
        while idx < len(lines):
            ind, txt = lines[idx]
            if ind < seq_indent or not (txt.startswith("- ") or txt == "-"):
                break
            if ind > seq_indent:
                break
            idx += 1
            rest = txt[1:].strip()
            if not rest:
                sub = parse_node(seq_indent + 1)
                arr.append(sub)
                continue
            kv = _split_key_val(rest)
            if kv is not None:
                k_str, v_str = kv
                item_dict: dict[str, Any] = {}
                key = str(_parse_scalar(k_str))
                if v_str in (">", "|", ">-", "|-"):
                    item_dict[key] = parse_block_scalar(ind + 2)
                elif v_str == "":
                    item_dict[key] = parse_node(ind + 1)
                else:
                    item_dict[key] = _parse_scalar(v_str)
                while idx < len(lines) and lines[idx][0] > ind:
                    sub_ind, sub_txt = lines[idx]
                    if sub_txt.startswith("-"):
                        break
                    sub_kv = _split_key_val(sub_txt)
                    if sub_kv is None:
                        break
                    idx += 1
                    sk, sv = sub_kv
                    skey = str(_parse_scalar(sk))
                    if sv in (">", "|", ">-", "|-"):
                        item_dict[skey] = parse_block_scalar(sub_ind)
                    elif sv == "":
                        item_dict[skey] = parse_node(sub_ind + 1)
                    else:
                        item_dict[skey] = _parse_scalar(sv)
                arr.append(item_dict)
            else:
                arr.append(_parse_scalar(rest))
        return arr

    def parse_block_scalar(parent_indent: int) -> str:
        nonlocal idx
        parts: list[str] = []
        while idx < len(lines) and lines[idx][0] > parent_indent:
            parts.append(lines[idx][1])
            idx += 1
        return " ".join(parts)

    def parse_map(map_indent: int) -> dict[str, Any]:
        nonlocal idx
        mapping: dict[str, Any] = {}
        while idx < len(lines):
            ind, txt = lines[idx]
            if ind < map_indent:
                break
            if ind > map_indent:
                idx += 1
                continue
            if txt.startswith("- ") or txt == "-":
                break
            kv = _split_key_val(txt)
            if kv is None:
                break
            idx += 1
            k_str, v_str = kv
            key = str(_parse_scalar(k_str))
            if v_str in (">", "|", ">-", "|-"):
                mapping[key] = parse_block_scalar(ind)
            elif v_str == "":
                if idx < len(lines) and lines[idx][0] >= ind:
                    if lines[idx][0] == ind and (
                        lines[idx][1].startswith("- ") or lines[idx][1] == "-"
                    ):
                        mapping[key] = parse_seq(ind)
                    elif lines[idx][0] > ind:
                        mapping[key] = parse_node(ind + 1)
                    else:
                        mapping[key] = None
                else:
                    mapping[key] = None
            else:
                mapping[key] = _parse_scalar(v_str)
        return mapping

    return parse_node(0)


def _format_scalar(val: Any) -> str:
    if val is None:
        return "null"
    if val is True:
        return "true"
    if val is False:
        return "false"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    if (
        s == ""
        or s in ("null", "true", "false", "~")
        or "\n" in s
        or ":" in s
        or "#" in s
        or s.startswith(
            ("{", "[", "-", "?", "*", "&", "!", "%", "@", "`", " ", "'", '"')
        )
        or s.endswith(" ")
        or re.match(r"^-?\d+(\.\d+)?$", s)
    ):
        return json.dumps(s)
    return s


def _dump_lines(obj: Any, indent: int = 0, sort_keys: bool = True) -> list[str]:
    prefix = " " * indent
    if isinstance(obj, dict):
        if not obj:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        keys = sorted(obj.keys(), key=str) if sort_keys else list(obj.keys())
        for k in keys:
            v = obj[k]
            k_str = _format_scalar(k)
            if isinstance(v, dict):
                if not v:
                    lines.append(f"{prefix}{k_str}: {{}}")
                else:
                    lines.append(f"{prefix}{k_str}:")
                    lines.extend(_dump_lines(v, indent + 2, sort_keys=sort_keys))
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{prefix}{k_str}: []")
                else:
                    lines.append(f"{prefix}{k_str}:")
                    lines.extend(_dump_lines(v, indent + 2, sort_keys=sort_keys))
            else:
                lines.append(f"{prefix}{k_str}: {_format_scalar(v)}")
        return lines
    if isinstance(obj, list):
        if not obj:
            return [f"{prefix}[]"]
        lines = []
        for item in obj:
            if isinstance(item, dict) and item:
                sub = _dump_lines(item, indent + 2, sort_keys=sort_keys)
                first = sub[0].lstrip(" ")
                lines.append(f"{prefix}- {first}")
                lines.extend(sub[1:])
            elif isinstance(item, (list, dict)):
                lines.append(f"{prefix}- {json.dumps(item)}")
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return lines
    return [f"{prefix}{_format_scalar(obj)}"]


def safe_dump(
    data: Any, stream: IO[str] | None = None, sort_keys: bool = True, **_kwargs: Any
) -> str:
    """Serialize Python object to block YAML."""
    output = "\n".join(_dump_lines(data, indent=0, sort_keys=sort_keys)) + "\n"
    if stream is not None:
        stream.write(output)
    return output


def dump(
    data: Any, stream: IO[str] | None = None, sort_keys: bool = True, **kwargs: Any
) -> str:
    """Alias for safe_dump."""
    return safe_dump(data, stream=stream, sort_keys=sort_keys, **kwargs)
