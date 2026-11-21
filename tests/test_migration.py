import hashlib
import sqlite3
import tempfile
import unittest
from collections import Counter
from contextlib import closing
from io import BytesIO
from pathlib import Path

from PIL import Image

import app
import catalog_numbers
import pricing
from tests.helpers import tiny_jpeg

DEFAULTS = [{"id": "SS", "label": "半袖", "unit_price": 2000},
            {"id": "LS", "label": "長袖", "unit_price": 2900}]


def colored_jpeg(color):
    buffer = BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, "JPEG")
    return buffer.getvalue()


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def legacy_ledger(self):
        """価格区分を持たない5列の旧台帳（user_version=2・確定注文あり）を作る。"""
        folder = self.tmp / "legacy"
        folder.mkdir()
        photos = {color: colored_jpeg(color) for color in ("red", "green", "blue")}
        digests = {color: hashlib.sha256(jpeg).hexdigest() for color, jpeg in photos.items()}
        with closing(sqlite3.connect(folder / "orders.sqlite3")) as con:
            con.executescript(app.SCHEMA)
            with con:
                con.executemany("INSERT INTO photos VALUES(?,?)",
                                [(digests[color], jpeg) for color, jpeg in photos.items()])
                con.executemany("INSERT INTO products VALUES(?,?,?,?,?)", [
                    ("SS001", "SS", 1, "商品A", digests["red"]),
                    ("SS002", "SS", 2, "商品B", digests["green"]),
                    ("LS001", "LS", 1, "商品C", digests["blue"]),
                ])
                con.execute("INSERT INTO orders VALUES(1,'2026-11-20T10:00+09:00')")
                con.executemany("INSERT INTO items VALUES(?,?,?,?,?)", [
                    (1, "SS001", "商品A", digests["red"], 2),
                    (1, "LS001", "商品C", digests["blue"], 1),
                ])
                con.execute("INSERT INTO order_quote_pdfs VALUES(1,?)", (b"%PDF-legacy-quote",))
            con.execute("PRAGMA user_version=2")
        return folder

    @staticmethod
    def snapshot(store):
        with store.transaction() as con:
            return dict(
                products=[tuple(row) for row in con.execute(
                    "SELECT code,sleeve,number,name,image FROM products ORDER BY code")],
                items=[tuple(row) for row in con.execute(
                    "SELECT order_id,code,name,image,qty FROM items ORDER BY order_id,code")],
                pdfs=[tuple(row) for row in con.execute("SELECT order_id,pdf FROM order_quote_pdfs")],
                photos=sorted(digest for (digest,) in con.execute("SELECT digest FROM photos")),
                version=con.execute("PRAGMA user_version").fetchone()[0],
            )

    def test_legacy_ledger_keeps_data(self):
        folder = self.legacy_ledger()
        with closing(sqlite3.connect(folder / "orders.sqlite3")) as con:
            original_items = con.execute(
                "SELECT order_id,code,name,image,qty FROM items ORDER BY order_id,code").fetchall()
            original_products = con.execute(
                "SELECT code,sleeve,number,name,image FROM products ORDER BY code").fetchall()

        first = self.snapshot(app.Store(folder))
        store = app.Store(folder)
        self.assertEqual(self.snapshot(store), first)
        self.assertEqual(first["products"], original_products)
        self.assertEqual(first["items"], original_items)
        self.assertEqual(first["pdfs"], [(1, b"%PDF-legacy-quote")])
        self.assertEqual(first["version"], 2)

        state = store.state()
        self.assertEqual(state["price_classes"], DEFAULTS)
        for row in state["products"]:
            self.assertEqual(row["price_class"], row["code"][:2])
            self.assertIsNone(row["assigned_price_class"])
        order = store.order(1)
        self.assertEqual([(i["code"], i["qty"]) for i in order["items"]], [("SS001", 2), ("LS001", 1)])
        self.assertTrue(order["has_quote_pdf"])

    def test_edited_price_survives_restart(self):
        folder = self.legacy_ledger()
        store = app.Store(folder)
        store.update_price_class({"id": "SS", "label": "半袖", "unit_price": 2300,
                                  "revision": store.state()["revision"]})
        restarted = app.Store(folder)
        with restarted.transaction() as con:
            self.assertEqual(pricing.list_price_classes(con)[0], {"id": "SS", "label": "半袖", "unit_price": 2300})
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_seed_imports_from_source(self):
        source = self.tmp / "source"
        jpeg = tiny_jpeg()
        for sleeve, label, count in [("SS", "半袖", 193), ("LS", "長袖", 85)]:
            (source / label).mkdir(parents=True)
            for i in range(1, count + 1):
                (source / label / f"商品_{sleeve}{i:03}.jpg").write_bytes(jpeg)
        store = app.Store(self.tmp / "ledger")
        self.assertFalse(store.seed(source))
        products = store.state()["products"]
        self.assertEqual(len(products), 278)
        self.assertEqual(Counter(row["code"][:2] for row in products), {"SS": 193, "LS": 85})
        for row in products:
            self.assertEqual(row["price_class"], row["code"][:2])
            self.assertIsNone(row["assigned_price_class"])
        with store.transaction() as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_seed_renumbers_reviewed_catalog(self):
        store = app.Store(self.tmp / "ledger")
        initial = [row for row in catalog_numbers.number_map()
                   if int(row["旧品番"][2:]) <= (193 if row["旧品番"].startswith("SS") else 85)]
        self.assertEqual(len(initial), 278)
        jpeg = tiny_jpeg()
        with store.transaction(True) as con:
            for row in initial:
                code, digest = row["旧品番"], row["旧写真ID"]
                con.execute("INSERT OR IGNORE INTO photos VALUES(?,?)", (digest, jpeg))
                con.execute("INSERT INTO products (code,sleeve,number,name,image) VALUES(?,?,?,?,?)",
                            (code, code[:2], int(code[2:]), row["商品名"], digest))

        self.assertTrue(store.seed(Path("/nonexistent")))
        products = store.state()["products"]
        self.assertEqual(len(products), 249)
        self.assertEqual(Counter(row["code"][:2] for row in products), {"SS": 174, "LS": 75})
        for row in products:
            self.assertEqual(row["price_class"], row["code"][:2])
            self.assertIsNone(row["assigned_price_class"])
        with store.transaction() as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
