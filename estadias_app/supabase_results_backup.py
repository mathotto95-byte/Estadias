from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from src.database.connection import _connect_postgres, _read_secret
from src.modules.estadias.repository import CROSS_TABLE
from src.utils.timezone import brasilia_now

from estadias_app.github_backup import _complete_backup_bytes, _valid_complete_backup, backup_payload


BACKUP_TABLE = "estadias.resultado_backups"
_scheduler_lock = threading.Lock()
_upload_lock = threading.Lock()
_scheduler: threading.Thread | None = None
_last_automatic_attempt: dict[str, str] = {}


def configured() -> bool:
    return bool(_read_secret("ESTADIAS_RESULTADOS_DATABASE_URL").strip())


def connection_summary() -> dict[str, str]:
    """Return connection coordinates without exposing the password."""
    url = _read_secret("ESTADIAS_RESULTADOS_DATABASE_URL").strip()
    if not url:
        return {"error": "URL de resultados nao configurada."}
    try:
        parsed = urlsplit(url)
        user = parsed.username or ""
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return {"error": "URL invalida. Codifique caracteres especiais da senha na URL."}
    if parsed.scheme not in {"postgresql", "postgres"} or not user or not host:
        return {"error": "URL incompleta. Confira protocolo, usuario e host."}
    result = {"user": user, "host": host, "port": str(port or 5432)}
    if host.endswith(".pooler.supabase.com") and "." not in user:
        result["error"] = "No pooler, o usuario deve incluir .IDENTIFICADOR_DO_PROJETO."
    return result


def _connect():
    url = _read_secret("ESTADIAS_RESULTADOS_DATABASE_URL").strip()
    if not url:
        raise ValueError("Configure ESTADIAS_RESULTADOS_DATABASE_URL nos Secrets do app.")
    password = _read_secret("ESTADIAS_RESULTADOS_DB_PASSWORD")
    return _connect_postgres(url, **({"password": password} if password else {}))


def status() -> dict[str, Any]:
    with _connect() as conn:
        if conn.execute("select to_regclass(?)", (BACKUP_TABLE,)).fetchone()[0] is None:
            raise ValueError("Tabela estadias.resultado_backups ausente no Supabase.")
        rows = conn.execute(
            f"select slot, gerado_em, viagens, octet_length(conteudo) from {BACKUP_TABLE} order by slot"
        ).fetchall()
    return {
        "schema": "estadias",
        "copias": [
            {"slot": row[0], "gerado_em": str(row[1]), "viagens": int(row[2]), "bytes_compactados": int(row[3])}
            for row in rows
        ],
    }


def _snapshot(payload: dict[str, Any]) -> tuple[bytes, str, int]:
    tables = payload.get("tables") or (payload.get("results") or {}).get("tables") or {}
    trips = len(tables.get(CROSS_TABLE) or [])
    if not trips:
        raise ValueError("Nao ha resultados de viagens para enviar ao Supabase.")
    stable = {key: value for key, value in payload.items() if key != "generated_at"}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return gzip.compress(content, compresslevel=6, mtime=0), digest, trips


def preview() -> dict[str, Any]:
    content, digest, trips = _snapshot(backup_payload())
    with _connect() as conn:
        rows = conn.execute(
            f"select slot, sha256, octet_length(conteudo) from {BACKUP_TABLE} where slot in ('atual', 'anterior')"
        ).fetchall()
    existing = {str(row[0]): {"sha256": str(row[1]), "bytes": int(row[2])} for row in rows}
    current = existing.get("atual")
    previous = existing.get("anterior")
    unchanged = bool(current and current["sha256"] == digest)
    stored_now = sum(item["bytes"] for item in existing.values())
    stored_after = stored_now if unchanged else len(content) + (current["bytes"] if current else 0)
    return {
        "viagens": trips,
        "bytes_compactados": len(content),
        "bytes_armazenados_apos_envio": stored_after,
        "variacao_bytes": stored_after - stored_now,
        "status": "SEM_ALTERACAO" if unchanged else "PRONTO_PARA_ENVIO",
    }


def upload() -> dict[str, Any]:
    content, digest, trips = _snapshot(backup_payload())
    with _upload_lock:
        with _connect() as conn:
            if conn.execute("select to_regclass(?)", (BACKUP_TABLE,)).fetchone()[0] is None:
                raise ValueError("Tabela estadias.resultado_backups ausente no Supabase.")
            current = conn.execute(f"select sha256 from {BACKUP_TABLE} where slot = 'atual'").fetchone()
            if current and current[0] == digest:
                return {"status": "SEM_ALTERACAO", "viagens": trips, "bytes_compactados": len(content)}
            conn.execute(
                f"insert into {BACKUP_TABLE} (slot, gerado_em, viagens, sha256, conteudo) "
                f"select 'anterior', gerado_em, viagens, sha256, conteudo from {BACKUP_TABLE} where slot = 'atual' "
                "on conflict (slot) do update set gerado_em = excluded.gerado_em, viagens = excluded.viagens, "
                "sha256 = excluded.sha256, conteudo = excluded.conteudo"
            )
            conn.execute(
                f"insert into {BACKUP_TABLE} (slot, gerado_em, viagens, sha256, conteudo) "
                "values ('atual', now(), ?, ?, ?) "
                "on conflict (slot) do update set gerado_em = excluded.gerado_em, viagens = excluded.viagens, "
                "sha256 = excluded.sha256, conteudo = excluded.conteudo",
                (trips, digest, content),
            )
    return {"status": "SUCESSO", "viagens": trips, "bytes_compactados": len(content)}


def upload_manual() -> dict[str, Any]:
    payload_bytes = _complete_backup_bytes()
    if not _valid_complete_backup(payload_bytes):
        raise ValueError("Backup completo invalido; copia manual anterior preservada.")
    content, digest, trips = _snapshot(json.loads(payload_bytes))
    with _upload_lock:
        with _connect() as conn:
            if conn.execute("select to_regclass(?)", (BACKUP_TABLE,)).fetchone()[0] is None:
                raise ValueError("Tabela estadias.resultado_backups ausente no Supabase.")
            conn.execute(
                f"insert into {BACKUP_TABLE} (slot, gerado_em, viagens, sha256, conteudo) "
                "values ('manual', now(), ?, ?, ?) "
                "on conflict (slot) do update set gerado_em = excluded.gerado_em, viagens = excluded.viagens, "
                "sha256 = excluded.sha256, conteudo = excluded.conteudo",
                (trips, digest, content),
            )
    return {"status": "SUCESSO", "viagens": trips, "bytes_compactados": len(content)}


def _seconds_until_daily_backup(now: datetime, last_success: date | None) -> float:
    today_at_20 = now.replace(hour=20, minute=0, second=0, microsecond=0)
    if now >= today_at_20 and last_success != now.date():
        return 0.0
    target = today_at_20 if now < today_at_20 else today_at_20 + timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


def automatic_status() -> dict[str, str]:
    return _last_automatic_attempt.copy()


def start_daily_backup_scheduler() -> None:
    global _scheduler
    if not configured():
        return
    with _scheduler_lock:
        if _scheduler and _scheduler.is_alive():
            return

        def run() -> None:
            last_success: date | None = None
            while True:
                time.sleep(_seconds_until_daily_backup(brasilia_now(), last_success))
                attempted_at = brasilia_now()
                try:
                    result = upload()
                    _last_automatic_attempt.update(
                        data=attempted_at.strftime("%d/%m/%Y %H:%M"),
                        status=result["status"],
                        viagens=str(result["viagens"]),
                    )
                    last_success = attempted_at.date()
                except Exception:
                    _last_automatic_attempt.update(
                        data=attempted_at.strftime("%d/%m/%Y %H:%M"),
                        status="ERRO",
                        viagens="",
                    )
                    time.sleep(15 * 60)

        _scheduler = threading.Thread(target=run, daemon=True, name="estadias-supabase-backup-20h")
        _scheduler.start()


def download(slot: str = "atual") -> bytes:
    if slot not in {"atual", "anterior", "manual"}:
        raise ValueError("Copia invalida.")
    with _connect() as conn:
        row = conn.execute(f"select sha256, conteudo from {BACKUP_TABLE} where slot = ?", (slot,)).fetchone()
    if not row:
        raise ValueError("Copia nao encontrada no Supabase.")
    content = gzip.decompress(bytes(row[1]))
    payload = json.loads(content)
    stable = {key: value for key, value in payload.items() if key != "generated_at"}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    if digest != row[0]:
        raise ValueError("Falha de integridade na copia do Supabase.")
    return content
