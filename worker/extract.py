import io
import logging
import re
from dataclasses import dataclass

import fitz  # PyMuPDF

from config import settings

log = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Problema permanente com o arquivo (não adianta tentar de novo)."""


@dataclass
class PageText:
    number: int  # 1-based
    text: str


def normalize(text: str) -> str:
    text = text.replace("\x00", "")  # Postgres rejeita NUL em TEXT
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ocr(page) -> str:
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi=200)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(image, lang=settings.ocr_langs)
    except Exception:
        log.warning("OCR falhou na página %s", page.number + 1, exc_info=True)
        return ""


def extract_pages(path: str) -> list[PageText]:
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":  # o Content-Type vem do cliente; conferimos o conteúdo
            raise ExtractionError("O arquivo não é um PDF válido")
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise ExtractionError("Não foi possível abrir o PDF") from exc
    with doc:
        if doc.needs_pass:
            raise ExtractionError("PDF protegido por senha")
        if doc.page_count > settings.max_pages:
            raise ExtractionError(f"PDF com mais de {settings.max_pages} páginas")
        pages: list[PageText] = []
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) < settings.ocr_min_chars and settings.ocr_enabled:
                text = _ocr(page).strip() or text
            pages.append(PageText(index, normalize(text)))
    return pages
