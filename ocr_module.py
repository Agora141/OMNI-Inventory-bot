import logging

import easyocr

from config import OCR_LANGUAGES, OCR_USE_GPU

logger = logging.getLogger(__name__)

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        logger.info("initializing EasyOCR (gpu=%s)...", OCR_USE_GPU)
        _reader = easyocr.Reader(OCR_LANGUAGES, gpu=OCR_USE_GPU)
    return _reader


def extract_text_from_image(image_path):
    reader  = _get_reader()
    results = reader.readtext(image_path, detail=1, paragraph=False)

    lines = [text for (_bbox, text, conf) in results if conf >= 0.1]
    return " ".join(lines)
