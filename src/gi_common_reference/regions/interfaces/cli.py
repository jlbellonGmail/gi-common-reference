"""CLI de incorporación de snapshots de Regions (`incorporate <archivo>`).

Se ejecuta con `python -m gi_common_reference.regions.interfaces.cli incorporate <archivo>`.
Es el único camino de escritura del catálogo Region/Subregion (RF-20, RF-21). La conexión se toma
de `REFERENCE_DATABASE_URL` y debe usar el rol `reference_loader`.

Código de salida: 0 incorporado o no-op; 1 snapshot inválido o rechazado; 2 error operativo.

La salida nunca reproduce la cadena de conexión ni el texto de los errores del driver: puede
contener fragmentos de credenciales. Los errores de base de datos se informan con tipo y SQLSTATE.
Los caracteres que la codificación de la salida no admite se escriben como escapes `\\uXXXX`.
"""

import argparse
import io
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from gi_common_reference.regions.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.regions.domain.errors import (
    InvalidConnectionString,
    PersistenceError,
    SchemaLoadError,
)
from gi_common_reference.regions.domain.ports import (
    PolicyLoader,
    RegionRepository,
    SnapshotFormatError,
    SnapshotReader,
)

DATABASE_URL = "REFERENCE_DATABASE_URL"

RepositoryFactory = Callable[[str], RegionRepository]


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
    policy_loader: PolicyLoader,
) -> int:
    _tolerate_unencodable_output()
    parser = argparse.ArgumentParser(prog="regions", description=__doc__)
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
        policy = policy_loader()
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
        result = incorporate_snapshot(document, repository_factory(conninfo), policy)
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
        f"(locale_snapshot_version={result.locale_snapshot_version}; "
        f"{result.new_regions} regiones nuevas, {result.new_subregions} subregiones nuevas, "
        f"{result.updated} actualizaciones, {result.reclassifications} reclasificaciones, "
        f"{result.recodings} recodificaciones)"
    )
    return 0


if __name__ == "__main__":
    # Único punto que conoce los adaptadores: la raíz de composición (`bootstrap`).
    from gi_common_reference.bootstrap import (
        postgres_region_repository,
        read_region_snapshot,
        required_locales,
    )

    raise SystemExit(
        main(
            repository_factory=postgres_region_repository,
            snapshot_reader=read_region_snapshot,
            policy_loader=required_locales,
        )
    )
