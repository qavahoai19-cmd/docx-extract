import zipfile
import posixpath
from dataclasses import dataclass
from lxml import etree
from . import ns


@dataclass
class Document:
    body: etree._Element
    rels: dict          # rId -> full zip path
    assets: dict        # full zip path -> bytes


def load(path: str) -> Document:
    with zipfile.ZipFile(path) as z:
        doc_xml = z.read("word/document.xml")
        # Một docx hợp lệ nhưng không có ảnh/OLE/relationship nào có thể
        # không có phần word/_rels/document.xml.rels trong zip — không được
        # crash giữa chừng vì thiếu 1 part không bắt buộc.
        try:
            rels_xml = z.read("word/_rels/document.xml.rels")
        except KeyError:
            rels_xml = None
        assets = {
            n: z.read(n)
            for n in z.namelist()
            if n.startswith("word/media/") or n.startswith("word/embeddings/")
        }

    root = etree.fromstring(doc_xml)
    body = root.find(ns.q("w", "body"))

    rels = {}
    if rels_xml is not None:
        for rel in etree.fromstring(rels_xml):
            rid = rel.get("Id")
            target = rel.get("Target")
            # Target tương đối với thư mục word/ ; chuẩn hoá về đường dẫn zip
            full = posixpath.normpath(posixpath.join("word", target))
            rels[rid] = full
    return Document(body=body, rels=rels, assets=assets)
