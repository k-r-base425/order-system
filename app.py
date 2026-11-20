"""バンドTシャツのローカル注文台帳。Python + Pillow + ReportLab。"""
import argparse
import base64
import binascii
import errno
from contextlib import closing, contextmanager
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import urlsplit
from urllib.request import urlopen
import webbrowser

from PIL import Image, ImageOps, UnidentifiedImageError

from catalog_names import READINGS, catalog_name

ROOT = Path(__file__).resolve().parent
MAX_IMAGE = 12 * 1024 * 1024
MAX_BODY = 4 * MAX_IMAGE // 3 + 65536
SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
 digest TEXT PRIMARY KEY, jpeg BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
 code TEXT PRIMARY KEY, sleeve TEXT NOT NULL, number INTEGER NOT NULL,
 name TEXT NOT NULL, image TEXT NOT NULL REFERENCES photos(digest),
 UNIQUE(sleeve,number)
);
CREATE TABLE IF NOT EXISTS draft (
 code TEXT PRIMARY KEY REFERENCES products(code), qty INTEGER NOT NULL CHECK (qty>0)
);
CREATE TABLE IF NOT EXISTS state (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL
);
INSERT OR IGNORE INTO state VALUES(1,0);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_quote_pdfs (
 order_id INTEGER PRIMARY KEY REFERENCES orders(id), pdf BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
 order_id INTEGER REFERENCES orders(id), code TEXT NOT NULL, name TEXT NOT NULL,
 image TEXT NOT NULL REFERENCES photos(digest), qty INTEGER NOT NULL CHECK(qty>0),
 PRIMARY KEY(order_id,code)
);
"""


class Conflict(ValueError):
    pass


def normalized_photo(raw):
    if len(raw) > MAX_IMAGE:
        raise ValueError("写真は12MB以内で選んでください。")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG"} or source.width * source.height > 40_000_000:
                raise ValueError("写真は4,000万画素以内のJPEG・PNGを選んでください。")
            frame = ImageOps.exif_transpose(source)
            frame.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
            rgba = frame.convert("RGBA")
            # 新しい画布に描き、EXIF、位置情報、コメントを引き継がない。
            clean = Image.new("RGB", rgba.size, "white")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            out = BytesIO()
            clean.save(out, format="JPEG", quality=89, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("画像を読み込めません。JPEG・PNGを確認してください。") from exc


class Store:
    def __init__(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        self.db = folder / "orders.sqlite3"
        with closing(self.connect()) as con:
            con.executescript(SCHEMA)

    def connect(self):
        con = sqlite3.connect(self.db, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    @contextmanager
    def transaction(self, write=False):
        with closing(self.connect()) as con, con:
            con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield con

    @staticmethod
    def save_photo(con, jpeg):
        digest = hashlib.sha256(jpeg).hexdigest()
        con.execute("INSERT OR IGNORE INTO photos VALUES (?,?)", (digest, jpeg))
        return digest

    def seed(self, source):
        with self.transaction(True) as con:
            if con.execute("SELECT COUNT(*) FROM products").fetchone()[0]:
                updates = [(catalog_name(name), name) for (name,) in con.execute(
                    "SELECT DISTINCT name FROM products") if name in READINGS]
                if updates:
                    con.executemany("UPDATE products SET name=? WHERE name=?", updates)
                    con.execute("UPDATE state SET revision=revision+1")
                return
            for sleeve, label, count in [("SS", "半袖", 193), ("LS", "長袖", 85)]:
                expected = {f"{sleeve}{i:03}" for i in range(1, count + 1)}
                photos = sorted((source / label).glob("*.jpg"))
                if len(photos) != count:
                    raise ValueError(f"{label}の元写真は{count}枚必要です。取込元を確認してください。")
                for path in photos:
                    name, _, code = path.stem.rpartition("_")
                    if not name or code not in expected:
                        raise ValueError(f"品番を取込できません: {path.name}")
                    expected.remove(code)
                    digest = self.save_photo(con, normalized_photo(path.read_bytes()))
                    con.execute("INSERT INTO products VALUES(?,?,?,?,?)",
                                (code, sleeve, int(code[2:]), catalog_name(name), digest))

    @staticmethod
    def products(con):
        return [dict(row) for row in con.execute(
            "SELECT code,name,image FROM products ORDER BY sleeve DESC,number")]

    @staticmethod
    def draft(con):
        return dict(con.execute("SELECT code,qty FROM draft"))

    @staticmethod
    def revision(con):
        return con.execute("SELECT revision FROM state").fetchone()[0]

    def check_revision(self, con, value):
        if type(value) is not int or self.revision(con) != value:
            raise Conflict("他の変更が保存されています。最新の内容を確認して、もう一度操作してください。")

    def state(self):
        with self.transaction() as con:
            orders = [dict(row) for row in con.execute(
                "SELECT id,created,SUM(qty) AS total FROM orders JOIN items ON order_id=id GROUP BY id ORDER BY id DESC")]
            return dict(products=with_urls(self.products(con)), draft=self.draft(con),
                        revision=self.revision(con), orders=orders)

    def update_draft(self, data):
        qty, code = data.get("qty"), data.get("code")
        if type(qty) is not int or not 0 <= qty <= 99999:
            raise ValueError("点数は0〜99,999の整数で入力してください。")
        with self.transaction(True) as con:
            self.check_revision(con, data.get("revision"))
            if not isinstance(code,str) or not con.execute("SELECT 1 FROM products WHERE code=?", (code,)).fetchone():
                raise ValueError("品番が見つかりません。")
            if qty:
                con.execute("INSERT OR REPLACE INTO draft VALUES(?,?)", (code, qty))
            else:
                con.execute("DELETE FROM draft WHERE code=?", (code,))
            con.execute("UPDATE state SET revision=revision+1")
            return dict(revision=self.revision(con), draft=self.draft(con))

    def confirm(self, data):
        with self.transaction(True) as con:
            self.check_revision(con, data.get("revision"))
            if not self.draft(con):
                raise ValueError("商品を選んでください。")
            now = datetime.now().astimezone().isoformat(timespec="minutes")
            order_id = con.execute("INSERT INTO orders(created) VALUES(?)", (now,)).lastrowid
            con.execute("""INSERT INTO items SELECT ?,d.code,p.name,p.image,d.qty
                           FROM draft d JOIN products p ON d.code=p.code""", (order_id,))
            con.execute("DELETE FROM draft")
            con.execute("UPDATE state SET revision=revision+1")
            return {"id": order_id}

    def order(self, order_id):
        with self.transaction() as con:
            order = con.execute("""SELECT id, created,
                EXISTS(SELECT 1 FROM order_quote_pdfs WHERE order_id=orders.id) AS has_quote_pdf
                FROM orders WHERE id=?""", (order_id,)).fetchone()
            if order is None:
                raise KeyError()
            items = [dict(row) for row in con.execute(
                """SELECT code,name,image,qty FROM items WHERE order_id=?
                   ORDER BY substr(code,1,2) DESC, CAST(substr(code,3) AS INTEGER)""", (order_id,))]
            return dict(order, items=items, total=sum(item["qty"] for item in items))

    @staticmethod
    def read_photo(con, digest):
        result = con.execute("SELECT jpeg FROM photos WHERE digest=?", (digest,)).fetchone()
        if result is None:
            raise KeyError()
        return result[0]

    def photo(self, digest):
        with self.transaction() as con:
            return self.read_photo(con, digest)

    def change_product(self, data):
        encoded = data.get("image")
        if not isinstance(encoded, str) or not re.match(r"^data:image/(jpeg|png);base64,", encoded):
            raise ValueError("JPEGまたはPNGを選んでください。")
        try:
            raw = base64.b64decode(encoded.split(",", 1)[1], validate=True)
        except binascii.Error as exc:
            raise ValueError("写真を読み込めません。") from exc
        jpeg = normalized_photo(raw)
        with self.transaction(True) as con:
            digest = self.save_photo(con, jpeg)
            if "code" in data:
                code = data["code"]
                if not isinstance(code,str) or not con.execute("UPDATE products SET image=? WHERE code=?", (digest,code)).rowcount:
                    raise ValueError("差し替える品番が見つかりません。")
            else:
                sleeve, name = data.get("sleeve"), data.get("name")
                if sleeve not in ("SS", "LS") or not isinstance(name,str) or not 1 <= len(name.strip()) <= 120:
                    raise ValueError("袖と商品名（120文字以内）を入力してください。")
                number = con.execute("SELECT COALESCE(MAX(number),0)+1 FROM products WHERE sleeve=?", (sleeve,)).fetchone()[0]
                code = f"{sleeve}{number:03}"
                con.execute("INSERT INTO products VALUES(?,?,?,?,?)", (code,sleeve,number,catalog_name(name.strip()),digest))
            con.execute("UPDATE state SET revision=revision+1")
            return {"code": code}

    def export(self, destination):
        from catalog_output import export_catalog
        with self.transaction() as con:
            products = self.products(con)
            export_catalog(products, lambda digest: self.read_photo(con, digest), destination)
        return {"count":len(products)}


def with_urls(rows):
    return [dict(row,image="/photos/"+row["image"]+".jpg") for row in rows]


class Handler(BaseHTTPRequestHandler):
    def reply(self, content, mime, status=200, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Order-Ledger", self.server.ledger_key)
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
        self.end_headers()
        self.wfile.write(content)

    def json(self, value, status=200):
        self.reply(json.dumps(value,ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def file(self,path):
        if not path.is_file():
            raise KeyError()
        self.reply(path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")

    def local_host(self):
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def do_GET(self):
        if not self.local_host():
            return self.json({"error":"ローカル接続を使用してください。"},403)
        route = urlsplit(self.path).path
        db = self.server.store
        try:
            if route in {"/","/index.html","/admin.css","/app.js"}:
                return self.file(ROOT/"web"/(route.strip("/") or "index.html"))
            if route == "/api/state":
                return self.json(db.state())
            if route == "/forms/template":
                if re.fullmatch(r"[A-Za-z0-9_-]+", self.server.template_id):
                    self.send_response(302)
                    self.send_header("Location", f"https://docs.google.com/spreadsheets/d/{self.server.template_id}/copy")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                return self.file(ROOT / "帳票ひな型.xlsx")
            if route.startswith("/catalog/"):
                base = self.server.catalog.resolve()
                path = (base/(route[9:] or "index.html")).resolve()
                if base not in path.parents:
                    raise KeyError()
                return self.file(path)
            if match := re.fullmatch(r"/photos/([a-f0-9]{64})\.jpg", route):
                return self.reply(db.photo(match[1]), "image/jpeg")
            if match := re.fullmatch(r"/api/orders/([1-9][0-9]{0,12})(/pdf)?", route):
                order = db.order(int(match[1]))
                if match[2]:
                    if order["has_quote_pdf"]:
                        with db.transaction() as con:
                            pdf = con.execute("SELECT pdf FROM order_quote_pdfs WHERE order_id=?",
                                              (order["id"],)).fetchone()[0]
                        return self.reply(pdf, "application/pdf", filename=f"quote-order-{order['id']:04}.pdf")
                    from catalog_output import make_pdf
                    order["test"] = self.server.test_mode
                    return self.reply(make_pdf(order,db.photo),"application/pdf",filename=f"order-{order['id']:04}.pdf")
                return self.json(dict(order,items=with_urls(order["items"])))
            raise KeyError()
        except KeyError:
            self.json({"error":"対象が見つかりません。"},404)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception:
            self.log_error("GET failed: %s",route)
            self.json({"error":"読込に失敗しました。"},500)

    def do_POST(self):
        host = self.headers.get("Host","")
        if not self.local_host() or self.headers.get("Origin",f"http://{host}") != f"http://{host}":
            return self.json({"error":"注文画面から操作してください。"},403)
        if self.headers.get_content_type() != "application/json":
            return self.json({"error":"JSONが必要です。"},415)
        try:
            length = int(self.headers.get("Content-Length","0"))
            if not 0 < length <= MAX_BODY:
                return self.json({"error":"入力が空か、写真が大きすぎます。"},413)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError("入力内容を確認してください。")
            store = self.server.store
            if self.path == "/api/export":
                with self.server.export_lock:
                    return self.json(store.export(self.server.catalog))
            fn = {"/api/draft":store.update_draft, "/api/orders":store.confirm, "/api/products":store.change_product}.get(self.path)
            if fn is None:
                return self.json({"error":"対象が見つかりません。"},404)
            self.json(fn(data))
        except Conflict as exc:
            self.json({"error":str(exc)},409)
        except (ValueError,TypeError) as exc:
            self.json({"error": str(exc)},400)
        except (OSError,sqlite3.Error) as exc:
            self.log_error("save failed: %s", type(exc).__name__)
            self.json({"error":"保存できませんでした。ディスクの空き容量と起動画面を確認してください。"},500)

    def log_request(self, code="-", size="-"):
        if str(code).startswith("5"):
            super().log_request(code,size)


def main():
    settings_path = ROOT / "settings.local.json"
    settings = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
    parser = argparse.ArgumentParser(description="ローカルの商品台帳・注文画面")
    parser.add_argument("--data", type=Path,default=ROOT/"台帳")
    parser.add_argument("--catalog",type=Path,default=ROOT/"照合用一覧")
    parser.add_argument("--source",type=Path,default=Path(settings.get("source", ROOT / "商品写真")))
    parser.add_argument("--port",type=int,default=8746)
    parser.add_argument("--open",action="store_true")
    parser.add_argument("--export-only",action="store_true")
    parser.add_argument("--test",action="store_true",help="検証台帳の注文書にテスト表示を付ける")
    args = parser.parse_args()
    store = Store(args.data)
    store.seed(args.source)
    if args.export_only or not (args.catalog/"index.html").is_file():
        result = store.export(args.catalog)
        print(f"照合用一覧に{result['count']}商品を出力しました。",flush=True)
    if args.export_only:
        return
    ledger_key = hashlib.sha256(str(store.db.resolve()).encode()).hexdigest()
    try:
        server = ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE or not args.open:
            raise
        url = f"http://127.0.0.1:{args.port}/"
        with urlopen(url,timeout=3) as response:
            if response.headers.get("X-Order-Ledger") != ledger_key:
                raise SystemExit("このポートは別のアプリが使用中です。")
        webbrowser.open(url)
        return
    server.template_id = settings.get("template_id", "")
    server.ledger_key,server.test_mode = ledger_key,args.test
    server.store,server.catalog,server.export_lock = store,args.catalog,threading.Lock()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"注文画面 {url}  終了は Control+C",flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
