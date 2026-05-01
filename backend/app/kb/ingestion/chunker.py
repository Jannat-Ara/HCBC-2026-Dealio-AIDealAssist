import re


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    # Preserve newlines as sentence boundaries before normalising spaces.
    # This keeps CSV rows and paragraph breaks intact across chunks.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    normalized = "\n".join(line for line in lines if line)
    if not normalized:
        return []

    words = normalized.split()
    if len(words) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    for start in range(0, len(words), step):
        chunk_words = words[start : start + chunk_size]
        if not chunk_words:
            continue
        chunks.append(" ".join(chunk_words).strip())
        if start + chunk_size >= len(words):
            break
    return chunks
