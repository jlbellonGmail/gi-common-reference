import json
from pathlib import Path
from typing import Any

DIR = Path(__file__).parent
CONTRACTS = DIR.parents[1] / "contracts"


def read(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


def synthetic_registry() -> str:
    return read("iana-synthetic.txt")


def real_registry() -> str:
    return read("iana-language-subtag-registry.txt")


def contract_json(name: str) -> Any:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
