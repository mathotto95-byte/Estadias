from __future__ import annotations

from pathlib import Path


APP_NAME = "Estadias"
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DATABASE_DIR = DATA_DIR / "database"
BACKUPS_DIR = DATA_DIR / "backups"
EXPORTS_DIR = DATA_DIR / "exports"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATABASE_DIR / "estadias.sqlite3"


def ensure_directories() -> None:
    for directory in [DATA_DIR, DATABASE_DIR, BACKUPS_DIR, EXPORTS_DIR, UPLOADS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
