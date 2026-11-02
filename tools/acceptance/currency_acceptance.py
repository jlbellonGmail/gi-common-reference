"""Runner de la aceptación de 004-currency (D24 del plan): ejecuta `tests/acceptance` y deja la
evidencia reproducible en `acceptance/currencies/evidence/`.

AI-NATIVE v3.4.3 no expone un comando de Native Acceptance (`ai-native help`), así que los criterios
de aceptación de la spec se ejecutan como pruebas de caja negra: CLI como subproceso, API real por
HTTP y Postgres real, con un guard de red en los procesos. Este runner no inventa resultados: copia
lo que ejecutó pytest y calcula las sumas de verificación.

Uso (desde la raíz del repositorio, con Docker en ejecución):

    python tools/acceptance/currency_acceptance.py [--base origin/develop]

Salida: 0 si todos los casos pasan; el código de pytest en otro caso.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "acceptance" / "currencies" / "evidence"
GENERATED = (
    "01-environment.txt",
    "02-inputs-sha256.json",
    "03-commands.json",
    "04-http-transcripts.json",
    "05-acceptance-results.txt",
    "06-manifest-sha256.txt",
)


def run(*argv: str) -> str:
    try:
        done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError as error:
        return f"no disponible ({type(error).__name__})"
    return (done.stdout + done.stderr).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment(base: str) -> str:
    versions = run(sys.executable, "-m", "pip", "list", "--format=freeze")
    wanted = ("fastapi", "psycopg", "pydantic", "pytest", "alembic", "uvicorn", "testcontainers")
    pinned = [line for line in versions.splitlines() if line.split("==")[0].lower() in wanted]
    return "\n".join(
        [
            "# Entorno de la aceptación de 004-currency (sintético, no productivo; S-9)",
            f"python: {platform.python_version()} ({platform.system()})",
            f"git HEAD: {run('git', 'rev-parse', 'HEAD')}",
            f"git base ({base}): {run('git', 'rev-parse', base)}",
            "ai-native (launcher del repositorio): "
            + run("node", ".ai-native/ai-native.mjs", "version").splitlines()[0],
            "base de datos: postgres:16-alpine (testcontainers, descartable)",
            "paquetes:",
            *(f"  {line}" for line in sorted(pinned)),
            "comando: python tools/acceptance/currency_acceptance.py",
        ]
    )


def normalize(output: str) -> str:
    """Quita lo que varía entre ejecuciones (duraciones, rutas temporales)."""
    output = re.sub(r" in \d+(\.\d+)?s( \(\d+:\d+:\d+\))?", "", output)
    output = re.sub(r"\[\s*\d+%\]", "", output)
    return output.replace(str(ROOT), "<repo>").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", default="origin/develop", help="rama base para el diff de 001-003"
    )
    args = parser.parse_args()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for name in GENERATED:
        (EVIDENCE / name).unlink(missing_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1", "ACCEPTANCE_EVIDENCE_DIR": str(EVIDENCE)}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/acceptance", "-v", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (EVIDENCE / "05-acceptance-results.txt").write_text(
        normalize(result.stdout + result.stderr) + "\n", encoding="utf-8", newline="\n"
    )
    for source, target in (
        ("inputs-sha256.json", "02-inputs-sha256.json"),
        ("commands.json", "03-commands.json"),
        ("http-transcripts.json", "04-http-transcripts.json"),
    ):
        (EVIDENCE / source).replace(EVIDENCE / target)
    (EVIDENCE / "01-environment.txt").write_text(
        environment(args.base) + f"\npytest exit code: {result.returncode}\n",
        encoding="utf-8",
        newline="\n",
    )
    files = sorted(p for p in EVIDENCE.iterdir() if p.is_file() and p.name in GENERATED[:5])
    manifest = "\n".join(f"{sha256(p)}  {p.name}" for p in files)
    (EVIDENCE / "06-manifest-sha256.txt").write_text(
        manifest + "\n", encoding="utf-8", newline="\n"
    )
    json.loads((EVIDENCE / "03-commands.json").read_text("utf-8"))  # evidencia bien formada
    print(manifest)
    print(f"pytest exit code: {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
