"""RNF-4, RNF-6: el contrato de arquitectura existe y el check de AI-NATIVE da PASS."""

import json
import subprocess
from pathlib import Path
from typing import Any

from tests.fixtures.ai_native import architecture_check

ROOT = Path(__file__).resolve().parents[2]
LOCALES = "src/gi_common_reference/locales"


def _contract() -> dict[str, Any]:
    contract: dict[str, Any] = json.loads((ROOT / "architecture.json").read_text(encoding="utf-8"))
    return contract


def test_architecture_json_declares_layers_and_locales_module() -> None:
    contract = _contract()
    layers = contract["layers"]
    assert set(layers) == {"domain", "application", "infrastructure", "interfaces"}
    assert layers["domain"]["mayDependOn"] == []
    assert "locales" in contract["modules"]
    assert contract["modules"]["locales"]["path"] == LOCALES


def test_domain_forbids_infrastructure_and_frameworks() -> None:
    forbidden = set(_contract()["layers"]["domain"]["forbiddenImports"])
    assert {"psycopg", "fastapi", "alembic", "uvicorn"} <= forbidden


def test_ai_native_architecture_check_passes() -> None:
    result = subprocess.run(
        ["node", str(architecture_check()), "--project", str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
