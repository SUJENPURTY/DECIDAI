from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ANALYSIS_CHARS = 24_000
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


class DocumentExtractionError(ValueError):
    pass


def validate_document(filename: str | None, content: bytes) -> str:
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentExtractionError("Unsupported file type. Please upload a PDF, DOCX, or TXT file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DocumentExtractionError("The supporting document exceeds the 10 MB maximum size.")
    return extension


def extract_text(filename: str | None, content: bytes) -> tuple[str, str | None]:
    extension = validate_document(filename, content)
    try:
        if extension == ".pdf":
            reader = PdfReader(BytesIO(content))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if not text.strip():
                raise DocumentExtractionError(
                    "No readable text was detected in this document. Please upload a text-based PDF, DOCX, or TXT file."
                )
        elif extension == ".docx":
            document = Document(BytesIO(content))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        else:
            text = content.decode("utf-8", errors="replace")
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError("We could not read this document. Please upload a readable PDF, DOCX, or TXT file.") from exc

    text = text.strip()
    if not text:
        raise DocumentExtractionError("The document is empty or contains no readable text. Please upload another file.")
    if len(text) > MAX_ANALYSIS_CHARS:
        return text[:MAX_ANALYSIS_CHARS], "Only the first portion of the document was analysed because the file exceeded the text processing limit."
    return text, None
