"""CLI de incorporación de snapshots (`... interfaces.cli incorporate <archivo>`).

Se ejecuta con `python -m gi_common_reference.locales.interfaces.cli incorporate <archivo>`.
Es el único camino de escritura del catálogo (RF-12, RF-14). La conexión se toma de
`REFERENCE_DATABASE_URL` y debe usar el rol `reference_loader`.

Código de salida: 0 incorporado o no-op; 1 snapshot inválido o rechazado; 2 error operativo.

La salida nunca reproduce la cadena de conexión ni el texto de los errores del driver: puede
contener fragmentos de credenciales. Los errores de base de datos se informan con tipo y SQLSTATE.

Los caracteres que la codificación de la salida no admite (p. ej. la flecha de los ciclos RF-22
con la salida redirigida en Windows, cp1252) se escriben como escapes `\\uXXXX` en lugar de
abortar con `UnicodeEncodeError`.
"""

import argparse
import io
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from gi_common_reference.locales.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.locales.domain.errors import (
    InvalidConnectionString,
    PersistenceError,
    SchemaLoadError,
)
from gi_common_reference.locales.domain.ports import (
    LocaleRepository,
    SnapshotFormatError,
    SnapshotReader,
)

DATABASE_URL = "REFERENCE_DATABASE_URL"

RepositoryFactory = Callable[[str], LocaleRepository]


def _tolerate_unencodable_output() -> None:
    """Conserva la codificación de stdout/stderr, pero escapa lo que esta no pueda representar."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    repository_factory: RepositoryFactory,
    snapshot_reader: SnapshotReader,
) -> int:
    _tolerate_unencodable_output()
    parser = argparse.ArgumentParser(prog="locales", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    incorporate = commands.add_parser("incorporate", help="incorporar un snapshot")
    incorporate.add_argument("archivo", type=Path, help="snapshot JSON producido por PREP")
    args = parser.parse_args(argv)

    env = os.environ if environ is None else environ
    conninfo = env.get(DATABASE_URL)
    if not conninfo:
        print(f"error: falta la variable de entorno {DATABASE_URL}", file=sys.stderr)
        return 2

    try:
        document = snapshot_reader(args.archivo)
    except SnapshotFormatError as error:
        print("RECHAZADO: snapshot inválido", file=sys.stderr)
        for problem in error.errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    except SchemaLoadError as error:
        print(f"error: instalación incompleta: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: no se pudo leer {args.archivo}: {error}", file=sys.stderr)
        return 2

    try:
        result = incorporate_snapshot(document, repository_factory(conninfo))
    except InvalidConnectionString as error:
        print(f"error: {DATABASE_URL}: {error}", file=sys.stderr)
        return 2
    except PersistenceError as error:  # la transacción ya se deshizo
        print(f"error: falló la base de datos: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # la transacción ya se deshizo; es un error operativo
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 2

    if result.outcome is Outcome.REJECTED:
        print(f"RECHAZADO snapshot_version={result.snapshot_version}", file=sys.stderr)
        for violation in result.violations:
            print(f"  - {violation.rule}: {violation.message}", file=sys.stderr)
        return 1
    if result.outcome is Outcome.NOOP:
        print(f"NO-OP snapshot_version={result.snapshot_version} ya incorporado")
        return 0
    print(
        f"INCORPORADO snapshot_version={result.snapshot_version} "
        f"({result.new_locales} nuevos, {result.updated_locales} actualizados)"
    )
    return 0


if __name__ == "__main__":
    # Único punto que conoce los adaptadores: la raíz de composición (`bootstrap`).
    from gi_common_reference.bootstrap import postgres_repository, read_snapshot

    raise SystemExit(main(repository_factory=postgres_repository, snapshot_reader=read_snapshot))
