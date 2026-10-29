"""Explicit experiment identity; dates are creation dates, never run dates."""
import json
import re
import tomllib
from datetime import datetime
from pathlib import Path


def validate_unique_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{1,6}-[0-9]{8}", value):
        raise ValueError("实验唯一名称须为 1–6 位大写字母-YYYYMMDD（实验建立日期）")
    try:
        datetime.strptime(value.split("-")[1], "%Y%m%d")
    except ValueError as exc:
        raise ValueError("实验唯一名称中的日期无效") from exc


def validate_metadata(value):
    required = {"full_name", "unique_name", "description"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("实验信息须且仅含 full_name、unique_name、description")
    if any(not isinstance(v, str) or not v.strip() for v in value.values()):
        raise ValueError("实验名称、唯一名称和简介均不能为空")
    validate_unique_name(value["unique_name"])
    return dict(value)


def load_metadata(path):
    return validate_metadata(tomllib.loads(Path(path).read_text(encoding="utf-8-sig")))


def save_metadata(path, value):
    value = validate_metadata(value)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in value.items()) + "\n", encoding="utf-8")
    temporary.replace(path)
