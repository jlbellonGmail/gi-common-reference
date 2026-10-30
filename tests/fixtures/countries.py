"""Constructores de snapshots de Countries para pruebas: siempre sellados salvo que se rompan.

TODO el contenido es sintético y NO productivo (S-7 de la spec): los países usan datos ISO 3166-1
reales solo como ejemplos; las banderas de `tests/fixtures/flags/` son rectángulos de color; la
procedencia lo declara. Los `locale_id` de `en` y `es` son los de la política empaquetada
(`required-locales.v1.json`) y los de Region/Subregion salen de `tests/fixtures/regions.py`.
"""

import copy
import hashlib
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gi_common_reference.countries.domain.digest import content_digest
from tests.fixtures.regions import EN, ES, region_id, subregion_id

FLAGS_DIR = Path(__file__).resolve().parent / "flags"
NAMESPACE = uuid.UUID("33333333-4444-5555-6666-777777777777")

# alpha2 → (alpha3, numérico, código de llamada, región M49, subregión M49,
#           nombre en, nombre es, nombre oficial en, nombre oficial es)
Row = tuple[str, str, str | None, str | None, str | None, str, str, str | None, str | None]
COUNTRIES: dict[str, Row] = {
    "AR": (
        "ARG",
        "032",
        "54",
        "019",
        "419",
        "Argentina",
        "Argentina",
        "Argentine Republic",
        "República Argentina",
    ),
    "NA": (
        "NAM",
        "516",
        "264",
        "002",
        "202",
        "Namibia",
        "Namibia",
        "Republic of Namibia",
        "República de Namibia",
    ),
    "AQ": ("ATA", "010", None, None, None, "Antarctica", "Antártida", None, None),
    "TW": ("TWN", "158", "886", None, None, "Taiwan", "Taiwán", None, None),
    "US": (
        "USA",
        "840",
        "1",
        "019",
        "021",
        "United States",
        "Estados Unidos",
        "United States of America",
        "Estados Unidos de América",
    ),
    "CA": ("CAN", "124", "1", "019", "021", "Canada", "Canadá", None, None),
    "PR": ("PRI", "630", "1", "019", "419", "Puerto Rico", "Puerto Rico", None, None),
    "BV": ("BVT", "074", None, "019", "419", "Bouvet Island", "Isla Bouvet", None, None),
    "TP": ("TMP", "626", "670", "142", "035", "East Timor", "Timor Oriental", None, None),
    "TL": (
        "TLS",
        "626",
        "670",
        "142",
        "035",
        "Timor-Leste",
        "Timor-Leste",
        "Democratic Republic of Timor-Leste",
        "República Democrática de Timor-Leste",
    ),
    "AN": (
        "ANT",
        "530",
        "599",
        "019",
        "419",
        "Netherlands Antilles",
        "Antillas Neerlandesas",
        None,
        None,
    ),
    "CW": ("CUW", "531", "599", "019", "419", "Curaçao", "Curazao", None, None),
    "SX": ("SXM", "534", "1", "019", "419", "Sint Maarten", "Sint Maarten", None, None),
    "BQ": (
        "BES",
        "535",
        "599",
        "019",
        "419",
        "Caribbean Netherlands",
        "Caribe Neerlandés",
        None,
        None,
    ),
}
DEFAULT_KEYS = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")
FLAG_EXCEPTIONS = {
    "AQ": "El Tratado Antártico no define una bandera oficial",
    "BV": "Sin bandera propia",
}


def country_id(key: str) -> str:
    """Id estable para pruebas, derivado de la clave (no del código, que puede recodificarse)."""
    return str(uuid.uuid5(NAMESPACE, f"country:{key}"))


def country(key: str, /, identity: str | None = None, **overrides: Any) -> dict[str, Any]:
    """País `active`; `identity` fija la clave del `country_id` si difiere del código."""
    alpha3, numeric, calling, region, subregion, *_ = COUNTRIES[key]
    base: dict[str, Any] = {
        "country_id": country_id(identity or key),
        "alpha2": key,
        "alpha3": alpha3,
        "numeric_code": numeric,
        "region_id": region_id(region) if region else None,
        "subregion_id": subregion_id(subregion) if subregion else None,
        "calling_code": calling,
        "status": "active",
        "replacement_country_id": None,
    }
    return {**base, **overrides}


def names(key: str, /, identity: str | None = None) -> list[dict[str, Any]]:
    *_, name_en, name_es, official_en, official_es = COUNTRIES[key]
    cid = country_id(identity or key)
    return [
        {"country_id": cid, "locale_id": EN, "name": name_en, "official_name": official_en},
        {"country_id": cid, "locale_id": ES, "name": name_es, "official_name": official_es},
    ]


def flag_bytes(key: str) -> bytes:
    return (FLAGS_DIR / f"{key.lower()}.svg").read_bytes()


def flag_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def flag(key: str, /, identity: str | None = None, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "country_id": country_id(identity or key),
        "asset_path": f"{key.lower()}.svg",
        "sha256": flag_digest(flag_bytes(key)),
        "media_type": "image/svg+xml",
        "source": "flags",
    }
    return {**base, **overrides}


def flag_exception(key: str, /, identity: str | None = None) -> dict[str, Any]:
    return {"country_id": country_id(identity or key), "reason": FLAG_EXCEPTIONS[key]}


def provenance(**overrides: Any) -> dict[str, Any]:
    def source(role: str, name: str) -> dict[str, Any]:
        return {
            "role": role,
            "name": name,
            "edition": "synthetic-1",
            "retrieved_at": "2026-10-30",
            "location": "tests/fixtures (sintético, no productivo)",
            "checksum": "sha256:" + "0" * 64,
            "license": "CC0-1.0 (fixture sintético)",
        }

    base: dict[str, Any] = {
        "sources": [
            source("identity", "ISO 3166-1 (sintético)"),
            source("names", "CLDR (sintético)"),
            source("calling_code", "ITU-T E.164 (sintético)"),
            source("classification", "UN M49 (sintético)"),
            source("flags", "Banderas sintéticas de prueba"),
        ],
        "unresolved_conflicts": [],
    }
    return {**base, **overrides}


def recoding_provenance(reference: str = "ISO 3166-1 newsletter") -> dict[str, Any]:
    return {"source": "ISO 3166 Maintenance Agency", "reference": reference}


def recoding(
    identity: str, previous: tuple[str, str, str], new: tuple[str, str, str], **overrides: Any
) -> dict[str, Any]:
    def triple(values: tuple[str, str, str]) -> dict[str, str]:
        return {"alpha2": values[0], "alpha3": values[1], "numeric_code": values[2]}

    base: dict[str, Any] = {
        "country_id": country_id(identity),
        "previous": triple(previous),
        "new": triple(new),
        "provenance": recoding_provenance(f"{previous[0]} → {new[0]}"),
    }
    return {**base, **overrides}


def reassignment(identity: str, code_kind: str, code: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "country_id": country_id(identity),
        "code_kind": code_kind,
        "code": code,
        "provenance": recoding_provenance(f"reasigna {code}"),
    }
    return {**base, **overrides}


def seal(document: dict[str, Any]) -> dict[str, Any]:
    """Recalcula el digest de contenido tras modificar el documento."""
    sealed = copy.deepcopy(document)
    sealed["content_digest"] = content_digest(sealed)
    return sealed


def build_snapshot(
    version: int = 1,
    *,
    keys: Sequence[str] = DEFAULT_KEYS,
    countries: Sequence[dict[str, Any]] | None = None,
    country_names: Sequence[dict[str, Any]] | None = None,
    flags: Sequence[dict[str, Any]] | None = None,
    flag_exceptions: Sequence[dict[str, Any]] | None = None,
    recodings: Sequence[dict[str, Any]] = (),
    code_reassignments: Sequence[dict[str, Any]] = (),
    region_snapshot_version: int = 1,
    catalog_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot válido y sellado. Por defecto: los países de `DEFAULT_KEYS` con nombres en `en` y
    `es`, bandera para cada uno salvo AQ y BV (excepción declarada) y sin recodificaciones."""
    country_list = list(countries) if countries is not None else [country(k) for k in keys]
    document: dict[str, Any] = {
        "snapshot_version": version,
        "content_digest": "",
        "region_snapshot_version": region_snapshot_version,
        "provenance": catalog_provenance if catalog_provenance is not None else provenance(),
        "countries": country_list,
        "country_names": (
            list(country_names)
            if country_names is not None
            else [item for k in keys for item in names(k)]
        ),
        "flags": (
            list(flags)
            if flags is not None
            else [flag(k) for k in keys if k not in FLAG_EXCEPTIONS]
        ),
        "flag_exceptions": (
            list(flag_exceptions)
            if flag_exceptions is not None
            else [flag_exception(k) for k in keys if k in FLAG_EXCEPTIONS]
        ),
        "recodings": list(recodings),
        "code_reassignments": list(code_reassignments),
    }
    return seal(document)


if __name__ == "__main__":
    # Regenera contracts/country-snapshot.v1.example.json:
    #   PYTHONUTF8=1 python -m tests.fixtures.countries > contracts/country-snapshot.v1.example.json
    print(json.dumps(build_snapshot(), indent=2, ensure_ascii=False))
