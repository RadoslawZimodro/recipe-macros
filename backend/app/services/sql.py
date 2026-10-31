from pathlib import Path

from sqlalchemy import TextClause, text

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def load_sql(name: str) -> TextClause:
    """Load a query from app/sql/<name>. Read on every call so edits show up during development."""
    return text((SQL_DIR / name).read_text(encoding="utf-8"))


def like_pattern(term: str | None) -> str | None:
    """Turn a search term into an ILIKE '%term%' pattern, escaping LIKE wildcards in the term."""
    if term is None:
        return None
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
