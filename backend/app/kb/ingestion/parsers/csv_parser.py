import csv
import io

from app.kb.ingestion.parsers.txt_parser import parse_txt


def parse_csv(content: bytes) -> str:
    """
    Convert CSV to a line-per-row text format that the chunker and LLM can read.
    Format: COLUMNS: col1, col2, col3  (header summary line)
            col1_val | col2_val | col3_val  (one line per data row)
    The header summary is prepended so the LLM always knows what each column means.
    """
    text = parse_txt(content)
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return ""

    # First non-empty row is treated as the header
    header = [cell.strip() for cell in rows[0] if cell.strip()]
    header_line = "COLUMNS: " + ", ".join(header) if header else ""

    data_lines = []
    for row in rows[1:]:
        cleaned = [cell.strip() for cell in row]
        # Zip with header names so each cell is labelled: "Column: value"
        if header:
            labelled = [f"{h}: {v}" for h, v in zip(header, cleaned) if v]
        else:
            labelled = [v for v in cleaned if v]
        if labelled:
            data_lines.append(" | ".join(labelled))

    parts = []
    if header_line:
        parts.append(header_line)
    parts.extend(data_lines)
    return "\n".join(parts)
