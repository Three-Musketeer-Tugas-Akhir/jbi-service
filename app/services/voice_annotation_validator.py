"""Voice Annotation Validator — KBBI exact-match OOV detection.

Uses the injected KBBI database table (`kbbi_dictionary`) with a hash index
on the `word` column for fast exact-match lookups. Any word not found in
the table is flagged as out-of-vocabulary (OOV).

Algorithm:
1. Strip punctuation, lowercase, split into words.
2. Query kbbi_dictionary in a single batched SELECT … WHERE word = ANY(:words).
3. Words that are NOT in the result set → OOV (flagged).
"""
import re
import logging
from typing import List, Set

from sqlalchemy import text as sql_text

from app.db.session import async_session

logger = logging.getLogger(__name__)


async def validate_text(text: str) -> List[str]:
    """Validate transcript text and return list of flagged (OOV) words.

    Algorithm:
    1. Strip punctuation, lowercase, split into words.
    2. Skip purely numeric tokens.
    3. Batch-query kbbi_dictionary for all unique words in one round-trip.
    4. Words not found → OOV.

    Returns:
        Sorted list of unique flagged words. Empty list means all clean.
    """
    if not text or not text.strip():
        return []

    # Clean text: remove punctuation, lowercase
    teks_bersih = re.sub(r"[^\w\s]", "", str(text)).lower()
    kata_kata = teks_bersih.split()

    # Deduplicate and skip numbers
    unique_words: Set[str] = set()
    for kata in kata_kata:
        if kata.isdigit():
            continue
        unique_words.add(kata)

    if not unique_words:
        return []

    # Batch exact-match query against KBBI table (hash index on word)
    async with async_session() as session:
        result = await session.execute(
            sql_text("SELECT word FROM kbbi_dictionary WHERE word = ANY(:words)"),
            {"words": list(unique_words)},
        )
        found_words = {row[0] for row in result.fetchall()}

    kata_tidak_ditemukan = unique_words - found_words
    return sorted(kata_tidak_ditemukan)
