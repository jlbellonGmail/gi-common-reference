"""Constructores de snapshots de Currency para pruebas: siempre sellados salvo que se rompan.

TODO el contenido es sintético y NO productivo (S-9 de la spec): las monedas usan datos ISO 4217
reales solo como ejemplos; las asociaciones y sus fechas ilustran los casos de la spec (HRK → EUR,
PAB + USD, readopción); la procedencia lo declara. Los `locale_id` de `en` y `es` son los de la
política empaquetada (`required-locales.v1.json`). Los Country se identifican por un id derivado
de su código alfabético 2 solo dentro de estas pruebas (Currency no importa Countries).

Regenerar el ejemplo publicado: `python -m tests.fixtures.currencies`.
"""

import copy
import json
import uuid
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from gi_common_reference.currencies.domain.digest import content_digest
from gi_common_reference.currencies.domain.model import (
    CountryCatalog,
    CountryInfo,
    LocaleCatalog,
    LocaleInfo,
)
from gi_common_reference.currencies.domain.policy import RequiredLocale, RequiredLocales

EN = "1d806402-a823-4580-9f4d-958c6e5a5354"
ES = "7d74e7f4-4dd7-4a85-a540-09d2393b9a91"
POLICY = RequiredLocales(1, (RequiredLocale(EN, "en"), RequiredLocale(ES, "es")))
NAMESPACE = uuid.UUID("44444444-5555-6666-7777-888888888888")
EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "currency-snapshot.v1.example.json"

# código → (numérico, unidades menores, fondos, nombre en, nombre es)
Row = tuple[str, int | None, bool, str, str]
CURRENCIES: dict[str, Row] = {
    "ARS": ("032", 2, False, "Argentine Peso", "peso argentino"),
    "USD": ("840", 2, False, "US Dollar", "dólar estadounidense"),
    "EUR": ("978", 2, False, "Euro", "euro"),
    "PAB": ("590", 2, False, "Panamanian Balboa", "balboa panameño"),
    "JPY": ("392", 0, False, "Japanese Yen", "yen"),
    "KWD": ("414", 3, False, "Kuwaiti Dinar", "dinar kuwaití"),
    "CLF": ("990", 4, True, "Unidad de Fomento", "unidad de fomento"),
    "XAU": ("959", None, False, "Gold", "oro"),
    "XDR": ("960", None, False, "SDR (Special Drawing Right)", "derechos especiales de giro"),
    "BOB": ("068", 2, False, "Boliviano", "boliviano"),
    "BOV": ("984", 2, True, "Bolivian Mvdol", "mvdol boliviano"),
    "CHF": ("756", 2, False, "Swiss Franc", "franco suizo"),
    "CHE": ("947", 2, True, "WIR Euro", "euro WIR"),
    "CHW": ("948", 2, True, "WIR Franc", "franco WIR"),
    "HRK": ("191", 2, False, "Croatian Kuna", "kuna croata"),
    "CZK": ("203", 2, False, "Czech Koruna", "corona checa"),
    "SKK": ("703", 2, False, "Slovak Koruna", "corona eslovaca"),
    "CSK": ("200", 2, False, "Czechoslovak Koruna", "corona checoslovaca"),
    "VEF": ("937", 2, False, "Venezuelan Bolívar Fuerte", "bolívar fuerte venezolano"),
    "VES": ("928", 2, False, "Venezuelan Bolívar Soberano", "bolívar soberano venezolano"),
    "YUM": ("891", 2, False, "Yugoslavian New Dinar", "nuevo dinar yugoslavo"),
    "CSD": ("891", 2, False, "Serbian Dinar", "dinar serbio"),
}
DEFAULT_CODES = (
    "ARS",
    "USD",
    "EUR",
    "PAB",
    "JPY",
    "KWD",
    "CLF",
    "XAU",
    "XDR",
    "BOB",
    "BOV",
    "CHF",
    "CHE",
    "CHW",
    "HRK",
)
# (país, moneda, inicio, fin) del snapshot por defecto; sin «moneda principal» (D-10)
DEFAULT_ASSOCIATIONS: tuple[tuple[str, str, date | None, date | None], ...] = (
    ("AR", "ARS", None, None),
    ("US", "USD", None, None),
    ("PA", "USD", date(1904, 1, 1), None),
    ("PA", "PAB", date(1904, 1, 1), None),
    ("DE", "EUR", date(1999, 1, 1), None),
    ("FR", "EUR", date(1999, 1, 1), None),
    ("JP", "JPY", None, None),
    ("KW", "KWD", None, None),
    ("CL", "CLF", None, None),
    ("BO", "BOB", None, None),
    ("BO", "BOV", None, None),
    ("CH", "CHF", None, None),
    ("CH", "CHE", None, None),
    ("CH", "CHW", None, None),
    ("HR", "HRK", date(1994, 5, 30), None),
)
COUNTRY_CODES = ("AR", "US", "PA", "DE", "FR", "JP", "KW", "CL", "BO", "CH", "HR", "AQ", "CZ", "SK")


def currency_id(code: str) -> str:
    """Id estable para pruebas, derivado del código (en producción lo asigna Reference)."""
    return str(uuid.uuid5(NAMESPACE, f"currency:{code}"))


def country_id(alpha2: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"country:{alpha2}"))


def association_id(alpha2: str, code: str, n: int = 1) -> str:
    return str(uuid.uuid5(NAMESPACE, f"cc:{alpha2}:{code}:{n}"))


def currency(code: str, /, **overrides: Any) -> dict[str, Any]:
    numeric, units, fund, *_ = CURRENCIES[code]
    base: dict[str, Any] = {
        "currency_id": currency_id(code),
        "alphabetic_code": code,
        "numeric_code": numeric,
        "minor_units": units,
        "fund_code": fund,
        "status": "active",
        "replacement_currency_ids": [],
    }
    return {**base, **overrides}


def names(code: str, /) -> list[dict[str, Any]]:
    *_, name_en, name_es = CURRENCIES[code]
    cid = currency_id(code)
    return [
        {"currency_id": cid, "locale_id": EN, "name": name_en},
        {"currency_id": cid, "locale_id": ES, "name": name_es},
    ]


def association(
    alpha2: str,
    code: str,
    valid_from: date | None = None,
    valid_to: date | None = None,
    *,
    n: int = 1,
    status: str = "active",
    **overrides: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "country_currency_id": association_id(alpha2, code, n),
        "country_id": country_id(alpha2),
        "currency_id": currency_id(code),
        "status": status,
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
    }
    return {**base, **overrides}


def provenance(**overrides: Any) -> dict[str, Any]:
    def source(role: str, name: str) -> dict[str, Any]:
        return {
            "role": role,
            "name": name,
            "edition": "synthetic-1",
            "retrieved_at": "2026-11-01",
            "location": "tests/fixtures (sintético, no productivo)",
            "checksum": "sha256:" + "0" * 64,
            "license": "CC0-1.0 (fixture sintético)",
        }

    base: dict[str, Any] = {
        "sources": [
            source("identity", "ISO 4217 List One (sintético)"),
            source("names", "CLDR (sintético)"),
            source("country_currency", "ISO 4217 entidades (sintético)"),
            source("validity", "CLDR territorio-moneda (sintético)"),
        ],
        "unresolved_conflicts": [],
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
    codes: Sequence[str] = DEFAULT_CODES,
    currencies: Sequence[dict[str, Any]] | None = None,
    currency_names: Sequence[dict[str, Any]] | None = None,
    country_currencies: Sequence[dict[str, Any]] | None = None,
    country_snapshot_version: int = 1,
    catalog_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot válido y sellado. Por defecto: las monedas de `DEFAULT_CODES`, con nombres en `en`
    y `es`, y las asociaciones de `DEFAULT_ASSOCIATIONS`."""
    document: dict[str, Any] = {
        "snapshot_version": version,
        "content_digest": "sha256:" + "0" * 64,
        "country_snapshot_version": country_snapshot_version,
        "provenance": catalog_provenance if catalog_provenance is not None else provenance(),
        "currencies": list(currencies) if currencies is not None else [currency(c) for c in codes],
        "currency_names": (
            list(currency_names)
            if currency_names is not None
            else [row for code in codes for row in names(code)]
        ),
        "country_currencies": (
            list(country_currencies)
            if country_currencies is not None
            else [association(a, c, f, t) for a, c, f, t in DEFAULT_ASSOCIATIONS if c in codes]
        ),
    }
    return seal(document)


def transition_snapshot(version: int = 2) -> dict[str, Any]:
    """HRK → EUR en HR (CL-8, CL-20): HRK inactive con reemplazo EUR, HR–HRK activa y cerrada el
    2023-01-01 (excluido) y HR–EUR abierta desde esa fecha."""
    retired = currency("HRK", status="inactive", replacement_currency_ids=[currency_id("EUR")])
    return build_snapshot(
        version,
        currencies=[currency(c) for c in DEFAULT_CODES if c != "HRK"] + [retired],
        currency_names=[n for c in DEFAULT_CODES for n in names(c)],
        country_currencies=[
            association(a, c, f, t) for a, c, f, t in DEFAULT_ASSOCIATIONS if c != "HRK"
        ]
        + [
            association("HR", "HRK", date(1994, 5, 30), date(2023, 1, 1)),
            association("HR", "EUR", date(2023, 1, 1), n=2),
        ],
    )


def locale_catalog(
    *, snapshot_version: int | None = 1, inactive: Sequence[str] = (), missing: Sequence[str] = ()
) -> LocaleCatalog:
    infos = [
        LocaleInfo(locale_id, code, "inactive" if locale_id in inactive else "active")
        for locale_id, code in ((EN, "en"), (ES, "es"))
        if locale_id not in missing
    ]
    return LocaleCatalog(snapshot_version, tuple(infos))


def country_catalog(
    *,
    snapshot_version: int | None = 1,
    versions: Sequence[int] = (1,),
    inactive: Sequence[str] = (),
    missing: Sequence[str] = (),
) -> CountryCatalog:
    infos = [
        CountryInfo(country_id(code), "inactive" if code in inactive else "active")
        for code in COUNTRY_CODES
        if code not in missing
    ]
    return CountryCatalog(snapshot_version, frozenset(versions), tuple(infos))


if __name__ == "__main__":
    EXAMPLE.write_text(
        json.dumps(build_snapshot(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"escrito {EXAMPLE}")
