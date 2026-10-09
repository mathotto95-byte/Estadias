"""Initialize an empty, isolated Estadias schema with an admin-only connection.

Set ESTADIAS_ADMIN_DATABASE_URL in the process environment. Never commit it.
This command does not copy or delete operational records.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.connection import _connect_postgres
from src.database.migrations import create_modular_tables


def main():
    url = os.getenv("ESTADIAS_ADMIN_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Defina ESTADIAS_ADMIN_DATABASE_URL no ambiente; nao passe a URL como argumento.")
    with _connect_postgres(url) as conn:
        conn.execute("create schema if not exists estadias")
        if conn.execute("select current_schema()").fetchone()[0] != "estadias":
            raise RuntimeError("Nao foi possivel selecionar o schema estadias.")
        create_modular_tables(conn)
    print("Estrutura do schema estadias criada/validada. Nenhum dado operacional foi importado.")


if __name__ == "__main__":
    main()
