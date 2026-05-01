from pathlib import Path

from app.kb.ingestion.chunker import chunk_text
from app.kb.ingestion.parsers import parse_csv, parse_docx, parse_pdf, parse_txt

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx", ".csv"}


def parse_document(filename: str, content: bytes) -> tuple[str, str]:
    extension = Path(filename).suffix.lower()
    if extension == ".txt":
        return parse_txt(content), "txt"
    if extension == ".pdf":
        return parse_pdf(content), "pdf"
    if extension == ".docx":
        return parse_docx(content), "docx"
    if extension == ".csv":
        return parse_csv(content), "csv"
    raise ValueError(f"Unsupported file type '{extension}'. Supported: txt, pdf, docx, csv")


def document_to_chunks(filename: str, content: bytes) -> tuple[str, list[str]]:
    parsed_text, file_type = parse_document(filename, content)
    chunks = chunk_text(parsed_text)
    if not chunks:
        raise ValueError("Document did not contain any readable text")
    return file_type, chunks
