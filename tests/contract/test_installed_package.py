"""M-1: la CLI funciona desde el paquete instalado, sin depender del checkout fuente.

Se construye el wheel del proyecto (con el backend de build `setuptools`, sin red), se extrae en un
directorio aparte y se ejecuta la CLI con ese directorio como único origen de `gi_common_reference`
y desde un directorio de trabajo vacío. Así, un schema que no viaje en el wheel, o una ruta
calculada relativa a los fuentes, hace fallar la prueba.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from gi_common_reference.locales.infrastructure.snapshot_reader import SCHEMA_RESOURCE

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_IN_WHEEL = f"gi_common_reference/locales/infrastructure/{SCHEMA_RESOURCE}"
SECRET = "SECRETPW"
UNREACHABLE = f"postgresql://user:{SECRET}@127.0.0.1:1/db?connect_timeout=1"
CLI = ["-m", "gi_common_reference.locales.interfaces.cli", "incorporate"]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if importlib.util.find_spec("setuptools") is None:
        pytest.fail("falta `setuptools` (extra `dev`): ver docs/desarrollo.md")
    project = tmp_path_factory.mktemp("project")
    shutil.copy(ROOT / "pyproject.toml", project)
    shutil.copytree(
        ROOT / "src",
        project / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    build = "from setuptools import build_meta; build_meta.build_wheel('dist')"
    done = subprocess.run(
        [sys.executable, "-c", build], cwd=project, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr
    (built,) = (project / "dist").glob("*.whl")
    return built


@pytest.fixture(scope="module")
def site(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Wheel extraído: lo único que el proceso hijo ve de `gi_common_reference`."""
    target = tmp_path_factory.mktemp("site")
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(target)
    return target


def run_python(
    site: Path, *args: str, cwd: Path, environ: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update({"PYTHONPATH": str(site), **(environ or {})})
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    return empty


def write_snapshot(directory: Path, document: object) -> Path:
    path = directory / "snapshot.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_the_wheel_contains_the_schema(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        assert SCHEMA_IN_WHEEL in archive.namelist()


def test_the_child_process_imports_the_installed_copy_and_loads_the_schema(
    site: Path, elsewhere: Path
) -> None:
    code = (
        "import gi_common_reference.locales.infrastructure.snapshot_reader as m;"
        "print(m.__file__);print(m.load_snapshot_schema()['$id'])"
    )
    done = run_python(site, "-c", code, cwd=elsewhere)
    assert done.returncode == 0, done.stderr
    module_file, schema_id = done.stdout.splitlines()
    assert Path(module_file).is_relative_to(site) and not Path(module_file).is_relative_to(ROOT)
    assert schema_id == "urn:gi:common-reference:locale-snapshot:v1"


def test_cli_validates_a_snapshot_against_the_installed_schema(site: Path, elsewhere: Path) -> None:
    snapshot = write_snapshot(elsewhere, {"snapshot_version": 1})
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(site, *CLI, str(snapshot), cwd=elsewhere, environ=environ)
    assert done.returncode == 1, done.stderr
    assert "snapshot inválido" in done.stderr and "content_digest" in done.stderr
    assert "instalación incompleta" not in done.stderr


def test_cli_reaches_the_database_with_a_valid_snapshot_and_hides_the_connection(
    site: Path, elsewhere: Path
) -> None:
    example = json.loads(
        (ROOT / "contracts" / "locale-snapshot.v1.example.json").read_text("utf-8")
    )
    snapshot = write_snapshot(elsewhere, example)
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(site, *CLI, str(snapshot), cwd=elsewhere, environ=environ)
    assert done.returncode == 2, done.stderr
    assert "falló la base de datos" in done.stderr
    assert "instalación incompleta" not in done.stderr
    assert SECRET not in done.stdout + done.stderr


def test_a_missing_schema_in_the_installation_is_reported_as_such(
    site: Path, elsewhere: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "broken-site"
    shutil.copytree(site, broken)
    (broken / SCHEMA_IN_WHEEL).unlink()
    snapshot = write_snapshot(elsewhere, {"snapshot_version": 1})
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(broken, *CLI, str(snapshot), cwd=elsewhere, environ=environ)
    assert done.returncode == 2, done.stderr
    assert "instalación incompleta" in done.stderr and SCHEMA_RESOURCE in done.stderr
    assert "no se pudo leer" not in done.stderr


def test_an_unreadable_snapshot_is_not_blamed_on_the_installation(
    site: Path, elsewhere: Path
) -> None:
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(site, *CLI, str(elsewhere / "no-existe.json"), cwd=elsewhere, environ=environ)
    assert done.returncode == 2, done.stderr
    assert "no se pudo leer" in done.stderr and "instalación incompleta" not in done.stderr


# --- Regions (spec 002): schema y política viajan en el wheel ----------------------------------

REGIONS_RESOURCES = (
    "gi_common_reference/regions/infrastructure/region-snapshot.v1.schema.json",
    "gi_common_reference/regions/infrastructure/required-locales.v1.json",
)
REGIONS_CLI = ["-m", "gi_common_reference.regions.interfaces.cli", "incorporate"]


def test_the_wheel_contains_the_regions_schema_and_policy(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    for resource in REGIONS_RESOURCES:
        assert resource in names, resource


def test_the_regions_cli_reaches_the_database_from_the_installed_copy(
    site: Path, elsewhere: Path
) -> None:
    example = json.loads(
        (ROOT / "contracts" / "region-snapshot.v1.example.json").read_text("utf-8")
    )
    snapshot = write_snapshot(elsewhere, example)
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(site, *REGIONS_CLI, str(snapshot), cwd=elsewhere, environ=environ)
    assert done.returncode == 2, done.stderr
    assert "falló la base de datos" in done.stderr
    assert "instalación incompleta" not in done.stderr
    assert SECRET not in done.stdout + done.stderr


@pytest.mark.parametrize("resource", REGIONS_RESOURCES)
def test_a_missing_regions_resource_is_reported_as_an_incomplete_installation(
    site: Path, elsewhere: Path, tmp_path: Path, resource: str
) -> None:
    broken = tmp_path / "broken-site"
    shutil.copytree(site, broken)
    (broken / resource).unlink()
    snapshot = write_snapshot(elsewhere, {"snapshot_version": 1})
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(broken, *REGIONS_CLI, str(snapshot), cwd=elsewhere, environ=environ)
    assert done.returncode == 2, done.stderr
    assert "instalación incompleta" in done.stderr and Path(resource).name in done.stderr


# --- Countries (spec 003): schema, política y directorio de assets viajan en el wheel ----------

COUNTRIES_RESOURCES = (
    "gi_common_reference/countries/infrastructure/country-snapshot.v1.schema.json",
    "gi_common_reference/countries/infrastructure/required-locales.v1.json",
    "gi_common_reference/countries/assets/__init__.py",
    "gi_common_reference/countries/assets/flags/README.md",
)
COUNTRIES_CLI = ["-m", "gi_common_reference.countries.interfaces.cli", "incorporate"]


def test_the_wheel_contains_the_countries_schema_policy_and_flag_assets_directory(
    wheel: Path,
) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    for resource in COUNTRIES_RESOURCES:
        assert resource in names, resource


def test_the_installed_copy_serves_the_packaged_flag_directory(site: Path, elsewhere: Path) -> None:
    code = (
        "from importlib import resources;"
        "from gi_common_reference.bootstrap import country_flag_store;"
        "flags = resources.files('gi_common_reference.countries.assets').joinpath('flags');"
        "print(flags.is_dir(), flags.joinpath('README.md').is_file());"
        "print(country_flag_store().read('missing.svg'))"
    )
    done = run_python(site, "-c", code, cwd=elsewhere)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["True True", "None"]


def test_the_countries_cli_reaches_the_database_from_the_installed_copy(
    site: Path, elsewhere: Path
) -> None:
    example = json.loads(
        (ROOT / "contracts" / "country-snapshot.v1.example.json").read_text("utf-8")
    )
    snapshot = write_snapshot(elsewhere, example)
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(site, *COUNTRIES_CLI, str(snapshot), cwd=elsewhere, environ=environ)
    assert done.returncode == 2, done.stderr
    assert "falló la base de datos" in done.stderr
    assert "instalación incompleta" not in done.stderr
    assert SECRET not in done.stdout + done.stderr


@pytest.mark.parametrize("resource", COUNTRIES_RESOURCES[:2])
def test_a_missing_countries_resource_is_reported_as_an_incomplete_installation(
    site: Path, elsewhere: Path, tmp_path: Path, resource: str
) -> None:
    broken = tmp_path / "broken-site"
    shutil.copytree(site, broken)
    (broken / resource).unlink()
    snapshot = write_snapshot(elsewhere, {"snapshot_version": 1})
    environ = {"REFERENCE_DATABASE_URL": UNREACHABLE}
    done = run_python(broken, *COUNTRIES_CLI, str(snapshot), cwd=elsewhere, environ=environ)
    assert done.returncode == 2, done.stderr
    assert "instalación incompleta" in done.stderr and Path(resource).name in done.stderr
