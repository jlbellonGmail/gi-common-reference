"""L-1: fuera de `locales` solo `interfaces.http` es importable, salvo la raíz de composición.

`architecture.json` declara público únicamente `locales/interfaces/http`. El check de AI-NATIVE solo
resuelve imports relativos, así que esta prueba aplica la regla a los imports absolutos de todo el
código fuente que no pertenece a `locales`. `bootstrap.py` es la única excepción: es la raíz de
composición, cuyo trabajo es cablear los puertos del dominio con los adaptadores de infraestructura.
Su lista de imports internos está fijada aquí y no puede crecer sin que esta prueba lo diga.
"""

import ast
import json
from pathlib import Path
from typing import Any

from tests.contract.test_layer_imports import _imports

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "gi_common_reference"
LOCALES = f"{PACKAGE}.locales"
PUBLIC = f"{LOCALES}.interfaces.http"
ANCESTORS = {PACKAGE, LOCALES, f"{LOCALES}.interfaces"}
COMPOSITION_ROOT = "bootstrap.py"
COMPOSITION_ROOT_MAY_IMPORT = {
    f"{LOCALES}.domain.ports",
    f"{LOCALES}.infrastructure.postgres_reader",
    f"{LOCALES}.infrastructure.postgres_repository",
    f"{LOCALES}.infrastructure.snapshot_reader",
}
SOURCE = ROOT / "src" / PACKAGE


def internal_imports(path: Path) -> set[str]:
    """Imports de `locales` que no son la superficie pública (ni paquetes que la contienen)."""
    names = {name for name, _ in _imports(ast.parse(path.read_text(encoding="utf-8")))}
    return {
        name
        for name in names
        if (name == LOCALES or name.startswith(f"{LOCALES}."))
        and name not in ANCESTORS
        and name != PUBLIC
        and not name.startswith(f"{PUBLIC}.")
    }


def _within(name: str, allowed: set[str]) -> bool:
    return any(name == module or name.startswith(f"{module}.") for module in allowed)


def violations(source_root: Path) -> list[str]:
    """Módulos fuera de `locales` que importan sus internos sin ser la raíz de composición."""
    found: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if relative.parts[0] == "locales":
            continue
        internals = internal_imports(path)
        if relative.as_posix() == COMPOSITION_ROOT:
            internals = {n for n in internals if not _within(n, COMPOSITION_ROOT_MAY_IMPORT)}
        found.extend(f"{relative.as_posix()}: {name}" for name in sorted(internals))
    return found


def test_only_the_composition_root_imports_locales_internals() -> None:
    assert violations(SOURCE) == []


def test_app_depends_only_on_the_public_surface() -> None:
    assert internal_imports(SOURCE / "app.py") == set()


def test_the_composition_root_allowlist_is_not_stale() -> None:
    """Cada módulo autorizado se usa de verdad; si deja de usarse, hay que sacarlo de la lista."""
    imported = internal_imports(SOURCE / COMPOSITION_ROOT)
    for allowed in COMPOSITION_ROOT_MAY_IMPORT:
        assert any(_within(name, {allowed}) for name in imported), allowed


def test_the_composition_root_documents_its_exception() -> None:
    docstring = ast.get_docstring(ast.parse((SOURCE / COMPOSITION_ROOT).read_text("utf-8"))) or ""
    assert "Raíz de composición" in docstring and "único módulo" in docstring


def test_the_public_surface_is_the_one_declared_in_architecture_json() -> None:
    contract: dict[str, Any] = json.loads((ROOT / "architecture.json").read_text("utf-8"))
    declared = contract["modules"]["locales"]["public"]
    assert declared == [f"src/{PUBLIC.replace('.', '/')}"]


def test_http_reexports_what_the_app_needs() -> None:
    from gi_common_reference.locales.interfaces import http

    assert {"LocaleReader", "LocaleSession", "create_api"} <= set(http.__all__)


# --- la propia prueba detecta violaciones ------------------------------------------------------


def tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def test_an_external_module_importing_a_domain_internal_is_detected(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app.py": f"from {LOCALES}.domain.ports import LocaleReader\n"})
    assert any("app.py" in item and "domain.ports" in item for item in violations(root))


def test_an_external_module_importing_the_cli_or_infrastructure_is_detected(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "other.py": f"from {LOCALES}.interfaces import cli\n",
            "more/x.py": f"import {LOCALES}.infrastructure.postgres_reader\n",
        },
    )
    found = violations(root)
    assert any("other.py" in item and "interfaces.cli" in item for item in found)
    assert any("more/x.py" in item and "infrastructure" in item for item in found)


def test_the_public_surface_is_accepted_for_any_importer(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "app.py": f"from {PUBLIC} import create_api\nimport {PUBLIC}\n",
            "bootstrap.py": f"from {LOCALES}.interfaces import http\n",
        },
    )
    assert violations(root) == []


def test_the_composition_root_cannot_import_anything_beyond_its_allowlist(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "bootstrap.py": (
                f"from {LOCALES}.domain.ports import LocaleReader\n"
                f"from {LOCALES}.infrastructure.postgres_reader import PostgresLocaleReader\n"
                f"from {LOCALES}.application.queries import list_locales\n"
                f"from {LOCALES}.interfaces.cli import main\n"
            )
        },
    )
    found = violations(root)
    assert any("application.queries" in item for item in found)
    assert any("interfaces.cli" in item for item in found)
    assert not any("domain.ports" in item or "postgres_reader" in item for item in found)


def test_modules_inside_locales_are_not_this_tests_business(tmp_path: Path) -> None:
    root = tree(tmp_path, {"locales/domain/a.py": f"from {LOCALES}.infrastructure import x\n"})
    assert violations(root) == []
