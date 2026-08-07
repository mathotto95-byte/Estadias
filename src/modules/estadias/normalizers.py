from __future__ import annotations

import re
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.normalizers.fields import normalize_column_name, normalize_text, parse_excel_date, parse_number


PLATE_PATTERN = re.compile(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}")


def normalizar_texto(value: Any) -> str:
    return normalize_text(value)


def normalizar_placa(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return text if PLATE_PATTERN.fullmatch(text) else ""


def extrair_placa_do_nome_arquivo(nome_arquivo: str) -> str:
    stem = Path(str(nome_arquivo or "")).stem.upper()
    compact = re.sub(r"[^A-Z0-9]", "", stem)
    match = PLATE_PATTERN.search(compact)
    return match.group(0) if match else ""


def normalizar_data(value: Any) -> str:
    if value in [None, ""]:
        return ""
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        parsed_iso = pd.to_datetime(text, errors="coerce")
        return "" if pd.isna(parsed_iso) else parsed_iso.date().isoformat()
    parsed_excel = parse_excel_date(value)
    if parsed_excel:
        return parsed_excel[:10]
    try:
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
        return "" if pd.isna(parsed) else parsed.date().isoformat()
    except Exception:
        return ""


def normalizar_hora(value: Any) -> str:
    if value in [None, ""]:
        return ""
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    if isinstance(value, (int, float)) and 0 <= float(value) < 1:
        seconds = int(round(float(value) * 24 * 60 * 60))
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    text = str(value).strip()
    parsed = pd.to_datetime(text, errors="coerce")
    if not pd.isna(parsed):
        return parsed.strftime("%H:%M:%S")
    match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if match:
        hour, minute, second = match.groups()
        return f"{int(hour):02d}:{int(minute):02d}:{int(second or 0):02d}"
    return ""


def normalizar_data_hora(data_value: Any = "", hora_value: Any = "", data_hora_value: Any = "") -> str:
    if data_hora_value not in [None, ""]:
        text = str(data_hora_value).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            parsed_iso = pd.to_datetime(text, errors="coerce")
            if not pd.isna(parsed_iso):
                return parsed_iso.isoformat(sep=" ", timespec="seconds")
        parsed_excel = parse_excel_date(data_hora_value)
        if parsed_excel:
            return parsed_excel.replace("T", " ")[:19]
        parsed = pd.to_datetime(data_hora_value, dayfirst=True, errors="coerce")
        if not pd.isna(parsed):
            return parsed.isoformat(sep=" ", timespec="seconds")
    date_text = normalizar_data(data_value)
    hour_text = normalizar_hora(hora_value) or "00:00:00"
    return f"{date_text} {hour_text}" if date_text else ""


def normalizar_valor_monetario(value: Any) -> float:
    return float(parse_number(value) or 0)


def identificar_coluna_flexivel(columns: Iterable[str], aliases: Iterable[str]) -> str:
    normalized_columns = {normalize_column_name(column): column for column in columns}
    for alias in aliases:
        normalized_alias = normalize_column_name(alias)
        if normalized_alias in normalized_columns:
            return str(normalized_columns[normalized_alias])
    return ""


def row_value(row: dict[str, Any], column: str) -> Any:
    return row.get(column) if column else ""
