"""台帳の単価区分。どの関数も呼び出し元のトランザクション内で動く。"""
import re

DEFAULT_CLASSES = [("SS", "半袖", 2000, 1), ("LS", "長袖", 2900, 2)]
MAX_PRICE = 9_999_999
CLASS_ID = re.compile(r"SS|LS|PC[0-9]{2,}")


def migrate_price_classes(con):
    """区分表と products.price_class を用意する。既存の値と user_version は変えない。"""
    con.execute("""CREATE TABLE IF NOT EXISTS price_classes (
     id TEXT PRIMARY KEY, label TEXT NOT NULL,
     unit_price INTEGER NOT NULL CHECK(unit_price BETWEEN 0 AND 9999999),
     sort INTEGER NOT NULL
    )""")
    con.executemany("INSERT OR IGNORE INTO price_classes VALUES(?,?,?,?)", DEFAULT_CLASSES)
    columns = {row[1] for row in con.execute("PRAGMA table_info(products)")}
    if "price_class" not in columns:
        con.execute("ALTER TABLE products ADD COLUMN price_class TEXT REFERENCES price_classes(id)")


def list_price_classes(con):
    return [{"id": id_, "label": label, "unit_price": price} for id_, label, price in con.execute(
        "SELECT id,label,unit_price FROM price_classes ORDER BY sort,id")]


def save_price_class(con, data):
    label, price = data.get("label"), data.get("unit_price")
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 40:
        raise ValueError("区分名は1〜40文字で入力してください。")
    # bool は int の派生型なので type() で判定する。
    if type(price) is not int or not 0 <= price <= MAX_PRICE:
        raise ValueError("単価は0〜9,999,999円の整数で入力してください。")
    label = label.strip()
    if "id" in data:
        class_id = data["id"]
        if not isinstance(class_id, str) or not CLASS_ID.fullmatch(class_id) or not con.execute(
                "UPDATE price_classes SET label=?,unit_price=? WHERE id=?", (label, price, class_id)).rowcount:
            raise ValueError("単価区分が見つかりません。")
        return class_id
    numbers = [int(id_[2:]) for (id_,) in con.execute("SELECT id FROM price_classes")
               if CLASS_ID.fullmatch(id_) and id_.startswith("PC")]
    class_id = f"PC{max(numbers, default=0) + 1:02}"
    sort = con.execute("SELECT COALESCE(MAX(sort),0)+1 FROM price_classes").fetchone()[0]
    con.execute("INSERT INTO price_classes VALUES(?,?,?,?)", (class_id, label, price, sort))
    return class_id


def assign_price_class(con, code, price_class):
    """None は袖の区分に戻す。"""
    if price_class is not None and (not isinstance(price_class, str) or not con.execute(
            "SELECT 1 FROM price_classes WHERE id=?", (price_class,)).fetchone()):
        raise ValueError("単価区分が見つかりません。")
    if not isinstance(code, str) or not con.execute(
            "UPDATE products SET price_class=? WHERE code=?", (price_class, code)).rowcount:
        raise ValueError("品番が見つかりません。")
