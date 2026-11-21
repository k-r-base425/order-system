import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import app
from tests.helpers import make_store


class HttpTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.store = make_store(self.tmp / "ledger", ["SS008", "LS075"])
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        server.store, server.catalog, server.export_lock = self.store, self.tmp / "catalog", threading.Lock()
        server.ledger_key, server.test_mode, server.template_id = "test", False, ""
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port

    def request(self, method, path, body=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            origin = f"127.0.0.1:{self.port}"
            headers = {"Host": origin, "Origin": f"http://{origin}", "Content-Type": "application/json"}
            con.request(method, path, None if body is None else json.dumps(body).encode(), headers)
            response = con.getresponse()
            return response.status, json.loads(response.read())
        finally:
            con.close()

    def test_invalid_price_is_400(self):
        before = self.store.state()
        status, body = self.request("POST", "/api/price-classes",
                                    {"id": "SS", "label": "半袖", "unit_price": -1, "revision": before["revision"]})
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertEqual(self.store.state(), before)

    def test_stale_revision_is_409(self):
        stale = self.store.state()["revision"]
        status, _ = self.request("POST", "/api/price-classes",
                                 {"label": "レア", "unit_price": 4500, "revision": stale})
        self.assertEqual(status, 200)
        before = self.store.state()
        status, body = self.request("POST", "/api/price-classes",
                                    {"id": "SS", "label": "半袖", "unit_price": 2200, "revision": stale})
        self.assertEqual(status, 409)
        self.assertIn("error", body)
        self.assertEqual(self.store.state(), before)

    def test_routes_registered(self):
        revision = self.store.state()["revision"]
        status, body = self.request("POST", "/api/price-classes",
                                    {"label": "レア", "unit_price": 4500, "revision": revision})
        self.assertEqual(status, 200)
        self.assertEqual(body["revision"], revision + 1)
        status, body = self.request("POST", "/api/products/price-class",
                                    {"code": "SS008", "price_class": "PC01", "revision": body["revision"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["revision"], revision + 2)

        status, state = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["revision"], revision + 2)
        self.assertIn({"id": "PC01", "label": "レア", "unit_price": 4500}, state["price_classes"])
        row = next(p for p in state["products"] if p["code"] == "SS008")
        self.assertEqual((row["price_class"], row["assigned_price_class"]), ("PC01", "PC01"))


if __name__ == "__main__":
    unittest.main()
