import sqlite3
from contextlib import contextmanager
from pathlib import Path
from config.settings import LOCAL_DB_PATH, BASE_DIR


def init_db(db_path: Path = LOCAL_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = (BASE_DIR / "db" / "schema.sql").read_text()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)


@contextmanager
def get_conn(db_path: Path = LOCAL_DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
