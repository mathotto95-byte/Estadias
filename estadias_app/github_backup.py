from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from src.database.connection import get_connection, read_sql
from src.modules.estadias.repository import (
    AUDITORIA_TABLE,
    CONFIG_TABLE,
    CONCLUSOES_TABLE,
    CONTROL_NORMALIZED_TABLE,
    CONTROL_ORIGINAL_TABLE,
    CROSS_TABLE,
    LCTE_NORMALIZED_TABLE,
    LCTE_ORIGINAL_TABLE,
    LOCAIS_TABLE,
    LOG_TABLE,
    PARAMETROS_TABLE,
    PREFERENCIAS_COLUNAS_TABLE,
    RASTREADOR_NORMALIZED_TABLE,
    RASTREADOR_ORIGINAL_TABLE,
    STATUS_LOG_TABLE,
)
from src.utils.timezone import brasilia_now_iso


ESTADIAS_TABLES = [
    LCTE_ORIGINAL_TABLE,
    LCTE_NORMALIZED_TABLE,
    CONTROL_ORIGINAL_TABLE,
    CONTROL_NORMALIZED_TABLE,
    RASTREADOR_ORIGINAL_TABLE,
    RASTREADOR_NORMALIZED_TABLE,
    LOG_TABLE,
    CROSS_TABLE,
    CONFIG_TABLE,
    LOCAIS_TABLE,
    PARAMETROS_TABLE,
    AUDITORIA_TABLE,
    CONCLUSOES_TABLE,
    PREFERENCIAS_COLUNAS_TABLE,
    STATUS_LOG_TABLE,
]

BACKUP_TABLES = [
    CROSS_TABLE,
    CONCLUSOES_TABLE,
    AUDITORIA_TABLE,
    STATUS_LOG_TABLE,
    CONFIG_TABLE,
    LOCAIS_TABLE,
    PARAMETROS_TABLE,
    PREFERENCIAS_COLUNAS_TABLE,
]

# Quantidade de snapshots historicos mantidos em backups/history no GitHub.
# Sem essa poda, cada backup automatico adiciona um arquivo novo para sempre,
# fazendo o repositorio (e o clone/deploy) crescer indefinidamente.
HISTORY_RETENTION_KEEP = 10

SECRET_ALIASES = {
    "GITHUB_TOKEN": ["GITHUB_TOKEN", "github_token", "token"],
    "GITHUB_REPOSITORY": ["GITHUB_REPOSITORY", "github_repository", "repository", "repo"],
    "GITHUB_BRANCH": ["GITHUB_BRANCH", "github_branch", "branch"],
    "GITHUB_BACKUP_PATH": ["GITHUB_BACKUP_PATH", "github_backup_path", "backup_path", "latest_path"],
    "GITHUB_AUTO_BACKUP": ["GITHUB_AUTO_BACKUP", "github_auto_backup", "auto_backup"],
}


def _read_secret(name: str, default: str = "") -> str:
    candidates = SECRET_ALIASES.get(name, [name])
    try:
        import streamlit as st

        for candidate in candidates:
            value = st.secrets.get(candidate)
            if value not in [None, ""]:
                return str(value).strip()
        github = st.secrets.get("github", {})
        if github:
            for candidate in candidates:
                value = github.get(candidate)
                if value not in [None, ""]:
                    return str(value).strip()
    except Exception:
        pass
    for candidate in candidates:
        value = os.getenv(candidate)
        if value not in [None, ""]:
            return str(value).strip()
    return default


def _sanitize_token(value: str) -> str:
    token = str(value or "").strip().strip('"').strip("'")
    for prefix in ["Bearer ", "bearer ", "token ", "Token "]:
        if token.startswith(prefix):
            token = token[len(prefix) :].strip()
    return token


def _token_is_placeholder(token: str) -> bool:
    cleaned = str(token or "").strip()
    return bool(cleaned) and ("..." in cleaned or cleaned in {"github_pat_", "ghp_", "gho_"})


def _mask_token(token: str) -> str:
    cleaned = str(token or "").strip()
    if not cleaned:
        return "nao configurado"
    if len(cleaned) <= 12:
        return "***"
    return f"{cleaned[:10]}...{cleaned[-4:]}"


def _yes(value: object, default: bool = False) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return default
    return text in {"1", "SIM", "S", "TRUE", "YES", "ON"}


def github_settings() -> dict[str, Any]:
    return {
        "token": _sanitize_token(_read_secret("GITHUB_TOKEN")),
        "repository": _read_secret("GITHUB_REPOSITORY", "mathotto95-byte/Estadias"),
        "branch": _read_secret("GITHUB_BRANCH", "main"),
        "latest_path": _read_secret("GITHUB_BACKUP_PATH", "backups/estadias_latest.json"),
        "healthcheck_path": _read_secret("GITHUB_HEALTHCHECK_PATH", "backups/_healthcheck.json"),
        "auto_backup": _yes(_read_secret("GITHUB_AUTO_BACKUP", "SIM"), True),
    }


def github_backup_configured() -> bool:
    settings = github_settings()
    return bool(settings["token"] and not _token_is_placeholder(settings["token"]) and settings["repository"] and settings["branch"])


def github_auto_backup_enabled() -> bool:
    settings = github_settings()
    return bool(github_backup_configured() and settings["auto_backup"])


def _api_url(repository: str, path: str) -> str:
    safe_path = "/".join(quote(part) for part in path.strip("/").split("/"))
    return f"https://api.github.com/repos/{repository}/contents/{safe_path}"


def _repo_api_url(repository: str) -> str:
    return f"https://api.github.com/repos/{quote(repository, safe='/')}"


def _build_request(method: str, url: str, token: str, payload: dict[str, Any] | None, auth_scheme: str) -> Request:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"{auth_scheme} {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    return request


def _request_json(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    last_unauthorized: HTTPError | None = None
    for auth_scheme in ["Bearer", "token"]:
        request = _build_request(method, url, token, payload, auth_scheme)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as exc:
            if exc.code == 401 and auth_scheme == "Bearer":
                last_unauthorized = exc
                continue
            raise
    if last_unauthorized:
        raise last_unauthorized
    return {}


def _remote_sha(settings: dict[str, Any], path: str) -> str:
    url = _api_url(settings["repository"], path) + f"?ref={quote(settings['branch'])}"
    try:
        result = _request_json("GET", url, settings["token"])
        return str(result.get("sha") or "")
    except HTTPError as exc:
        if exc.code == 404:
            return ""
        raise


def _download_text(settings: dict[str, Any], path: str) -> str:
    url = _api_url(settings["repository"], path) + f"?ref={quote(settings['branch'])}"
    result = _request_json("GET", url, settings["token"])
    content = str(result.get("content") or "").replace("\n", "")
    encoding = str(result.get("encoding") or "")
    if encoding == "base64":
        return base64.b64decode(content.encode("ascii")).decode("utf-8")
    return content


def _upload_bytes(settings: dict[str, Any], path: str, content: bytes, message: str, retries: int = 3) -> dict[str, Any]:
    last_error: HTTPError | None = None
    for attempt in range(max(int(retries or 1), 1)):
        payload = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": settings["branch"],
        }
        sha = _remote_sha(settings, path)
        if sha:
            payload["sha"] = sha
        try:
            return _request_json("PUT", _api_url(settings["repository"], path), settings["token"], payload)
        except HTTPError as exc:
            last_error = exc
            if exc.code != 409 or attempt >= retries - 1:
                raise
            time.sleep(0.8 + attempt * 0.8)
    if last_error:
        raise last_error
    return {}


def _list_directory(settings: dict[str, Any], path: str) -> list[dict[str, Any]]:
    url = _api_url(settings["repository"], path) + f"?ref={quote(settings['branch'])}"
    try:
        request = Request(url, method="GET")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {settings['token']}")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        with urlopen(request, timeout=30) as response:
            raw = response.read()
        result = json.loads(raw.decode("utf-8")) if raw else []
        return result if isinstance(result, list) else []
    except HTTPError as exc:
        if exc.code == 404:
            return []
        raise


def _delete_file(settings: dict[str, Any], path: str, sha: str, message: str) -> None:
    payload = {"message": message, "sha": sha, "branch": settings["branch"]}
    _request_json("DELETE", _api_url(settings["repository"], path), settings["token"], payload)


def prune_history(keep: int = HISTORY_RETENTION_KEEP) -> dict[str, Any]:
    """Remove snapshots antigos de backups/history, mantendo apenas os `keep` mais recentes.

    Os nomes dos arquivos comecam com timestamp (YYYYMMDD_HHMMSS), entao a
    ordenacao alfabetica corresponde a ordenacao cronologica.
    """
    settings = github_settings()
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "removidos": 0}
    entries = _list_directory(settings, "backups/history")
    files = sorted((item for item in entries if item.get("type") == "file"), key=lambda item: str(item.get("name") or ""))
    excess = files[: max(len(files) - max(int(keep or 1), 1), 0)]
    removed = 0
    errors = 0
    for item in excess:
        try:
            _delete_file(settings, str(item.get("path")), str(item.get("sha")), "Poda de historico de backup (retencao automatica)")
            removed += 1
        except Exception:
            errors += 1
    return {"status": "SUCESSO" if errors == 0 else "PARCIAL", "removidos": removed, "erros": errors, "restantes": len(files) - removed}


def _github_http_error_message(exc: HTTPError) -> str:
    if exc.code == 401:
        return "GitHub recusou o token: token invalido, expirado ou sem acesso."
    if exc.code == 403:
        return "GitHub recusou por permissao. O token precisa ter Contents: Read and write."
    if exc.code == 404:
        return "GitHub nao encontrou o repositorio, branch ou arquivo de backup configurado."
    if exc.code == 422:
        return "GitHub nao conseguiu gravar o arquivo. Confira se a branch existe e permite escrita."
    return str(exc)


def _table_exists(table: str) -> bool:
    try:
        with get_connection() as conn:
            if conn.db_type == "postgres":
                row = conn.execute(
                    "select 1 from information_schema.tables where table_schema = 'public' and table_name = ?",
                    (table,),
                ).fetchone()
            else:
                row = conn.execute("select 1 from sqlite_master where type = 'table' and name = ?", (table,)).fetchone()
        return bool(row)
    except Exception:
        return False


def _table_columns(table: str) -> list[str]:
    with get_connection() as conn:
        if conn.db_type == "postgres":
            rows = conn.execute(
                "select column_name from information_schema.columns where table_schema = 'public' and table_name = ? order by ordinal_position",
                (table,),
            ).fetchall()
            return [str(row[0]) for row in rows]
        rows = conn.execute(f"pragma table_info({table})").fetchall()
        return [str(row["name"] if hasattr(row, "keys") else row[1]) for row in rows]


def all_database_tables() -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for table in BACKUP_TABLES:
        if _table_exists(table):
            tables[table] = read_sql(f"select * from {table}")
        else:
            tables[table] = pd.DataFrame()
    return tables


def backup_payload() -> dict[str, Any]:
    tables = all_database_tables()
    rows = {
        table: json.loads(df.where(pd.notna(df), None).to_json(orient="records", force_ascii=False))
        for table, df in tables.items()
    }
    return {
        "schema": "estadias_backup_v1",
        "generated_at": brasilia_now_iso(),
        "records": {table: len(values) for table, values in rows.items()},
        "tables": rows,
    }


def backup_json_bytes() -> bytes:
    return json.dumps(backup_payload(), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def database_has_data() -> bool:
    for table in BACKUP_TABLES:
        if not _table_exists(table):
            continue
        try:
            df = read_sql(f"select 1 from {table} limit 1")
            if not df.empty:
                return True
        except Exception:
            continue
    return False


def data_signature() -> str:
    pieces: list[str] = []
    with get_connection() as conn:
        for table in BACKUP_TABLES:
            if not _table_exists(table):
                pieces.append(f"{table}:0:0")
                continue
            try:
                row = conn.execute(f"select count(*) as total, max(id) as max_id from {table}").fetchone()
                total = row[0] if row else 0
                max_id = row[1] if row and len(row) > 1 else 0
                pieces.append(f"{table}:{total or 0}:{max_id or 0}")
            except Exception:
                pieces.append(f"{table}:erro:0")
    return "|".join(pieces)


def restore_payload(payload: dict[str, Any], mode: str = "merge") -> dict[str, Any]:
    if str(payload.get("schema") or "") != "estadias_backup_v1":
        raise ValueError("Arquivo JSON nao e um backup Estadias valido.")
    tables = payload.get("tables") or {}
    restored = ignored = errors = 0
    replace = mode == "replace"
    with get_connection() as conn:
        for table in BACKUP_TABLES:
            rows = tables.get(table) or []
            if replace and _table_exists(table):
                conn.execute(f"delete from {table}")
            if not rows:
                continue
            columns = _table_columns(table)
            insert_columns = [column for column in columns if column in rows[0]]
            if not insert_columns:
                ignored += len(rows)
                continue
            placeholders = ", ".join("?" for _ in insert_columns)
            sql = f"insert into {table} ({', '.join(insert_columns)}) values ({placeholders})"
            for row in rows:
                try:
                    conn.execute(sql, tuple(row.get(column) for column in insert_columns))
                    restored += 1
                except Exception:
                    errors += 1
                    ignored += 1
    return {"status": "SUCESSO" if errors == 0 else "PARCIAL", "restored": restored, "ignored": ignored, "errors": errors}


def restore_json_bytes(content: bytes, mode: str = "merge") -> dict[str, Any]:
    payload = json.loads(content.decode("utf-8-sig"))
    return restore_payload(payload, mode)


def backup_to_github(reason: str = "manual") -> dict[str, Any]:
    settings = github_settings()
    if _token_is_placeholder(settings["token"]):
        return {"status": "TOKEN_INVALIDO", "message": "GITHUB_TOKEN incompleto ou com reticencias.", "records": 0}
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "message": "Configure GITHUB_TOKEN para habilitar backup no GitHub.", "records": 0}
    if not database_has_data():
        return {"status": "IGNORADO_BASE_VAZIA", "message": "Backup GitHub ignorado: base vazia.", "records": 0}
    content = backup_json_bytes()
    stamp = brasilia_now_iso().replace("-", "").replace(":", "").replace("T", "_").replace("+", "_")
    history_path = f"backups/history/{stamp}_{uuid.uuid4().hex[:8]}_estadias.json"
    try:
        _upload_bytes(settings, settings["latest_path"], content, f"Backup Estadias latest ({reason})")
        _upload_bytes(settings, history_path, content, f"Backup Estadias historico ({reason})", retries=1)
    except HTTPError as exc:
        return {"status": "ERRO", "message": _github_http_error_message(exc), "records": 0}
    except (URLError, TimeoutError) as exc:
        return {"status": "ERRO", "message": str(exc), "records": 0}
    try:
        prune_history()
    except Exception:
        pass
    payload = json.loads(content.decode("utf-8"))
    return {"status": "SUCESSO", "message": f"Backup enviado para {settings['latest_path']}.", "records": sum(payload["records"].values())}


def restore_from_github_if_empty() -> dict[str, Any]:
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "message": "GitHub backup nao configurado.", "records": 0}
    if database_has_data():
        return {"status": "IGNORADO_BASE_COM_DADOS", "message": "Base local ja possui dados.", "records": 0}
    settings = github_settings()
    try:
        raw = _download_text(settings, settings["latest_path"])
        payload = json.loads(raw)
        total = sum(len(rows or []) for rows in (payload.get("tables") or {}).values())
        if total <= 0:
            return {"status": "IGNORADO_BACKUP_VAZIO", "message": "Backup GitHub vazio.", "records": 0}
        result = restore_payload(payload, "replace")
    except HTTPError as exc:
        if exc.code == 404:
            return {"status": "NAO_ENCONTRADO", "message": "Nenhum backup latest encontrado no GitHub.", "records": 0}
        return {"status": "ERRO", "message": _github_http_error_message(exc), "records": 0}
    except Exception as exc:
        return {"status": "ERRO", "message": str(exc), "records": 0}
    return {"status": "RESTAURADO", "message": "Backup GitHub restaurado.", "records": int(result.get("restored") or 0)}


def github_diagnostic() -> dict[str, Any]:
    settings = github_settings()
    token = settings["token"]
    return {
        "repository": settings["repository"],
        "branch": settings["branch"],
        "latest_path": settings["latest_path"],
        "destination_type": "Arquivo JSON no repositorio GitHub, nao GitHub Release",
        "token_masked": _mask_token(token),
        "token_length": len(token),
        "token_placeholder": _token_is_placeholder(token),
        "configured": github_backup_configured(),
    }


def test_github_connection() -> dict[str, Any]:
    settings = github_settings()
    diagnostic = github_diagnostic()
    if not settings["token"]:
        return {"status": "NAO_CONFIGURADO", "message": "GITHUB_TOKEN nao configurado.", **diagnostic}
    if _token_is_placeholder(settings["token"]):
        return {"status": "TOKEN_INVALIDO", "message": "GITHUB_TOKEN parece incompleto.", **diagnostic}
    try:
        repo = _request_json("GET", _repo_api_url(settings["repository"]), settings["token"])
        healthcheck = {
            "schema": "estadias_github_healthcheck_v1",
            "generated_at": brasilia_now_iso(),
            "repository": settings["repository"],
            "branch": settings["branch"],
            "latest_path": settings["latest_path"],
        }
        _upload_bytes(
            settings,
            settings["healthcheck_path"],
            json.dumps(healthcheck, ensure_ascii=False, indent=2).encode("utf-8"),
            "Teste de escrita Estadias backup GitHub",
            retries=1,
        )
    except HTTPError as exc:
        return {"status": "ERRO", "message": _github_http_error_message(exc), **diagnostic}
    except (URLError, TimeoutError) as exc:
        return {"status": "ERRO", "message": str(exc), **diagnostic}
    return {"status": "SUCESSO", "message": "GitHub conectado e escrita validada.", "repo_private": bool(repo.get("private")), **diagnostic}
