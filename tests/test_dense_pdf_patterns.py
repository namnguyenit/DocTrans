"""Regression coverage for graphic-only tiling patterns during extraction."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

import fitz

spec = importlib.util.spec_from_file_location(
    "extract_pdf", Path(__file__).resolve().parents[1] / "src/Data/extract_pdf.py")
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


def pattern(doc, stream=b"0 0 1 1 re f", resources="<< >>", step=".05", matrix="1 0 0 1 0 0"):
    xref = doc.get_new_xref()
    doc.update_object(xref, f"<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 "
                      f"/BBox [0 0 1 1] /XStep {step} /YStep {step} "
                      f"/Matrix [{matrix}] /Resources {resources} >>")
    doc.update_stream(xref, stream)
    return xref


class DensePatternTests(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page().insert_text((72, 72), "Readable source text 123.")
        self.addCleanup(self.doc.close)

    def test_only_dense_graphic_pattern_is_simplified(self):
        dense = pattern(self.doc)
        normal = pattern(self.doc, step="10")
        scaled = pattern(self.doc, matrix="100 0 0 100 0 0")
        self.assertEqual(extractor.simplify_dense_nontext_patterns(self.doc), [dense])
        self.assertEqual(self.doc.xref_stream(dense), b"")
        self.assertNotEqual(self.doc.xref_stream(normal), b"")
        self.assertNotEqual(self.doc.xref_stream(scaled), b"")

    def test_direct_and_nested_text_is_preserved(self):
        direct = pattern(self.doc, b"BT (essential text) Tj ET")
        form = self.doc.get_new_xref()
        self.doc.update_object(form, "<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] >>")
        self.doc.update_stream(form, b"BT [(nested text)] TJ ET")
        nested = pattern(self.doc, b"/Form Do", f"<< /XObject << /Form {form} 0 R >> >>")
        self.assertEqual(extractor.simplify_dense_nontext_patterns(self.doc), [])
        self.assertIn(b"essential", self.doc.xref_stream(direct))
        self.assertIn(b"/Form", self.doc.xref_stream(nested))

    def test_unknown_recursive_resources_are_preserved(self):
        recursive = pattern(self.doc)
        self.doc.xref_set_key(recursive, "Resources", f"<< /Self {recursive} 0 R >>")
        self.assertEqual(extractor.simplify_dense_nontext_patterns(self.doc), [])

    def test_full_extraction_preserves_text_and_source_file(self):
        dense = pattern(self.doc)
        page = self.doc[0]
        resources = int(self.doc.xref_get_key(page.xref, "Resources")[1].split()[0])
        self.doc.xref_set_key(resources, "Pattern", f"<< /Dense {dense} 0 R >>")
        content = self.doc.get_new_xref()
        self.doc.update_object(content, "<< >>")
        self.doc.update_stream(content, b"/Pattern cs /Dense scn 0 0 500 700 re f")
        old = " ".join(f"{xref} 0 R" for xref in page.get_contents())
        self.doc.xref_set_key(page.xref, "Contents", f"[{old} {content} 0 R]")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dense.pdf"
            self.doc.save(path)
            before = hashlib.sha256(path.read_bytes()).digest()
            pages = extractor.extract_pdf_pages(str(path))
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
            self.assertEqual(len(pages), 1)
            self.assertIn("Readable source text 123.", pages[0]["text"])


if __name__ == "__main__":
    unittest.main()
