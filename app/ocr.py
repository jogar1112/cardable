"""OCR seam.

extract_text() is the clean interface the intake flow calls. v1 ships a
STUB engine: it returns an empty draft and says so honestly. Drop in a real
engine (tesseract / cloud vision) behind this function without touching
callers. The image is always the card; OCR only drafts the text layer,
which the player confirms or corrects.
"""


def extract_text(image_path):
    return {
        "engine": "stub",
        "name": "",
        "text": "",
        "primary": "",
        "confidence": 0.0,
        "note": "OCR engine not installed in v1 -- type or correct the fields; the image is already playable.",
    }
