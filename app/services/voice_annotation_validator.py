"""Voice Annotation Validator — Sastrawi-based OOV detection.

Exact implementation of the reference algorithm. Uses the PySastrawi
dictionary and stemmer to flag out-of-vocabulary (OOV) words in a
transcript string.

Algorithm:
1. Load Sastrawi stemmer and kamus (dictionary)
2. For each word in input text:
   - Skip if purely numeric
   - CEK 1: Is word in kamus?
   - CEK 2: Stem word, is stem in kamus?
   - If neither → OOV (flagged)
"""
import re
import logging
from typing import List, Set

logger = logging.getLogger(__name__)

# Lazy singleton so the heavy Sastrawi dictionary is loaded only once
_stemmer = None
_kamus: Set[str] = set()


def _ensure_loaded():
    """Load Sastrawi stemmer and dictionary once."""
    global _stemmer, _kamus
    if _stemmer is not None:
        return

    try:
        from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
        factory = StemmerFactory()
        _stemmer = factory.create_stemmer()
        _kamus = set(factory.get_words())
        logger.info("Sastrawi dictionary loaded: %d words", len(_kamus))
    except ImportError:
        logger.warning(
            "PySastrawi not installed — all words will pass validation. "
            "Install with: pip install PySastrawi"
        )
        _stemmer = None
        _kamus = set()


def validate_text(text: str) -> List[str]:
    """Validate transcript text and return list of flagged (OOV) words.

    Algorithm (exact match with reference implementation):
    1. Strip punctuation, lowercase, split into words.
    2. For each word:
       - Skip if purely numeric.
       - CEK 1: Apakah kata dasar ada di kamus Indonesia?
       - CEK 2: Stemming Indonesia — apakah akar kata ada di kamus?
       - Jika lolos dari pengecekan, berarti OOV.

    Returns:
        Sorted list of unique flagged words. Empty list means all clean.
    """
    _ensure_loaded()

    if not text or not text.strip():
        return []

    # If Sastrawi failed to load, treat everything as clean
    if _stemmer is None:
        return []

    # Clean text: remove punctuation, lowercase
    teks_bersih = re.sub(r'[^\w\s]', '', str(text)).lower()
    kata_kata = teks_bersih.split()

    kata_tidak_ditemukan: set = set()

    for kata in kata_kata:
        if kata.isdigit():
            continue

        # --- CEK 1: Apakah kata dasar ada di kamus Indonesia? ---
        if kata in _kamus:
            continue

        # --- CEK 2: Stemming Indonesia ---
        akar_id = _stemmer.stem(kata)
        if akar_id in _kamus:
            continue

        # Jika lolos dari pengecekan, berarti OOV
        kata_tidak_ditemukan.add(kata)

    return sorted(kata_tidak_ditemukan)
