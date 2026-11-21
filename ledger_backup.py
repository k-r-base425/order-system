"""台帳（SQLite）の1日1回の自動バックアップ。"""
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path

NAME = re.compile(r"orders-(\d{4}-\d{2}-\d{2})\.sqlite3")


def backup_ledger(db: Path, folder: Path, today: date, keep: int = 14) -> Path | None:
    if not db.is_file():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"orders-{today.isoformat()}.sqlite3"
    if target.exists():
        return None
    handle = tempfile.NamedTemporaryFile(dir=folder, prefix=".writing-", delete=False)
    handle.close()
    temp = Path(handle.name)
    try:
        # 読み取り専用では途中終了で残ったジャーナルを戻せないため、通常接続で開く。
        with closing(sqlite3.connect(db)) as src, \
                closing(sqlite3.connect(temp)) as dst:
            src.backup(dst)
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    dated = sorted((p for p in folder.iterdir() if NAME.fullmatch(p.name)),
                   key=lambda p: NAME.fullmatch(p.name).group(1), reverse=True)
    for old in dated[keep:]:
        old.unlink()
    return target
