"""Genera un snapshot inicial de locales a partir de un registro IANA, para aceptación y desarrollo.

NO es runtime de Reference ni reemplaza a PREP (`gi-common-reference-prep`), que es el productor
definitivo de snapshots. Sirve para ejercitar el circuito real IANA → snapshot → CLI → base → API.

Es una implementación independiente del contrato (`contracts/locale-snapshot.v1.schema.json` y
`contracts/locale-snapshot.v1.vectors.json`): no importa el dominio de Reference, para que la
admisión posterior con el código de Reference sea un control cruzado y no una tautología.

Reglas aplicadas a cada entrada `Type: language` del registro (spec 001, "Reglas de publicación"):

- se publican solo los subtags simples (no rangos `qaa..qtz`) de 2 o 3 letras;
- se excluyen `Scope: special` y los subtags con *Preferred-Value* (no son su propia forma
  preferida: `iw` no se publica, se resuelve a `he` por alias);
- `iana_deprecated` es la presencia de `Deprecated`; deprecado implica `inactive` (RF-27);
- en una primera publicación no hay `replacement`: todo subtag con *Preferred-Value* queda fuera.

`locale_id` es un UUID aleatorio (plan D4: no se deriva del código). Con `--previous` se conservan
los `locale_id` de un snapshot anterior y solo se generan para códigos nuevos.

Uso:

    python tools/acceptance/build_locale_snapshot.py --registry <registro.txt> \
        --snapshot-version 2 --output <snapshot.json> [--previous <snapshot.json>]
"""

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IANA_SOURCE = "https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry"
TOOL = "gi-common-reference/tools/acceptance/build_locale_snapshot.py"
TOOL_VERSION = "0.1.0"
VECTORS = Path(__file__).resolve().parents[2] / "contracts" / "locale-snapshot.v1.vectors.json"

FIELD = re.compile(r"([A-Za-z][A-Za-z-]*):[ \t]*(.*)")
PUBLISHABLE = re.compile(r"[a-z]{2,3}")


def parse_records(text: str) -> list[dict[str, str]]:
    """Registro record-jar (RFC 5646 §3.1.1): el primero es el encabezado con `File-Date`."""
    records: list[dict[str, str]] = [{}]
    last: str | None = None
    for number, line in enumerate(text.split("\n"), start=1):
        if line.strip() == "%%":
            records.append({})
            last = None
        elif not line.strip():
            continue
        elif line[0] in " \t":
            if last is None:
                raise SystemExit(f"línea {number}: continuación sin campo previo")
            previous = records[-1][last]
            records[-1][last] = f"{previous} {line.strip()}" if previous else line.strip()
        else:
            match = FIELD.fullmatch(line)
            if match is None:
                raise SystemExit(f"línea {number}: no es un campo 'Nombre: valor'")
            last = match.group(1).lower()
            records[-1].setdefault(last, match.group(2).strip())
    return records


def canonical_json(value: Any) -> bytes:
    """JSON canónico de `locale-snapshot.v1.vectors.json`: claves ordenadas, sin espacios."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def check_vectors() -> None:
    """El canonicalizador propio debe reproducir los vectores publicados para PREP."""
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    for case in vectors["content_digest"]:
        body = {k: v for k, v in case["document"].items() if k != "content_digest"}
        if canonical_json(body).decode("utf-8") != case["canonical"]:
            raise SystemExit(f"vector {case['name']}: JSON canónico distinto")
        if sha256(canonical_json(body)) != case["digest"]:
            raise SystemExit(f"vector {case['name']}: digest distinto")


def build_locales(
    records: list[dict[str, str]], previous_ids: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    locales: list[dict[str, Any]] = []
    skipped = {"range": 0, "format": 0, "scope_special": 0, "preferred_value": 0}
    for fields in records[1:]:
        if fields.get("type") != "language":
            continue
        subtag = fields["subtag"]
        code = subtag.lower()
        if ".." in subtag:
            skipped["range"] += 1
        elif not PUBLISHABLE.fullmatch(code):
            skipped["format"] += 1
        elif fields.get("scope") == "special":
            skipped["scope_special"] += 1
        elif "preferred-value" in fields:
            skipped["preferred_value"] += 1
        else:
            deprecated = "deprecated" in fields
            locales.append(
                {
                    "locale_id": previous_ids.get(code) or str(uuid.uuid4()),
                    "code": code,
                    "status": "inactive" if deprecated else "active",
                    "iana_deprecated": deprecated,
                    "replacement_locale_id": None,
                }
            )
    locales.sort(key=lambda locale: locale["code"])
    return locales, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", type=Path, required=True, help="registro IANA (UTF-8, LF)")
    parser.add_argument("--snapshot-version", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path, help="snapshot anterior cuyos ids se conservan")
    parser.add_argument("--registry-origin", default="", help="de dónde se tomó el archivo")
    args = parser.parse_args(argv)

    check_vectors()
    raw = args.registry.read_bytes()
    if b"\r" in raw:
        raise SystemExit(
            "el registro tiene CR: el archivo de IANA usa LF. En Windows, el checkout con "
            "core.autocrlf lo convierte; extraer el blob con `git cat-file blob <rev>:<ruta>`."
        )
    text = raw.decode("utf-8")
    records = parse_records(text)
    file_date = records[0].get("file-date", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", file_date):
        raise SystemExit(f"File-Date ausente o inválido: {file_date!r}")

    previous_ids: dict[str, str] = {}
    if args.previous:
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
        previous_ids = {item["code"]: item["locale_id"] for item in previous["locales"]}

    locales, skipped = build_locales(records, previous_ids)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    iana_provenance: dict[str, str] = {"source": IANA_SOURCE}
    if args.registry_origin:
        iana_provenance["copied_from"] = args.registry_origin
    document: dict[str, Any] = {
        "snapshot_version": args.snapshot_version,
        "iana": {
            "file_date": file_date,
            "digest": sha256(text.encode("utf-8")),
            "provenance": iana_provenance,
            "registry_text": text,
        },
        "provenance": {
            "source": TOOL,
            "tool_version": TOOL_VERSION,
            "generated_at": now,
            "purpose": "aceptación/desarrollo; no es un snapshot de PREP",
        },
        "locales": locales,
    }
    document["content_digest"] = sha256(canonical_json(document))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    summary = {
        "snapshot_version": args.snapshot_version,
        "file_date": file_date,
        "iana_digest": document["iana"]["digest"],
        "content_digest": document["content_digest"],
        "locales": len(locales),
        "active": sum(1 for item in locales if item["status"] == "active"),
        "inactive": sum(1 for item in locales if item["status"] == "inactive"),
        "deprecated": sum(1 for item in locales if item["iana_deprecated"]),
        "excluded": skipped,
        "reused_ids": sum(1 for item in locales if item["code"] in previous_ids),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
