"""Constructores de snapshots de Units para pruebas: siempre sellados salvo que se rompan.

TODO el contenido es sintético y NO productivo (S-3 de la spec): el catálogo inicial de S-6 con
datos reales como ejemplo (factores exactos SI/NIST SP 811, códigos UCUM verificados contra la
tabla empaquetada y códigos UNECE Rec 20), pero la procedencia lo declara y los nombres son
sintéticos. Los `locale_id` de `en` y `es` son los de la política empaquetada
(`required-locales.v1.json`). Es la única fuente del ejemplo publicado: una prueba compara
`contracts/units-snapshot.v1.example.json` con `build_snapshot()`.

Regenerar el ejemplo publicado: `python -m tests.fixtures.units`.
"""

import copy
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gi_common_reference.units.domain.digest import content_digest

EN = "1d806402-a823-4580-9f4d-958c6e5a5354"
ES = "7d74e7f4-4dd7-4a85-a540-09d2393b9a91"
# Generado una sola vez; los ids derivados (uuid5) quedan escritos literalmente en el ejemplo.
NAMESPACE = uuid.UUID("e322e8e9-0993-4ab1-96b4-3ae9b47a04d5")
EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "units-snapshot.v1.example.json"
UCUM_SHA256 = "dfccea1b5dc284245ebae97edd1dc03c45864da4e87df55bc9851797b4fd0b61"
UNECE_SHA256 = "e2d06370cdadf5da1bce705783ff5d0d94d11d70eacba6d592adf401c32fb76e"

# clave → (UCUM, UNECE, símbolo, en singular, en plural, es singular, es plural)
UnitRow = tuple[str | None, str | None, str, str, str, str, str]
UNITS: dict[str, UnitRow] = {
    "kg": ("kg", "KGM", "kg", "kilogram", "kilograms", "kilogramo", "kilogramos"),
    "g": ("g", "GRM", "g", "gram", "grams", "gramo", "gramos"),
    "mg": ("mg", "MGM", "mg", "milligram", "milligrams", "miligramo", "miligramos"),
    "t": ("t", "TNE", "t", "tonne", "tonnes", "tonelada", "toneladas"),
    "lb": ("[lb_av]", "LBR", "lb", "pound", "pounds", "libra", "libras"),
    "oz": ("[oz_av]", "ONZ", "oz", "ounce", "ounces", "onza", "onzas"),
    "m": ("m", "MTR", "m", "meter", "meters", "metro", "metros"),
    "mm": ("mm", "MMT", "mm", "millimeter", "millimeters", "milímetro", "milímetros"),
    "cm": ("cm", "CMT", "cm", "centimeter", "centimeters", "centímetro", "centímetros"),
    "km": ("km", "KMT", "km", "kilometer", "kilometers", "kilómetro", "kilómetros"),
    "in": ("[in_i]", "INH", "in", "inch", "inches", "pulgada", "pulgadas"),
    "ft": ("[ft_i]", "FOT", "ft", "foot", "feet", "pie", "pies"),
    "mi": ("[mi_i]", "SMI", "mi", "mile", "miles", "milla", "millas"),
    "m2": (
        "m2",
        "MTK",
        "m²",
        "square meter",
        "square meters",
        "metro cuadrado",
        "metros cuadrados",
    ),
    "cm2": (
        "cm2",
        "CMK",
        "cm²",
        "square centimeter",
        "square centimeters",
        "centímetro cuadrado",
        "centímetros cuadrados",
    ),
    "km2": (
        "km2",
        "KMK",
        "km²",
        "square kilometer",
        "square kilometers",
        "kilómetro cuadrado",
        "kilómetros cuadrados",
    ),
    "ha": ("har", None, "ha", "hectare", "hectares", "hectárea", "hectáreas"),
    "m3": ("m3", "MTQ", "m³", "cubic meter", "cubic meters", "metro cúbico", "metros cúbicos"),
    "cm3": (
        "cm3",
        "CMQ",
        "cm³",
        "cubic centimeter",
        "cubic centimeters",
        "centímetro cúbico",
        "centímetros cúbicos",
    ),
    "mL": ("mL", "MLT", "mL", "milliliter", "milliliters", "mililitro", "mililitros"),
    "L": ("L", "LTR", "L", "liter", "liters", "litro", "litros"),
    "gal": (
        "[gal_us]",
        "GLL",
        "gal",
        "US gallon",
        "US gallons",
        "galón estadounidense",
        "galones estadounidenses",
    ),
    "s": ("s", "SEC", "s", "second", "seconds", "segundo", "segundos"),
    "min": ("min", "MIN", "min", "minute", "minutes", "minuto", "minutos"),
    "h": ("h", "HUR", "h", "hour", "hours", "hora", "horas"),
    "d": ("d", "DAY", "d", "day", "days", "día", "días"),
    "wk": ("wk", "WEE", "wk", "week", "weeks", "semana", "semanas"),
    "K": ("K", "KEL", "K", "kelvin", "kelvins", "kelvin", "kelvin"),
    "Cel": (
        "Cel",
        "CEL",
        "°C",
        "degree Celsius",
        "degrees Celsius",
        "grado Celsius",
        "grados Celsius",
    ),
    "degF": (
        "[degF]",
        "FAH",
        "°F",
        "degree Fahrenheit",
        "degrees Fahrenheit",
        "grado Fahrenheit",
        "grados Fahrenheit",
    ),
    "m/s": (
        "m/s",
        "MTS",
        "m/s",
        "meter per second",
        "meters per second",
        "metro por segundo",
        "metros por segundo",
    ),
    "km/h": (
        "km/h",
        "KMH",
        "km/h",
        "kilometer per hour",
        "kilometers per hour",
        "kilómetro por hora",
        "kilómetros por hora",
    ),
    "mph": (
        "[mi_i]/h",
        "HM",
        "mph",
        "mile per hour",
        "miles per hour",
        "milla por hora",
        "millas por hora",
    ),
    "kg/m3": (
        "kg/m3",
        "KMQ",
        "kg/m³",
        "kilogram per cubic meter",
        "kilograms per cubic meter",
        "kilogramo por metro cúbico",
        "kilogramos por metro cúbico",
    ),
    "g/cm3": (
        "g/cm3",
        "23",
        "g/cm³",
        "gram per cubic centimeter",
        "grams per cubic centimeter",
        "gramo por centímetro cúbico",
        "gramos por centímetro cúbico",
    ),
    "kg/L": (
        "kg/L",
        "B35",
        "kg/L",
        "kilogram per liter",
        "kilograms per liter",
        "kilogramo por litro",
        "kilogramos por litro",
    ),
    "g/L": (
        "g/L",
        "GL",
        "g/L",
        "gram per liter",
        "grams per liter",
        "gramo por litro",
        "gramos por litro",
    ),
    "mg/L": (
        "mg/L",
        "M1",
        "mg/L",
        "milligram per liter",
        "milligrams per liter",
        "miligramo por litro",
        "miligramos por litro",
    ),
    "kg/m2": (
        "kg/m2",
        "28",
        "kg/m²",
        "kilogram per square meter",
        "kilograms per square meter",
        "kilogramo por metro cuadrado",
        "kilogramos por metro cuadrado",
    ),
    "g/m2": (
        "g/m2",
        "GM",
        "g/m²",
        "gram per square meter",
        "grams per square meter",
        "gramo por metro cuadrado",
        "gramos por metro cuadrado",
    ),
    "kg/ha": (
        "kg/har",
        None,
        "kg/ha",
        "kilogram per hectare",
        "kilograms per hectare",
        "kilogramo por hectárea",
        "kilogramos por hectárea",
    ),
    "t/ha": (
        "t/har",
        None,
        "t/ha",
        "tonne per hectare",
        "tonnes per hectare",
        "tonelada por hectárea",
        "toneladas por hectárea",
    ),
    "m3/m2": (
        "m3/m2",
        None,
        "m³/m²",
        "cubic meter per square meter",
        "cubic meters per square meter",
        "metro cúbico por metro cuadrado",
        "metros cúbicos por metro cuadrado",
    ),
    "L/ha": (
        "L/har",
        None,
        "L/ha",
        "liter per hectare",
        "liters per hectare",
        "litro por hectárea",
        "litros por hectárea",
    ),
    "mL/m2": (
        "mL/m2",
        None,
        "mL/m²",
        "milliliter per square meter",
        "milliliters per square meter",
        "mililitro por metro cuadrado",
        "mililitros por metro cuadrado",
    ),
    "each": ("{each}", "H87", "ea", "each", "each", "unidad", "unidades"),
    "one": ("1", "C62", "1", "one", "one", "uno", "uno"),
    "%": ("%", "P1", "%", "percent", "percent", "por ciento", "por ciento"),
    "ppth": (
        "[ppth]",
        "NX",
        "‰",
        "part per thousand",
        "parts per thousand",
        "parte por mil",
        "partes por mil",
    ),
    "ppm": (
        "[ppm]",
        "59",
        "ppm",
        "part per million",
        "parts per million",
        "parte por millón",
        "partes por millón",
    ),
}

# Asociación: (unidad, factor, desplazamiento); la primera es la de referencia (factor 1, desp. 0).
Association = tuple[str, str, str]
# código → (tipo, [asociaciones], nombre en, nombre es)
KindRow = tuple[str, list[Association], str, str]
KINDS: dict[str, KindRow] = {
    "mass": (
        "linear",
        [
            ("kg", "1", "0"),
            ("g", "0.001", "0"),
            ("mg", "0.000001", "0"),
            ("t", "1000", "0"),
            ("lb", "0.45359237", "0"),
            ("oz", "0.028349523125", "0"),
        ],
        "Mass",
        "Masa",
    ),
    "length": (
        "linear",
        [
            ("m", "1", "0"),
            ("mm", "0.001", "0"),
            ("cm", "0.01", "0"),
            ("km", "1000", "0"),
            ("in", "0.0254", "0"),
            ("ft", "0.3048", "0"),
            ("mi", "1609.344", "0"),
        ],
        "Length",
        "Longitud",
    ),
    "area": (
        "linear",
        [("m2", "1", "0"), ("cm2", "0.0001", "0"), ("km2", "1000000", "0"), ("ha", "10000", "0")],
        "Area",
        "Superficie",
    ),
    "volume": (
        "linear",
        [
            ("m3", "1", "0"),
            ("cm3", "0.000001", "0"),
            ("mL", "0.000001", "0"),
            ("L", "0.001", "0"),
            ("gal", "0.003785411784", "0"),
        ],
        "Volume",
        "Volumen",
    ),
    "duration": (
        "linear",
        [("s", "1", "0"), ("min", "60", "0"), ("h", "3600", "0"), ("d", "86400", "0")]
        + [("wk", "604800", "0")],
        "Duration",
        "Duración",
    ),
    "temperature": (
        "affine",
        [("K", "1", "0"), ("Cel", "1", "273.15"), ("degF", "5/9", "459.67")],
        "Temperature",
        "Temperatura",
    ),
    "temperature_difference": (
        "linear",
        [("K", "1", "0"), ("Cel", "1", "0"), ("degF", "5/9", "0")],
        "Temperature difference",
        "Diferencia de temperatura",
    ),
    "speed": (
        "linear",
        [("m/s", "1", "0"), ("km/h", "5/18", "0"), ("mph", "0.44704", "0")],
        "Speed",
        "Velocidad",
    ),
    "density": (
        "linear",
        [("kg/m3", "1", "0"), ("g/cm3", "1000", "0"), ("kg/L", "1000", "0")],
        "Density",
        "Densidad",
    ),
    "mass_concentration": (
        "linear",
        [("kg/m3", "1", "0"), ("g/L", "1", "0"), ("mg/L", "0.001", "0")],
        "Mass concentration",
        "Concentración másica",
    ),
    "mass_per_area": (
        "linear",
        [
            ("kg/m2", "1", "0"),
            ("g/m2", "0.001", "0"),
            ("kg/ha", "0.0001", "0"),
            ("t/ha", "0.1", "0"),
        ],
        "Mass per area",
        "Masa por superficie",
    ),
    "volume_per_area": (
        "linear",
        [("m3/m2", "1", "0"), ("L/ha", "0.0000001", "0"), ("mL/m2", "0.000001", "0")],
        "Volume per area",
        "Volumen por superficie",
    ),
    "count": ("linear", [("each", "1", "0")], "Count", "Conteo"),
    "dimensionless_ratio": (
        "linear",
        [("one", "1", "0"), ("%", "0.01", "0"), ("ppth", "0.001", "0"), ("ppm", "0.000001", "0")],
        "Dimensionless ratio",
        "Razón adimensional",
    ),
}
DEFAULT_KINDS = tuple(KINDS)


def unit_id(key: str) -> str:
    """Id estable para pruebas, derivado de la clave (en producción lo asigna Reference)."""
    return str(uuid.uuid5(NAMESPACE, f"unit:{key}"))


def kind_id(code: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"quantity-kind:{code}"))


def unit(key: str, /, **overrides: Any) -> dict[str, Any]:
    ucum, unece, symbol, *_ = UNITS[key]
    base: dict[str, Any] = {
        "unit_id": unit_id(key),
        "ucum_code": ucum,
        "unece_code": unece,
        "symbol": symbol,
        "status": "active",
    }
    return {**base, **overrides}


def quantity_kind(code: str, /, **overrides: Any) -> dict[str, Any]:
    conversion_type, associations, *_ = KINDS[code]
    base: dict[str, Any] = {
        "quantity_kind_id": kind_id(code),
        "code": code,
        "conversion_type": conversion_type,
        "reference_unit_id": unit_id(associations[0][0]),
        "status": "active",
    }
    return {**base, **overrides}


def associations(code: str, /) -> list[dict[str, Any]]:
    return [
        {
            "quantity_kind_id": kind_id(code),
            "unit_id": unit_id(key),
            "factor": factor,
            "offset": offset,
            "status": "active",
        }
        for key, factor, offset in KINDS[code][1]
    ]


def kind_names(code: str, /) -> list[dict[str, Any]]:
    _, _, name_en, name_es = KINDS[code]
    return [
        {"quantity_kind_id": kind_id(code), "locale_id": EN, "name": name_en},
        {"quantity_kind_id": kind_id(code), "locale_id": ES, "name": name_es},
    ]


def unit_names(key: str, /) -> list[dict[str, Any]]:
    *_, en_one, en_many, es_one, es_many = UNITS[key]
    return [
        {"unit_id": unit_id(key), "locale_id": EN, "name": en_one, "plural": en_many},
        {"unit_id": unit_id(key), "locale_id": ES, "name": es_one, "plural": es_many},
    ]


def unit_keys(codes: Sequence[str]) -> list[str]:
    """Claves de unidad usadas por las magnitudes pedidas, en orden de aparición, sin repetir."""
    seen: dict[str, None] = {}
    for code in codes:
        for key, _, _ in KINDS[code][1]:
            seen.setdefault(key)
    return list(seen)


def provenance(**overrides: Any) -> dict[str, Any]:
    def source(
        role: str, name: str, edition: str, location: str, checksum: str, license_: str
    ) -> dict[str, Any]:
        return {
            "role": role,
            "name": name,
            "edition": edition,
            "retrieved_at": "2026-11-02",
            "location": location,
            "checksum": checksum,
            "license": license_,
        }

    synthetic = "tests/fixtures (sintético, no productivo)"
    base: dict[str, Any] = {
        "sources": [
            source(
                "definitions",
                "BIPM SI Brochure 9th ed. / NIST SP 811 (2008) (sintético)",
                "synthetic-1",
                synthetic,
                "sha256:" + "0" * 64,
                "CC0-1.0 (fixture sintético)",
            ),
            source(
                "ucum",
                "UCUM ucum-essence.xml",
                "2.2 (2024-06-17)",
                "https://raw.githubusercontent.com/ucum-org/ucum/main/ucum-essence.xml"
                " (ejemplo no productivo)",
                "sha256:" + UCUM_SHA256,
                "UCUM License v1.1",
            ),
            source(
                "names",
                "Nombres de unidades (sintético)",
                "synthetic-1",
                synthetic,
                "sha256:" + "0" * 64,
                "CC0-1.0 (fixture sintético)",
            ),
            source(
                "unece",
                "UNECE Rec 20 vía datasets/unece-units-of-measure (sintético)",
                "synthetic-1",
                "units-of-measure.csv (copia derivada; ejemplo no productivo)",
                "sha256:" + UNECE_SHA256,
                "CC0-1.0 (fixture sintético)",
            ),
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
    codes: Sequence[str] = DEFAULT_KINDS,
    quantity_kinds: Sequence[dict[str, Any]] | None = None,
    units: Sequence[dict[str, Any]] | None = None,
    quantity_kind_units: Sequence[dict[str, Any]] | None = None,
    quantity_kind_names: Sequence[dict[str, Any]] | None = None,
    unit_names_: Sequence[dict[str, Any]] | None = None,
    catalog_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot válido y sellado. Por defecto: el catálogo inicial de S-6 con nombres en `en` y
    `es`; `codes` elige magnitudes (y las unidades que usan)."""
    keys = unit_keys(codes)
    document: dict[str, Any] = {
        "snapshot_version": version,
        "content_digest": "sha256:" + "0" * 64,
        "provenance": catalog_provenance if catalog_provenance is not None else provenance(),
        "quantity_kinds": (
            list(quantity_kinds)
            if quantity_kinds is not None
            else [quantity_kind(c) for c in codes]
        ),
        "units": list(units) if units is not None else [unit(k) for k in keys],
        "quantity_kind_units": (
            list(quantity_kind_units)
            if quantity_kind_units is not None
            else [row for code in codes for row in associations(code)]
        ),
        "quantity_kind_names": (
            list(quantity_kind_names)
            if quantity_kind_names is not None
            else [row for code in codes for row in kind_names(code)]
        ),
        "unit_names": (
            list(unit_names_)
            if unit_names_ is not None
            else [row for key in keys for row in unit_names(key)]
        ),
    }
    return seal(document)


if __name__ == "__main__":
    EXAMPLE.write_text(
        json.dumps(build_snapshot(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"escrito {EXAMPLE}")
