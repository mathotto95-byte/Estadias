from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.database.connection import get_connection, read_sql
from src.database.migrations import MODULAR_COPY_MAP
from src.utils.timezone import brasilia_now_iso


def table_exists(table: str) -> bool:
    with get_connection() as conn:
        if getattr(conn, "db_type", "sqlite") == "postgres":
            row = conn.execute(
                """
                select 1
                from information_schema.tables
                where table_schema = 'public' and table_name = ?
                """,
                (table,),
            ).fetchone()
        else:
            row = conn.execute(
                "select 1 from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()
    return bool(row)


def table_count(table: str) -> int:
    if not table_exists(table):
        return 0
    try:
        with get_connection() as conn:
            row = conn.execute(f"select count(*) from {table}").fetchone()
            return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def preferred_table(modular_table: str, legacy_table: str = "") -> tuple[str, bool]:
    if table_count(modular_table) > 0:
        return modular_table, False
    if legacy_table and table_count(legacy_table) > 0:
        return legacy_table, True
    return modular_table, False


def read_preferred_table(modular_table: str, legacy_table: str = "", limit: int = 500) -> tuple[pd.DataFrame, bool, str]:
    table, using_fallback = preferred_table(modular_table, legacy_table)
    if not table_exists(table):
        return pd.DataFrame(), using_fallback, table
    return read_sql(f"select * from {table} limit ?", (limit,)), using_fallback, table


def insert_system_log(
    usuario: str,
    modulo: str,
    submodulo: str,
    acao: str,
    nivel: str,
    mensagem: str,
    detalhes: dict[str, Any] | None = None,
) -> None:
    payload = json.dumps(detalhes or {}, ensure_ascii=False, default=str)
    with get_connection() as conn:
        conn.execute(
            """
            insert into logs_sistema_modular (
                data_hora, usuario, modulo, submodulo, acao, nivel, mensagem, detalhes_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (brasilia_now_iso(), usuario, modulo, submodulo, acao, nivel, mensagem, payload),
        )


def latest_import_logs(table: str, limit: int = 10) -> pd.DataFrame:
    if not table_exists(table):
        return pd.DataFrame()
    return read_sql(
        f"""
        select data_hora, usuario, tipo_importacao, arquivo_origem, quantidade_linhas,
               quantidade_registros_inseridos, quantidade_registros_atualizados,
               quantidade_registros_ignorados, status, mensagem, lote_importacao
        from {table}
        order by id desc
        limit ?
        """,
        (limit,),
    )


def modular_counts() -> pd.DataFrame:
    rows = []
    for legacy_table, modular_table in MODULAR_COPY_MAP.items():
        rows.append(
            {
                "Tabela origem": legacy_table,
                "Tabela modular": modular_table,
                "Linhas origem": table_count(legacy_table),
                "Linhas modular": table_count(modular_table),
                "Usando fallback": "SIM" if table_count(modular_table) == 0 and table_count(legacy_table) > 0 else "NAO",
            }
        )
    return pd.DataFrame(rows)

