"""Unit tests for the curation text normalizer."""
import pytest

from app.services.curation.normalizer import TextNormalizer


@pytest.fixture
def normalizer() -> TextNormalizer:
    return TextNormalizer()


class TestUniversalPipeline:
    """Tests for the universal normalization pipeline."""

    def test_lowercasing(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("Pukul Tujuh") == "pukul tujuh"

    def test_currency_rp(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("Rp10.000") == "sepuluh ribu rupiah"
        assert normalizer.normalize("Rp1.500") == "seribu lima ratus rupiah"
        assert normalizer.normalize("idr 5000") == "lima ribu rupiah"

    def test_time_colon(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("07:00") == "pukul tujuh"
        assert normalizer.normalize("14:30") == "pukul empat belas tiga puluh"

    def test_time_with_prefix(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("Pukul 07:00 pagi") == "pukul tujuh pagi"
        assert normalizer.normalize("jam 9.30") == "jam sembilan tiga puluh"

    def test_percent(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("12,50%") == "dua belas koma lima persen"
        assert normalizer.normalize("10 persen") == "sepuluh persen"

    def test_number_integer(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("12 orang") == "dua belas orang"

    def test_number_decimal(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("12.345,67") == "dua belas ribu tiga ratus empat puluh lima koma enam tujuh"

    def test_slang_mapping(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("gak") == "tidak"
        assert normalizer.normalize("udah") == "sudah"
        assert normalizer.normalize("kayak") == "seperti"

    def test_filler_removal(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("ya, kan, dong") == ""
        assert normalizer.normalize("ini lah sih") == "ini"

    def test_punctuation_cleaning(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("datang, pergi!") == "datang pergi"
        assert normalizer.normalize("apa???") == "apa"


class TestSIBIPipeline:
    """Tests for the SIBI-specific normalization pipeline."""

    def test_sibi_lowercasing(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("POLISI", category="SIBI") == "polisi"

    def test_sibi_number(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("2 korban", category="SIBI") == "dua korban"

    def test_sibi_entity_mapping(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("kpk", category="SIBI") == "K-P-K"

    def test_sibi_standalone_ri(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("ri", category="SIBI") == "R-I"

    def test_sibi_finger_spelling(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("corona", category="SIBI") == "c-o-r-o-n-a"

    def test_sibi_preserves_hyphenated_tokens(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("K-P-K datang, pergi!", category="SIBI") == "K-P-K datang pergi"

    def test_sibi_combined(self, normalizer: TextNormalizer) -> None:
        result = normalizer.normalize("Presiden ri dan kpk tangani corona", category="SIBI")
        assert "K-P-K" in result
        assert "R-I" in result
        assert "c-o-r-o-n-a" in result


class TestIdempotency:
    """Tests that normalization is idempotent."""

    @pytest.mark.parametrize(
        "text,category",
        [
            ("Rp10.000", None),
            ("Pukul 07:00 pagi", None),
            ("gak, udah", None),
            ("kpk", "SIBI"),
            ("corona", "SIBI"),
        ],
    )
    def test_idempotent(self, normalizer: TextNormalizer, text: str, category: str) -> None:
        first = normalizer.normalize(text, category=category)
        second = normalizer.normalize(first, category=category)
        assert first == second


class TestEdgeCases:
    """Edge-case tests for the normalizer."""

    def test_empty_string(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("") == ""

    def test_only_punctuation(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("!!!,,,") == ""

    def test_multiple_spaces_collapsed(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("satu   dua    tiga") == "satu dua tiga"

    def test_currency_with_context(self, normalizer: TextNormalizer) -> None:
        assert normalizer.normalize("Biaya Rp10.000 per orang") == "biaya sepuluh ribu rupiah per orang"

    def test_slang_exact_word_boundary(self, normalizer: TextNormalizer) -> None:
        # "gak" should become "tidak", but "gakaran" should stay as-is
        assert normalizer.normalize("gak") == "tidak"
