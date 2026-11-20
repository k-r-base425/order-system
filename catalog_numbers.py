"""2026-11-20 に確認済みの同一写真を統合する品番対応表。"""
import csv
import hashlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def number_map():
    with (ROOT / "品番対応表.csv").open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def renumber_reviewed_catalog(con):
    """照合済みの旧台帳だけを、呼び出し元のトランザクション内で更新する。"""
    if con.execute("PRAGMA user_version").fetchone()[0] != 0:
        return False
    entries = number_map()
    prior = {row["旧品番"]: row for row in entries}
    products = dict(con.execute("SELECT code,image FROM products"))
    initial = {code for code in prior if int(code[2:]) <= (193 if code.startswith("SS") else 85)}
    if products.keys() != initial and products.keys() != prior.keys():
        return False
    if any(image != prior[code]["旧写真ID"] for code, image in products.items()):
        return False

    quantities = Counter()
    for code, qty in con.execute("SELECT code,qty FROM draft"):
        quantities[prior[code]["新品番"]] += qty
    # 注文明細は発行当時の品番・写真を持つ独立したスナップショット。
    con.execute("DELETE FROM draft")
    con.execute("DELETE FROM products")
    for row in entries:
        old = row["旧品番"]
        if old != row["残した旧品番"]:
            continue
        code, digest = row["新品番"], row["旧写真ID"]
        if old not in products:
            # 初期278品番からの起動時も、その後に掲載した商品を取り込む。
            photo = (ROOT / "照合用一覧" / "images" / (digest + ".jpg")).read_bytes()
            if hashlib.sha256(photo).hexdigest() != digest:
                raise ValueError(f"{code} の商品写真を確認してください。")
            con.execute("INSERT OR IGNORE INTO photos VALUES(?,?)", (digest, photo))
        con.execute("INSERT INTO products VALUES(?,?,?,?,?)",
                    (code, code[:2], int(code[2:]), row["商品名"], digest))
    con.executemany("INSERT INTO draft VALUES(?,?)", quantities.items())
    con.execute("UPDATE state SET revision=revision+1")
    con.execute("PRAGMA user_version=1")
    return True
