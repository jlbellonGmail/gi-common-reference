"""T3: lector de la tabla UCUM empaquetada con verificación de sha256 (RNF-7, D8)."""

import hashlib
from collections.abc import Callable
from importlib import resources

import pytest

from gi_common_reference.units.domain.errors import SchemaLoadError
from gi_common_reference.units.infrastructure import ucum_reader
from gi_common_reference.units.infrastructure.ucum_reader import (
    UCUM_PACKAGE,
    UCUM_RESOURCE,
    UCUM_SHA256,
    load_ucum_table,
    parse_ucum_table,
    read_ucum_bytes,
)


def official() -> bytes:
    return read_ucum_bytes()


def test_the_pinned_checksum_is_the_one_of_the_official_file() -> None:
    assert UCUM_SHA256 == "dfccea1b5dc284245ebae97edd1dc03c45864da4e87df55bc9851797b4fd0b61"
    assert hashlib.sha256(official()).hexdigest() == UCUM_SHA256


def test_the_table_is_a_resource_of_the_units_package() -> None:
    assert UCUM_PACKAGE == "gi_common_reference.units.infrastructure"
    path = resources.files(UCUM_PACKAGE).joinpath("ucum").joinpath(UCUM_RESOURCE)
    assert path.read_bytes() == official()


def test_the_loaded_table_reports_version_revision_date_and_checksum() -> None:
    table = load_ucum_table()
    assert table.version == "2.2"
    assert table.revision_date == "2024-06-17"
    assert table.sha256 == UCUM_SHA256


def test_the_table_exposes_prefixes_base_units_and_atoms() -> None:
    table = load_ucum_table()
    assert len(table.prefixes) == 24 and table.prefixes["k"].value == "1e3"
    assert table.prefixes["m"].value == "1e-3" and table.prefixes["Ki"].value == "1024"
    base = {code for code, atom in table.atoms.items() if atom.dimension is not None}
    assert base == {"m", "s", "g", "rad", "K", "C", "cd"}
    assert table.atoms["m"].is_metric and table.atoms["m"].value is None
    assert len(table.atoms) == 305 + 7


def test_atoms_carry_value_unit_and_flags() -> None:
    table = load_ucum_table()
    mile = table.atoms["[mi_i]"]
    assert (mile.value, mile.unit, mile.is_metric) == ("5280", "[ft_i]", False)
    assert not mile.is_special and not mile.is_arbitrary and mile.function is None
    hectare = table.atoms["ar"]
    assert hectare.is_metric and hectare.value == "100" and hectare.unit == "m2"
    assert table.atoms["[hp_X]"].is_arbitrary


def test_special_units_carry_the_function_named_by_the_file() -> None:
    table = load_ucum_table()
    fahrenheit = table.atoms["[degF]"]
    assert fahrenheit.is_special and fahrenheit.function is not None
    assert (fahrenheit.function.name, fahrenheit.function.value, fahrenheit.function.unit) == (
        "degF",
        "5",
        "K/9",
    )
    celsius = table.atoms["Cel"]
    assert celsius.is_special and celsius.function is not None
    assert celsius.function.name == "Cel"


def test_the_non_prefixed_atoms_of_the_initial_catalog_exist() -> None:
    table = load_ucum_table()
    for code in ("[lb_av]", "[oz_av]", "t", "min", "h", "d", "wk", "[in_i]", "[gal_us]", "L", "%"):
        assert code in table.atoms, code
    assert "[ppth]" in table.atoms and "[ppm]" in table.atoms


def append_space(data: bytes) -> bytes:
    return data + b" "


def change_a_prefix_value(data: bytes) -> bytes:
    return data.replace(b'value="1e3"', b'value="1e4"', 1)


def change_line_endings(data: bytes) -> bytes:
    return data.replace(b"\n", b"\r\n")


def truncate(data: bytes) -> bytes:
    return data[:-10]


def empty(data: bytes) -> bytes:
    return b""


def rename_a_prefix(data: bytes) -> bytes:
    return data.replace(b"yotta", b"Yotta", 1)


@pytest.mark.parametrize(
    "tamper",
    [append_space, change_a_prefix_value, change_line_endings, truncate, empty, rename_a_prefix],
)
def test_a_tampered_table_is_rejected_by_checksum(tamper: Callable[[bytes], bytes]) -> None:
    data = tamper(official())
    assert data != official()
    with pytest.raises(SchemaLoadError) as error:
        parse_ucum_table(data)
    assert "sha256" in str(error.value)


def test_the_expected_checksum_can_be_overridden_for_a_different_published_version() -> None:
    data = official()
    table = parse_ucum_table(data, expected_sha256=hashlib.sha256(data).hexdigest())
    assert table.version == "2.2"
    with pytest.raises(SchemaLoadError):
        parse_ucum_table(data, expected_sha256="0" * 64)


def test_a_file_that_matches_the_checksum_but_is_not_ucum_is_an_environment_error() -> None:
    data = b"<root/>"
    with pytest.raises(SchemaLoadError):
        parse_ucum_table(data, expected_sha256=hashlib.sha256(data).hexdigest())
    junk = b"not xml"
    with pytest.raises(SchemaLoadError):
        parse_ucum_table(junk, expected_sha256=hashlib.sha256(junk).hexdigest())


def test_a_missing_resource_is_an_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ucum_reader, "UCUM_RESOURCE", "does-not-exist.xml")
    with pytest.raises(SchemaLoadError):
        ucum_reader.load_ucum_table()
