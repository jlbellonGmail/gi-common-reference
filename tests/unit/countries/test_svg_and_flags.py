"""T7: verificación de assets SVG y almacén de banderas (RF-19, RF-49, RF-50)."""

import hashlib
from pathlib import Path

import pytest

from gi_common_reference.countries.application.flags import (
    FlagReadError,
    read_verified_flag,
    verify_flag_declarations,
)
from gi_common_reference.countries.domain.model import FlagDeclaration
from gi_common_reference.countries.domain.svg import (
    MAX_SVG_BYTES,
    sha256_of,
    svg_content_problems,
)
from gi_common_reference.countries.infrastructure.flag_store import (
    DirectoryFlagStore,
    packaged_flag_store,
)
from tests.fixtures.countries import FLAGS_DIR, flag_bytes, flag_digest

NS = 'xmlns="http://www.w3.org/2000/svg"'
XLINK = 'xmlns:xlink="http://www.w3.org/1999/xlink"'


def svg(body: str, attributes: str = "") -> bytes:
    return f"<svg {NS} {XLINK} {attributes}>{body}</svg>".encode()


VALID = [
    svg('<rect width="3" height="2" fill="#74acdf"/>'),
    svg('<defs><linearGradient id="g"/></defs><rect fill="url(#g)" width="1" height="1"/>'),
    svg('<defs><path id="p" d="M0 0"/></defs><use href="#p"/><use xlink:href="#p"/>'),
    svg('<rect style="fill:url(#g);stroke:red"/>'),
    svg("<style>rect { fill: url(#g); }</style><rect/>"),
    b'<?xml version="1.0" encoding="UTF-8"?>\n' + svg("<title>Flag</title>"),
]
REJECTED = {
    "doctype": b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd">' + svg(""),
    "doctype lowercase": b"<!doctype svg>" + svg(""),
    "entity": b'<!DOCTYPE svg [<!ENTITY a "x">]>' + svg("&a;"),
    "billion laughs": b'<!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]>' + svg("&b;"),
    "not svg root": b"<html xmlns='http://www.w3.org/1999/xhtml'/>",
    "svg without namespace": b"<svg><rect/></svg>",
    "script": svg("<script>alert(1)</script>"),
    "script uppercase": svg("<SCRIPT>alert(1)</SCRIPT>"),
    "foreignObject": svg("<foreignObject><div/></foreignObject>"),
    "iframe": svg("<iframe src='#a'/>"),
    "object": svg("<object data='#a'/>"),
    "embed": svg("<embed src='#a'/>"),
    "onload": svg("<rect/>", 'onload="x()"'),
    "onclick on child": svg('<rect onclick="x()"/>'),
    "ONCLICK uppercase": svg('<rect ONCLICK="x()"/>'),
    "http href": svg('<image href="http://example.com/a.png"/>'),
    "https xlink href": svg('<image xlink:href="https://example.com/a.png"/>'),
    "javascript href": svg('<a href="javascript:alert(1)"/>'),
    "data href": svg('<image href="data:image/png;base64,AAAA"/>'),
    "relative href": svg('<image href="other.svg"/>'),
    "src": svg('<rect src="http://example.com"/>'),
    "empty fragment": svg('<use href="#"/>'),
    "style url": svg('<rect style="fill:url(http://example.com/a)"/>'),
    "style url quoted": svg("<rect style=\"fill:url('http://example.com/a')\"/>"),
    "attribute url": svg('<rect fill="url(http://example.com/a)"/>'),
    "style element import": svg("<style>@import url(http://example.com/a.css);</style>"),
    "style element url": svg("<style>rect { fill: url(http://example.com/a); }</style>"),
    "stylesheet pi": b'<?xml-stylesheet href="http://example.com/a.css"?>' + svg(""),
    "not well formed": b"<svg " + NS.encode() + b"><rect></svg>",
    "empty": b"",
    "not xml": b"just text",
    "utf-16": svg("<rect/>").decode().encode("utf-16"),
    "nul byte": svg("<rect/>") + b"\x00",
    "invalid utf-8": b"\xff\xfe<svg/>",
    "too large": svg("<!-- " + "x" * MAX_SVG_BYTES + " -->"),
}


@pytest.mark.parametrize("data", VALID)
def test_valid_svgs_are_accepted(data: bytes) -> None:
    assert svg_content_problems(data) == []


@pytest.mark.parametrize("data", [pytest.param(v, id=k) for k, v in REJECTED.items()])
def test_active_or_malformed_content_is_rejected(data: bytes) -> None:
    assert svg_content_problems(data)


def test_every_fixture_flag_is_a_valid_svg() -> None:
    files = sorted(FLAGS_DIR.glob("*.svg"))
    assert len(files) >= 13
    for path in files:
        assert svg_content_problems(path.read_bytes()) == [], path.name


def test_the_size_limit_is_512_kib_and_exactly_the_limit_is_accepted() -> None:
    assert MAX_SVG_BYTES == 512 * 1024
    head, tail = f"<svg {NS}><!-- ".encode(), b" --></svg>"
    filler = b"x" * (MAX_SVG_BYTES - len(head) - len(tail))
    assert svg_content_problems(head + filler + tail) == []
    assert svg_content_problems(head + filler + b"x" + tail)


def test_the_checksum_is_computed_over_the_exact_bytes() -> None:
    lf, crlf = b"<svg " + NS.encode() + b"/>\n", b"<svg " + NS.encode() + b"/>\r\n"
    assert sha256_of(lf) == "sha256:" + hashlib.sha256(lf).hexdigest()
    assert sha256_of(lf) != sha256_of(crlf)
    assert flag_digest(flag_bytes("AR")) == sha256_of(flag_bytes("AR"))


# --- almacén y verificación de lo declarado ------------------------------------------------------


def declaration(path: str, data: bytes, *, sha256: str | None = None) -> FlagDeclaration:
    return FlagDeclaration("c1", path, sha256 or sha256_of(data), "image/svg+xml", "flags")


@pytest.fixture
def store(tmp_path: Path) -> DirectoryFlagStore:
    (tmp_path / "4x3").mkdir()
    (tmp_path / "ar.svg").write_bytes(VALID[0])
    (tmp_path / "4x3" / "na.svg").write_bytes(VALID[1])
    (tmp_path / "bad.svg").write_bytes(REJECTED["script"])
    return DirectoryFlagStore(tmp_path)


def test_the_directory_store_reads_files_by_relative_path(store: DirectoryFlagStore) -> None:
    assert store.read("ar.svg") == VALID[0]
    assert store.read("4x3/na.svg") == VALID[1]
    assert store.read("missing.svg") is None
    assert store.read("4x3") is None  # un directorio no es un asset


@pytest.mark.parametrize("path", ["../ar.svg", "/ar.svg", "a/../ar.svg", "ar.png", "a\\b.svg", ""])
def test_the_store_never_reads_outside_its_root(
    tmp_path: Path, store: DirectoryFlagStore, path: str
) -> None:
    (tmp_path.parent / "outside.svg").write_bytes(VALID[0])
    assert store.read(path) is None


def test_the_packaged_store_serves_the_package_directory_and_reads_no_network() -> None:
    packaged = packaged_flag_store()
    assert packaged.read("does-not-exist.svg") is None
    assert packaged.read("README.md") is None  # solo .svg


def test_declared_flags_that_match_their_asset_pass(store: DirectoryFlagStore) -> None:
    flags = [declaration("ar.svg", VALID[0]), declaration("4x3/na.svg", VALID[1])]
    assert verify_flag_declarations(flags, store) == []


def test_a_missing_asset_is_detected(store: DirectoryFlagStore) -> None:
    problems = verify_flag_declarations([declaration("gone.svg", b"x")], store)
    assert [p.rule for p in problems] == ["RF-49"] and "no existe" in problems[0].message


def test_a_checksum_mismatch_is_detected(store: DirectoryFlagStore) -> None:
    problems = verify_flag_declarations(
        [declaration("ar.svg", VALID[0], sha256="sha256:" + "0" * 64)], store
    )
    assert [p.rule for p in problems] == ["RF-49"] and "suma" in problems[0].message


def test_active_content_is_reported_even_when_the_checksum_matches(
    store: DirectoryFlagStore,
) -> None:
    problems = verify_flag_declarations([declaration("bad.svg", REJECTED["script"])], store)
    assert [p.rule for p in problems] == ["RF-49"] and "script" in problems[0].message.lower()


def test_an_unsafe_declared_path_is_rejected_without_touching_the_store(tmp_path: Path) -> None:
    class Exploding:
        def read(self, asset_path: str) -> bytes | None:
            raise AssertionError("no debe consultarse el almacén")

    problems = verify_flag_declarations([declaration("../ar.svg", b"x")], Exploding())
    assert [p.rule for p in problems] == ["RF-49"]


def test_every_problem_of_every_flag_is_reported(store: DirectoryFlagStore) -> None:
    flags = [
        declaration("gone.svg", b"x"),
        declaration("bad.svg", REJECTED["script"]),
        declaration("ar.svg", VALID[0], sha256="sha256:" + "1" * 64),
    ]
    assert len(verify_flag_declarations(flags, store)) == 3


# --- servir una bandera verificada (RF-50) -------------------------------------------------------


def test_a_verified_flag_is_served_with_its_checksum(store: DirectoryFlagStore) -> None:
    served = read_verified_flag(store, "ar.svg", sha256_of(VALID[0]))
    assert served == VALID[0]


def test_serving_detects_a_file_that_no_longer_matches_what_was_registered(
    store: DirectoryFlagStore,
) -> None:
    with pytest.raises(FlagReadError) as error:
        read_verified_flag(store, "ar.svg", "sha256:" + "0" * 64)
    assert error.value.reason == "checksum_mismatch"


def test_serving_a_missing_asset_is_an_integrity_error(store: DirectoryFlagStore) -> None:
    with pytest.raises(FlagReadError) as error:
        read_verified_flag(store, "gone.svg", "sha256:" + "0" * 64)
    assert error.value.reason == "missing_asset"
