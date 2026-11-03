"""Variantes del snapshot de Units para las pruebas de incorporación y de conversión (T6, T7).

`sack_snapshot` agrega al ejemplo sellado una unidad SIN código UCUM (el «saco», asociado a la
masa): no tiene verificación cruzada, así que su factor puede cambiar entre versiones sin chocar con
la definición normativa. Es lo que permite probar un cambio de factor y la reproducibilidad
histórica.
"""

from typing import Any

from tests.fixtures.units import EN, ES, build_snapshot, kind_id, seal, unit_id
from tests.unit.units.helpers import association_row, edit, unit_row

SACK_ID = "6f0e0000-0000-4000-8000-000000000001"
BULK_ID = "6f0e0000-0000-4000-8000-000000000002"


def sack_snapshot(
    version: int = 1, *, factor: str = "60", retired: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Ejemplo + unidad `sack` (sin UCUM ni UNECE) asociada a la masa con `factor` respecto de kg.

    `retired` lista claves de unidad (p. ej. `oz`, `sack`) que pasan a `inactive` junto con sus
    asociaciones.
    """

    def change(document: dict[str, Any]) -> None:
        document["snapshot_version"] = version
        document["units"].append(
            {
                "unit_id": SACK_ID,
                "ucum_code": None,
                "unece_code": None,
                "symbol": "sack",
                "status": "active",
            }
        )
        document["quantity_kind_units"].append(
            {
                "quantity_kind_id": kind_id("mass"),
                "unit_id": SACK_ID,
                "factor": factor,
                "offset": "0",
                "status": "active",
            }
        )
        document["unit_names"] += [
            {"unit_id": SACK_ID, "locale_id": EN, "name": "sack", "plural": "sacks"},
            {"unit_id": SACK_ID, "locale_id": ES, "name": "saco", "plural": None},
        ]
        for key in retired:
            target = SACK_ID if key == "sack" else unit_id(key)
            for row in document["units"]:
                if row["unit_id"] == target:
                    row["status"] = "inactive"
            for row in document["quantity_kind_units"]:
                if row["unit_id"] == target:
                    row["status"] = "inactive"

    return seal(edit(build_snapshot(1), change))


def retired_oz(version: int = 2) -> dict[str, Any]:
    """El ejemplo con `oz` y su asociación a la masa retiradas (status `inactive`)."""

    def change(document: dict[str, Any]) -> None:
        document["snapshot_version"] = version
        unit_row(document, "oz")["status"] = "inactive"
        association_row(document, "mass", "oz")["status"] = "inactive"

    return seal(edit(build_snapshot(1), change))
