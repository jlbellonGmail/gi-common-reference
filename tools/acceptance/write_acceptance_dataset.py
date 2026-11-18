"""Escribe el dataset sintético del manual de aceptación (docs/aceptacion-manual.md).

Son exactamente los snapshots que usa `tests/acceptance/test_cross_module_acceptance.py`: mismos
builders, mismos bytes en cada ejecución (deterministas). Contenido SINTÉTICO y NO productivo.

Uso (desde la raíz del repositorio, con el entorno de desarrollo instalado):

    python tools/acceptance/write_acceptance_dataset.py <directorio>

Imprime el sha256 de cada archivo escrito.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tests.acceptance.cross_module_support import (  # noqa: E402
    countries_retiring_pr,
    countries_with_ghost_region,
    currencies_closing_pr,
    currency_snapshot,
    snapshots,
)


def dataset() -> dict[str, dict[str, Any]]:
    v1 = snapshots()
    return {
        "01-locales-v1.json": v1["locales"],
        "02-regions-v1.json": v1["regions"],
        "03-countries-v1.json": v1["countries"],
        "04-currencies-v1.json": v1["currencies"],
        "05-units-v1.json": v1["units"],
        "N1-countries-v2-ghost-region.json": countries_with_ghost_region(),
        "N2-currencies-v2-future-countries.json": currency_snapshot(2, country_snapshot_version=2),
        "D1-countries-v2-retire-pr.json": countries_retiring_pr(),
        "D2-currencies-v2-close-pr.json": currencies_closing_pr(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directorio", type=Path)
    args = parser.parse_args()
    args.directorio.mkdir(parents=True, exist_ok=True)
    for name, document in dataset().items():
        data = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
        (args.directorio / name).write_bytes(data)
        print(f"{hashlib.sha256(data).hexdigest()}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
