"""Constructores de snapshots de Regions para pruebas: siempre sellados salvo que se rompan.

Los `locale_id` de `en` y `es` son los de la política empaquetada (`required-locales.v1.json`), así
las pruebas de punta a punta usan la política real.
"""

import copy
import uuid
from collections.abc import Sequence
from typing import Any

from gi_common_reference.regions.domain.digest import content_digest
from gi_common_reference.regions.domain.model import LocaleCatalog, LocaleInfo
from gi_common_reference.regions.domain.policy import RequiredLocale, RequiredLocales
from tests.fixtures.snapshots import build_snapshot as build_locale_snapshot
from tests.fixtures.snapshots import locale

EN = "1d806402-a823-4580-9f4d-958c6e5a5354"
ES = "7d74e7f4-4dd7-4a85-a540-09d2393b9a91"
FR = "b8756f67-cbc0-4499-b3b6-453605c505b2"
NAMESPACE = uuid.UUID("22222222-3333-4444-5555-666666666666")
POLICY = RequiredLocales(1, (RequiredLocale(EN, "en"), RequiredLocale(ES, "es")))

# Datos UN M49 reales (nombres oficiales en inglés y español).
REGIONS = {"002": ("Africa", "África"), "019": ("Americas", "Américas"), "142": ("Asia", "Asia")}
SUBREGIONS = {
    "015": ("002", "Northern Africa", "África septentrional"),
    "202": ("002", "Sub-Saharan Africa", "África subsahariana"),
    "419": ("019", "Latin America and the Caribbean", "América Latina y el Caribe"),
    "021": ("019", "Northern America", "América septentrional"),
    "030": ("142", "Eastern Asia", "Asia oriental"),
}


def entity_id(kind: str, key: str) -> str:
    """Id estable para pruebas: `region:019`, `subregion:419` o cualquier otra clave."""
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{key}"))


def region_id(key: str) -> str:
    return entity_id("region", key)


def subregion_id(key: str) -> str:
    return entity_id("subregion", key)


def region(key: str, /, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "region_id": region_id(key),
        "code": key,
        "status": "active",
        "replacement_region_id": None,
    }
    return {**base, **overrides}


def subregion(key: str, parent: str | None = None, /, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "subregion_id": subregion_id(key),
        "region_id": region_id(parent or SUBREGIONS[key][0]),
        "code": key,
        "status": "active",
        "replacement_subregion_id": None,
    }
    return {**base, **overrides}


def region_name(key: str, locale_id: str, name: str) -> dict[str, Any]:
    return {"region_id": region_id(key), "locale_id": locale_id, "name": name}


def subregion_name(key: str, locale_id: str, name: str) -> dict[str, Any]:
    return {"subregion_id": subregion_id(key), "locale_id": locale_id, "name": name}


def names_for_regions(ids: Sequence[str]) -> list[dict[str, Any]]:
    """Nombre en `en` y `es` para cada Region; los ids que no son de M49 reciben uno genérico."""
    known = {region_id(key): names for key, names in REGIONS.items()}
    names: list[dict[str, Any]] = []
    for identifier in ids:
        english, spanish = known.get(
            identifier, (f"Region {identifier[:8]}", f"Región {identifier[:8]}")
        )
        names += [
            {"region_id": identifier, "locale_id": EN, "name": english},
            {"region_id": identifier, "locale_id": ES, "name": spanish},
        ]
    return names


def names_for_subregions(ids: Sequence[str]) -> list[dict[str, Any]]:
    known = {subregion_id(key): (en, es) for key, (_, en, es) in SUBREGIONS.items()}
    names: list[dict[str, Any]] = []
    for identifier in ids:
        english, spanish = known.get(
            identifier, (f"Subregion {identifier[:8]}", f"Subregión {identifier[:8]}")
        )
        names += [
            {"subregion_id": identifier, "locale_id": EN, "name": english},
            {"subregion_id": identifier, "locale_id": ES, "name": spanish},
        ]
    return names


def provenance(reference: str = "UN M49") -> dict[str, Any]:
    return {"source": "UN Statistics Division, M49", "reference": reference}


def recoding(kind: str, key: str, previous: str, new: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "entity_type": kind,
        "entity_id": entity_id(kind, key),
        "previous_code": previous,
        "new_code": new,
        "provenance": provenance(f"M49 recodificación {previous} → {new}"),
    }
    return {**base, **overrides}


def reassignment(kind: str, key: str, code: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "entity_type": kind,
        "entity_id": entity_id(kind, key),
        "code": code,
        "provenance": provenance(f"M49 reasigna {code}"),
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
    regions: Sequence[dict[str, Any]] | None = None,
    subregions: Sequence[dict[str, Any]] | None = None,
    region_names: Sequence[dict[str, Any]] | None = None,
    subregion_names: Sequence[dict[str, Any]] | None = None,
    recodings: Sequence[dict[str, Any]] = (),
    code_reassignments: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Snapshot válido y sellado. Por defecto: Africa y Americas con sus subregiones M49."""
    region_list = list(regions) if regions is not None else [region("002"), region("019")]
    subregion_list = (
        list(subregions)
        if subregions is not None
        else [subregion("015"), subregion("202"), subregion("419"), subregion("021")]
    )
    region_ids = [item["region_id"] for item in region_list]
    subregion_ids = [item["subregion_id"] for item in subregion_list]
    document: dict[str, Any] = {
        "snapshot_version": version,
        "content_digest": "",
        "provenance": provenance(),
        "regions": region_list,
        "subregions": subregion_list,
        "region_names": (
            list(region_names) if region_names is not None else names_for_regions(region_ids)
        ),
        "subregion_names": (
            list(subregion_names)
            if subregion_names is not None
            else names_for_subregions(subregion_ids)
        ),
        "recodings": list(recodings),
        "code_reassignments": list(code_reassignments),
    }
    return seal(document)


def locale_catalog(
    version: int | None = 1, *, inactive: Sequence[str] = (), extra: Sequence[str] = ()
) -> LocaleCatalog:
    """Vista de Locale con `en`, `es`, `fr` (y `extra`); los de `inactive` quedan `inactive`."""
    ids = {"en": EN, "es": ES, "fr": FR}
    ids.update({code: str(uuid.uuid5(NAMESPACE, f"locale:{code}")) for code in extra})
    return LocaleCatalog(
        version,
        tuple(
            LocaleInfo(locale_id, code, "inactive" if code in inactive else "active")
            for code, locale_id in ids.items()
        ),
    )


def locale_snapshot(version: int = 1) -> dict[str, Any]:
    """Snapshot de Locale con `en`, `es` y `fr` usando los ids de la política."""
    ids = {"en": EN, "es": ES, "fr": FR}
    locales = [locale(code, locale_id=locale_id) for code, locale_id in ids.items()]
    return build_locale_snapshot(
        version, file_date=f"2026-09-{version:02d}", codes=tuple(ids), locales=locales
    )
