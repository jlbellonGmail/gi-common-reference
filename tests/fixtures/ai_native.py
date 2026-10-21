"""Localiza el check `architecture` de la release de AI-NATIVE fijada en `ai-native.lock.json`.

Es un requisito del entorno, no un detalle accidental: la release debe estar en la caché local de
AI-NATIVE (`AI_NATIVE_CACHE`, o `~/.ai-native/cache`) y hace falta `node`. Si falta algo, las
pruebas FALLAN con la instrucción para provisionarlo; nunca se saltan (ver `docs/desarrollo.md`).
"""

import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def architecture_check() -> Path:
    if shutil.which("node") is None:
        pytest.fail("falta `node` en el PATH: el check `architecture` de AI-NATIVE lo requiere")
    lock = json.loads((ROOT / "ai-native.lock.json").read_text(encoding="utf-8"))
    digest = str(lock["platform"]["digest"])
    cache = Path(os.environ.get("AI_NATIVE_CACHE") or Path.home() / ".ai-native" / "cache")
    check = cache / "releases" / digest.removeprefix("sha256:") / "runtime/policy/architecture.mjs"
    if not check.is_file():
        pytest.fail(
            f"la release de AI-NATIVE fijada ({digest}) no está en la caché {cache}. "
            "Provisionarla una vez con `node <release>/runtime/bootstrap/cli.mjs sync --project .` "
            "(ver docs/desarrollo.md)"
        )
    return check
