"""閲覧用静的カタログと、注文時の写真を使うスマートフォン用PDF。"""

import fcntl
import html
import io
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from catalog_numbers import number_map

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


_DIGEST = re.compile(r"[a-f0-9]{64}")
_CODE = re.compile(r"(SS|LS)[0-9]{3,}")
_TEMPLATE = Path(__file__).with_name("web") / "catalog.html"
_FONT = "BandOrderJapanese"
_FONT_LOCK = threading.Lock()


def _atomic_file(path, content):
    """同じディレクトリに書き終えてから公開する。"""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".writing-", delete=False) as file:
        tmp = Path(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            file.close()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def export_catalog(products, image_bytes, destination):
    """専用ディレクトリに現在の品番、表示名と公開用JPEGのみを出力する。"""
    catalog = list(products)
    for product in catalog:
        if not _DIGEST.fullmatch(product["image"]) or not _CODE.fullmatch(product["code"]):
            raise ValueError("一覧に出力できない品番または画像番号があります。")
    catalog.sort(key=lambda p: (p["code"][:2] != "SS", int(p["code"][2:])))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    image_dir = destination / "images"
    image_dir.mkdir(exist_ok=True)
    template = _TEMPLATE.read_text(encoding="utf-8")
    # フォルダ自体をロックするので配布物にロックファイルは残らない。
    fd = os.open(destination, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        keep = set()
        cards = []
        for index, product in enumerate(catalog):
            filename = product["image"] + ".jpg"
            keep.add(filename)
            target = image_dir / filename
            if not target.exists():
                _atomic_file(target, image_bytes(product["image"]))
            code = product["code"]
            name = html.escape(product["name"], quote=True)
            long = code.startswith("LS")
            sleeve = "長袖" if long else "半袖"
            cls = "sleeve long" if long else "sleeve"
            lazy = ' loading="lazy"' if index >= 8 else ""
            cards.append(
                f'<button type="button" class="card" data-code="{code}" '
                f'aria-label="{code} {name} 拡大" aria-haspopup="dialog">'
                f'<img class="photo" src="images/{filename}" alt=""{lazy} decoding="async">'
                f'<span class="info"><span class="meta"><span class="code">{code}</span>'
                f'<span class="{cls}">{sleeve}</span></span>'
                f'<span class="name">{name}</span></span></button>'
            )
        template = template.replace("%%ORDER_SCRIPT%%", _TEMPLATE.with_name("catalog-orders.js").read_text(encoding="utf-8"))
        entries = number_map()
        previous = {version: {row[column]: row["新品番"] for row in entries}
                    for version, column in [(1, "旧品番"), (2, "初回整理後品番")]}
        images = {row["旧品番"]: row["旧写真ID"] for row in entries}
        # file:// で確定した旧注文には、ブラウザ側に写真のコピーがない。
        aliases = {f'images/{row["旧写真ID"]}.jpg': f'images/{images[row["残した旧品番"]]}.jpg'
                   for row in entries if row["旧写真ID"] != images[row["残した旧品番"]]}
        template = template.replace("%%PREVIOUS_PHOTOS%%", json.dumps(aliases, separators=(",", ":")))
        template = template.replace("%%PREVIOUS_CODES%%", json.dumps(previous, separators=(",", ":")))
        page = template.replace("%%COUNT%%", str(len(catalog))).replace("%%CARDS%%", "\n".join(cards))
        _atomic_file(destination / "index.html", page.encode("utf-8"))
        # 差し替え前の写真は配布フォルダから外す。注文の保存領域とは独立。
        for path in image_dir.glob("*.jpg"):
            if _DIGEST.fullmatch(path.stem) and path.name not in keep:
                path.unlink()
    finally:
        os.close(fd)


def make_pdf(order, image_bytes):
    """確定明細のJPEGを埋め込み、最初と最後のページに注文見出しを表示する。"""
    with _FONT_LOCK:
        if _FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(_FONT, "/Library/Fonts/Arial Unicode.ttf"))

    items = list(order["items"])
    if not items:
        raise ValueError("注文書に載せる商品がありません。")
    width, height = A4
    buffer = io.BytesIO()
    doc = canvas.Canvas(buffer, pagesize=(width, height), pageCompression=1, invariant=1)
    order_no = f'PO-{order["id"]:04d}'
    doc.setTitle(f'写真付き注文書 {order_no}')
    doc.setAuthor("")
    doc.setCreator("バンドTシャツ注文台帳")
    page_capacity = 6
    pages = (len(items) + page_capacity - 1) // page_capacity
    for page in range(pages):
        show_header = page == 0 or page == pages - 1
        header_height = 73 if show_header else 0
        if show_header:
            doc.setFillColor(HexColor("#153b2f"))
            doc.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
            doc.setFillColor(HexColor("#ffffff"))
            doc.setFont(_FONT, 24)
            doc.drawString(16, height - 33, "注文書")
            doc.setFont(_FONT, 10)
            doc.drawString(17, height - 55, f'{order_no}   {str(order["created"])[:10]}')
            if order.get("test"):
                doc.drawRightString(width - 16, height - 55, "テスト注文")
            doc.setFillColor(HexColor("#dff29c"))
            doc.setFont(_FONT, 15)
            doc.drawRightString(width - 16, height - 32, f'合計 {order["total"]:,} 点')
        first_item = page * page_capacity
        margin, gutter = 20, 14
        w = (width - 2 * margin - gutter) / 2
        row_height = (height - header_height - 16 - 24) / 3
        h = row_height - 36
        for index, item in enumerate(items[first_item:first_item + page_capacity]):
            row, column = divmod(index, 2)
            top = height - header_height - 16 - row * row_height
            x = margin + column * (w + gutter)
            y = top - h
            doc.setFillColor(HexColor("#eeeee7"))
            doc.roundRect(x, y, w, h, 5, fill=1, stroke=0)
            photo = ImageReader(io.BytesIO(image_bytes(item["image"])))
            doc.drawImage(photo, x, y, w, h, preserveAspectRatio=True, anchor="c")
            doc.setFillColor(HexColor("#18382c"))
            doc.setFont("Helvetica-Bold", 19)
            doc.drawString(x, y - 21, item["code"])
            doc.setFont(_FONT, 17)
            doc.drawRightString(x + w, y - 21, f'{item["qty"]:,} 点')
            doc.setStrokeColor(HexColor("#ced8ce"))
            doc.line(x, y - 25, x + w, y - 25)
        doc.setFillColor(HexColor("#55675d"))
        doc.setFont("Helvetica", 10)
        doc.drawRightString(width - 16, 14, f"{page + 1} / {pages}")
        doc.showPage()
    doc.save()
    return buffer.getvalue()
