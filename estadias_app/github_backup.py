from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from src.database.connection import get_connection, get_database_config, read_sql
from src.modules.estadias.repository import (
    ANALYSIS_TABLE,
    AUDITORIA_TABLE,
    CONFIG_TABLE,
    CONCLUSOES_TABLE,
    CROSS_TABLE,
    ESTADIA_POSITIONS_TABLE,
    LCTE_NORMALIZED_TABLE,
    LCTE_ORIGINAL_TABLE,
    LOCAIS_TABLE,
    LOG_TABLE,
    PARAMETROS_TABLE,
    PREFERENCIAS_COLUNAS_TABLE,
    RASTREADOR_NORMALIZED_TABLE,
    RASTREADOR_ORIGINAL_TABLE,
    STATUS_LOG_TABLE,
    restore_analysis_dates,
    save_no_treatment_flag,
    save_manual_conferences,
)
from src.utils.timezone import brasilia_now, brasilia_now_iso


ESTADIAS_TABLES = [
    LCTE_ORIGINAL_TABLE,
    LCTE_NORMALIZED_TABLE,
    RASTREADOR_ORIGINAL_TABLE,
    RASTREADOR_NORMALIZED_TABLE,
    ESTADIA_POSITIONS_TABLE,
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
    ANALYSIS_TABLE,
    CONCLUSOES_TABLE,
    AUDITORIA_TABLE,
    STATUS_LOG_TABLE,
    CONFIG_TABLE,
    LOCAIS_TABLE,
    PARAMETROS_TABLE,
    PREFERENCIAS_COLUNAS_TABLE,
]

IMPORT_BACKUP_TABLES = [
    LCTE_NORMALIZED_TABLE,
]

# Os dois arquivos fixos substituem o historico de snapshots avulsos.
HISTORY_RETENTION_KEEP = 0
_backup_lock = threading.Lock()
_analysis_backup_lock = threading.Lock()
_analysis_scheduler_lock = threading.Lock()
_analysis_scheduler: threading.Thread | None = None
ANALYSIS_BACKUP_PATH = "backups/estadias_analises.csv"

SECRET_ALIASES = {
    "GITHUB_TOKEN": ["GITHUB_TOKEN", "github_token", "token"],
    "GITHUB_REPOSITORY": ["GITHUB_REPOSITORY", "github_repository", "repository", "repo"],
    "GITHUB_BACKUP_BRANCH": ["GITHUB_BACKUP_BRANCH", "github_backup_branch"],
    "GITHUB_BACKUP_PATH": ["GITHUB_BACKUP_PATH", "github_backup_path", "backup_path", "latest_path"],
    "GITHUB_IMPORTS_BACKUP_PATH": ["GITHUB_IMPORTS_BACKUP_PATH", "github_imports_backup_path", "imports_backup_path"],
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
        "branch": _read_secret("GITHUB_BACKUP_BRANCH", "backup-data"),
        "latest_path": _read_secret("GITHUB_BACKUP_PATH", "backups/estadias_latest.json"),
        "previous_path": "backups/estadias_previous.json",
        "imports_path": _read_secret("GITHUB_IMPORTS_BACKUP_PATH", "backups/estadias_importacoes_latest.json"),
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
    request = Request(url, method="GET")
    request.add_header("Accept", "application/vnd.github.raw+json")
    request.add_header("Authorization", f"Bearer {settings['token']}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urlopen(request, timeout=120) as response:
        raw = response.read()
    if raw.startswith(b"{"):
        try:
            wrapper = json.loads(raw)
            if isinstance(wrapper, dict) and wrapper.get("encoding") == "base64":
                return base64.b64decode(str(wrapper.get("content") or "")).decode("utf-8")
        except (ValueError, TypeError):
            pass
    return raw.decode("utf-8")


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
    """Remove arquivos legados somente quando as duas copias completas existem."""
    settings = github_settings()
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "removidos": 0}
    if not all(_valid_complete_backup(_download_text(settings, path).encode("utf-8")) for path in (settings["latest_path"], settings["previous_path"])):
        return {"status": "SEM_DUAS_COPIAS", "removidos": 0, "erros": 0}
    return _prune_legacy_history(settings, keep)


def _prune_legacy_history(settings: dict[str, Any], keep: int = 0) -> dict[str, Any]:
    entries = _list_directory(settings, "backups/history")
    files = sorted((item for item in entries if item.get("type") == "file"), key=lambda item: str(item.get("name") or ""))
    excess = files[: max(len(files) - max(int(keep), 0), 0)]
    removed = 0
    errors = 0
    for item in excess:
        try:
            _delete_file(settings, str(item.get("path")), str(item.get("sha")), "Poda de historico de backup (retencao automatica)")
            removed += 1
        except Exception:
            errors += 1
    legacy_sha = _remote_sha(settings, settings["imports_path"])
    if legacy_sha:
        try:
            _delete_file(settings, settings["imports_path"], legacy_sha, "Remove backup separado legado")
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
                    "select 1 from information_schema.tables where table_schema = current_schema() and table_name = ?",
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
                "select column_name from information_schema.columns where table_schema = current_schema() and table_name = ? order by ordinal_position",
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


def imported_database_tables() -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for table in IMPORT_BACKUP_TABLES:
        if _table_exists(table):
            tables[table] = read_sql(f"select * from {table}")
        else:
            tables[table] = pd.DataFrame()
    return tables


def table_counts(table_names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with get_connection() as conn:
        for table in table_names:
            if not _table_exists(table):
                counts[table] = 0
                continue
            try:
                row = conn.execute(f"select count(*) from {table}").fetchone()
                counts[table] = int(row[0] or 0) if row else 0
            except Exception:
                counts[table] = 0
    return counts


def imported_database_counts() -> dict[str, int]:
    return table_counts(IMPORT_BACKUP_TABLES)


def _tables_payload(tables: dict[str, pd.DataFrame]) -> dict[str, list[dict[str, Any]]]:
    return {
        table: json.loads(df.where(pd.notna(df), None).to_json(orient="records", force_ascii=False))
        for table, df in tables.items()
    }


def backup_payload() -> dict[str, Any]:
    tables = all_database_tables()
    rows = _tables_payload(tables)
    return {
        "schema": "estadias_backup_v1",
        "generated_at": brasilia_now_iso(),
        "records": {table: len(values) for table, values in rows.items()},
        "tables": rows,
        "performance_envios": json.loads(read_sql(
            f"select lcte_id, analise_enviada_em from {ANALYSIS_TABLE}"
        ).to_json(orient="records", force_ascii=False, date_format="iso")) if _table_exists(ANALYSIS_TABLE) else [],
    }


def import_backup_payload() -> dict[str, Any]:
    tables = imported_database_tables()
    rows = _tables_payload(tables)
    return {
        "schema": "estadias_importacoes_backup_v1",
        "generated_at": brasilia_now_iso(),
        "records": {table: len(values) for table, values in rows.items()},
        "tables": rows,
        "observacao": "Base normalizada LCTE para permitir recalculo posterior.",
    }


def backup_json_bytes() -> bytes:
    return json.dumps(backup_payload(), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def backup_analysis_marks_to_github() -> dict[str, Any]:
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "message": "Backup GitHub nao configurado."}
    with _analysis_backup_lock:
        try:
            rows = read_sql(
                f"select nf, analise_enviada_em, analise_respondida_em, sem_tratativa_origem, sem_tratativa_destino, "
                "conferencia_origem, motivo_conferencia_origem, conferencia_destino, motivo_conferencia_destino "
                f"from {ANALYSIS_TABLE} order by nf, analise_enviada_em"
            )
            if rows.empty:
                return {"status": "IGNORADO_BASE_VAZIA", "message": "Nenhuma marcacao encontrada; backup anterior preservado."}
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Nota fiscal", "Enviada em", "Respondida em", "Sem tratativa origem", "Sem tratativa destino", "Conferencia origem", "Motivo origem", "Conferencia destino", "Motivo destino"])
            writer.writerows(rows.fillna("").itertuples(index=False, name=None))
            _upload_bytes(
                github_settings(),
                ANALYSIS_BACKUP_PATH,
                output.getvalue().encode("utf-8-sig"),
                "Backup das marcacoes de analise Estadias",
            )
            return {"status": "SUCESSO", "message": f"{len(rows)} marcacao(oes) salvas no GitHub."}
        except HTTPError as exc:
            return {"status": "ERRO", "message": _github_http_error_message(exc)}
        except Exception as exc:
            return {"status": "ERRO", "message": str(exc)}


def restore_analysis_marks_from_github(usuario: str = "", dry_run: bool = True) -> dict[str, Any]:
    if not github_backup_configured():
        raise ValueError("Backup GitHub nao configurado.")
    try:
        content = _download_text(github_settings(), ANALYSIS_BACKUP_PATH)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError("O backup das marcacoes ainda nao existe no GitHub; ele sera criado apos as 19h.") from exc
        raise
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    legacy_fields = ["Nota fiscal", "Enviada em", "Respondida em"]
    expected = [*legacy_fields, "Sem tratativa origem", "Sem tratativa destino"]
    complete = [*expected, "Conferencia origem", "Motivo origem", "Conferencia destino", "Motivo destino"]
    if reader.fieldnames not in (legacy_fields, expected, complete):
        raise ValueError("O backup das marcacoes tem colunas invalidas.")

    backed_up: dict[str, tuple[str, str, int, int, str, str, str, str]] = {}
    conflicting: set[str] = set()
    invalid = 0
    for row in reader:
        nf = str(row["Nota fiscal"] or "").strip()
        sent_at = str(row["Enviada em"] or "").strip()
        replied_at = str(row["Respondida em"] or "").strip()
        origin = str(row.get("Sem tratativa origem") or "0").strip()
        destination = str(row.get("Sem tratativa destino") or "0").strip()
        origin_verdict = str(row.get("Conferencia origem") or "").strip().upper()
        destination_verdict = str(row.get("Conferencia destino") or "").strip().upper()
        origin_reason = str(row.get("Motivo origem") or "").strip()
        destination_reason = str(row.get("Motivo destino") or "").strip()
        try:
            if not nf or (replied_at and not sent_at) or origin not in {"0", "1"} or destination not in {"0", "1"} or origin_verdict not in {"", "A CONFERIR", "VALIDA", "INVALIDA"} or destination_verdict not in {"", "A CONFERIR", "VALIDA", "INVALIDA"}:
                raise ValueError
            if sent_at:
                datetime.fromisoformat(sent_at)
            if replied_at:
                datetime.fromisoformat(replied_at)
        except ValueError:
            invalid += 1
            continue
        dates = (sent_at, replied_at, int(origin), int(destination), origin_verdict, origin_reason, destination_verdict, destination_reason)
        if nf in backed_up and backed_up[nf] != dates:
            conflicting.add(nf)
        backed_up[nf] = dates

    current = read_sql(f"""select c.lcte_id, c.nf, a.analise_enviada_em, a.analise_respondida_em,
        a.sem_tratativa_origem, a.sem_tratativa_destino,
        a.conferencia_origem, a.motivo_conferencia_origem, a.conferencia_destino, a.motivo_conferencia_destino
        from {CROSS_TABLE} c left join {ANALYSIS_TABLE} a on a.lcte_id = c.lcte_id""")
    by_nf: dict[str, list[tuple[int, str, str, int, int, str, str, str, str]]] = {}
    for row in current.itertuples(index=False):
        nf = str(row.nf).strip() if pd.notna(row.nf) else ""
        if nf:
            sent = str(row.analise_enviada_em) if pd.notna(row.analise_enviada_em) else ""
            replied = str(row.analise_respondida_em) if pd.notna(row.analise_respondida_em) else ""
            origin = int(getattr(row, "sem_tratativa_origem", 0) or 0) if pd.notna(getattr(row, "sem_tratativa_origem", 0)) else 0
            destination = int(getattr(row, "sem_tratativa_destino", 0) or 0) if pd.notna(getattr(row, "sem_tratativa_destino", 0)) else 0
            manual = tuple(str(getattr(row, col, "") or "") if pd.notna(getattr(row, col, "")) else ""
                           for col in ("conferencia_origem", "motivo_conferencia_origem", "conferencia_destino", "motivo_conferencia_destino"))
            by_nf.setdefault(nf, []).append((int(row.lcte_id), sent, replied, origin, destination, *manual))

    updates: list[tuple[int, str, str]] = []
    flag_updates: list[tuple[int, str]] = []
    review_updates: list[tuple[int, str, str, str]] = []
    missing = ambiguous = already_present = 0
    for nf, (sent_at, replied_at, origin, destination, origin_verdict, origin_reason, destination_verdict, destination_reason) in backed_up.items():
        if nf in conflicting:
            continue
        existing = by_nf.get(nf, [])
        if not existing:
            missing += 1
        elif len({item[0] for item in existing}) != 1:
            ambiguous += 1
        else:
            lcte_id = existing[0][0]
            if sent_at and any(not item[1] or (replied_at and not item[2]) for item in existing):
                updates.append((lcte_id, sent_at, replied_at))
            if origin and not existing[0][3]:
                flag_updates.append((lcte_id, "ORIGEM"))
            if destination and not existing[0][4]:
                flag_updates.append((lcte_id, "DESTINO"))
            for tipo, verdict, reason, old_verdict, old_reason in (("ORIGEM", origin_verdict, origin_reason, existing[0][5], existing[0][6]), ("DESTINO", destination_verdict, destination_reason, existing[0][7], existing[0][8])):
                if (verdict or reason) and not old_verdict and not old_reason:
                    review_updates.append((lcte_id, tipo, verdict, reason))
            if not any(item[0] == lcte_id for item in updates) and not any(item[0] == lcte_id for item in flag_updates) and not any(item[0] == lcte_id for item in review_updates):
                already_present += 1

    if not dry_run:
        restore_analysis_dates(updates, usuario)
        for lcte_id, tipo in flag_updates:
            save_no_treatment_flag(lcte_id, tipo, True, usuario)
        save_manual_conferences(review_updates, usuario)
    ready_ids = {lcte_id for lcte_id, *_ in updates} | {lcte_id for lcte_id, _ in flag_updates} | {lcte_id for lcte_id, *_ in review_updates}
    restored = len(ready_ids) if not dry_run else 0
    return {
        "backup": len(backed_up), "ready": len(ready_ids), "restored": restored,
        "missing": missing, "ambiguous": ambiguous + len(conflicting),
        "invalid": invalid, "already_present": already_present,
    }


def _seconds_until_analysis_backup(now: datetime, last_run: date | None) -> float:
    today_at_19 = now.replace(hour=19, minute=0, second=0, microsecond=0)
    if now >= today_at_19 and last_run != now.date():
        return 0.0
    target = today_at_19 if now < today_at_19 else today_at_19 + timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


def start_analysis_backup_scheduler() -> None:
    global _analysis_scheduler
    with _analysis_scheduler_lock:
        if _analysis_scheduler and _analysis_scheduler.is_alive():
            return

        def run() -> None:
            last_run: date | None = None
            while True:
                time.sleep(_seconds_until_analysis_backup(brasilia_now(), last_run))
                last_run = brasilia_now().date()
                backup_analysis_marks_to_github()

        _analysis_scheduler = threading.Thread(target=run, daemon=True, name="estadias-analises-backup-19h")
        _analysis_scheduler.start()


def import_backup_json_bytes() -> bytes:
    return json.dumps(import_backup_payload(), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _complete_backup_bytes() -> bytes:
    results = backup_payload()
    imports = import_backup_payload()
    payload = {
        "schema": "estadias_completo_v1",
        "generated_at": brasilia_now_iso(),
        "results": results,
        "imports": imports,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def _valid_complete_backup(content: bytes) -> bool:
    try:
        payload = json.loads(content)
        if payload.get("schema") != "estadias_completo_v1":
            return False
        for key, schema, expected_tables in (
            ("results", "estadias_backup_v1", BACKUP_TABLES),
            ("imports", "estadias_importacoes_backup_v1", IMPORT_BACKUP_TABLES),
        ):
            part = payload.get(key) or {}
            tables = part.get("tables") or {}
            required = [table for table in expected_tables if key != "results" or table != ANALYSIS_TABLE]
            if part.get("schema") != schema or not all(isinstance(tables.get(table), list) for table in required):
                return False
            if any(int(part.get("records", {}).get(table, -1)) != len(tables[table]) for table in required):
                return False
            if ANALYSIS_TABLE in tables and key == "results" and (
                not isinstance(tables[ANALYSIS_TABLE], list)
                or int(part.get("records", {}).get(ANALYSIS_TABLE, -1)) != len(tables[ANALYSIS_TABLE])
            ):
                return False
        return any(count > 0 for key in ("results", "imports") for count in payload[key]["records"].values())
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def _without_position_backup(content: bytes) -> bytes:
    """Keep older results while dropping GPS positions from rotating copies."""
    payload = json.loads(content)
    results = payload.get("results") or {}
    (results.get("tables") or {}).pop(ESTADIA_POSITIONS_TABLE, None)
    (results.get("records") or {}).pop(ESTADIA_POSITIONS_TABLE, None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def _restore_complete_backup(content: bytes, mode: str) -> dict[str, Any]:
    if not _valid_complete_backup(content):
        raise ValueError("Backup completo invalido ou incompleto.")
    payload = json.loads(content)
    results = restore_payload(payload["results"], mode)
    imports = restore_payload(payload["imports"], mode)
    return {
        "status": "SUCESSO" if not (results["errors"] or imports["errors"]) else "PARCIAL",
        "schema": payload["schema"],
        "generated_at": payload.get("generated_at"),
        "restored": results["restored"] + imports["restored"],
        "ignored": results["ignored"] + imports["ignored"],
        "errors": results["errors"] + imports["errors"],
        "per_table": {**results["per_table"], **imports["per_table"]},
    }


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


def imported_database_has_data() -> bool:
    for table in IMPORT_BACKUP_TABLES:
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
                marker = "atualizado_em" if table == ANALYSIS_TABLE else "id"
                row = conn.execute(f"select count(*) as total, max({marker}) as max_id from {table}").fetchone()
                total = row[0] if row else 0
                max_id = row[1] if row and len(row) > 1 else 0
                pieces.append(f"{table}:{total or 0}:{max_id or 0}")
            except Exception:
                pieces.append(f"{table}:erro:0")
    return "|".join(pieces)


def restore_payload(payload: dict[str, Any], mode: str = "merge") -> dict[str, Any]:
    schema = str(payload.get("schema") or "")
    if schema == "estadias_backup_v1":
        target_tables = BACKUP_TABLES
    elif schema == "estadias_importacoes_backup_v1":
        target_tables = IMPORT_BACKUP_TABLES
    else:
        raise ValueError("Arquivo JSON nao e um backup Estadias valido.")
    tables = payload.get("tables") or {}
    restored = ignored = errors = 0
    per_table: dict[str, dict[str, int]] = {}
    replace = mode == "replace"
    with get_connection() as conn:
        for table in target_tables:
            if table == ANALYSIS_TABLE and table not in tables:
                continue
            rows = tables.get(table) or []
            table_restored = table_ignored = table_errors = 0
            if replace and _table_exists(table):
                if getattr(conn, "db_type", "sqlite") == "postgres":
                    conn.execute(f"truncate table {table} restart identity")
                else:
                    conn.execute(f"delete from {table}")
            if not rows:
                per_table[table] = {"arquivo": 0, "restaurados": 0, "ignorados": 0, "erros": 0}
                continue
            if not _table_exists(table):
                ignored += len(rows)
                per_table[table] = {"arquivo": len(rows), "restaurados": 0, "ignorados": len(rows), "erros": 0}
                continue
            columns = _table_columns(table)
            insert_columns = [column for column in columns if column in rows[0]]
            if not insert_columns:
                ignored += len(rows)
                per_table[table] = {"arquivo": len(rows), "restaurados": 0, "ignorados": len(rows), "erros": 0}
                continue
            placeholders = ", ".join("?" for _ in insert_columns)
            sql = f"insert into {table} ({', '.join(insert_columns)}) values ({placeholders})"
            for row_number, row in enumerate(rows, start=1):
                try:
                    conn.execute(sql, tuple(row.get(column) for column in insert_columns))
                    restored += 1
                    table_restored += 1
                except Exception as exc:
                    if getattr(conn, "db_type", "sqlite") == "postgres":
                        raise ValueError(f"Falha ao restaurar {table} na linha {row_number}; nenhuma alteracao foi aplicada.") from exc
                    errors += 1
                    ignored += 1
                    table_errors += 1
                    table_ignored += 1
            if getattr(conn, "db_type", "sqlite") == "postgres" and "id" in insert_columns:
                conn.execute(
                    f"select setval(pg_get_serial_sequence(?, 'id'), coalesce(max(id), 1), count(*) > 0) from {table}",
                    (table,),
                )
            per_table[table] = {"arquivo": len(rows), "restaurados": table_restored, "ignorados": table_ignored, "erros": table_errors}
    try:
        import streamlit as st

        st.cache_data.clear()
    except Exception:
        pass
    return {
        "status": "SUCESSO" if errors == 0 else "PARCIAL",
        "schema": schema,
        "restored": restored,
        "ignored": ignored,
        "errors": errors,
        "per_table": per_table,
    }


def restore_json_bytes(content: bytes, mode: str = "merge") -> dict[str, Any]:
    payload = json.loads(content.decode("utf-8-sig"))
    if payload.get("schema") == "estadias_completo_v1":
        return _restore_complete_backup(content, mode)
    return restore_payload(payload, mode)


def backup_to_github(reason: str = "manual") -> dict[str, Any]:
    if get_database_config().db_type == "postgres":
        return {"status": "DESATIVADO", "message": "Backup GitHub legado desativado para PostgreSQL; politica nova pendente.", "records": 0}
    settings = github_settings()
    if _token_is_placeholder(settings["token"]):
        return {"status": "TOKEN_INVALIDO", "message": "GITHUB_TOKEN incompleto ou com reticencias.", "records": 0}
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "message": "Configure GITHUB_TOKEN para habilitar backup no GitHub.", "records": 0}
    if not _backup_lock.acquire(blocking=False):
        return {"status": "EM_ANDAMENTO", "message": "Outro backup GitHub esta em andamento.", "records": 0}
    try:
        content = _complete_backup_bytes()
        if not _valid_complete_backup(content):
            return {"status": "IGNORADO_BASE_VAZIA", "message": "Backup completo vazio ou incompleto; copias preservadas.", "records": 0}
        payload = json.loads(content)
        records = sum(sum(part["records"].values()) for part in (payload["results"], payload["imports"]))
        previous = None
        try:
            previous = _download_text(settings, settings["latest_path"]).encode("utf-8")
        except HTTPError as exc:
            if exc.code != 404:
                raise
        if previous and _valid_complete_backup(previous):
            if hashlib.sha256(previous).digest() == hashlib.sha256(content).digest():
                try:
                    older = _download_text(settings, settings["previous_path"]).encode("utf-8")
                except HTTPError as exc:
                    if exc.code != 404:
                        raise
                    older = b""
                if not _valid_complete_backup(older):
                    _upload_bytes(settings, settings["previous_path"], content, f"Backup Estadias anterior inicial ({reason})")
                cleanup = _prune_legacy_history(settings)
                return {"status": "SEM_ALTERACAO", "message": "Duas copias completas confirmadas; backup atual ja corresponde ao banco.", "records": records, "cleanup": cleanup}
            _upload_bytes(settings, settings["previous_path"], _without_position_backup(previous), f"Backup Estadias anterior ({reason})")
        elif previous:
            try:
                old_schema = json.loads(previous).get("schema")
            except (ValueError, TypeError, AttributeError):
                old_schema = ""
            if old_schema != "estadias_backup_v1":
                return {"status": "ERRO", "message": "Backup atual invalido; copias preservadas para analise.", "records": 0}
            try:
                older = _download_text(settings, settings["previous_path"]).encode("utf-8")
            except HTTPError as exc:
                if exc.code != 404:
                    raise
                older = b""
            if not _valid_complete_backup(older):
                _upload_bytes(settings, settings["previous_path"], content, f"Backup Estadias anterior inicial ({reason})")
        else:
            _upload_bytes(settings, settings["previous_path"], content, f"Backup Estadias anterior inicial ({reason})")
        _upload_bytes(settings, settings["latest_path"], content, f"Backup Estadias atual ({reason})")
        try:
            cleanup = _prune_legacy_history(settings)
        except Exception:
            cleanup = {"status": "PARCIAL"}
        message = "Backups atual e anterior gravados no GitHub."
        if cleanup.get("status") != "SUCESSO":
            message += " Limpeza dos arquivos antigos pendente."
        return {"status": "SUCESSO", "message": message, "records": records}
    except HTTPError as exc:
        return {"status": "ERRO", "message": _github_http_error_message(exc), "records": 0}
    except (URLError, TimeoutError) as exc:
        return {"status": "ERRO", "message": str(exc), "records": 0}
    finally:
        _backup_lock.release()


def restore_from_github_if_empty() -> dict[str, Any]:
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "message": "GitHub backup nao configurado.", "records": 0}
    if database_has_data() and imported_database_has_data():
        return {"status": "IGNORADO_BASE_COM_DADOS", "message": "Base local ja possui dados.", "records": 0}
    settings = github_settings()
    restored = 0
    restored_parts: list[str] = []
    try:
        for path, label in ((settings["latest_path"], "atual"), (settings["previous_path"], "anterior")):
            try:
                complete = _download_text(settings, path).encode("utf-8")
            except HTTPError as exc:
                if exc.code == 404:
                    continue
                raise
            if not _valid_complete_backup(complete):
                continue
            payload = json.loads(complete)
            parts = []
            if not database_has_data():
                parts.append(("results", "resultados"))
            if not imported_database_has_data():
                parts.append(("imports", "importacoes"))
            for key, part_label in parts:
                result = restore_payload(payload[key], "replace")
                restored += int(result["restored"])
                restored_parts.append(part_label)
                if result["status"] != "SUCESSO":
                    return {"status": "ERRO", "message": f"Restauracao de {part_label} foi parcial. Verifique o banco.", "records": restored}
            return {"status": "RESTAURADO", "message": f"Backup completo {label} restaurado: {', '.join(restored_parts)}.", "records": restored}
        # Compatibilidade com os arquivos separados gravados antes da rotacao.
        if not database_has_data():
            raw = _download_text(settings, settings["latest_path"])
            payload = json.loads(raw)
            total = sum(len(rows or []) for rows in (payload.get("tables") or {}).values())
            if total > 0:
                result = restore_payload(payload, "replace")
                restored += int(result.get("restored") or 0)
                restored_parts.append("resultados")
        if not imported_database_has_data():
            try:
                import_raw = _download_text(settings, settings["imports_path"])
                import_payload = json.loads(import_raw)
                import_total = sum(len(rows or []) for rows in (import_payload.get("tables") or {}).values())
                if import_total > 0:
                    import_result = restore_payload(import_payload, "replace")
                    restored += int(import_result.get("restored") or 0)
                    restored_parts.append("importacoes")
            except HTTPError as exc:
                if exc.code != 404:
                    raise
    except HTTPError as exc:
        if exc.code == 404:
            return {"status": "NAO_ENCONTRADO", "message": "Nenhum backup latest encontrado no GitHub.", "records": 0}
        return {"status": "ERRO", "message": _github_http_error_message(exc), "records": 0}
    except Exception as exc:
        return {"status": "ERRO", "message": str(exc), "records": 0}
    if restored <= 0:
        return {"status": "IGNORADO_BACKUP_VAZIO", "message": "Backup GitHub vazio.", "records": 0}
    return {"status": "RESTAURADO", "message": f"Backup GitHub restaurado: {', '.join(restored_parts)}.", "records": restored}


def github_backup_versions() -> list[dict[str, Any]]:
    if not github_backup_configured():
        return []
    settings = github_settings()
    versions = []
    for label, path in (("Atual", settings["latest_path"]), ("Anterior", settings["previous_path"])):
        try:
            content = _download_text(settings, path).encode("utf-8")
            if not _valid_complete_backup(content):
                continue
            payload = json.loads(content)
            versions.append({"label": label, "path": path, "generated_at": payload.get("generated_at", ""), "bytes": len(content)})
        except HTTPError as exc:
            if exc.code != 404:
                raise
    return versions


def restore_github_version(label: str) -> dict[str, Any]:
    if not github_backup_configured():
        raise ValueError("GitHub backup nao configurado.")
    settings = github_settings()
    paths = {"Atual": settings["latest_path"], "Anterior": settings["previous_path"]}
    if label not in paths:
        raise ValueError("Versao de backup invalida.")
    return _restore_complete_backup(_download_text(settings, paths[label]).encode("utf-8"), "replace")


def github_diagnostic() -> dict[str, Any]:
    settings = github_settings()
    token = settings["token"]
    return {
        "repository": settings["repository"],
        "branch": settings["branch"],
        "latest_path": settings["latest_path"],
        "previous_path": settings["previous_path"],
        "imports_path": settings["imports_path"],
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
