import sqlite3
from pathlib import Path


DB_DIR = Path("./workfolder/data")
DB_PATH = DB_DIR / "database.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_number TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    package_code TEXT,
    pallet_code TEXT,
    scanned_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scans_task_number ON scans (task_number);
CREATE INDEX IF NOT EXISTS idx_scans_package_code ON scans (package_code);
CREATE INDEX IF NOT EXISTS idx_scans_pallet_code ON scans (pallet_code);
"""


def init_db() -> Path:
    """Создаёт ./workfolder/data/database.db и таблицу scans, если их
    ещё нет. Безопасно вызывать при каждом запуске приложения —
    CREATE TABLE/INDEX IF NOT EXISTS ничего не затирает."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    """Открывает соединение с базой. Строки возвращаются как sqlite3.Row
    (доступ и по индексу, и по имени колонки)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    path = init_db()
    print(f"База данных создана: {path.resolve()}")
