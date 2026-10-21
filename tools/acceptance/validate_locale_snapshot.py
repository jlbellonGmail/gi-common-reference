"""Valida un snapshot de locales sin base de datos, antes de incorporarlo (aceptación).

1. JSON Schema publicado para PREP (`contracts/locale-snapshot.v1.schema.json`).
2. Lector de la CLI (`read_snapshot_document`: schema empaquetado, claves duplicadas, no enteros).
3. Admisión del dominio de Reference contra un historial vacío (digests, RF-29/30/32/33) y plan
   del catálogo (RF-3/4/15–17/22/26–28).

Uso: python tools/acceptance/validate_locale_snapshot.py <snapshot.json>
"""

import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

from gi_common_reference.locales.domain.catalog import locale_records, plan_catalog_changes
from gi_common_reference.locales.domain.snapshot import evaluate_snapshot
from gi_common_reference.locales.infrastructure.snapshot_reader import read_snapshot_document

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "locale-snapshot.v1.schema.json"


def main(path: Path) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(document))
    print(f"schema publicado: {'OK' if not errors else f'{len(errors)} errores'}")
    if errors:
        return 1

    document = read_snapshot_document(path)
    print("lector de la CLI (schema empaquetado): OK")

    decision = evaluate_snapshot(document, [])
    if not decision.proceeds or decision.registry is None:
        print(f"admisión: RECHAZADO {decision.classification} {decision.violations}")
        return 1
    print(f"admisión: OK (clasificación {decision.classification})")

    plan = plan_catalog_changes(locale_records(document), [], decision.registry)
    if not plan.ok:
        print(f"plan del catálogo: RECHAZADO ({len(plan.violations)} violaciones)")
        for violation in plan.violations[:20]:
            print(f"  - {violation.rule}: {violation.message}")
        return 1
    aliases = decision.registry.language_aliases()
    statuses = Counter(record.status for record in plan.new_locales)
    summary = {
        "snapshot_version": document["snapshot_version"],
        "iana_file_date": document["iana"]["file_date"],
        "locales": len(plan.new_locales),
        "active": statuses["active"],
        "inactive": statuses["inactive"],
        "deprecated": sum(1 for record in plan.new_locales if record.iana_deprecated),
        "aliases": len(aliases),
        "alias_iw": aliases.get("iw"),
        "alias_in": aliases.get("in"),
        "alias_ji": aliases.get("ji"),
    }
    print("plan del catálogo: OK")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
