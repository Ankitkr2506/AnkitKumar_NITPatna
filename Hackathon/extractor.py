import requests
from io import BytesIO
from PIL import Image
import pytesseract
from pytesseract import Output

# Point to your local Tesseract installation
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# =========================================================
# Image Downloader
# =========================================================
def load_image_from_url(image_url: str) -> Image.Image:
    """Fetch an image from the internet and return as a PIL object."""
    session_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    resp = requests.get(image_url, headers=session_headers, timeout=20)
    resp.raise_for_status()

    byte_stream = BytesIO(resp.content)
    return Image.open(byte_stream).convert("RGB")


# =========================================================
# OCR Helpers
# =========================================================
def text_from_image(img: Image.Image) -> str:
    """Simple OCR wrapper returning plain text."""
    return pytesseract.image_to_string(img)


def text_with_boxes(img: Image.Image):
    """OCR that returns bounding boxes for each token."""
    return pytesseract.image_to_data(img, output_type=Output.DICT)


# =========================================================
# Convert OCR output into grouped rows
# =========================================================
def group_tokens_by_line(ocr_data: dict, threshold: int = 12):
    """
    Group detected words into horizontal lines according to their Y positions.
    Returns: list of rows → each row is a list of (x, text)
    """
    rows = []
    current_line = []
    previous_y = None

    for x, y, token in zip(ocr_data["left"], ocr_data["top"], ocr_data["text"]):
        cleaned = token.strip()
        if not cleaned:
            continue

        if previous_y is None or abs(y - previous_y) <= threshold:
            current_line.append((x, cleaned))
        else:
            rows.append(sorted(current_line, key=lambda v: v[0]))
            current_line = [(x, cleaned)]

        previous_y = y

    if current_line:
        rows.append(sorted(current_line, key=lambda v: v[0]))

    return rows


# =========================================================
# Detect table header + infer column split boundaries
# =========================================================
def find_table_header(rows):
    """
    Identify the row that contains headers like Description, Qty, Rate, Amount.
    Also estimates column cut points based on x-positions.
    """
    header_index = None
    header_row = None

    for idx, row in enumerate(rows):
        merged = " ".join(word for _, word in row).lower()

        if ("description" in merged and "qty" in merged and "rate" in merged) or \
           ("qty" in merged and ("gross" in merged or "amount" in merged)):
            header_index = idx
            header_row = row
            break

    if header_row is None:
        return None, None

    positions = {"desc": None, "qty": None, "rate": None, "amt": None}

    for x, word in header_row:
        w = word.lower()
        if "desc" in w:
            positions["desc"] = x
        elif "qty" in w:
            positions["qty"] = x
        elif "rate" in w:
            positions["rate"] = x
        elif "amount" in w or "gross" in w or "net" in w:
            positions["amt"] = x

    # Collect existing x-coordinates only
    xs = [v for v in positions.values() if v is not None]
    xs.sort()

    boundaries = {}
    if len(xs) > 1:
        boundaries["desc_end"] = (xs[0] + xs[1]) / 2
    if len(xs) > 2:
        boundaries["qty_end"] = (xs[1] + xs[2]) / 2
    if len(xs) > 3:
        boundaries["rate_end"] = (xs[2] + xs[3]) / 2

    return header_index, boundaries


# =========================================================
# Utility Conversions
# =========================================================
def as_number(value: str):
    try:
        return float(value.replace(",", ""))
    except:
        return None


def strip_serial(desc: str) -> str:
    """Remove serial number from description if present."""
    parts = desc.split()
    if parts and parts[0].isdigit():
        return " ".join(parts[1:])
    return desc


# =========================================================
# Parse line-items
# =========================================================
def extract_line_items(rows, header_row_idx, boundaries):
    """
    Convert each parsed row into structured invoice line items.
    """
    if header_row_idx is None or boundaries is None:
        return []

    items = []

    for row in rows[header_row_idx + 1:]:
        row_text_full = " ".join(word for _, word in row).lower()

        # stop markers
        if "category total" in row_text_full:
            continue
        if "printed" in row_text_full:
            break

        desc_col = []
        qty_col = []
        rate_col = []
        amt_col = []

        for x, token in row:
            if x < boundaries.get("desc_end", 99999):
                desc_col.append(token)
            elif x < boundaries.get("qty_end", 99999):
                qty_col.append(token)
            elif x < boundaries.get("rate_end", 99999):
                rate_col.append(token)
            else:
                amt_col.append(token)

        description = strip_serial(" ".join(desc_col).strip())
        quantity = as_number("".join(qty_col))
        rate_val = as_number("".join(rate_col))

        amount_val = None
        # First numeric token in amount bucket is used
        for tok in amt_col:
            num = as_number(tok)
            if num is not None:
                amount_val = num
                break

        if not description or amount_val is None:
            continue

        items.append({
            "item_name": description,
            "item_quantity": quantity if quantity else 1.0,
            "item_rate": rate_val if rate_val else amount_val,
            "item_amount": amount_val
        })

    return items


# =========================================================
# Public function used by FastAPI
# =========================================================
def extract_bill_info_from_url(image_url: str) -> dict:
    """
    Main pipeline:
    1. Download image
    2. OCR + bounding boxes
    3. Group into rows
    4. Locate header + parse line items
    """
    img = load_image_from_url(image_url)
    ocr_data = text_with_boxes(img)

    rows = group_tokens_by_line(ocr_data)
    header_idx, bounds = find_table_header(rows)

    line_items = extract_line_items(rows, header_idx, bounds)

    return {
        "is_success": True,
        "data": {
            "pagewise_line_items": [
                {
                    "page_no": "1",
                    "bill_items": line_items
                }
            ],
            "total_item_count": len(line_items),
            "reconciled_amount": sum(item["item_amount"] for item in line_items)
        }
    }
