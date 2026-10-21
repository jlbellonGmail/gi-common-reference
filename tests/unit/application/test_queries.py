"""T8: consultas de solo lectura (RF-7–RF-13), sobre un lector en memoria."""

import pytest

from gi_common_reference.locales.application.queries import (
    LookupStatus,
    get_locale_by_code,
    get_locale_by_id,
    list_locales,
)
from gi_common_reference.locales.domain.model import LocaleRecord
from tests.fixtures.fakes import FakeReader
from tests.fixtures.snapshots import locale_id


def rec(code: str, status: str = "active") -> LocaleRecord:
    return LocaleRecord(locale_id(code), code, status, False, None)


ES, EN, PT = rec("es"), rec("en"), rec("pt")
HE = rec("he")
IW = LocaleRecord(locale_id("iw"), "iw", "inactive", True, locale_id("he"))


def reader(*locales: LocaleRecord, aliases: dict[str, str] | None = None) -> FakeReader:
    return FakeReader(version=3, locales=locales, aliases=aliases)


# --- por id (RF-7) -----------------------------------------------------------------------------


def test_by_id_finds_the_locale_with_the_snapshot_version() -> None:
    result = get_locale_by_id(reader(ES, EN), locale_id("es"))
    assert result.status is LookupStatus.FOUND
    assert result.locale == ES and result.snapshot_version == 3


def test_by_id_not_found() -> None:
    result = get_locale_by_id(reader(ES), locale_id("zz"))
    assert result.status is LookupStatus.NOT_FOUND
    assert result.locale is None and result.snapshot_version == 3


@pytest.mark.parametrize("raw", ["", "abc", "not-a-uuid", "es", "by-code", " " + locale_id("es")])
def test_by_id_with_a_malformed_id_is_not_found_and_never_reaches_the_reader(raw: str) -> None:
    source = reader(ES)
    result = get_locale_by_id(source, raw)
    assert result.status is LookupStatus.NOT_FOUND
    assert source.sessions == 1  # una sesión solo para informar la snapshot_version


def test_by_id_accepts_an_uppercase_uuid() -> None:
    result = get_locale_by_id(reader(ES), locale_id("es").upper())
    assert result.status is LookupStatus.FOUND and result.locale == ES


def test_by_id_returns_inactive_locales_too() -> None:
    result = get_locale_by_id(reader(IW, HE), locale_id("iw"))
    assert result.status is LookupStatus.FOUND and result.locale == IW


# --- por código (RF-8, RF-9, RF-10) ------------------------------------------------------------


@pytest.mark.parametrize("raw", ["es", "ES", "Es", "eS"])
def test_by_code_is_case_tolerant(raw: str) -> None:
    result = get_locale_by_code(reader(ES), raw)
    assert result.status is LookupStatus.FOUND and result.locale == ES


def test_by_code_returns_the_published_code_whatever_its_status() -> None:
    result = get_locale_by_code(reader(IW, HE, aliases={"iw": "he"}), "iw")
    assert result.locale == IW  # el locale iw, no he (RF-8)


def test_by_code_resolves_an_unpublished_deprecated_code_to_its_preferred_value() -> None:
    result = get_locale_by_code(reader(ES, HE, aliases={"iw": "he"}), "iw")
    assert result.status is LookupStatus.FOUND and result.locale == HE


def test_by_code_alias_is_case_tolerant() -> None:
    result = get_locale_by_code(reader(HE, aliases={"iw": "he"}), "IW")
    assert result.locale == HE


def test_by_code_alias_without_the_preferred_locale_is_not_found() -> None:
    result = get_locale_by_code(reader(ES, aliases={"iw": "he"}), "iw")
    assert result.status is LookupStatus.NOT_FOUND and result.locale is None


def test_by_code_follows_only_one_alias_hop() -> None:
    result = get_locale_by_code(reader(rec("xc"), aliases={"xa": "xb", "xb": "xc"}), "xa")
    assert result.status is LookupStatus.NOT_FOUND


@pytest.mark.parametrize("raw", ["spa", "eng", "ger", "zz"])
def test_by_code_well_formed_but_unknown_is_not_found_without_fallback(raw: str) -> None:
    result = get_locale_by_code(reader(ES, EN), raw)
    assert result.status is LookupStatus.NOT_FOUND
    assert result.locale is None and result.snapshot_version == 3


@pytest.mark.parametrize(
    "raw",
    ["es-AR", "es-419", "pt-BR", "zh-Hant", "es_AR", "x-klingon", "i-klingon", "en-u-ca-gregory"]
    + [" es ", " es", "es ", "", "e", "espa", "e1"],
)
def test_by_code_not_well_formed_is_invalid(raw: str) -> None:
    result = get_locale_by_code(reader(ES), raw)
    assert result.status is LookupStatus.INVALID
    assert result.locale is None and result.snapshot_version == 3 and result.detail


def test_by_code_invalid_is_distinguishable_from_not_found() -> None:
    source = reader(ES)
    assert get_locale_by_code(source, "es-AR").status is not get_locale_by_code(source, "zz").status


# --- listado (RF-11) ---------------------------------------------------------------------------


def test_list_returns_every_published_locale_ordered_by_code() -> None:
    result = list_locales(reader(PT, ES, IW, EN, HE), None)
    assert result.status is LookupStatus.FOUND
    assert [r.code for r in result.locales] == ["en", "es", "he", "iw", "pt"]
    assert result.snapshot_version == 3


def test_list_can_be_restricted_to_active() -> None:
    result = list_locales(reader(PT, ES, IW, HE), "active")
    assert [r.code for r in result.locales] == ["es", "he", "pt"]


def test_list_can_be_restricted_to_inactive() -> None:
    assert [r.code for r in list_locales(reader(ES, IW), "inactive").locales] == ["iw"]


@pytest.mark.parametrize("status", ["", "ACTIVE", "deprecated", "all", " active"])
def test_list_with_an_unknown_status_is_invalid(status: str) -> None:
    result = list_locales(reader(ES), status)
    assert result.status is LookupStatus.INVALID
    assert result.locales == () and result.snapshot_version == 3 and result.detail


# --- catálogo vacío y una sola lectura consistente ---------------------------------------------


def test_empty_catalog_never_fails() -> None:
    empty = FakeReader(version=None)
    by_id = get_locale_by_id(empty, locale_id("es"))
    by_code = get_locale_by_code(empty, "es")
    listing = list_locales(empty, None)
    assert (by_id.status, by_id.snapshot_version) == (LookupStatus.NOT_FOUND, None)
    assert (by_code.status, by_code.snapshot_version) == (LookupStatus.NOT_FOUND, None)
    assert (listing.status, listing.snapshot_version, listing.locales) == (
        LookupStatus.FOUND,
        None,
        (),
    )


def test_each_query_uses_a_single_session_so_version_and_data_are_consistent() -> None:
    source = reader(ES, HE, aliases={"iw": "he"})
    get_locale_by_id(source, locale_id("es"))
    get_locale_by_code(source, "iw")  # busca el código y luego el alias, en la misma sesión
    list_locales(source, "active")
    assert source.sessions == 3
