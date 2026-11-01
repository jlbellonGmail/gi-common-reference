"""T3: reglas de código (spec 001, "Reglas de publicación", RF-3, RF-4, RF-9, RF-28)."""

import pytest

from gi_common_reference.locales.domain.codes import (
    CodeViolation,
    is_lowercase,
    lookup_key,
    publication_violations,
)
from gi_common_reference.locales.domain.iana import IanaRegistry, parse_registry
from tests.fixtures import real_registry, synthetic_registry


@pytest.fixture(scope="module")
def synthetic() -> IanaRegistry:
    return parse_registry(synthetic_registry())


@pytest.fixture(scope="module")
def real() -> IanaRegistry:
    return parse_registry(real_registry())


# --- lookup: forma bien formada (RF-8, RF-9) ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "key"),
    [("es", "es"), ("ES", "es"), ("Es", "es"), ("eS", "es"), ("fil", "fil"), ("FIL", "fil")],
)
def test_lookup_key_lowercases_well_formed_codes(raw: str, key: str) -> None:
    assert lookup_key(raw) == key


@pytest.mark.parametrize(
    "raw",
    [
        "es-AR",
        "es-419",
        "pt-BR",
        "zh-Hant",
        "es_AR",
        "x-klingon",
        "i-klingon",
        "en-u-ca-gregory",
        " es",
        "es ",
        " es ",
        "e s",
        "",
        "e",
        "espa",
        "e1",
        "12",
        "és",
        "ｅｓ",
        "es\n",
        "es\x00",
    ],
)
def test_lookup_key_rejects_what_is_not_a_well_formed_language_subtag(raw: str) -> None:
    assert lookup_key(raw) is None


def test_lookup_key_does_not_trim_or_translate() -> None:
    assert lookup_key("spa") == "spa"  # bien formado; "no encontrado" lo decide la consulta
    assert lookup_key("zz") == "zz"


# --- RF-28: minúsculas, sin normalizar ---------------------------------------------------------


@pytest.mark.parametrize("code", ["He", "ES", "Pt", "eS", "FIL", "hE"])
def test_is_lowercase_rejects_any_uppercase(code: str) -> None:
    assert not is_lowercase(code)


@pytest.mark.parametrize("code", ["es", "he", "pt", "fil"])
def test_is_lowercase_accepts_lowercase(code: str) -> None:
    assert is_lowercase(code)


# --- reglas de publicación 1-6 -----------------------------------------------------------------


@pytest.mark.parametrize("code", ["es", "en", "fil", "he", "id", "ar", "arb", "bih", "dz", "afa"])
def test_registered_preferred_languages_are_publishable(synthetic: IanaRegistry, code: str) -> None:
    assert publication_violations(code, synthetic) == []


@pytest.mark.parametrize("code", ["iw", "in", "bh", "adp"])
def test_deprecated_code_with_preferred_value_is_not_publishable(
    synthetic: IanaRegistry, code: str
) -> None:
    """Regla 4: el Preferred-Value prevalece, sea cual sea su longitud (2→3 y 3→2 incluidos)."""
    assert publication_violations(code, synthetic) == [CodeViolation.NOT_PREFERRED]


def test_deprecated_code_without_preferred_value_is_its_own_preferred_form(
    synthetic: IanaRegistry,
) -> None:
    assert publication_violations("sh", synthetic) == []


@pytest.mark.parametrize("code", ["spa", "eng", "ger", "zz", "aao", "latn", "i-klingon"])
def test_codes_not_registered_as_language_are_rejected(synthetic: IanaRegistry, code: str) -> None:
    """Regla 3: ISO 639 alternativos, inexistentes y subtags de otro tipo."""
    violations = publication_violations(code, synthetic)
    assert violations in ([CodeViolation.NOT_REGISTERED], [CodeViolation.FORMAT])


@pytest.mark.parametrize("code", ["spa", "eng", "ger", "zz", "aao"])
def test_well_formed_unregistered_codes_report_not_registered(
    synthetic: IanaRegistry, code: str
) -> None:
    assert publication_violations(code, synthetic) == [CodeViolation.NOT_REGISTERED]


@pytest.mark.parametrize("code", ["und", "mul", "mis", "zxx"])
def test_scope_special_is_excluded(synthetic: IanaRegistry, code: str) -> None:
    """Regla 5."""
    assert publication_violations(code, synthetic) == [CodeViolation.SCOPE_SPECIAL]


@pytest.mark.parametrize("code", ["qaa", "qab", "qmz", "qtz"])
def test_private_use_range_is_excluded(synthetic: IanaRegistry, code: str) -> None:
    """Regla 5."""
    assert publication_violations(code, synthetic) == [CodeViolation.PRIVATE_USE]


@pytest.mark.parametrize(
    "code",
    [
        "ES",
        "He",
        "es-AR",
        "es-419",
        "zh-Hant",
        "es_AR",
        "x-klingon",
        "en-u-ca-gregory",
        " es",
        "",
        "e",
        "espa",
        "e1",
    ],
)
def test_malformed_or_non_lowercase_codes_fail_format(synthetic: IanaRegistry, code: str) -> None:
    """Reglas 2 y 6: 2–3 letras ASCII minúsculas, sin `-`, `_` ni espacios; no se normaliza."""
    assert publication_violations(code, synthetic) == [CodeViolation.FORMAT]


def test_violations_are_independent_of_other_registry_content(synthetic: IanaRegistry) -> None:
    only_es = parse_registry("File-Date: 2026-09-01\n%%\nType: language\nSubtag: es\n")
    assert publication_violations("es", only_es) == []
    assert publication_violations("en", only_es) == [CodeViolation.NOT_REGISTERED]
    assert publication_violations("en", synthetic) == []


# --- contra el artefacto real ------------------------------------------------------------------


def test_real_registry_known_cases(real: IanaRegistry) -> None:
    for code in ("es", "en", "pt", "fil", "he", "id", "yi", "zh", "cmn", "bih", "dz"):
        assert publication_violations(code, real) == [], code
    for code in ("iw", "in", "ji", "bh", "adp"):
        assert publication_violations(code, real) == [CodeViolation.NOT_PREFERRED], code
    for code in ("spa", "eng", "ger", "zz"):
        assert publication_violations(code, real) == [CodeViolation.NOT_REGISTERED], code
    for code in ("und", "mul", "mis", "zxx"):
        assert publication_violations(code, real) == [CodeViolation.SCOPE_SPECIAL], code
    for code in ("qaa", "qtz"):
        assert publication_violations(code, real) == [CodeViolation.PRIVATE_USE], code


def test_real_registry_every_language_entry_follows_the_rules(real: IanaRegistry) -> None:
    checked = 0
    for entry in real.entries:
        if entry.type != "language" or ".." in entry.subtag:
            continue
        violations = publication_violations(entry.subtag, real)
        if entry.scope == "special":
            expected = [CodeViolation.SCOPE_SPECIAL]
        elif entry.preferred_value:
            expected = [CodeViolation.NOT_PREFERRED]
        elif len(entry.subtag) in (2, 3):
            expected = []
        else:
            expected = [CodeViolation.FORMAT]
        assert violations == expected, entry.subtag
        checked += 1
    assert checked > 8000
