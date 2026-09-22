import os
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["VECLIB_MAXIMUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"

import json
import base64
import collections
import contextlib
import hashlib
import io
import math
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        sys.exit(1)

_ocr_engine = None

def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from pathlib import Path
            from rapidocr_onnxruntime import RapidOCR
            
            script_dir = Path(__file__).resolve().parent
            candidates = [
                script_dir / "../../models/ocr",
                script_dir / "../models/ocr",
                script_dir / "models/ocr",
                Path.cwd() / "models/ocr",
            ]
            ocr_dir = None
            for c in candidates:
                if (c / "ch_PP-OCRv3_det_infer.onnx").exists():
                    ocr_dir = c.resolve()
                    break
            
            if ocr_dir:
                _ocr_engine = RapidOCR(
                    det_model_path=str(ocr_dir / "ch_PP-OCRv3_det_infer.onnx"),
                    rec_model_path=str(ocr_dir / "ch_PP-OCRv3_rec_infer.onnx"),
                    cls_model_path=str(ocr_dir / "ch_ppocr_mobile_v2.0_cls_infer.onnx")
                )
            else:
                _ocr_engine = RapidOCR()
        except Exception:
            _ocr_engine = False
    return _ocr_engine

FIGURE_CAPTION_RE = re.compile(
    r"^\s*(?:Figure|Fig\.)\s+\d+(?:\s*[-–.]\s*\d+)*\b", re.IGNORECASE
)
FIGURE_INTRO_RE = re.compile(
    r"(?:following|below).*(?:figure|diagram)|(?:figure|diagram).*(?:shows|illustrates)",
    re.IGNORECASE,
)
TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:Table|Tab\.)\s+\d+(?:\s*[-–.]\s*\d+)*\b", re.IGNORECASE
)
NAVIGATION_TITLES = {
    "contents": "Contents",
    "table of contents": "Contents",
    "tables": "Tables",
    "list of tables": "Tables",
    "figures": "Figures",
    "list of figures": "Figures",
    "illustrations": "Figures",
    "list of illustrations": "Figures",
}
LEADER_RE = re.compile(r"(?:\s*[.·•…]\s*){3,}\s*$")
LEADER_PAGE_RE = re.compile(
    r"^(.*?)(?:\s*[.·•…]\s*){3,}\s*(\d+|[ivxlcdm]+)\s*$", re.IGNORECASE
)
BULLET_RE = re.compile(r"^\s*[•●▪■□◻◼*–—-]\s*")
TRAILING_BULLET_RE = re.compile(r"\s*[•●▪■□◻◼]\s*$")
NOTE_RE = re.compile(
    r"^\s*(NOTE|WARNING|CAUTION|IMPORTANT)\b\s*[:\-–—]?\s*",
    re.IGNORECASE,
)
TABLE_PREFIX = "[[READDOC_TABLE:"
TABLE_SUFFIX = "]]"
IMAGE_PREFIX = "[[READDOC_IMAGE:"
CODE_PREFIX = "[[READDOC_CODE:"
TOC_PREFIX = "[[READDOC_TOC:"


def line_text(line):
    """Read a PDF line left-to-right even when its content stream is unordered."""
    spans = sorted(
        line.get("spans", []),
        key=lambda span: span.get("bbox", (0, 0, 0, 0))[0],
    )
    return "".join(span.get("text", "") for span in spans).strip()


def lines_share_visual_row(first, second):
    """Treat slightly baseline-shifted labels/bullets as one visual row."""
    first_box = first.get("bbox", (0, 0, 0, 0))
    second_box = second.get("bbox", (0, 0, 0, 0))
    first_height = max(1.0, first_box[3] - first_box[1])
    second_height = max(1.0, second_box[3] - second_box[1])
    overlap = min(first_box[3], second_box[3]) - max(first_box[1], second_box[1])
    center_delta = abs(
        (first_box[1] + first_box[3]) / 2.0
        - (second_box[1] + second_box[3]) / 2.0
    )
    return (
        overlap >= min(first_height, second_height) * 0.55
        or center_delta <= max(2.25, min(first_height, second_height) * 0.22)
    )


def visual_block_text(lines):
    """Reconstruct rows geometrically, then read their components left-to-right."""
    visible = [line for line in lines if line_text(line)]
    rows = []
    for line in sorted(
            visible,
            key=lambda item: (
                item.get("bbox", (0, 0, 0, 0))[1],
                item.get("bbox", (0, 0, 0, 0))[0],
            )):
        matching_row = next(
            (row for row in reversed(rows) if any(
                lines_share_visual_row(member, line) for member in row
            )),
            None,
        )
        if matching_row is None:
            rows.append([line])
        else:
            matching_row.append(line)

    values = []
    for row in rows:
        parts = [
            line_text(line) for line in sorted(
                row, key=lambda item: item.get("bbox", (0, 0, 0, 0))[0]
            )
        ]
        value = " ".join(part for part in parts if part).strip()
        if value:
            values.append(value)
    return "\n".join(values).strip()


def dict_block_text(block):
    return visual_block_text(block.get("lines", []))


def positioned_text_blocks(page, text_dict):
    """Return text blocks, splitting creator-merged left/right column lines."""
    result = []
    middle = (page.rect.x0 + page.rect.x1) / 2.0
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = [
            line for line in block.get("lines", [])
            if any(span.get("text", "").strip() for span in line.get("spans", []))
        ]
        left = [line for line in lines if line.get("bbox")[2] <= middle + 5]
        right = [line for line in lines if line.get("bbox")[0] >= middle - 5]
        other = [line for line in lines if line not in left and line not in right]
        groups = (left, right) if left and right and not other else (lines,)
        for group in groups:
            if not group:
                continue
            text = visual_block_text(group)
            if not text:
                continue
            bbox = (
                min(line.get("bbox")[0] for line in group),
                min(line.get("bbox")[1] for line in group),
                max(line.get("bbox")[2] for line in group),
                max(line.get("bbox")[3] for line in group),
            )
            result.append((*bbox, text, block.get("number", -1), 0))
    return result


def normalize_margin_text(text):
    value = " ".join(text.lower().split())
    value = re.sub(r"\d+", "#", value)
    return value.strip(" |·-–—\t")


def detect_body_font_size(document):
    weights = collections.Counter()
    for page in document:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            bbox = block.get("bbox", (0, 0, 0, 0))
            if bbox[1] < page.rect.height * 0.08 or bbox[3] > page.rect.height * 0.92:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        weights[round(float(span.get("size", 0)) * 2) / 2] += len(text)
    return weights.most_common(1)[0][0] if weights else 10.0


def detect_repeated_margin_fragments(document):
    per_page = collections.Counter()
    per_page_images = collections.Counter()
    for page in document:
        candidates = set()
        image_candidates = set()
        for block in page.get_text("dict").get("blocks", []):
            bbox = block.get("bbox", (0, 0, 0, 0))
            if bbox[3] > page.rect.height * 0.10 and bbox[1] < page.rect.height * 0.90:
                continue
            if block.get("type") == 1 and block.get("image"):
                image_candidates.add(hashlib.sha1(block["image"]).hexdigest())
                continue
            if block.get("type") != 0:
                continue
            values = [dict_block_text(block)]
            values.extend(
                span.get("text", "")
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            )
            for value in values:
                normalized = normalize_margin_text(value)
                if len(normalized) >= 8 and sum(ch.isalpha() for ch in normalized) >= 5:
                    candidates.add(normalized)
        per_page.update(candidates)
        per_page_images.update(image_candidates)
    threshold = max(3, int(len(document) * 0.08))
    return (
        {value for value, count in per_page.items() if count >= threshold},
        {value for value, count in per_page_images.items() if count >= threshold},
    )


def is_repeated_margin_block(page, block, repeated_fragments):
    if (block[3] > page.rect.height * 0.10
            and block[1] < page.rect.height * 0.90):
        return False
    normalized = normalize_margin_text(block[4])
    return any(fragment in normalized for fragment in repeated_fragments)


def dict_block_style(block):
    spans = [
        span for line in block.get("lines", []) for span in line.get("spans", [])
        if span.get("text", "").strip()
    ]
    if not spans:
        return {"size": 0.0, "bold_ratio": 0.0, "monospace": False}
    total = sum(max(1, len(span.get("text", "").strip())) for span in spans)
    bold = sum(
        max(1, len(span.get("text", "").strip())) for span in spans
        if (span.get("flags", 0) & 16)
        or any(token in span.get("font", "").lower() for token in ("bold", "heavy", "-bd"))
    )
    monospace = sum(
        max(1, len(span.get("text", "").strip())) for span in spans
        if (span.get("flags", 0) & 8)
        or any(token in span.get("font", "").lower() for token in ("mono", "courier", "menlo"))
    )
    return {
        "size": max(float(span.get("size", 0)) for span in spans),
        "bold_ratio": bold / total,
        "monospace": monospace / total > 0.55,
    }


def normalize_list_block(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if BULLET_RE.match(lines[0]):
        first = BULLET_RE.sub("", lines[0], count=1).strip()
        rest = " ".join(lines[1:]).strip()
        content = " ".join(part for part in (first, rest) if part)
        return f"• {content}" if content else ""
    # Some generators emit a bullet as a separate, slightly shifted PDF line.
    # Keep this fallback for malformed files where no reliable bbox is available.
    if TRAILING_BULLET_RE.search(lines[-1]):
        lines[-1] = TRAILING_BULLET_RE.sub("", lines[-1]).strip()
        content = " ".join(line for line in lines if line).strip()
        return f"• {content}" if content else ""
    return ""


def normalize_note_block(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    match = NOTE_RE.match(lines[0])
    if not match:
        return ""
    label = match.group(1).upper()
    first = NOTE_RE.sub("", lines[0], count=1)
    first = BULLET_RE.sub("", first, count=1).strip()
    content = " ".join(part for part in (first, *lines[1:]) if part).strip()
    content = TRAILING_BULLET_RE.sub("", content).strip()
    return f"{label}: {content}" if content else label


def block_to_markdown(block, styled_block=None, body_font_size=10.0):
    text = block[4].strip()
    if not text:
        return ""
    lines = text.split("\n")

    note_text = normalize_note_block(text)
    if note_text:
        return note_text

    list_text = normalize_list_block(text)
    if list_text:
        return list_text

    style = dict_block_style(styled_block or {})
    short_heading = len(" ".join(text.split())) < 160 and len(lines) <= 3
    caption = FIGURE_CAPTION_RE.match(text) or TABLE_CAPTION_RE.match(text)
    terminal_sentence = text.rstrip().endswith((".", ",", ";"))
    styled_heading = (
        style["size"] >= max(body_font_size + 1.0, body_font_size * 1.14)
        or (style["bold_ratio"] >= 0.62 and style["size"] >= body_font_size * 0.97)
    )
    numbered_heading = bool(
        re.match(r"^\d+(?:\.\d+)+\s+\S", text)
        or re.match(r"^\d+\s+[A-Z]", text)
    )
    if (short_heading and not caption and not terminal_sentence
            and (styled_heading or numbered_heading)):
        return f"### {' '.join(line.strip() for line in lines if line.strip())}"

    if len(lines) == 1 and len(text) < 70 and not text.endswith((".", ":", ",", ";")):
        if text.isupper() or text.istitle():
            return f"### {text}"

    is_code = any(
        line.startswith("KBUILD_") or "?=" in line or ":=" in line or "${" in line
        for line in lines
    ) or style["monospace"]
    if is_code:
        return text
    return " ".join(line.strip() for line in lines if line.strip())


def encode_table(rows):
    normalized = [
        ["" if cell is None else str(cell).strip() for cell in row]
        for row in rows
    ]
    payload = json.dumps(normalized, ensure_ascii=False).encode("utf-8")
    return TABLE_PREFIX + base64.b64encode(payload).decode("ascii") + TABLE_SUFFIX


def encode_image(block):
    payload = json.dumps(
        {
            "ext": block.get("ext", "png"),
            "width": block.get("width", 0),
            "height": block.get("height", 0),
            "data": base64.b64encode(block.get("image", b"")).decode("ascii"),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    return IMAGE_PREFIX + base64.b64encode(payload).decode("ascii") + TABLE_SUFFIX


def encode_rendered_region(page, bbox, scale=2.25):
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale), clip=fitz.Rect(bbox), alpha=False
    )
    return encode_image({
        "ext": "png",
        "width": pixmap.width,
        "height": pixmap.height,
        "image": pixmap.tobytes("png"),
    })


def encode_code(text):
    return CODE_PREFIX + base64.b64encode(text.encode("utf-8")).decode("ascii") + TABLE_SUFFIX


def encode_toc(rows):
    payload = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    return TOC_PREFIX + base64.b64encode(payload).decode("ascii") + TABLE_SUFFIX


def detect_navigation_title(page, text_dict=None):
    text_dict = text_dict or page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        if bbox[1] < page.rect.height * 0.07 or bbox[1] > page.rect.height * 0.25:
            continue
        value = " ".join(dict_block_text(block).split()).strip(" :")
        canonical = NAVIGATION_TITLES.get(value.lower())
        if canonical:
            return canonical
    return ""


def strip_leader_dots(value):
    return LEADER_RE.sub("", " ".join(value.split())).strip(" .·•…\t")


def extract_navigation_rows(page, navigation_title, text_dict=None):
    text_dict = text_dict or page.get_text("dict")
    grouped = {}
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            if (line.get("bbox", (0, 0, 0, 0))[1] < page.rect.height * 0.08
                    or line.get("bbox")[1] > page.rect.height * 0.90):
                continue
            key = int(round(line["bbox"][1] * 2.0))
            grouped.setdefault(key, []).extend(line.get("spans", []))

    rows = []
    for key in sorted(grouped):
        spans = sorted(grouped[key], key=lambda span: span.get("bbox", (0, 0, 0, 0))[0])
        page_number = ""
        title_parts = []
        is_bold = False
        for span in spans:
            value = span.get("text", "").strip()
            if not value:
                continue
            x0 = span.get("bbox", (0, 0, 0, 0))[0]
            if (x0 > page.rect.width * 0.72
                    and re.fullmatch(r"\d+|[ivxlcdm]+", value, re.IGNORECASE)):
                page_number = value
                continue
            title_parts.append(value)
            is_bold = is_bold or bool(span.get("flags", 0) & 16)

        combined = " ".join(title_parts).strip()
        if not page_number:
            trailing = LEADER_PAGE_RE.match(combined)
            if trailing:
                combined, page_number = trailing.groups()
        if not page_number:
            continue

        if navigation_title == "Contents":
            match = re.match(
                r"^((?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*))\s+(.+)$", combined
            )
        elif navigation_title == "Tables":
            match = re.match(
                r"^((?:Table|Tab\.)\s+\d+(?:\s*[-–.]\s*\d+)*):?\s+(.+)$",
                combined, re.IGNORECASE,
            )
        else:
            match = re.match(
                r"^((?:Figure|Fig\.)\s+\d+(?:\s*[-–.]\s*\d+)*):?\s+(.+)$",
                combined, re.IGNORECASE,
            )
        if not match:
            continue
        section_number, title = match.groups()
        title = strip_leader_dots(title)
        if not title:
            continue
        level = section_number.count(".") if navigation_title == "Contents" else 0
        rows.append({
            "number": section_number,
            "title": title,
            "page": page_number,
            "level": level,
            "bold": is_bold,
        })
    return rows


def intersects_table(block, table_bbox):
    block_rect = fitz.Rect(block[:4])
    table_rect = fitz.Rect(table_bbox)
    intersection = block_rect & table_rect
    return (
        not intersection.is_empty
        and block_rect.get_area() > 0
        and intersection.get_area() / block_rect.get_area() > 0.20
    )


def block_intersection_ratio(block, bbox):
    block_rect = fitz.Rect(block[:4])
    intersection = block_rect & fitz.Rect(bbox)
    if intersection.is_empty or block_rect.get_area() <= 0:
        return 0.0
    return intersection.get_area() / block_rect.get_area()


def drawing_centers_inside(drawings, bbox):
    region = fitz.Rect(bbox)
    count = 0
    for drawing in drawings:
        rect = fitz.Rect(drawing.get("rect"))
        center = fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)
        if region.contains(center):
            count += 1
    return count


def find_vector_figure_regions(page, blocks, drawings=None):
    """Locate framed/vector figures that do not exist as PDF image objects."""
    if drawings is None:
        drawings = page.get_drawings()
    if not drawings:
        return []

    regions = []
    page_rect = page.rect
    captions = [block for block in blocks if FIGURE_CAPTION_RE.match(block[4].strip())]
    for caption in captions:
        caption_rect = fitz.Rect(caption[:4])
        candidates = []
        for drawing in drawings:
            rect = fitz.Rect(drawing.get("rect"))
            gap = caption_rect.y0 - rect.y1
            if (rect.width < page_rect.width * 0.25 or rect.height < 18
                    or gap < -3 or gap > 55):
                continue
            density = drawing_centers_inside(drawings, rect)
            candidates.append((rect.get_area(), density, rect))

        if candidates:
            # The outer frame normally has the largest area and contains all paths.
            region = max(candidates, key=lambda item: (item[0], item[1]))[2]
        else:
            intro_blocks = [
                block for block in blocks
                if block[3] < caption_rect.y0
                and caption_rect.y0 - block[3] < 450
                and FIGURE_INTRO_RE.search(" ".join(block[4].split()))
            ]
            top = max(page_rect.y0 + page_rect.height * 0.08, caption_rect.y0 - 320)
            if intro_blocks:
                intro = max(intro_blocks, key=lambda block: block[3])
                top = intro[3] + 4
            relevant = [
                fitz.Rect(drawing.get("rect")) for drawing in drawings
                if drawing.get("rect").y0 >= top - 3
                and drawing.get("rect").y1 <= caption_rect.y0 + 2
                and (drawing.get("rect").width > 2 or drawing.get("rect").height > 2)
            ]
            if len(relevant) < 3:
                continue
            region = fitz.Rect(
                min(rect.x0 for rect in relevant), min(rect.y0 for rect in relevant),
                max(rect.x1 for rect in relevant), max(rect.y1 for rect in relevant),
            )
            if region.width < page_rect.width * 0.20 or region.height < 15:
                continue

        region = fitz.Rect(
            max(page_rect.x0, region.x0 - 1), max(page_rect.y0, region.y0 - 1),
            min(page_rect.x1, region.x1 + 1), min(page_rect.y1, region.y1 + 1),
        )
        if any((region & old).get_area() > min(region.get_area(), old.get_area()) * 0.8
               for old in regions):
            continue
        regions.append(region)
    return regions


def find_code_boxes(page, table_bboxes, excluded_bboxes=(), drawings=None):
    boxes = []
    if drawings is None:
        drawings = page.get_drawings()
    for drawing in drawings:
        rect = drawing.get("rect")
        fill = drawing.get("fill")
        if not rect or not fill or len(fill) < 3:
            continue
        is_light_gray = all(0.88 <= channel <= 0.99 for channel in fill[:3])
        is_large_box = rect.width > 200 and rect.height > 25
        overlaps_table = any((fitz.Rect(rect) & fitz.Rect(bbox)).get_area() > rect.get_area() * 0.5
                             for bbox in table_bboxes)
        overlaps_excluded = any(
            (fitz.Rect(rect) & fitz.Rect(bbox)).get_area() > rect.get_area() * 0.5
            for bbox in excluded_bboxes
        )
        if is_light_gray and is_large_box and not overlaps_table and not overlaps_excluded:
            boxes.append(tuple(rect))
    return boxes


def overlaps_region(bbox, regions, threshold=0.25):
    rect = fitz.Rect(bbox)
    if rect.get_area() <= 0:
        return False
    return any((rect & fitz.Rect(region)).get_area() / rect.get_area() > threshold
               for region in regions)


def order_layout_items(items, page_rect):
    """Order positioned items and preserve common two-column reading flow."""
    if len(items) < 2:
        return items
    items = sorted(items, key=lambda item: (item[0].y0, item[0].x0))
    content_left = min(item[0].x0 for item in items)
    content_right = max(item[0].x1 for item in items)
    content_width = max(1.0, content_right - content_left)
    middle = (content_left + content_right) / 2.0
    separators = [
        item for item in items
        if item[0].x0 < middle < item[0].x1
        and item[0].width >= content_width * 0.55
    ]

    def order_group(group):
        if len(group) < 2:
            return sorted(group, key=lambda item: (item[0].y0, item[0].x0))
        left = [item for item in group if item[0].x1 <= middle + 5]
        right = [item for item in group if item[0].x0 >= middle - 5]
        other = [item for item in group if item not in left and item not in right]
        if left and right and not other:
            return (sorted(left, key=lambda item: (item[0].y0, item[0].x0))
                    + sorted(right, key=lambda item: (item[0].y0, item[0].x0)))
        return sorted(group, key=lambda item: (item[0].y0, item[0].x0))

    if not separators:
        return order_group(items)
    ordered = []
    remaining = list(items)
    for separator in sorted(separators, key=lambda item: item[0].y0):
        if separator not in remaining:
            continue
        before = [
            item for item in remaining if item is not separator
            and item[0].y1 <= separator[0].y0 + 2
        ]
        ordered.extend(order_group(before))
        remaining = [item for item in remaining if item not in before]
        ordered.append(separator)
        remaining.remove(separator)
    ordered.extend(order_group(remaining))
    return ordered


def split_lines_into_paragraphs(lines, angle):
    """Split lines of a text block into separate paragraphs based on:
    1. Blank / empty lines.
    2. Vertical spacing gaps between lines (gap > 0.40 * line_height).
    3. Short ending lines with terminal punctuation followed by left-margin start.
    """
    if not lines or abs(angle) > 5:
        return [lines] if lines else []

    valid_lines = [l for l in lines if "".join(s.get("text", "") for s in l.get("spans", [])).strip()]
    if not valid_lines:
        return []

    min_x0 = min(l["bbox"][0] for l in valid_lines)
    max_x1 = max(l["bbox"][2] for l in valid_lines)
    block_w = max_x1 - min_x0

    paras = []
    curr = []
    prev_line = None

    for l in lines:
        txt = "".join(s.get("text", "") for s in l.get("spans", [])).strip()
        if not txt:
            if curr:
                paras.append(curr)
                curr = []
            prev_line = None
            continue

        if prev_line is not None:
            prev_txt = "".join(s.get("text", "") for s in prev_line.get("spans", [])).strip()
            prev_y0, prev_y1 = prev_line["bbox"][1], prev_line["bbox"][3]
            curr_y0, curr_y1 = l["bbox"][1], l["bbox"][3]
            line_h = max(1.0, prev_y1 - prev_y0)
            gap = curr_y0 - prev_y1
            line_step = curr_y0 - prev_y0

            is_gap = (gap > max(3.5, line_h * 0.40) or line_step > line_h * 1.40)

            is_short_terminal = False
            if prev_txt and prev_txt[-1] in ".!?:)\"\x27”’":
                prev_w = prev_line["bbox"][2] - min_x0
                right_gap = max_x1 - prev_line["bbox"][2]
                if prev_w < block_w * 0.85 and right_gap >= 25.0 and l["bbox"][0] <= min_x0 + 20.0:
                    is_short_terminal = True

            if is_gap or is_short_terminal:
                if curr:
                    paras.append(curr)
                    curr = []

        curr.append(l)
        prev_line = l

    if curr:
        paras.append(curr)
    return paras


def extract_pdf_pages(filepath, target_page=None, include_images=False, password=None):
    try:
        document = fitz.open(filepath)
    except Exception as exc:
        raise RuntimeError(f"Error opening PDF: {exc}") from exc

    if document.needs_pass or (document.is_encrypted and password):
        if document.needs_pass and not password:
            raise RuntimeError("PASSWORD_REQUIRED")
        if password:
            auth = document.authenticate(password)
            if auth == 0 and document.needs_pass:
                raise RuntimeError("INCORRECT_PASSWORD")

    pages = []
    try:
        body_font_size = detect_body_font_size(document)
        repeated_fragments, repeated_margin_images = (
            detect_repeated_margin_fragments(document)
            if len(document) <= 15 else (set(), set())
        )
        page_indices = range(len(document))
        if target_page is not None:
            target_idx = max(0, min(len(document) - 1, target_page - 1))
            page_indices = [target_idx]

        for page_idx in page_indices:
            page = document[page_idx]
            text_dict = page.get_text("dict", sort=False)
            
            layout_blocks = []
            block_id = 0
            for b in text_dict.get("blocks", []):
                if b.get("type") != 0:
                    continue
                lines = b.get("lines", [])
                if not lines:
                    continue
                dir_v = lines[0].get("dir", (1.0, 0.0)) if lines else (1.0, 0.0)
                dx, dy = dir_v
                angle_deg = round(math.degrees(math.atan2(dy, dx)))
                if angle_deg <= -180:
                    angle_deg += 360
                elif angle_deg > 180:
                    angle_deg -= 360

                if abs(angle_deg) <= 3:
                    angle = 0
                elif abs(angle_deg - 90) <= 3:
                    angle = 90
                elif abs(angle_deg + 90) <= 3:
                    angle = -90
                elif abs(abs(angle_deg) - 180) <= 3:
                    angle = 180
                else:
                    angle = angle_deg

                # Split block into distinct paragraphs to preserve original PDF paragraph separation
                para_groups = split_lines_into_paragraphs(lines, angle)
                valid_block_lines = [l for l in lines if "".join(s.get("text", "") for s in l.get("spans", [])).strip()]
                b_min_x0 = min(l["bbox"][0] for l in valid_block_lines) if valid_block_lines else b["bbox"][0]
                b_max_x1 = max(l["bbox"][2] for l in valid_block_lines) if valid_block_lines else b["bbox"][2]
                b_width = b_max_x1 - b_min_x0

                for para_lines in para_groups:
                    text = visual_block_text(para_lines).strip()
                    if not text:
                        continue

                    spans = [s for l in para_lines for s in l.get("spans", []) if s.get("text", "").strip()]
                    avg_size = sum(s.get("size", 11.0) for s in spans) / max(1, len(spans))
                    is_bold = any((s.get("flags", 0) & 2) != 0 or "bold" in s.get("font", "").lower() for s in spans)
                    is_heading = is_bold and avg_size >= 12.5

                    hex_color = "#111827"
                    if spans:
                        c = spans[0].get("color", 0)
                        if isinstance(c, int):
                            r = (c >> 16) & 0xFF
                            g = (c >> 8) & 0xFF
                            b_col = c & 0xFF
                            if r > 240 and g > 240 and b_col > 240:
                                hex_color = "#FFFFFF"
                            elif r > 10 or g > 10 or b_col > 10:
                                hex_color = f"#{r:02X}{g:02X}{b_col:02X}"

                    p_x0 = min(l["bbox"][0] for l in para_lines)
                    p_y0 = min(l["bbox"][1] for l in para_lines)
                    p_x1 = max(l["bbox"][2] for l in para_lines)
                    p_y1 = max(l["bbox"][3] for l in para_lines)

                    # For multi-line body columns (width > 150 pt), align left & right margins to column
                    # so translations wrap naturally without being artificially cut off on 1-line paragraphs
                    if abs(angle) <= 5 and b_width > 150:
                        if abs(p_x0 - b_min_x0) <= 20:
                            p_x0 = b_min_x0
                        p_x1 = max(p_x1, b_max_x1)

                    bbox = [round(p_x0, 2), round(p_y0, 2), round(p_x1, 2), round(p_y1, 2)]
                    bw = bbox[2] - bbox[0]
                    bh = bbox[3] - bbox[1]

                    # Watermark detection
                    is_diagonal = (abs(angle) > 10 and abs(angle) < 80) or (abs(angle) > 100 and abs(angle) < 170)
                    watermark_keywords = ("internal use", "confidential", "proprietary", "draft", "watermark", "sample", "strictly private", "hsptek", "do not distribute")
                    text_lower = text.lower()
                    is_watermark_text = any(kw in text_lower for kw in watermark_keywords)
                    is_huge_sparse = (bw > page.rect.width * 0.35 and bh > page.rect.height * 0.25 and (is_diagonal or len(text.split()) < 15))
                    is_watermark = is_diagonal or is_watermark_text or is_huge_sparse

                    layout_blocks.append({
                        "id": block_id,
                        "bbox": bbox,
                        "text": text,
                        "font_size": round(avg_size, 1),
                        "color": hex_color,
                        "angle": angle,
                        "is_heading": is_heading,
                        "is_bold": is_bold,
                        "is_watermark": is_watermark,
                    })
                    block_id += 1

            # 2. OCR text inside embedded diagram images (only for single page or small docs)
            ocr = get_ocr_engine() if (target_page is not None or len(document) <= 5) else None
            should_run_image_ocr = ocr is not None
            if should_run_image_ocr:
                for b in text_dict.get("blocks", []):
                    if b.get("type") == 1 and b.get("image"):
                        img_bbox = fitz.Rect(b["bbox"])
                        # Only OCR diagrams/flowcharts (skip tiny icons or full-page backgrounds)
                        if img_bbox.width < 60 or img_bbox.height < 40:
                            continue
                        if img_bbox.width > page.rect.width * 0.98 and img_bbox.height > page.rect.height * 0.98:
                            continue
                        img_bytes = b["image"]
                        try:
                            ocr_res, _ = ocr(img_bytes)
                            if ocr_res:
                                pix = fitz.Pixmap(img_bytes)
                                w, h = pix.width, pix.height
                                for item in ocr_res:
                                    pts, ocr_text, score = item
                                    if float(score) < 0.40 or len(ocr_text.strip()) == 0:
                                        continue
                                    ox0 = min(p[0] for p in pts)
                                    oy0 = min(p[1] for p in pts)
                                    ox1 = max(p[0] for p in pts)
                                    oy1 = max(p[1] for p in pts)
                                    px0 = img_bbox.x0 + (ox0 / w) * img_bbox.width
                                    py0 = img_bbox.y0 + (oy0 / h) * img_bbox.height
                                    px1 = img_bbox.x0 + (ox1 / w) * img_bbox.width
                                    py1 = img_bbox.y0 + (oy1 / h) * img_bbox.height
                                    
                                    f_size = max(7.5, min(24.0, (py1 - py0) * 0.85))
                                    layout_blocks.append({
                                        "id": block_id,
                                        "bbox": [round(px0, 2), round(py0, 2), round(px1, 2), round(py1, 2)],
                                        "text": ocr_text.strip(),
                                        "font_size": round(f_size, 1),
                                        "color": "#111827",
                                        "angle": 0,
                                        "is_heading": False,
                                        "is_bold": False,
                                    })
                                    block_id += 1
                        except Exception:
                            pass

            pages.append({
                "page_index": page_idx,
                "width": round(page.rect.width, 2),
                "height": round(page.rect.height, 2),
                "text": "\n\n".join(b["text"] for b in layout_blocks),
                "blocks": layout_blocks,
            })
    finally:
        document.close()
    return pages


def extract_pdf_to_markdown(filepath, password=None):
    pages = extract_pdf_pages(filepath, password=password)
    texts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in pages]
    return "\n\n".join(
        text + f"\n\n— TRANG {index + 1} —" for index, text in enumerate(texts)
    )


def main():
    arguments = sys.argv[1:]
    json_mode = False
    target_page = None
    password = None
    clean_args = []
    i = 0
    while i < len(arguments):
        if arguments[i] == "--json":
            json_mode = True
            i += 1
        elif arguments[i] == "--page" and i + 1 < len(arguments):
            try:
                target_page = int(arguments[i + 1])
            except ValueError:
                pass
            i += 2
        elif arguments[i] in ("--password", "-p") and i + 1 < len(arguments):
            password = arguments[i + 1]
            i += 2
        else:
            clean_args.append(arguments[i])
            i += 1

    if not clean_args:
        print("Usage: extract_pdf.py [--json] [--page <N>] [--password <pwd>] <pdf_file>", file=sys.stderr)
        return 1
    try:
        pages = extract_pdf_pages(clean_args[0], target_page=target_page, password=password)
    except Exception as exc:
        err_msg = str(exc)
        if json_mode:
            print(json.dumps({"error": err_msg, "pages": []}, ensure_ascii=False))
        else:
            print(err_msg, file=sys.stderr)
        return 1
    if json_mode:
        print(json.dumps({"pages": pages}, ensure_ascii=False))
    else:
        texts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in pages]
        print("\n\n".join(
            text + f"\n\n— TRANG {index + 1} —" for index, text in enumerate(texts)
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
