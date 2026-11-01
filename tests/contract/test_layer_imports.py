"""RNF-4, RNF-6: imports absolutos entre capas y entre catálogos.

El check `architecture` de AI-NATIVE solo resuelve imports relativos; esta prueba aplica las
mismas reglas de `architecture.json` a los imports absolutos del paquete. Cada catálogo (`locales`,
`regions`, `countries`) solo importa sus propias capas: importar otro catálogo, aunque sea del
mismo repositorio,
es una violación. La raíz de composición (`gi_common_reference.bootstrap`) solo puede importarse
dentro de un bloque `if __name__ == "__main__":`, el punto de entrada que conecta los adaptadores.
"""

import ast
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "gi_common_reference"
LOCALES = f"{PACKAGE}.locales"
REGIONS = f"{PACKAGE}.regions"
COUNTRIES = f"{PACKAGE}.countries"
CURRENCIES = f"{PACKAGE}.currencies"
COMPOSITION_ROOT = f"{PACKAGE}.bootstrap"


def _layers() -> dict[str, Any]:
    contract = json.loads((ROOT / "architecture.json").read_text(encoding="utf-8"))
    layers: dict[str, Any] = contract["layers"]
    return layers


def _is_main_guard(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
    )


def _imports(node: ast.AST, in_main_guard: bool = False) -> list[tuple[str, bool]]:
    """(módulo importado, dentro de `if __name__ == "__main__"`) de todo el árbol."""
    found: list[tuple[str, bool]] = []
    for child in ast.iter_child_nodes(node):
        inside = in_main_guard or _is_main_guard(child)
        if isinstance(child, ast.Import):
            found.extend((alias.name, inside) for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
            found.append((child.module, inside))
            found.extend((f"{child.module}.{alias.name}", inside) for alias in child.names)
        else:
            found.extend(_imports(child, inside))
    return found


def _catalog_of(base: str) -> str:
    """`src/gi_common_reference/<catálogo>/<capa>` → `<catálogo>`."""
    return Path(base).parts[2]


def violations(root: Path, layers: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for layer, spec in layers.items():
        allowed = {layer, *spec["mayDependOn"]}
        for base in spec["paths"]:
            catalog = _catalog_of(base)
            for path in sorted((root / base).rglob("*.py")):
                rel = path.relative_to(root).as_posix()
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for name, in_main_guard in _imports(tree):
                    parts = name.split(".")
                    if name == COMPOSITION_ROOT or name.startswith(f"{COMPOSITION_ROOT}."):
                        if not in_main_guard:
                            found.append(f"{rel}: {name} (raíz de composición fuera de __main__)")
                    elif parts[0] == PACKAGE and name != PACKAGE and parts[1] != catalog:
                        found.append(f"{rel}: {name} (otro catálogo)")
                    elif parts[0] == PACKAGE and len(parts) > 2 and parts[2] in layers:
                        if parts[2] not in allowed:
                            found.append(f"{rel}: {name} (capa {layer} -> {parts[2]})")
    return found


def test_no_absolute_import_breaks_layer_rules_or_reaches_other_catalogs() -> None:
    assert violations(ROOT, _layers()) == []


# --- la propia prueba detecta violaciones ------------------------------------------------------


def tree_with(tmp_path: Path, files: dict[str, str], catalog: str = "locales") -> Path:
    for name, source in files.items():
        path = tmp_path / "src" / PACKAGE / catalog / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def layers_under(tmp_path: Path) -> dict[str, Any]:
    return {
        name: {
            "paths": [
                f"src/{PACKAGE}/{catalog}/{name}"
                for catalog in ("locales", "regions", "countries", "currencies")
            ],
            "mayDependOn": spec["mayDependOn"],
        }
        for name, spec in _layers().items()
    }


@pytest.mark.parametrize(
    ("file", "source", "expected"),
    [
        ("domain/a.py", f"from {LOCALES}.infrastructure import x\n", "domain -> infrastructure"),
        ("domain/a.py", f"import {LOCALES}.application.incorporate\n", "domain -> application"),
        ("application/a.py", f"from {LOCALES}.infrastructure.pg import x\n", "application ->"),
        (
            "interfaces/a.py",
            f"from {LOCALES}.infrastructure.snapshot_reader import r\n",
            "interfaces ->",
        ),
        ("domain/a.py", f"import {PACKAGE}.countries.model\n", "otro catálogo"),
        ("domain/a.py", f"from {REGIONS}.domain.model import RegionRecord\n", "otro catálogo"),
        ("interfaces/a.py", f"from {COMPOSITION_ROOT} import x\n", "fuera de __main__"),
        (
            "domain/a.py",
            f"def f():\n    from {LOCALES}.interfaces import x\n",
            "domain -> interfaces",
        ),
    ],
)
def test_violations_are_detected(tmp_path: Path, file: str, source: str, expected: str) -> None:
    root = tree_with(tmp_path, {file: source})
    found = violations(root, layers_under(root))
    assert any(expected in item for item in found), found


@pytest.mark.parametrize(
    ("file", "source", "expected"),
    [
        ("domain/a.py", f"from {REGIONS}.infrastructure import x\n", "domain -> infrastructure"),
        ("application/a.py", f"import {REGIONS}.interfaces.http\n", "application -> interfaces"),
        ("domain/a.py", f"from {LOCALES}.domain.model import Violation\n", "otro catálogo"),
        ("infrastructure/a.py", f"import {LOCALES}.infrastructure.conninfo\n", "otro catálogo"),
        ("domain/a.py", f"import {PACKAGE}.countries.model\n", "otro catálogo"),
        ("domain/a.py", f"from {PACKAGE}.currency import model\n", "otro catálogo"),
    ],
)
def test_violations_of_the_regions_catalog_are_detected(
    tmp_path: Path, file: str, source: str, expected: str
) -> None:
    root = tree_with(tmp_path, {file: source}, catalog="regions")
    found = violations(root, layers_under(root))
    assert any(expected in item for item in found), found


def test_composition_root_is_accepted_inside_the_main_guard(tmp_path: Path) -> None:
    source = (
        "def main(): ...\n"
        'if __name__ == "__main__":\n'
        f"    from {COMPOSITION_ROOT} import postgres_repository\n"
        "    main()\n"
    )
    root = tree_with(tmp_path, {"interfaces/cli.py": source})
    assert violations(root, layers_under(root)) == []


def test_allowed_dependencies_are_accepted(tmp_path: Path) -> None:
    root = tree_with(
        tmp_path,
        {
            "application/a.py": f"from {LOCALES}.domain.model import V\n",
            "interfaces/a.py": f"from {LOCALES}.application.incorporate import i\n",
            "infrastructure/a.py": f"from {LOCALES}.domain.ports import P\n",
        },
    )
    assert violations(root, layers_under(root)) == []


def test_allowed_dependencies_inside_regions_are_accepted(tmp_path: Path) -> None:
    root = tree_with(
        tmp_path,
        {
            "application/a.py": f"from {REGIONS}.domain.model import RegionRecord\n",
            "interfaces/a.py": f"from {REGIONS}.application.queries import q\n",
            "infrastructure/a.py": f"from {REGIONS}.domain.ports import P\n",
        },
        catalog="regions",
    )
    assert violations(root, layers_under(root)) == []


@pytest.mark.parametrize(
    ("file", "source", "expected"),
    [
        ("domain/a.py", f"from {COUNTRIES}.infrastructure import x\n", "domain -> infrastructure"),
        ("application/a.py", f"import {COUNTRIES}.interfaces.http\n", "application -> interfaces"),
        ("domain/a.py", f"from {LOCALES}.domain.model import Violation\n", "otro catálogo"),
        ("domain/a.py", f"from {REGIONS}.domain.model import RegionRecord\n", "otro catálogo"),
        ("infrastructure/a.py", f"import {REGIONS}.infrastructure.conninfo\n", "otro catálogo"),
        ("domain/a.py", f"from {PACKAGE}.currency import model\n", "otro catálogo"),
        ("interfaces/a.py", f"from {COMPOSITION_ROOT} import x\n", "fuera de __main__"),
    ],
)
def test_violations_of_the_countries_catalog_are_detected(
    tmp_path: Path, file: str, source: str, expected: str
) -> None:
    root = tree_with(tmp_path, {file: source}, catalog="countries")
    found = violations(root, layers_under(root))
    assert any(expected in item for item in found), found


@pytest.mark.parametrize("catalog", ["locales", "regions"])
def test_other_catalogs_importing_countries_are_detected(tmp_path: Path, catalog: str) -> None:
    root = tree_with(
        tmp_path, {"domain/a.py": f"from {COUNTRIES}.domain.model import C\n"}, catalog=catalog
    )
    found = violations(root, layers_under(root))
    assert any("otro catálogo" in item for item in found), found


def test_allowed_dependencies_inside_countries_are_accepted(tmp_path: Path) -> None:
    root = tree_with(
        tmp_path,
        {
            "application/a.py": f"from {COUNTRIES}.domain.model import CountryRecord\n",
            "interfaces/a.py": f"from {COUNTRIES}.application.queries import q\n",
            "infrastructure/a.py": f"from {COUNTRIES}.domain.ports import P\n",
        },
        catalog="countries",
    )
    assert violations(root, layers_under(root)) == []


@pytest.mark.parametrize(
    ("file", "source"),
    [
        ("domain/a.py", f"from {LOCALES}.domain.model import Violation\n"),
        ("domain/a.py", f"from {REGIONS}.domain.model import RegionRecord\n"),
        ("domain/a.py", f"from {COUNTRIES}.domain.model import CountryRecord\n"),
        ("infrastructure/a.py", f"import {COUNTRIES}.infrastructure.conninfo\n"),
    ],
)
def test_currencies_importing_other_catalogs_is_detected(
    tmp_path: Path, file: str, source: str
) -> None:
    root = tree_with(tmp_path, {file: source}, catalog="currencies")
    found = violations(root, layers_under(root))
    assert any("otro catálogo" in item for item in found), found


@pytest.mark.parametrize("catalog", ["locales", "regions", "countries"])
def test_other_catalogs_importing_currencies_are_detected(tmp_path: Path, catalog: str) -> None:
    """RNF-6: Country (y Locale, Regions) no dependen de Currency."""
    root = tree_with(
        tmp_path, {"domain/a.py": f"from {CURRENCIES}.domain.model import C\n"}, catalog=catalog
    )
    found = violations(root, layers_under(root))
    assert any("otro catálogo" in item for item in found), found


def test_the_composition_root_is_still_forbidden_inside_currencies(tmp_path: Path) -> None:
    root = tree_with(
        tmp_path, {"interfaces/a.py": f"from {COMPOSITION_ROOT} import x\n"}, catalog="currencies"
    )
    assert any("fuera de __main__" in item for item in violations(root, layers_under(root)))


def test_allowed_dependencies_inside_currencies_are_accepted(tmp_path: Path) -> None:
    root = tree_with(
        tmp_path,
        {
            "application/a.py": f"from {CURRENCIES}.domain.model import CurrencyRecord\n",
            "interfaces/a.py": f"from {CURRENCIES}.application.queries import q\n",
            "infrastructure/a.py": f"from {CURRENCIES}.domain.ports import P\n",
        },
        catalog="currencies",
    )
    assert violations(root, layers_under(root)) == []
