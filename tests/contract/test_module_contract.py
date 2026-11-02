"""RNF-4: el contrato público de cada módulo es su `interfaces/http`.

Qué cubre cada pieza:
- contrato público: `architecture.json` declara `locales` y `regions` con `public` limitado a su
  `interfaces/http`;
- arquitectura interna: el check `architecture` de AI-NATIVE lo aplica a los imports estáticos
  del repositorio (no inspecciona consumidores externos, tablas ni migraciones);
- acceso directo a persistencia: lo cubren las pruebas de privilegios de las migraciones.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.ai_native import architecture_check

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ["src/gi_common_reference/locales/interfaces/http"]
MODULE = "src/gi_common_reference/locales"
REGIONS_PUBLIC = ["src/gi_common_reference/regions/interfaces/http"]
REGIONS = "src/gi_common_reference/regions"
COUNTRIES_PUBLIC = ["src/gi_common_reference/countries/interfaces/http"]
COUNTRIES = "src/gi_common_reference/countries"
CURRENCIES_PUBLIC = ["src/gi_common_reference/currencies/interfaces/http"]
CURRENCIES = "src/gi_common_reference/currencies"


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


def test_architecture_json_limits_the_public_surface_of_regions_to_interfaces_http() -> None:
    contract: dict[str, Any] = json.loads((ROOT / "architecture.json").read_text(encoding="utf-8"))
    assert contract["modules"]["regions"] == {"path": REGIONS, "public": REGIONS_PUBLIC}
    assert (ROOT / REGIONS_PUBLIC[0]).with_suffix(".py").is_file()


def test_architecture_json_limits_the_public_surface_of_countries_to_interfaces_http() -> None:
    contract: dict[str, Any] = json.loads((ROOT / "architecture.json").read_text(encoding="utf-8"))
    assert contract["modules"]["countries"] == {"path": COUNTRIES, "public": COUNTRIES_PUBLIC}
    assert (ROOT / COUNTRIES_PUBLIC[0]).with_suffix(".py").is_file()


def test_architecture_json_limits_the_public_surface_of_currencies_to_interfaces_http() -> None:
    contract: dict[str, Any] = json.loads((ROOT / "architecture.json").read_text(encoding="utf-8"))
    assert contract["modules"]["currencies"] == {"path": CURRENCIES, "public": CURRENCIES_PUBLIC}


def test_the_check_passes_on_the_repository_with_the_http_layer_in_place() -> None:
    result = run_check(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def sample_project(tmp_path: Path, consumer_source: str) -> Path:
    """Copia el contrato real, crea ambos módulos y agrega un consumidor interno al repositorio."""
    (tmp_path / "architecture.json").write_text(
        (ROOT / "architecture.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    for module in (MODULE, REGIONS, COUNTRIES, CURRENCIES):
        for name in ("domain", "application", "infrastructure", "interfaces"):
            layer = tmp_path / module / name
            layer.mkdir(parents=True)
            (layer / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / module / "interfaces" / "http.py").write_text("", encoding="utf-8")
        (tmp_path / module / "domain" / "model.py").write_text("", encoding="utf-8")
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


@pytest.mark.parametrize("module", ["locales", "regions", "countries", "currencies"])
def test_importing_the_public_surface_is_allowed(tmp_path: Path, module: str) -> None:
    project = sample_project(tmp_path, f"from ..{module}.interfaces import http\n")
    result = run_check(project)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_regions_declaration_is_enforced_for_static_imports(tmp_path: Path) -> None:
    project = sample_project(tmp_path, "from ..regions.domain import model\n")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "public contract" in output and "regions/interfaces/http" in output


def test_regions_cannot_reach_locales_internals(tmp_path: Path) -> None:
    project = sample_project(tmp_path, "")
    source = project / REGIONS / "domain" / "uses_locales.py"
    source.write_text("from ...locales.domain import model\n", encoding="utf-8")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "locales/interfaces/http" in output


def test_the_countries_declaration_is_enforced_for_static_imports(tmp_path: Path) -> None:
    project = sample_project(tmp_path, "from ..countries.domain import model\n")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "public contract" in output and "countries/interfaces/http" in output


@pytest.mark.parametrize("other", ["locales", "regions"])
def test_countries_cannot_reach_other_catalogs_internals(tmp_path: Path, other: str) -> None:
    project = sample_project(tmp_path, "")
    source = project / COUNTRIES / "domain" / "uses_other.py"
    source.write_text(f"from ...{other}.domain import model\n", encoding="utf-8")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert f"{other}/interfaces/http" in output


@pytest.mark.parametrize("other", ["locales", "regions"])
def test_other_catalogs_cannot_reach_countries_internals(tmp_path: Path, other: str) -> None:
    project = sample_project(tmp_path, "")
    source = project / "src" / "gi_common_reference" / other / "domain" / "uses_countries.py"
    source.write_text("from ...countries.domain import model\n", encoding="utf-8")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "countries/interfaces/http" in output


def test_the_currencies_declaration_is_enforced_for_static_imports(tmp_path: Path) -> None:
    project = sample_project(tmp_path, "from ..currencies.domain import model\n")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "public contract" in output and "currencies/interfaces/http" in output


@pytest.mark.parametrize("other", ["locales", "regions", "countries"])
def test_currencies_cannot_reach_other_catalogs_internals(tmp_path: Path, other: str) -> None:
    project = sample_project(tmp_path, "")
    source = project / CURRENCIES / "domain" / "uses_other.py"
    source.write_text(f"from ...{other}.domain import model\n", encoding="utf-8")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert f"{other}/interfaces/http" in output


@pytest.mark.parametrize("other", ["locales", "regions", "countries"])
def test_other_catalogs_cannot_reach_currencies_internals(tmp_path: Path, other: str) -> None:
    """RNF-6, CA-24: nadie de 001-003 depende de Currency."""
    project = sample_project(tmp_path, "")
    source = project / "src" / "gi_common_reference" / other / "domain" / "uses_currencies.py"
    source.write_text("from ...currencies.domain import model\n", encoding="utf-8")
    result = run_check(project)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "currencies/interfaces/http" in output
