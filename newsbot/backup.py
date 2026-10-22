"""Резервные копии базы: ежедневно на диск сервера, раз в неделю — файлом администратору в Telegram."""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from newsbot.config import backup_dir, db_path

KEEP_BACKUPS = 14


def backup_db(dest_dir: str | None = None, keep: int = KEEP_BACKUPS) -> Path:
    """
    Копия через SQLite backup API: корректна, даже если база в этот момент пишется.
    Хранит последние `keep` копий, старые удаляет.
    """
    dest = Path(dest_dir or backup_dir())
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"news-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(dest.glob('news-*.db'))[:-keep]:
        os.remove(old)
    return target
