"""Verificación de los assets de bandera declarados y lectura verificada (RF-19, RF-49, RF-50).

La E/S pasa por el puerto `FlagStore`; el chequeo del contenido es una función pura del dominio.
Nunca se consulta una fuente externa: el asset es un archivo del repositorio (RF-26).
"""

from collections.abc import Sequence

from gi_common_reference.countries.domain.model import FlagDeclaration, Violation
from gi_common_reference.countries.domain.ports import FlagStore
from gi_common_reference.countries.domain.svg import (
    is_safe_asset_path,
    sha256_of,
    svg_content_problems,
)


class FlagReadError(Exception):
    """El asset registrado no se puede servir íntegro; `reason` es un código estable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def verify_flag_declarations(flags: Sequence[FlagDeclaration], store: FlagStore) -> list[Violation]:
    """Cada asset existe, su suma coincide con la declarada y su contenido es un SVG sin partes
    activas. Informa todos los problemas de todas las banderas (RF-49)."""
    violations: list[Violation] = []
    for flag in flags:
        where = f"bandera del país {flag.country_id} ({flag.asset_path})"
        if not is_safe_asset_path(flag.asset_path):
            violations.append(Violation("RF-49", f"{where}: la ruta no es relativa ni segura"))
            continue
        data = store.read(flag.asset_path)
        if data is None:
            violations.append(Violation("RF-49", f"{where}: el asset no existe en el repositorio"))
            continue
        actual = sha256_of(data)
        if actual != flag.sha256:
            message = f"{where}: la suma de verificación declarada no coincide ({actual})"
            violations.append(Violation("RF-49", message))
        for problem in svg_content_problems(data):
            violations.append(Violation("RF-49", f"{where}: {problem}"))
    return violations


def read_verified_flag(store: FlagStore, asset_path: str, expected_sha256: str) -> bytes:
    """Los bytes del asset si su suma coincide con la registrada (RF-50); si no, `FlagReadError`."""
    data = store.read(asset_path) if is_safe_asset_path(asset_path) else None
    if data is None:
        raise FlagReadError("missing_asset")
    if sha256_of(data) != expected_sha256:
        raise FlagReadError("checksum_mismatch")
    return data
