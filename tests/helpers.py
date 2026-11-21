import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

import app


def tiny_jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, "JPEG")
    return buffer.getvalue()


def png_data_url() -> str:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def make_store(tmp: Path, codes: list[str]) -> app.Store:
    """一時フォルダに台帳を作り、各品番に白JPEGと名前を登録する（seedは呼ばない）。"""
    store = app.Store(Path(tmp))
    with store.transaction(True) as con:
        digest = store.save_photo(con, tiny_jpeg())
        for code in codes:
            con.execute("INSERT INTO products (code,sleeve,number,name,image) VALUES (?,?,?,?,?)",
                        (code, code[:2], int(code[2:]), f"商品 {code}", digest))
    return store
