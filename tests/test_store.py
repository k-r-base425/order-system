import re
import tempfile
import unittest
from pathlib import Path

import app
from catalog_output import japanese_font_path, make_pdf
from tests.helpers import make_store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_draft_and_confirm(self):
        store = make_store(self.tmp, ["SS008", "LS075"])
        revision = store.state()["revision"]
        revision = store.update_draft({"code": "SS008", "qty": 2, "revision": revision})["revision"]
        revision = store.update_draft({"code": "LS075", "qty": 1, "revision": revision})["revision"]
        order_id = store.confirm({"revision": revision})["id"]
        order = store.order(order_id)
        self.assertEqual(order["total"], 3)
        self.assertEqual([(i["code"], i["qty"]) for i in order["items"]], [("SS008", 2), ("LS075", 1)])

    def test_stale_revision_conflicts(self):
        store = make_store(self.tmp, ["SS008"])
        revision = store.state()["revision"]
        store.update_draft({"code": "SS008", "qty": 1, "revision": revision})
        with self.assertRaises(Exception) as caught:
            store.update_draft({"code": "SS008", "qty": 2, "revision": revision})
        self.assertIs(type(caught.exception), app.Conflict)

    def test_pdf_paginates(self):
        codes = [f"SS{i:03}" for i in range(1, 8)]
        store = make_store(self.tmp, codes)
        revision = store.state()["revision"]
        for code in codes:
            revision = store.update_draft({"code": code, "qty": 1, "revision": revision})["revision"]
        order = store.order(store.confirm({"revision": revision})["id"])
        pdf = make_pdf(order, store.photo)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(len(re.findall(rb"/Type /Page[^s]", pdf)), 2)

    def test_font_fallback(self):
        existing = self.tmp / "exists.ttf"
        existing.write_bytes(b"x")
        self.assertEqual(japanese_font_path([self.tmp / "none.ttf", existing]), existing)
        with self.assertRaises(FileNotFoundError):
            japanese_font_path([self.tmp / "none.ttf"])


if __name__ == "__main__":
    unittest.main()
