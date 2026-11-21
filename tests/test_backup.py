import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import app
import ledger_backup
from ledger_backup import backup_ledger
from tests.helpers import tiny_jpeg


def count(path, table):
    with closing(sqlite3.connect(path)) as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class BackupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "orders.sqlite3"
        self.folder = self.tmp / "backup"

    def make_db(self):
        import hashlib
        jpeg = tiny_jpeg()
        digest = hashlib.sha256(jpeg).hexdigest()
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript(app.SCHEMA)
            with con:
                con.execute("INSERT INTO photos VALUES(?,?)", (digest, jpeg))
                con.executemany("INSERT INTO products VALUES(?,?,?,?,?)", [
                    ("SS001", "SS", 1, "商品A", digest),
                    ("LS001", "LS", 1, "商品B", digest),
                ])
                con.execute("INSERT INTO orders VALUES(1,'2026-11-20T10:00+09:00')")
                con.executemany("INSERT INTO items VALUES(?,?,?,?,?)", [
                    (1, "SS001", "商品A", digest, 2),
                    (1, "LS001", "商品B", digest, 1),
                ])

    def test_creates_daily_copy(self):
        self.make_db()
        result = backup_ledger(self.db, self.folder, date(2026, 11, 21))
        self.assertEqual(result, self.folder / "orders-2026-11-21.sqlite3")
        self.assertTrue(result.is_file())
        self.assertEqual(count(result, "products"), count(self.db, "products"))
        self.assertEqual(count(result, "items"), 2)
        with closing(sqlite3.connect(result)) as con:
            cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
        self.assertNotIn("price_class", cols)

    def test_once_per_day(self):
        self.make_db()
        self.assertIsNotNone(backup_ledger(self.db, self.folder, date(2026, 11, 21)))
        self.assertIsNone(backup_ledger(self.db, self.folder, date(2026, 11, 21)))

    def test_keeps_latest(self):
        self.make_db()
        start = date(2026, 11, 1)
        for i in range(15):
            backup_ledger(self.db, self.folder, start + timedelta(days=i))
        (self.folder / "memo.txt").write_text("keep")
        backup_ledger(self.db, self.folder, start + timedelta(days=14))
        names = sorted(p.name for p in self.folder.glob("orders-*.sqlite3"))
        self.assertEqual(len(names), 14)
        self.assertNotIn("orders-2026-11-01.sqlite3", names)
        self.assertIn("orders-2026-11-15.sqlite3", names)
        self.assertTrue((self.folder / "memo.txt").exists())

    def test_missing_db(self):
        self.assertIsNone(backup_ledger(self.db, self.folder, date(2026, 11, 21)))
        self.assertFalse(self.folder.exists())

    def test_failure_leaves_no_file(self):
        self.make_db()
        real_connect = sqlite3.connect

        class Failing:
            def __init__(self, *args, **kwargs):
                self.con = real_connect(*args, **kwargs)

            def backup(self, target):
                raise sqlite3.OperationalError("boom")

            def close(self):
                self.con.close()

        # sqlite3.Connection は不変型のため属性を差し替えられない。connect を包んで backup だけ失敗させる。
        with mock.patch.object(ledger_backup.sqlite3, "connect", Failing):
            with self.assertRaises(sqlite3.OperationalError):
                backup_ledger(self.db, self.folder, date(2026, 11, 21))
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertIsNotNone(backup_ledger(self.db, self.folder, date(2026, 11, 21)))


if __name__ == "__main__":
    unittest.main()
