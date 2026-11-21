import tempfile
import unittest
from pathlib import Path

import pricing
from tests.helpers import make_store, png_data_url

DEFAULTS = [{"id": "SS", "label": "半袖", "unit_price": 2000},
            {"id": "LS", "label": "長袖", "unit_price": 2900}]


class PricingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    @staticmethod
    def product(rows, code):
        return next(row for row in rows if row["code"] == code)

    def test_default_classes(self):
        store = make_store(self.tmp, ["SS008"])
        with store.transaction() as con:
            self.assertEqual(pricing.list_price_classes(con), DEFAULTS)
        self.assertEqual(store.state()["price_classes"], DEFAULTS)

    def test_add_and_edit_class(self):
        store = make_store(self.tmp, ["SS008"])
        revision = store.state()["revision"]
        added = store.update_price_class({"label": "レア", "unit_price": 4500, "revision": revision})
        self.assertEqual(added["revision"], revision + 1)
        self.assertEqual(added["price_classes"], DEFAULTS + [{"id": "PC01", "label": "レア", "unit_price": 4500}])
        self.assertEqual(self.product(added["products"], "SS008")["image"][:8], "/photos/")

        edited = store.update_price_class({"id": "SS", "label": "半袖", "unit_price": 2200,
                                           "revision": added["revision"]})
        self.assertEqual(edited["revision"], revision + 2)
        expected = [{"id": "SS", "label": "半袖", "unit_price": 2200}, DEFAULTS[1],
                    {"id": "PC01", "label": "レア", "unit_price": 4500}]
        self.assertEqual(edited["price_classes"], expected)
        self.assertEqual(store.state()["price_classes"], expected)

        again = store.update_price_class({"label": "特価", "unit_price": 0, "revision": edited["revision"]})
        self.assertEqual(again["revision"], revision + 3)
        self.assertEqual(again["price_classes"][-1], {"id": "PC02", "label": "特価", "unit_price": 0})

    def test_assign_and_reset(self):
        store = make_store(self.tmp, ["SS008", "LS075"])
        revision = store.update_price_class({"label": "レア", "unit_price": 4500,
                                             "revision": store.state()["revision"]})["revision"]
        result = store.set_product_price_class({"code": "SS008", "price_class": "PC01", "revision": revision})
        self.assertEqual(result["revision"], revision + 1)
        for rows in (result["products"], store.state()["products"]):
            self.assertEqual(self.product(rows, "SS008")["price_class"], "PC01")
            self.assertEqual(self.product(rows, "SS008")["assigned_price_class"], "PC01")
            self.assertEqual(self.product(rows, "LS075")["price_class"], "LS")
            self.assertIsNone(self.product(rows, "LS075")["assigned_price_class"])

        result = store.set_product_price_class({"code": "SS008", "price_class": None,
                                                "revision": result["revision"]})
        row = self.product(store.state()["products"], "SS008")
        self.assertEqual(row["price_class"], "SS")
        self.assertIsNone(row["assigned_price_class"])

        store.set_product_price_class({"code": "SS008", "price_class": "SS", "revision": result["revision"]})
        row = self.product(store.state()["products"], "SS008")
        self.assertEqual(row["price_class"], "SS")
        self.assertEqual(row["assigned_price_class"], "SS")

    def test_rejects_invalid_price(self):
        store = make_store(self.tmp, ["SS008"])
        revision = store.update_price_class({"label": "レア", "unit_price": 4500,
                                             "revision": store.state()["revision"]})["revision"]
        revision = store.set_product_price_class({"code": "SS008", "price_class": "PC01",
                                                  "revision": revision})["revision"]
        before = store.state()
        cases = []
        for price in (-1, 1.5, True, "2000", 10000000):
            cases.append((store.update_price_class, {"label": "追加", "unit_price": price}))
            cases.append((store.update_price_class, {"id": "SS", "label": "半袖", "unit_price": price}))
        cases += [
            (store.update_price_class, {"label": "   ", "unit_price": 100}),
            (store.update_price_class, {"label": "あ" * 41, "unit_price": 100}),
            (store.update_price_class, {"id": "SS", "label": "   ", "unit_price": 100}),
            (store.update_price_class, {"id": "PC09", "label": "なし", "unit_price": 100}),
            (store.update_price_class, {"id": "XX", "label": "形式違い", "unit_price": 100}),
            (store.set_product_price_class, {"code": "SS008", "price_class": "PC09"}),
            (store.set_product_price_class, {"code": "SS999", "price_class": "PC01"}),
        ]
        for fn, data in cases:
            with self.subTest(fn=fn.__name__, data=data):
                with self.assertRaises(Exception) as caught:
                    fn(dict(data, revision=revision))
                self.assertIs(type(caught.exception), ValueError)
                self.assertEqual(store.state(), before)

    def test_confirmed_order_unchanged(self):
        store = make_store(self.tmp, ["SS008", "LS075"])
        revision = store.update_draft({"code": "SS008", "qty": 2, "revision": store.state()["revision"]})["revision"]
        revision = store.update_draft({"code": "LS075", "qty": 1, "revision": revision})["revision"]
        order_id = store.confirm({"revision": revision})["id"]
        before = store.order(order_id)

        revision = store.update_price_class({"id": "SS", "label": "半袖", "unit_price": 2500,
                                             "revision": store.state()["revision"]})["revision"]
        revision = store.update_price_class({"label": "レア", "unit_price": 4500, "revision": revision})["revision"]
        store.set_product_price_class({"code": "SS008", "price_class": "PC01", "revision": revision})
        self.assertEqual(store.order(order_id), before)

    def test_new_product_after_migration(self):
        store = make_store(self.tmp, ["SS008"])
        code = store.change_product({"sleeve": "SS", "name": "新商品", "image": png_data_url()})["code"]
        self.assertEqual(code, "SS009")
        row = self.product(store.state()["products"], code)
        self.assertEqual(row["price_class"], "SS")
        self.assertIsNone(row["assigned_price_class"])


if __name__ == "__main__":
    unittest.main()
