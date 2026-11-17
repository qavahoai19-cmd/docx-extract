import json
import zipfile

from docx_extract import ns
from docx_extract.batch import clean_docx_batch
from docx_extract.mathocr import OCRClient


def make_document(path, images):
    objects = "".join(f'<w:p><w:r><w:object><v:imagedata r:id="i{index}"/>'
                      '<o:OLEObject ProgID="Equation.DSMT4"/></w:object></w:r></w:p>'
                      for index in range(len(images)))
    xml = (f'<w:document xmlns:w="{ns.W[1:-1]}" xmlns:v="{ns.V[1:-1]}" '
           f'xmlns:o="{ns.O[1:-1]}" xmlns:r="{ns.R[1:-1]}"><w:body>{objects}</w:body></w:document>')
    relationships = "".join(f'<Relationship Id="i{index}" Target="media/{index}.wmf"/>'
                            for index in range(len(images)))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
        archive.writestr("word/_rels/document.xml.rels", f"<Relationships>{relationships}</Relationships>")
        for index, data in enumerate(images):
            archive.writestr(f"word/media/{index}.wmf", data)
    return path


class Session:
    def __init__(self, omit=None):
        self.posts = []
        self.omit = omit

    def get(self, *args, **kwargs):
        return self.response({"batch": True})

    @staticmethod
    def response(payload):
        class Response:
            status_code = 200

            def json(self):
                return payload

            def raise_for_status(self):
                pass
        return Response()

    def post(self, url, **kwargs):
        self.posts.append(kwargs)
        ids = json.loads(kwargs["data"]["ids"])
        return self.response({"results": [{"id": oid, "latex": f"latex:{oid}"}
                                           for oid in reversed(ids) if oid != self.omit]})

    def close(self):
        pass


def test_batch_deduplicates_across_documents_and_restores_local_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_NATIVE_MATH", "1")
    paths = [make_document(tmp_path/"one.docx", [b"shared", b"one"]),
             make_document(tmp_path/"two.docx", [b"shared", b"two"])]
    session = Session()
    with OCRClient(endpoint="http://test/ocr", session=session, cache_path="off", prepare=False) as client:
        documents, metrics = clean_docx_batch(paths, client)
    assert metrics["total"] == 4 and metrics["unique"] == 3 and metrics["deduplicated"] == 1
    assert len(session.posts) == 1 and len(session.posts[0]["files"]) == 3
    for document in documents:
        assert document.context.native_stats["native_attempted"] == 0
        assert document.context.latex["mathtype_1"] == "latex:d1__mathtype_1"
        assert document.context.written["mathtype_1.wmf"] == b"shared"
        assert "d1__" not in document.markup
    assert documents[0].context.latex["mathtype_2"] != documents[1].context.latex["mathtype_2"]


def test_bad_document_and_missing_ocr_result_do_not_destroy_other_results(tmp_path):
    good = make_document(tmp_path/"good.docx", [b"one", b"two"])
    broken = tmp_path/"broken.docx"
    broken.write_bytes(b"not a ZIP")
    with OCRClient(endpoint="http://test/ocr", session=Session(omit="d1__mathtype_2"),
                   cache_path="off", prepare=False) as client:
        documents, metrics = clean_docx_batch([good, broken], client)
    assert documents[1].error and metrics["failed_documents"] == 1
    assert documents[0].context.latex == {"mathtype_1": "latex:d1__mathtype_1"}
    assert documents[0].context.ocr_stats["failures"] == 1
    assert documents[0].context.written["mathtype_2.wmf"] == b"two"
