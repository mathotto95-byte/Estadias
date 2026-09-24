from __future__ import annotations

def database_type(conn) -> str:
    return getattr(conn, "db_type", "sqlite")


def adapt_sql(conn, sql: str) -> str:
    if database_type(conn) != "postgres":
        return sql
    return (
        sql.replace("integer primary key autoincrement", "serial primary key")
        .replace("original_json text not null", "original_json jsonb not null")
        .replace("normalized_json text not null", "normalized_json jsonb not null")
    )


def ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    if database_type(conn) == "postgres":
        existing = {
            row["column_name"]
            for row in conn.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public' and table_name = ?
                """,
                (table,),
            ).fetchall()
        }
    else:
        existing = {
            row["name"]
            for row in conn.execute(f"pragma table_info({table})").fetchall()
        }
    for name, definition in columns.items():
        if name not in existing:
            try:
                conn.execute(adapt_sql(conn, f"alter table {table} add column {name} {definition}"))
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate column" not in message and "already exists" not in message:
                    raise
