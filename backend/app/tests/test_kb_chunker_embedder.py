from app.kb.ingestion.chunker import chunk_text
from app.kb.ingestion.embedder import VECTOR_DIMENSIONS, embed_text, vector_to_pgvector
from app.kb.ingestion.pipeline import document_to_chunks


def test_chunk_text_splits_with_overlap() -> None:
    text = " ".join(f"word{i}" for i in range(20))
    chunks = chunk_text(text, chunk_size=8, overlap=2)
    assert len(chunks) == 3
    assert chunks[0].startswith("word0")
    assert "word6" in chunks[1]


def test_embed_text_returns_768_dimension_normalized_vector() -> None:
    vector = embed_text("finance policy invoice approval")
    assert len(vector) == VECTOR_DIMENSIONS
    assert any(value != 0 for value in vector)
    assert vector_to_pgvector(vector).startswith("[")


def test_document_to_chunks_parses_txt() -> None:
    file_type, chunks = document_to_chunks("policy.txt", b"Finance policy requires approval.")
    assert file_type == "txt"
    assert chunks == ["Finance policy requires approval."]


def test_document_to_chunks_rejects_unsupported_file_type() -> None:
    try:
        document_to_chunks("policy.exe", b"bad")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("Expected unsupported file type error")
