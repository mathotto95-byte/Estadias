from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any

from src.database.connection import _connect_postgres, _read_secret
from src.modules.estadias.repository import CROSS_TABLE

from estadias_app.github_backup import backup_payload


BACKUP_TABLE = "estadias.resultado_backups"


def configured() -> bool:
    return bool(_read_secret("ESTADIAS_RESULTADOS_DATABASE_URL").strip())


def _connect():
    url = _read_secret("ESTADIAS_RESULTADOS_DATABASE_URL").strip()
    if not url:
        raise ValueError("Configure ESTADIAS_RESULTADOS_DATABASE_URL nos Secrets do app.")
    return _connect_postgres(url)


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
    trips = len((payload.get("tables") or {}).get(CROSS_TABLE) or [])
    if not trips:
        raise ValueError("Nao ha resultados de viagens para enviar ao Supabase.")
    stable = {key: value for key, value in payload.items() if key != "generated_at"}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return gzip.compress(content, mtime=0), digest, trips


def upload() -> dict[str, Any]:
    content, digest, trips = _snapshot(backup_payload())
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


def download(slot: str = "atual") -> bytes:
    if slot not in {"atual", "anterior"}:
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
