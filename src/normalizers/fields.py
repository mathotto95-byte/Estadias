from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


def normalize_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().upper()


def normalize_location_key(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalizar_texto_match(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"[\u200b-\u200f\ufeff\r\n\t]+", " ", text)
    text = re.sub(r"[-/\\.,;:]+", " ", text)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalizar_produto_kmm_coupa(value: Any) -> str:
    text = normalizar_texto_match(value)
    if text in {"T TODOS", "T TODO", "TODOS", "TODO"}:
        return "TODOS"
    if ("ETANOL" in text or "ALCOOL" in text) and "ANIDRO" in text:
        return "ETANOL ANIDRO"
    if ("ETANOL" in text or "ALCOOL" in text) and "HIDRATADO" in text:
        return "ETANOL HIDRATADO"
    if "ETANOL" in text or "ALCOOL" in text:
        return "ETANOL"
    if "BIODIESEL" in text or "B100" in text:
        return "BIODIESEL"
    if "DIESEL" in text or "GASOLINA" in text or "DERIVADO" in text:
        return "DERIVADOS"
    return text


def normalizar_produto_ipiranga(value: Any) -> str:
    return normalizar_produto_kmm_coupa(value)


def normalize_column_name(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "coluna"


def make_unique_columns(columns: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for column in columns:
        base = normalize_column_name(column)
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def normalize_cnpj(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    digits = re.sub(r"\D", "", text)
    return digits.zfill(14) if digits and len(digits) < 14 else digits


def normalize_plate(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))


def normalize_document_number(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    text = re.sub(r"\.0$", "", text)
    digits = re.sub(r"\D", "", text)
    return digits.lstrip("0") or digits


def normalizar_nf(value: Any) -> str:
    return normalize_document_number(value)


def parse_date(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().isoformat(timespec="seconds")
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat(timespec="seconds")
    try:
        number = float(value)
        if 30000 <= number <= 60000:
            converted = datetime(1899, 12, 30) + timedelta(days=number)
            return converted.isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text in {"0", "00/00/0000", "0000-00-00"}:
        return ""
    converted = pd.to_datetime(text, dayfirst=not text.startswith(tuple(str(y) for y in range(1900, 2100))), errors="coerce")
    if pd.isna(converted):
        converted = pd.to_datetime(text, dayfirst=True, errors="coerce")
    return "" if pd.isna(converted) else converted.to_pydatetime().isoformat(timespec="seconds")


def parse_excel_date(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().isoformat(timespec="seconds")
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat(timespec="seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = pd.to_datetime(float(value), unit="D", origin="1899-12-30", errors="coerce")
            return "" if pd.isna(converted) else converted.to_pydatetime().isoformat(timespec="seconds")
        except (OverflowError, ValueError, TypeError):
            return ""
    text = str(value).strip()
    if not text or text in {"0", "00/00/0000", "0000-00-00"}:
        return ""
    try:
        number = float(text.replace(",", "."))
        if 30000 <= number <= 60000:
            converted = pd.to_datetime(number, unit="D", origin="1899-12-30", errors="coerce")
            return "" if pd.isna(converted) else converted.to_pydatetime().isoformat(timespec="seconds")
    except (OverflowError, ValueError, TypeError):
        pass
    converted = pd.to_datetime(text, dayfirst=True, errors="coerce")
    return "" if pd.isna(converted) else converted.to_pydatetime().isoformat(timespec="seconds")


def converter_data_excel_robusta(value: Any) -> str:
    return parse_excel_date(value)


def parse_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[^\d,.\-]", "", text)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def normalizar_valor_monetario(value: Any) -> float | None:
    return parse_number(value)


def safe_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def hash_dict(value: dict) -> str:
    return hashlib.sha256(safe_json(value).encode("utf-8")).hexdigest()


def get_first(row: dict, aliases: list[str]) -> Any:
    for alias in aliases:
        normalized = normalize_column_name(alias)
        if normalized in row and not is_empty(row[normalized]):
            return row[normalized]
    return None


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except ValueError:
        return False


def split_nf_list(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    pieces = re.split(r"[/;,|]+", str(value))
    notes: list[str] = []
    seen: set[str] = set()
    for nf in (normalize_document_number(piece) for piece in pieces):
        if nf and nf not in seen:
            notes.append(nf)
            seen.add(nf)
    return notes


def to_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        converted = pd.to_datetime(value, errors="coerce", dayfirst=True)
        return None if pd.isna(converted) else converted.to_pydatetime()
