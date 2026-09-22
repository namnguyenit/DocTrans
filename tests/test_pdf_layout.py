#!/usr/bin/env python3
import base64
import json
import pathlib
import sys
import tempfile
import unittest

import fitz

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "Data"))
import extract_pdf as extractor


class PdfLayoutTests(unittest.TestCase):
    def save_document(self, document):
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.close()
        document.save(handle.name)
        document.close()
        self.addCleanup(pathlib.Path(handle.name).unlink, missing_ok=True)
        return handle.name

    def test_repeated_margin_content_is_removed(self):
        document = fitz.open()
        for index in range(5):
            page = document.new_page(width=612, height=792)
            page.insert_text((54, 32), "Reusable Technical Manual", fontsize=9)
            page.insert_text((54, 120), f"Unique body paragraph {index}", fontsize=11)
            page.insert_text((54, 765), f"Confidential material {index + 1}", fontsize=8)
        pages = extractor.extract_pdf_pages(self.save_document(document))
        self.assertEqual(len(pages), 5)
        self.assertTrue(all("Reusable Technical Manual" not in page for page in pages))
        self.assertTrue(all("Confidential material" not in page for page in pages))
        self.assertTrue(all(f"Unique body paragraph {i}" in page for i, page in enumerate(pages)))

    def test_navigation_rows_strip_leaders_and_keep_columns(self):
        document = fitz.open()
        page = document.new_page(width=612, height=792)
        page.insert_text((54, 125), "List of Figures", fontsize=22)
        for index, y in enumerate((215, 240, 265), 1):
            page.insert_text(
                (72, y), f"Figure 1-{index}: Vector diagram {index} " + ". " * 24,
                fontsize=10,
            )
            page.insert_text((540, y), str(index + 10), fontsize=10)
        pages = extractor.extract_pdf_pages(self.save_document(document))
        encoded = pages[0].split(extractor.TOC_PREFIX, 1)[1].split(
            extractor.TABLE_SUFFIX, 1
        )[0]
        rows = json.loads(base64.b64decode(encoded))
        self.assertEqual([row["number"] for row in rows], ["Figure 1-1", "Figure 1-2", "Figure 1-3"])
        self.assertEqual([row["page"] for row in rows], ["11", "12", "13"])
        self.assertTrue(all("." not in row["title"] for row in rows))

    def test_vector_figure_has_priority_over_table_detector(self):
        document = fitz.open()
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 110), "The following figure shows a packet diagram.", fontsize=10)
        frame = fitz.Rect(72, 135, 540, 275)
        page.draw_rect(frame, color=(0.7, 0.7, 0.7), fill=(1, 1, 1))
        for x in (90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390, 420, 450, 480, 500):
            page.draw_line((x, 185), (x, 235), color=(0.2, 0.2, 0.2))
        page.draw_line((90, 185), (500, 185), color=(0.2, 0.2, 0.2))
        page.draw_line((90, 235), (500, 235), color=(0.2, 0.2, 0.2))
        page.insert_text((100, 215), "START", fontsize=9)
        page.insert_text((225, 215), "DATA", fontsize=9)
        page.insert_text((400, 215), "STOP", fontsize=9)
        page.insert_text((72, 295), "Figure 1-1 Packet diagram", fontsize=10)
        pages = extractor.extract_pdf_pages(self.save_document(document))
        self.assertEqual(pages[0].count(extractor.IMAGE_PREFIX), 1)
        self.assertEqual(pages[0].count(extractor.TABLE_PREFIX), 0)
        self.assertEqual(pages[0].count("START"), 0)
        self.assertIn("Figure 1-1 Packet diagram", pages[0])

    def test_two_column_text_reads_left_then_right(self):
        document = fitz.open()
        page = document.new_page(width=612, height=792)
        page.insert_textbox(fitz.Rect(342, 170, 558, 205), "RIGHT ONE.", fontsize=10)
        page.insert_textbox(fitz.Rect(54, 220, 270, 255), "LEFT TWO.", fontsize=10)
        page.insert_textbox(fitz.Rect(342, 220, 558, 255), "RIGHT TWO.", fontsize=10)
        page.insert_textbox(fitz.Rect(54, 170, 270, 205), "LEFT ONE.", fontsize=10)
        pages = extractor.extract_pdf_pages(self.save_document(document))
        text = pages[0]
        self.assertLess(text.index("LEFT ONE"), text.index("LEFT TWO"))
        self.assertLess(text.index("LEFT TWO"), text.index("RIGHT ONE"))
        self.assertLess(text.index("RIGHT ONE"), text.index("RIGHT TWO"))

    def test_shifted_bullet_and_note_are_read_left_to_right(self):
        def line(x0, y0, x1, y1, text):
            return {
                "bbox": (x0, y0, x1, y1),
                "spans": [{"bbox": (x0, y0, x1, y1), "text": text}],
            }

        bullet_block = {
            "lines": [
                line(126, 126.3, 260, 137.3, "QUP v3 overview"),
                line(108, 127.3, 112, 135.3, "■"),
            ]
        }
        note_block = {
            "lines": [
                line(180, 206.9, 500, 217.9, "The source is available to developers"),
                line(125, 207.0, 154, 218.0, "NOTE"),
                line(165.6, 207.9, 170, 216.0, "■"),
                line(180, 218.9, 300, 229.9, "with authorized access."),
            ]
        }

        self.assertEqual(extractor.dict_block_text(bullet_block), "■ QUP v3 overview")
        self.assertEqual(
            extractor.block_to_markdown((0, 0, 0, 0, extractor.dict_block_text(bullet_block), 0, 0)),
            "• QUP v3 overview",
        )
        self.assertEqual(
            extractor.block_to_markdown((0, 0, 0, 0, extractor.dict_block_text(note_block), 0, 0)),
            "NOTE: The source is available to developers with authorized access.",
        )


if __name__ == "__main__":
    unittest.main()
