from __future__ import annotations

from pathlib import Path


APP_NAME = "Estadias"
ROOT_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT_DIR / "assets"
DATA_DIR = ROOT_DIR / "data"
DATABASE_DIR = DATA_DIR / "database"
DB_PATH = DATABASE_DIR / "estadias.sqlite3"


def ensure_directories() -> None:
    for directory in [DATA_DIR, DATABASE_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
