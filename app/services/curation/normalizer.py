"""Text normalization service for the Curation module.

Provides automated dataset cleaning for Indonesian transcripts and SIBI glosses.
"""

import json
import os
import re
from typing import Dict, List, Optional

from num2words import num2words


# ---------------------------------------------------------------------------
# Load lookup tables once at module import
# ---------------------------------------------------------------------------

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _load_json(filename: str):
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_slang_dict() -> Dict[str, str]:
    return _load_json("slang_dictionary.json")


def _load_filler_words() -> List[str]:
    return _load_json("filler_words.json")


def _load_sibi_entities() -> Dict[str, str]:
    return _load_json("sibi_entity_mapping.json")


def _load_sibi_finger_spelling() -> List[str]:
    return _load_json("sibi_finger_spelling.json")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _indonesian_num2words(number: float) -> str:
    """Convert a number to Indonesian words using num2words."""
    try:
        # num2words supports 'id' locale
        return num2words(number, lang="id")
    except Exception:
        return str(number)


def _parse_indonesian_number(num_str: str) -> Optional[float]:
    """Parse an Indonesian-formatted number string.

    Indonesia uses:
      - '.' as thousands separator
      - ',' as decimal separator
    """
    # Strip whitespace
    num_str = num_str.strip()
    if not num_str:
        return None

    # Handle ranges like "1-5" — return None here; ranges are handled separately
    if "-" in num_str and num_str.count("-") == 1 and num_str.replace("-", "").replace(",", "").replace(".", "").isdigit():
        return None

    # Remove thousand separators
    cleaned = num_str.replace(".", "")

    # Replace decimal comma with dot for Python float parsing
    cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def _replace_number_match(match: re.Match) -> str:
    """Callback for regex number replacement."""
    raw = match.group(0)
    parsed = _parse_indonesian_number(raw)
    if parsed is None:
        return raw
    # If the number is effectively an integer, convert as int for cleaner wording
    if parsed == int(parsed):
        parsed = int(parsed)
    return _indonesian_num2words(parsed)


# ---------------------------------------------------------------------------
# TextNormalizer
# ---------------------------------------------------------------------------


class TextNormalizer:
    """Idempotent text normalizer for Indonesian transcripts and SIBI glosses."""

    def __init__(self):
        self.slang_dict = _load_slang_dict()
        self.filler_words = _load_filler_words()
        self.sibi_entities = _load_sibi_entities()
        self.sibi_finger_spelling = _load_sibi_finger_spelling()

        # One alternation compiled once, instead of one regex per entry compiled
        # and run on every call. The dictionary grew from 139 to ~1.3k entries,
        # which would otherwise mean ~1.3k compiles plus ~1.3k full-string scans
        # for EVERY sentence — and a job can hold hundreds of sentences.
        #
        # Longest-first ordering matters: Python's alternation takes the first
        # branch that matches, so "ngomong-ngomong" must be offered before
        # "ngomong" or the compound would only be half-replaced.
        # Hyphen-aware boundaries instead of \b. SIBI finger-spelling writes a
        # word as single letters joined by hyphens ("S-P-B-U"), and \b treats a
        # hyphen as a boundary, so every one of those letters looked like a
        # standalone word. The dictionary legitimately maps some single letters
        # ("u" -> "kamu", "g" -> "tidak"), which turned "S-P-B-U" into
        # "s-p-b kamu" — silently corrupting the gloss.
        #
        # Refusing a match that touches a hyphen protects finger-spelling while
        # still rewriting the same word standing on its own, and still matches
        # hyphenated KEYS like "ngomong-ngomong" (nothing adjoins those ends).
        self._slang_pattern = None
        if self.slang_dict:
            alternatives = sorted(self.slang_dict, key=len, reverse=True)
            self._slang_pattern = re.compile(
                r"(?<![\w-])(" + "|".join(re.escape(a) for a in alternatives) + r")(?![\w-])"
            )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def normalize(self, text: str, category: Optional[str] = None) -> str:
        """Run the full normalization pipeline.

        Args:
            text: Raw input text.
            category: Either "SIBI" or "BISINDO". If "SIBI", extra SIBI-specific
                rules are applied after the universal pipeline.

        Returns:
            Normalized text string.
        """
        result = self._universal_pipeline(text)
        if category and category.upper() == "SIBI":
            result = self._sibi_pipeline(result)
        return result

    # -----------------------------------------------------------------------
    # Universal Pipeline (applies to both SIBI and BISINDO)
    # -----------------------------------------------------------------------

    def _universal_pipeline(self, text: str) -> str:
        result = text
        result = self._step_lowercase(result)
        result = self._step_currency(result)
        result = self._step_time(result)
        result = self._step_percent(result)
        result = self._step_number(result)
        result = self._step_slang(result)
        result = self._step_filler(result)
        result = self._step_punctuation(result)
        return result.strip()

    def _step_lowercase(self, text: str) -> str:
        return text.lower()

    def _step_currency(self, text: str) -> str:
        """Normalize Rupiah / IDR currency patterns."""
        # Pattern: Rp / IDR / Rp. optionally followed by digits with . or ,
        pattern = re.compile(r"\b(?:rp\.?|idr)\s*(\d[\d\.,]*)\b", re.IGNORECASE)

        def repl(m: re.Match) -> str:
            num_str = m.group(1)
            parsed = _parse_indonesian_number(num_str)
            if parsed is None:
                return m.group(0)
            if parsed == int(parsed):
                parsed = int(parsed)
            words = _indonesian_num2words(parsed)
            return f"{words} rupiah"

        return pattern.sub(repl, text)

    def _step_time(self, text: str) -> str:
        """Normalize HH:MM or HH.MM time patterns to verbal form."""
        # Match times like 07:00, 7.00, 14:30, optionally preceded by "pukul" or "jam"
        pattern = re.compile(r"\b(pukul|jam)\s+(\d{1,2})[:\.](\d{2})\b|\b(\d{1,2})[:\.](\d{2})\b")

        def repl(m: re.Match) -> str:
            prefix = m.group(1)
            if prefix:
                hour = int(m.group(2))
                minute = int(m.group(3))
            else:
                hour = int(m.group(4))
                minute = int(m.group(5))

            hour_words = _indonesian_num2words(hour)
            if minute == 0:
                time_words = hour_words
            else:
                minute_words = _indonesian_num2words(minute)
                time_words = f"{hour_words} {minute_words}"

            if prefix:
                return f"{prefix} {time_words}"
            return f"pukul {time_words}"

        return pattern.sub(repl, text)

    def _step_percent(self, text: str) -> str:
        """Normalize percent patterns."""
        # Match number + % or number + persen
        # Use (?<!\w) and (?!\w) instead of \b because % is a non-word char
        pattern = re.compile(r"(?<!\w)(\d[\d\.,]*)\s*(%|persen)(?!\w)")

        def repl(m: re.Match) -> str:
            num_str = m.group(1)
            parsed = _parse_indonesian_number(num_str)
            if parsed is None:
                return m.group(0)
            if parsed == int(parsed):
                parsed = int(parsed)
            words = _indonesian_num2words(parsed)
            return f"{words} persen"

        return pattern.sub(repl, text)

    def _step_number(self, text: str) -> str:
        """Normalize remaining standalone numbers."""
        # Match integers and decimals in Indonesian format
        # Examples: 12, 1.234, 12.345,67, 0,5
        # Avoid matching things already processed (currency symbols removed)
        pattern = re.compile(r"\b\d[\d\.,]*\b")

        # We need to avoid re-processing numbers that were already converted to words
        # Since words don't contain digits, a simple digit-based regex is safe.
        return pattern.sub(_replace_number_match, text)

    def _step_slang(self, text: str) -> str:
        """Replace slang words with standard Indonesian equivalents.

        Single pass over the text. The previous implementation substituted the
        whole dictionary sequentially, so a word produced by one replacement
        could be rewritten again by a later entry. The dictionary is now
        chain-flattened (no value is itself a key), which makes one pass both
        correct and idempotent.
        """
        if not self._slang_pattern:
            return text
        return self._slang_pattern.sub(
            lambda m: self.slang_dict.get(m.group(0), m.group(0)), text
        )

    def _step_filler(self, text: str) -> str:
        """Remove filler words."""
        result = text
        for word in sorted(self.filler_words, key=lambda x: -len(x)):
            pattern = re.compile(r"\b" + re.escape(word) + r"\b")
            result = pattern.sub("", result)
        # Collapse multiple spaces
        result = re.sub(r"\s+", " ", result)
        return result.strip()

    def _step_punctuation(self, text: str) -> str:
        """Remove punctuation except hyphens. Replace with spaces."""
        # Keep only letters, digits, spaces, and hyphens
        result = re.sub(r"[^a-z0-9\s-]", " ", text)
        result = re.sub(r"\s+", " ", result)
        return result.strip()

    # -----------------------------------------------------------------------
    # SIBI-specific Pipeline
    # -----------------------------------------------------------------------

    def _sibi_pipeline(self, text: str) -> str:
        result = text
        result = self._sibi_step_entity_mapping(result)
        result = self._sibi_step_standalone_ri(result)
        result = self._sibi_step_finger_spelling(result)
        result = self._sibi_step_punctuation(result)
        return result.strip()

    def _sibi_step_finger_spelling(self, text: str) -> str:
        """Convert specific words to hyphenated letter spelling."""
        result = text
        for word in sorted(self.sibi_finger_spelling, key=lambda x: -len(x)):
            pattern = re.compile(r"\b" + re.escape(word) + r"\b")
            spelled = "-".join(list(word.replace("-", "").replace(" ", "")))
            result = pattern.sub(spelled, result)
        return result

    def _sibi_step_entity_mapping(self, text: str) -> str:
        """Map known entities to hyphenated uppercase form."""
        result = text
        for entity, mapped in sorted(self.sibi_entities.items(), key=lambda x: -len(x[0])):
            # Match plain lowercase entity (e.g., "kpk")
            pattern = re.compile(r"\b" + re.escape(entity) + r"\b")
            result = pattern.sub(mapped, result)
            # Match already-hyphenated lowercase version (e.g., "k-p-k")
            hyphenated_entity = "-".join(list(entity))
            pattern2 = re.compile(r"\b" + re.escape(hyphenated_entity) + r"\b")
            result = pattern2.sub(mapped, result)
        return result

    def _sibi_step_standalone_ri(self, text: str) -> str:
        """Map standalone 'ri' to 'R-I'."""
        return re.sub(r"\bri\b", "R-I", text)

    def _sibi_step_punctuation(self, text: str) -> str:
        """Clean punctuation but preserve hyphens inside letter groups like K-P-K."""
        # We first protect hyphenated letter sequences by marking them
        # Pattern: sequences of single letters separated by hyphens, e.g. K-P-K, c-o-r-o-n-a
        protected: List[str] = []

        def protect(m: re.Match) -> str:
            token = f"ZZZPROTECTED{len(protected)}ZZZ"
            protected.append(m.group(0))
            return token

        # Protect sequences like K-P-K or c-o-r-o-n-a
        result = re.sub(r"\b(?:[a-zA-Z]-)+[a-zA-Z]\b", protect, text)

        # Now remove all punctuation except spaces
        result = re.sub(r"[^a-zA-Z0-9\s]", " ", result)
        result = re.sub(r"\s+", " ", result)

        # Restore protected tokens
        for idx, original in enumerate(protected):
            result = result.replace(f"ZZZPROTECTED{idx}ZZZ", original)

        return result.strip()
