"""RNF-4: el contrato público del módulo es `interfaces/http`.

Qué cubre cada pieza:
- contrato público: `architecture.json` declara `locales` con `public` limitado a `interfaces/http`;
- arquitectura interna: el check `architecture` de AI-NATIVE lo aplica a los imports estáticos
  del repositorio (no inspecciona consumidores externos, tablas ni migraciones);
- acceso directo a persistencia: lo cubren las pruebas de privilegios de la migración 0001.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from tests.fixtures.ai_native import architecture_check

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ["src/gi_common_reference/locales/interfaces/http"]
MODULE = "src/gi_common_reference/locales"


def run_check(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(architecture_check()), "--project", str(project)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_architecture_json_limits_the_public_surface_of_locales_to_interfaces_http() -> None:
    contract: dict[str, Any] = json.loads((ROOT / "architecture.json").read_text(encoding="utf-8"))
    assert contract["modules"]["locales"] == {"path": MODULE, "public": PUBLIC}
    assert (ROOT / PUBLIC[0]).with_suffix(".py").is_file()


def test_the_check_passes_on_the_repository_with_the_http_layer_in_place() -> None:
    result = run_check(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def sample_project(tmp_path: Path, consumer_source: str) -> Path:
    """Copia el contrato real y agrega un consumidor interno al repositorio."""
    (tmp_path / "architecture.json").write_text(
        (ROOT / "architecture.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    for name in ("domain", "application", "infrastructure", "interfaces"):
        layer = tmp_path / MODULE / name
        layer.mkdir(parents=True)
        (layer / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / MODULE / "interfaces" / "http.py").write_text("", encoding="utf-8")
    (tmp_path / MODULE / "domain" / "model.py").write_text("", encoding="utf-8")
    consumer = tmp_path / "src" / "gi_common_reference" / "consumer"
    consumer.mkdir(parents=True)
    (consumer / "use.py").write_text(consumer_source, encoding="utf-8")
    return tmp_path


def test_the_declaration_is_enforced_for_static_imports_inside_the_repository(
    tmp_path: Path,
) -> None:
    project = sample_project(tmp_path, "from ..locales.domain import model\n")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "public contract" in output and "locales/interfaces/http" in output


def test_importing_the_public_surface_is_allowed(tmp_path: Path) -> None:
    project = sample_project(tmp_path, "from ..locales.interfaces import http\n")
    result = run_check(project)
    assert result.returncode == 0, result.stdout + result.stderr
