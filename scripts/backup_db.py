"""make backup: согласованная копия базы через sqlite3.Connection.backup.

Каталог копий — `backup/` рядом с файлом базы (для `CQA_DB_PATH=data/cqa.db`
это `data/backup/cqa-<HHMM>.db` из design/ports.md). Диалоги попадают в базу
через HTTP (POST /api/datasets/upload), апелляция — через Store: маршрут
/api/appeals пишет другая группа, здесь важна сама копия.
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    db_path = Path(os.environ.get("CQA_DB_PATH", "data/cqa.db"))
    if not db_path.exists():
        print(f"ошибка: база {db_path} не найдена", file=sys.stderr)
        return 2

    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"cqa-{datetime.now():%H%M}.db"

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)  # согласованный снимок, работает при живом сервере (WAL)
    finally:
        src.close()
        dst.close()

    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
