"""Voice Annotation Validator — Sastrawi-based OOV detection.

Improved implementation with:
- Custom whitelist dictionary for named entities, places, greetings, etc.
- Robust text preprocessing (unicode normalization, hidden characters, etc.)
- Efficient dedup-first loop to avoid redundant stemming calls.

Algorithm:
1. Load Sastrawi stemmer and kamus (dictionary)
2. Clean & normalize input text
3. For each *unique* word in input text:
   - Skip if purely numeric or contains digits (e.g. "3x", "ke2")
   - CEK 0: Is word in custom whitelist?
   - CEK 1: Is word in Sastrawi kamus?
   - CEK 2: Stem word, is stem in kamus?
   - CEK 3: Stem word, is stem in whitelist?
   - If none match → OOV (flagged)
"""
import re
import unicodedata
import logging
from typing import List, Set, FrozenSet

logger = logging.getLogger(__name__)

# ─── Lazy singletons (loaded once) ─────────────────────────────────
_stemmer = None
_kamus: Set[str] = set()
_loaded: bool = False  # explicit flag so we don't re-attempt on ImportError

# ─── Custom Whitelist ───────────────────────────────────────────────
# Words that are valid Indonesian but absent from Sastrawi's KBBI-based
# dictionary.  Extend this set as needed — all entries MUST be lowercase.
#
# Categories included:
#   • Nama tempat / geografi (place names)
#   • Sapaan & gelar (greetings & titles)
#   • Nama hari & bulan (day/month names)
#   • Kata serapan umum (common loanwords)
#   • Singkatan yang sering diucapkan (spoken abbreviations)
#   • Named entities yang sering muncul di berita (news entities)

CUSTOM_WHITELIST: FrozenSet[str] = frozenset({
    # ── Nama Tempat / Geografi ──────────────────────────────────────
    "indonesia", "jakarta", "bandung", "surabaya", "medan", "semarang",
    "yogyakarta", "jogja", "makassar", "denpasar", "bali", "palembang",
    "manado", "pontianak", "banjarmasin", "balikpapan", "samarinda",
    "malang", "solo", "bogor", "depok", "tangerang", "bekasi",
    "cirebon", "sukabumi", "tasikmalaya", "garut", "purwakarta",
    "karawang", "subang", "cianjur", "ciamis", "majalengka",
    "sumedang", "indramayu", "kuningan", "pangandaran",
    "aceh", "padang", "pekanbaru", "jambi", "bengkulu", "lampung",
    "bangka", "belitung", "batam", "bintan", "riau",
    "kalimantan", "sulawesi", "papua", "sumatra", "sumatera", "jawa",
    "nusa", "tenggara", "maluku", "gorontalo",
    "jabodetabek", "jabotabek", "pantura",

    # ── Sapaan & Gelar ──────────────────────────────────────────────
    "pak", "bu", "bapak", "ibu", "mas", "mbak", "mba", "bang", "kak",
    "om", "tante", "oom", "abang", "adek", "adik", "dek", "nak",
    "neng", "teteh", "teh", "aa", "akang", "uda", "uni", "cak", "ning",
    "gus", "kiai", "kyai", "ustaz", "ustadz", "ustad", "ustadzah",
    "habib", "syekh", "sheikh",
    "haji", "hajjah", "hajah",
    "dokter", "profesor", "prof",
    "presiden", "wakil", "menteri", "gubernur", "walikota", "bupati",
    "camat", "lurah", "kades",
    "jenderal", "kolonel", "mayor", "kapten", "letnan", "sersan",
    "kopral", "prajurit", "brigadir", "komisaris", "inspektur",
    "kombes", "irjen", "kapolri", "kapolda", "kapolres", "kapolsek",
    "komandan", "panglima",

    # ── Hari & Bulan ────────────────────────────────────────────────
    "senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu",
    "januari", "februari", "maret", "april", "mei", "juni",
    "juli", "agustus", "september", "oktober", "november", "desember",

    # ── Kata Serapan Umum & Loanwords ───────────────────────────────
    "online", "offline", "digital", "internet", "website", "aplikasi",
    "smartphone", "handphone", "laptop", "komputer", "software",
    "hardware", "streaming", "download", "upload", "update",
    "video", "audio", "media", "sosial", "channel", "subscribe",
    "trending", "viral", "konten", "kreator", "influencer",
    "ojol", "ojek", "gojek", "grab", "uber", "maxim",
    "vaksin", "covid", "corona", "pandemi", "protokol",
    "inflasi", "deflasi", "resesi", "ekonomi",
    "demo", "aksi", "unjuk",

    # ── Singkatan Yang Sering Diucapkan ─────────────────────────────
    "dpr", "mpr", "dprd", "ri", "nkri", "tni", "polri",
    "bumn", "bumd", "umkm", "apbn", "apbd",
    "ktp", "nik", "npwp", "bpjs", "pln", "pertamina",
    "bca", "bni", "bri", "mandiri", "btn",
    "krl", "lrt", "mrt", "tol", "jtts",
    "kpk", "mk", "ma", "pn", "ojk", "bi",
    "sma", "smp", "sd", "smk", "paud",
    "ui", "itb", "ugm", "ipb", "undip", "unair", "its", "unpad",
    "tv", "tvri", "rcti", "sctv", "antv", "mnctv", "inews",
    "cnn", "bbc", "voa",

    # ── Kata Informal / Percakapan ──────────────────────────────────
    "nggak", "enggak", "gak", "ngga", "nga", "ndak", "tak",
    "udah", "dah", "udeh", "nih", "dong", "deh", "sih", "loh", "lho",
    "yuk", "ayo", "yah", "ya", "iya", "yoi",
    "emang", "emangnya", "gimana", "gitu", "gini",
    "banget", "bener", "biar", "biarin",
    "kayak", "kayaknya", "kek", "doang", "aja",
    "ngomong", "ngomongin", "ngapain", "ngeluh",
    "nyari", "nyoba", "nyuruh",
    "pengen", "pengin", "pingin",
    "ntar", "bentar", "sebentar",

    # ── Partikel & Kata Tugas Tambahan ──────────────────────────────
    "eh", "oh", "ah", "uh", "hm", "hmm", "em", "uhm",
    "nah", "wah", "duh", "aduh", "waduh", "astaga",
    "halo", "hai", "hey", "he",
    "oke", "ok", "okay", "sip",
    "makasih", "makasi", "trims", "thanks",
    "sorry", "maaf", "sori",
    "please", "tolong",
})


# ─── Precompiled regex patterns ────────────────────────────────────
# Characters to KEEP: word characters (\w) and whitespace — everything
# else (punctuation, symbols) is stripped.
_RE_NON_ALNUM = re.compile(r'[^\w\s]', re.UNICODE)
# Collapse any run of whitespace (spaces, tabs, newlines, NBSP, etc.)
_RE_MULTI_SPACE = re.compile(r'\s+')
# Detect tokens that are purely numeric or contain digits (e.g. "3x", "ke2")
_RE_HAS_DIGIT = re.compile(r'\d')


def _ensure_loaded() -> None:
    """Load Sastrawi stemmer and dictionary once."""
    global _stemmer, _kamus, _loaded
    if _loaded:
        return
    _loaded = True

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


def _clean_text(raw: str) -> str:
    """Normalize and clean transcript text for reliable tokenization.

    Steps:
    1. Unicode NFC normalization (merge combining characters)
    2. Strip zero-width & invisible Unicode characters
    3. Remove all punctuation / symbols (keep alphanumeric + space)
    4. Collapse whitespace (double spaces, tabs, newlines → single space)
    5. Lowercase + strip
    """
    # 1. NFC normalization — é composed as single char, not e + combining accent
    text = unicodedata.normalize("NFC", raw)

    # 2. Remove zero-width joiners, BOM, soft hyphens, and other invisibles
    text = re.sub(
        r'[\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f'
        r'\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069]',
        '', text
    )

    # 3. Strip punctuation and symbols
    text = _RE_NON_ALNUM.sub(' ', text)

    # 4. Collapse whitespace
    text = _RE_MULTI_SPACE.sub(' ', text)

    # 5. Lowercase + strip
    return text.lower().strip()


def validate_text(text: str) -> List[str]:
    """Validate transcript text and return list of flagged (OOV) words.

    Improved algorithm:
    1. Clean & normalize text (unicode, invisible chars, whitespace).
    2. Deduplicate tokens first → each unique word is checked only once.
    3. For each unique word:
       - Skip if numeric or contains digits (ordinals like "ke2", codes).
       - CEK 0: In custom whitelist? → skip
       - CEK 1: Kata dasar ada di kamus Sastrawi? → skip
       - CEK 2: Stem kata, akar ada di kamus? → skip
       - CEK 3: Stem kata, akar ada di whitelist? → skip
       - Else → OOV (flagged)

    Returns:
        Sorted list of unique flagged words. Empty list means all clean.
    """
    _ensure_loaded()

    if not text or not text.strip():
        return []

    # If Sastrawi failed to load, treat everything as clean
    if _stemmer is None:
        return []

    # ── Step 1: Clean text ──────────────────────────────────────────
    teks_bersih = _clean_text(text)

    if not teks_bersih:
        return []

    # ── Step 2: Deduplicate tokens ──────────────────────────────────
    # Using a set for O(1) uniqueness — we only need to stem each
    # distinct word once instead of once per occurrence.
    unique_tokens: Set[str] = set(teks_bersih.split())

    # ── Step 3: Check each unique word ──────────────────────────────
    kata_tidak_ditemukan: List[str] = []

    for kata in unique_tokens:
        # Skip empty tokens (defensive)
        if not kata:
            continue

        # Skip tokens with digits: pure numbers, ordinals ("ke3"),
        # codes ("b2"), etc.
        if _RE_HAS_DIGIT.search(kata):
            continue

        # Skip single characters (unlikely to be meaningful OOV)
        if len(kata) <= 1:
            continue

        # --- CEK 0: Apakah ada di custom whitelist? ---
        if kata in CUSTOM_WHITELIST:
            continue

        # --- CEK 1: Apakah kata dasar ada di kamus Indonesia? ---
        if kata in _kamus:
            continue

        # --- CEK 2: Stemming Indonesia — apakah akar kata ada di kamus? ---
        akar_id = _stemmer.stem(kata)
        if akar_id in _kamus:
            continue

        # --- CEK 3: Apakah akar kata ada di whitelist? ---
        # (handles prefixed/suffixed whitelist words like "sejakarta" edge case)
        if akar_id in CUSTOM_WHITELIST:
            continue

        # Jika lolos dari semua pengecekan, berarti OOV
        kata_tidak_ditemukan.append(kata)

    return sorted(kata_tidak_ditemukan)
