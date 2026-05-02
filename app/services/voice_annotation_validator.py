"""Voice Annotation Validator — Sastrawi-based OOV detection.

Adapted from the user's reference implementation. Uses the PySastrawi
dictionary and stemmer to flag out-of-vocabulary (OOV) words in a
transcript string.
"""
import re
import logging
from typing import List, Set

logger = logging.getLogger(__name__)

# Lazy singleton so the heavy Sastrawi dictionary is loaded only once
_stemmer = None
_kamus: Set[str] = set()

# Seed list of common proper nouns / brand names that are NOT in Sastrawi
# but appear frequently in Indonesian news broadcasts.
CUSTOM_DICTIONARY: Set[str] = {
    # Politik & Pemerintahan
    "jokowi", "joko", "widodo", "prabowo", "subianto", "gibran",
    "megawati", "soekarnoputri", "ahok", "anies", "baswedan",
    "ganjar", "pranowo", "sandiaga", "uno", "mahfud",
    "luhut", "pandjaitan", "sri", "mulyani", "retno", "marsudi",
    "risma", "erick", "thohir", "nadiem", "makarim",
    # Lembaga & Organisasi
    "kpu", "kpk", "bpk", "dpr", "dprd", "mpr", "mk", "ma",
    "polri", "tni", "bnn", "bnpb", "bpom", "ojk", "bi",
    "kominfo", "kemendikbud", "kemenkes", "kemenhub",
    "nu", "muhammadiyah", "pdip", "gerindra", "golkar",
    "demokrat", "pks", "pkb", "nasdem", "psi", "perindo",
    # Kota & Daerah
    "jakarta", "bandung", "surabaya", "semarang", "yogyakarta",
    "jogja", "medan", "makassar", "palembang", "denpasar",
    "bali", "lombok", "sulawesi", "kalimantan", "sumatra",
    "papua", "maluku", "ntt", "ntb", "jabar", "jateng",
    "jatim", "banten", "dki", "diy",
    # Media & Teknologi
    "chatgpt", "openai", "google", "facebook", "instagram",
    "tiktok", "youtube", "whatsapp", "twitter", "telegram",
    "netflix", "spotify", "linkedin", "zoom",
    # Istilah Umum Berita
    "covid", "corona", "omicron", "vaksin", "booster",
    "pilkada", "pilpres", "pemilu", "rapbd", "apbn",
    "rupiah", "dollar", "euro",
    # Singkatan Umum
    "ri", "ruu", "uu", "pp", "perpres", "perda", "rp",
    "km", "kg", "dll", "dsb", "dkk", "sda", "sdm",
}


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

    Algorithm (matching user's reference implementation):
    1. Strip punctuation, lowercase, split into words.
    2. For each word:
       - Skip if purely numeric.
       - Check custom dictionary.
       - Check Sastrawi dictionary.
       - Check stemmed result in dictionary.
       - Otherwise → flagged.

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
    teks_bersih = re.sub(r'[^\w\s]', '', text).lower()
    kata_kata = teks_bersih.split()

    flagged: set = set()

    for kata in kata_kata:
        if not kata:
            continue

        # Skip pure numbers
        if kata.isdigit():
            continue

        # Check 1: Custom dictionary (proper nouns, abbreviations)
        if kata in CUSTOM_DICTIONARY:
            continue

        # Check 2: Sastrawi dictionary (exact match)
        if kata in _kamus:
            continue

        # Check 3: Stemming — does the stem exist in dictionary?
        akar = _stemmer.stem(kata)
        if akar in _kamus:
            continue

        # Failed all checks → OOV
        flagged.add(kata)

    return sorted(flagged)
