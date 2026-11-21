import html
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_store

TEMPLATE = Path(__file__).resolve().parent.parent / "web" / "catalog.html"


class ExportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "out"

    def store_with_class(self):
        store = make_store(self.tmp / "ledger", ["SS008", "LS075"])
        revision = store.update_price_class({"label": "レア", "unit_price": 4500,
                                             "revision": store.state()["revision"]})["revision"]
        store.set_product_price_class({"code": "SS008", "price_class": "PC01", "revision": revision})
        return store

    def page(self):
        return (self.out / "index.html").read_text(encoding="utf-8")

    def test_cards_have_price_class(self):
        self.store_with_class().export(self.out)
        page = self.page()
        self.assertRegex(page, r'data-code="SS008"[^>]*data-price-class="PC01"|data-price-class="PC01"[^>]*data-code="SS008"')
        self.assertRegex(page, r'data-code="LS075"[^>]*data-price-class="LS"|data-price-class="LS"[^>]*data-code="LS075"')

    def test_price_json_embedded(self):
        self.store_with_class().export(self.out)
        page = self.page()
        match = re.search(r'<script type="application/json" id="price-classes">(.*?)</script>', page, re.S)
        self.assertEqual(json.loads(match.group(1)), {"SS": 2000, "LS": 2900, "PC01": 4500})
        self.assertNotIn("レア", page)

    def test_placeholders_not_reexpanded(self):
        name = "%%COUNT%%</script>%%PRICE_CLASSES%%%%PREVIOUS_CODES%%%%CARDS%%"
        store = make_store(self.tmp / "ledger", ["SS008", "LS075"])
        with store.transaction(True) as con:
            con.execute("UPDATE products SET name=? WHERE code='SS008'", (name,))
        store.export(self.out)
        page = self.page()
        self.assertIn(html.escape(name, quote=True), page)
        self.assertIn("<b>2</b> 商品", page)
        self.assertIn("2 件を表示", page)
        match = re.search(r'<script type="application/json" id="price-classes">(.*?)</script>', page, re.S)
        self.assertEqual(json.loads(match.group(1)), {"SS": 2000, "LS": 2900})
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(page.count("<script"), template.count("<script"))

    def test_embedded_json_escapes_lt(self):
        from catalog_output import _embedded_json
        value = {"a": "</script><!--"}
        text = _embedded_json(value)
        self.assertNotIn("<", text)
        self.assertIn(r"\u003c", text)
        self.assertEqual(json.loads(text), value)

    def test_no_private_data(self):
        store = make_store(self.tmp / "ledger", ["SS008", "LS075"])
        revision = store.update_draft({"code": "SS008", "qty": 1, "revision": store.state()["revision"]})["revision"]
        store.confirm({"revision": revision})
        with store.transaction(True) as con:
            con.execute("UPDATE items SET name='注文だけの名前ZQX9'")
        store.export(self.out)
        files = [p for p in self.out.rglob("*") if p.is_file()]
        self.assertTrue(files)
        for path in files:
            data = path.read_bytes()
            self.assertNotIn("注文だけの名前ZQX9".encode(), data, path)
            self.assertNotIn(b"/Users/", data, path)

    def test_invalid_class_id_rejected(self):
        from catalog_output import export_catalog
        product = {"code": "SS008", "name": "a", "image": "0" * 64, "price_class": "SS"}
        for classes, products in [([{"id": "bad", "label": "x", "unit_price": 1}], [product]),
                                  ([{"id": "LS", "label": "x", "unit_price": 1}], [product])]:
            with self.assertRaises(ValueError):
                export_catalog(products, lambda d: b"", self.out, classes)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
