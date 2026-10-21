"""T3: parser del artefacto IANA (record-jar, RFC 5646 §3.1.1)."""

from datetime import date

import pytest

from gi_common_reference.locales.domain.iana import IanaFormatError, parse_registry
from tests.fixtures import real_registry, synthetic_registry

HEADER = "File-Date: 2026-09-01\n%%\n"


def test_exposes_file_date_and_fields_by_subtag() -> None:
    registry = parse_registry(synthetic_registry())
    assert registry.file_date == date(2026, 9, 1)

    iw = registry.language("iw")
    assert iw is not None
    assert (iw.type, iw.subtag) == ("language", "iw")
    assert iw.deprecated == "1989-01-01"
    assert iw.preferred_value == "he"
    assert iw.scope is None

    es = registry.language("es")
    assert es is not None
    assert (es.deprecated, es.preferred_value, es.scope) == (None, None, None)

    assert registry.language("ar") is not None
    assert registry.language("ar").scope == "macrolanguage"  # type: ignore[union-attr]
    assert registry.language("und").scope == "special"  # type: ignore[union-attr]


def test_optional_fields_may_be_missing_in_an_entry() -> None:
    registry = parse_registry(HEADER + "Type: language\nSubtag: es\n")
    entry = registry.language("es")
    assert entry is not None
    assert (entry.deprecated, entry.preferred_value, entry.scope) == (None, None, None)


def test_deprecated_without_preferred_value() -> None:
    sh = parse_registry(synthetic_registry()).language("sh")
    assert sh is not None
    assert sh.deprecated == "2000-02-18"
    assert sh.preferred_value is None


def test_continuation_lines_do_not_break_the_next_fields() -> None:
    registry = parse_registry(synthetic_registry())
    bih = registry.language("bih")
    assert bih is not None and bih.scope == "collection"
    sh = registry.language("sh")
    assert sh is not None and sh.deprecated == "2000-02-18"


def test_continuation_of_a_field_we_expose_is_joined() -> None:
    text = HEADER + "Type: language\nSubtag: xx\nScope: macro\n  language\n"
    entry = parse_registry(text).language("xx")
    assert entry is not None
    assert entry.scope == "macro language"


def test_repeated_descriptions_are_tolerated() -> None:
    assert parse_registry(synthetic_registry()).language("es") is not None


def test_only_type_language_entries_are_languages() -> None:
    registry = parse_registry(synthetic_registry())
    assert registry.language("aao") is None  # extlang
    assert registry.language("latn") is None  # script
    assert registry.language("ar-es") is None
    assert registry.language("i-klingon") is None  # grandfathered, se identifica con Tag
    assert [e.type for e in registry.entries if e.subtag == "i-klingon"] == ["grandfathered"]
    assert [e.type for e in registry.entries if e.subtag == "zh-Hant"] == ["redundant"]


def test_language_lookup_is_exact_not_by_range() -> None:
    registry = parse_registry(synthetic_registry())
    assert registry.language("qaa") is None
    assert registry.language("qaa..qtz") is None


@pytest.mark.parametrize("code", ["qaa", "qab", "qmz", "qtz"])
def test_private_use_range_covers_its_codes(code: str) -> None:
    assert parse_registry(synthetic_registry()).is_private_use(code)


@pytest.mark.parametrize("code", ["qa", "qua", "qub", "es", "zzz", "qaaa", "und"])
def test_private_use_range_does_not_cover_other_codes(code: str) -> None:
    assert not parse_registry(synthetic_registry()).is_private_use(code)


def test_crlf_line_endings_are_accepted() -> None:
    text = synthetic_registry().replace("\n", "\r\n")
    assert parse_registry(text).language("iw") is not None


# --- estructura inválida -----------------------------------------------------------------------


def test_missing_file_date_is_rejected() -> None:
    with pytest.raises(IanaFormatError, match="File-Date"):
        parse_registry("%%\nType: language\nSubtag: es\n")


def test_empty_text_is_rejected() -> None:
    with pytest.raises(IanaFormatError, match="File-Date"):
        parse_registry("")


@pytest.mark.parametrize("value", ["2026-13-01", "01/09/2026", "", "2026-9-1x"])
def test_invalid_file_date_is_rejected(value: str) -> None:
    with pytest.raises(IanaFormatError, match="File-Date"):
        parse_registry(f"File-Date: {value}\n%%\nType: language\nSubtag: es\n")


def test_entry_without_type_is_rejected() -> None:
    with pytest.raises(IanaFormatError, match="Type"):
        parse_registry(HEADER + "Subtag: es\nDescription: Spanish\n")


def test_entry_without_subtag_or_tag_is_rejected() -> None:
    with pytest.raises(IanaFormatError, match="Subtag"):
        parse_registry(HEADER + "Type: language\nDescription: Spanish\n")


def test_line_that_is_not_a_field_is_rejected() -> None:
    with pytest.raises(IanaFormatError, match="línea"):
        parse_registry(HEADER + "Type: language\nSubtag es\n")


def test_continuation_without_a_field_is_rejected() -> None:
    with pytest.raises(IanaFormatError, match="continuación"):
        parse_registry("  huérfana\n%%\nType: language\nSubtag: es\n")


def test_duplicate_language_subtag_is_rejected() -> None:
    entry = "Type: language\nSubtag: es\n%%\n"
    with pytest.raises(IanaFormatError, match="duplicad"):
        parse_registry(HEADER + entry + entry)


def test_errors_are_value_errors() -> None:
    assert issubclass(IanaFormatError, ValueError)


# --- artefacto real ----------------------------------------------------------------------------


def test_real_registry_parses_completely() -> None:
    registry = parse_registry(real_registry())
    assert registry.file_date == date(2026, 9, 17)
    types = {e.type for e in registry.entries}
    assert {"language", "extlang", "script", "region", "variant"} <= types
    assert {"grandfathered", "redundant"} <= types
    assert len(registry.entries) > 9000


def test_real_registry_known_languages() -> None:
    registry = parse_registry(real_registry())
    for code in ("es", "en", "pt", "fil", "he", "id", "yi", "zh", "cmn", "ar", "arb"):
        entry = registry.language(code)
        assert entry is not None, code
        assert entry.deprecated is None, code
    for code in ("spa", "eng", "ger", "zz"):
        assert registry.language(code) is None, code


@pytest.mark.parametrize(
    ("old", "preferred"), [("iw", "he"), ("in", "id"), ("ji", "yi"), ("bh", "bih"), ("adp", "dz")]
)
def test_real_registry_preferred_values_of_any_length(old: str, preferred: str) -> None:
    entry = parse_registry(real_registry()).language(old)
    assert entry is not None
    assert entry.deprecated is not None
    assert entry.preferred_value == preferred


def test_real_registry_special_scope_and_private_use() -> None:
    registry = parse_registry(real_registry())
    for code in ("und", "mul", "mis", "zxx"):
        assert registry.language(code).scope == "special"  # type: ignore[union-attr]
    assert registry.is_private_use("qaa") and registry.is_private_use("qtz")
    assert not registry.is_private_use("es")


def test_real_registry_deprecated_without_preferred_value_exists() -> None:
    registry = parse_registry(real_registry())
    assert any(
        e.type == "language" and e.deprecated and not e.preferred_value for e in registry.entries
    )


# --- alias por Preferred-Value (D8, RF-8) ------------------------------------------------------


def test_language_aliases_map_each_subtag_to_its_preferred_value() -> None:
    aliases = parse_registry(synthetic_registry()).language_aliases()
    assert aliases == {"bh": "bih", "adp": "dz", "iw": "he", "in": "id"}


def test_language_aliases_ignore_other_types_ranges_and_entries_without_preferred_value() -> None:
    aliases = parse_registry(synthetic_registry()).language_aliases()
    assert "sh" not in aliases  # deprecado sin Preferred-Value
    assert "aao" not in aliases  # extlang
    assert "i-klingon" not in aliases  # grandfathered
    assert not any(".." in key for key in aliases)


def test_real_registry_aliases_include_the_known_cases() -> None:
    aliases = parse_registry(real_registry()).language_aliases()
    assert aliases["iw"] == "he" and aliases["in"] == "id" and aliases["ji"] == "yi"
    assert aliases["bh"] == "bih" and aliases["adp"] == "dz"
    assert all(key == key.lower() and value == value.lower() for key, value in aliases.items())


# --- RF-33: regla única de Deprecated y Preferred-Value (campo presente = valor no vacío) --------


def test_is_deprecated_is_true_exactly_when_the_deprecated_field_is_present() -> None:
    registry = parse_registry(synthetic_registry())
    assert registry.language("iw").is_deprecated  # type: ignore[union-attr]
    assert registry.language("sh").is_deprecated  # type: ignore[union-attr]  # sin Preferred-Value
    assert not registry.language("es").is_deprecated  # type: ignore[union-attr]


@pytest.mark.parametrize("field", ["Deprecated", "Preferred-Value"])
@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_an_empty_deprecated_or_preferred_value_is_rejected_as_malformed(
    field: str, value: str
) -> None:
    text = HEADER + f"Type: language\nSubtag: xx\n{field}:{value}\n"
    with pytest.raises(IanaFormatError, match=f"{field} vacío"):
        parse_registry(text)


def test_an_empty_deprecated_is_rejected_even_if_other_fields_follow_it() -> None:
    text = HEADER + "Type: language\nSubtag: xx\nDeprecated:\nPreferred-Value: yy\n"
    with pytest.raises(IanaFormatError, match="Deprecated vacío"):
        parse_registry(text)


def test_a_value_on_a_continuation_line_counts_as_present() -> None:
    registry = parse_registry(HEADER + "Type: language\nSubtag: xx\nDeprecated:\n  2020-01-01\n")
    assert registry.language("xx").is_deprecated  # type: ignore[union-attr]


# --- RF-33: el valor en una línea de continuación no conserva espacios artificiales --------------

CONTINUED_IW = (
    HEADER + "Type: language\nSubtag: iw\nDeprecated:\n  1989-01-01\nPreferred-Value:\n  he\n%%\n"
    "Type: language\nSubtag: he\n"
)


def test_a_preferred_value_on_a_continuation_line_has_no_leading_space() -> None:
    entry = parse_registry(CONTINUED_IW).language("iw")
    assert entry is not None
    assert entry.preferred_value == "he"
    assert entry.deprecated == "1989-01-01"
    assert entry.is_deprecated


def test_a_preferred_value_on_a_continuation_line_yields_the_same_alias() -> None:
    assert parse_registry(CONTINUED_IW).language_aliases() == {"iw": "he"}


@pytest.mark.parametrize(
    "layout",
    [
        "Deprecated:\n  1989-01-01\n",
        "Deprecated:\t\n\t1989-01-01\t\n",
        "Deprecated:   \n   1989-01-01   \n",
        "Deprecated: 1989-01-01\n",
        "Deprecated:\r\n  1989-01-01\r\n",
    ],
)
def test_deprecated_has_the_same_value_however_it_is_laid_out(layout: str) -> None:
    entry = parse_registry(HEADER + f"Type: language\nSubtag: xx\n{layout}").language("xx")
    assert entry is not None
    assert entry.deprecated == "1989-01-01"


def test_a_value_continued_over_several_lines_is_joined_with_single_spaces() -> None:
    registry = parse_registry(HEADER + "Type: language\nSubtag: xx\nDescription: uno\n  dos\n")
    assert registry.entries[0].subtag == "xx"
    text = HEADER + "Type: language\nSubtag: xx\nDeprecated: 1989-01-01\n  (nota)\n"
    assert parse_registry(text).language("xx").deprecated == "1989-01-01 (nota)"  # type: ignore[union-attr]


@pytest.mark.parametrize("field", ["Deprecated", "Preferred-Value"])
def test_a_field_whose_only_continuation_line_is_blank_is_still_empty(field: str) -> None:
    text = HEADER + f"Type: language\nSubtag: xx\n{field}:\n   \n\t\n"
    with pytest.raises(IanaFormatError, match=f"{field} vacío"):
        parse_registry(text)
