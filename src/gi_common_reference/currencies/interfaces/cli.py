"""CLI de Currency: `incorporate <archivo>`, `diff <archivo>` y `check-integrity`.

Se ejecuta con `python -m gi_common_reference.currencies.interfaces.cli incorporate <archivo>`.
`incorporate` es el único camino de escritura del catálogo Currency (RF-34, RF-36); `diff` solo lee
y muestra qué cambiaría, para la revisión humana previa a la aprobación (RF-41); `check-integrity`
solo lee y lista las asociaciones `active` abiertas sobre un Country o una Currency `inactive`, la
deriva que puede producir un retiro en Countries entre incorporaciones (RF-19, S-8). La conexión se
toma de `REFERENCE_DATABASE_URL` y, para incorporar, debe usar el rol `reference_loader`.

Código de salida: 0 incorporado, no-op, diff calculado o catálogo íntegro; 1 snapshot inválido o
rechazado, o integridad violada; 2 error operativo.

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
from typing import Any

from gi_common_reference.currencies.application.diff import check_integrity, preview_snapshot
from gi_common_reference.currencies.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.currencies.domain.errors import (
    InvalidConnectionString,
    PersistenceError,
    SchemaLoadError,
)
from gi_common_reference.currencies.domain.policy import RequiredLocales
from gi_common_reference.currencies.domain.ports import (
    CurrencyRepository,
    PolicyLoader,
    SnapshotFormatError,
    SnapshotReader,
)

DATABASE_URL = "REFERENCE_DATABASE_URL"

RepositoryFactory = Callable[[str], CurrencyRepository]


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
    parser = argparse.ArgumentParser(prog="currencies", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    incorporate = commands.add_parser("incorporate", help="incorporar un snapshot")
    incorporate.add_argument("archivo", type=Path, help="snapshot JSON producido por PREP")
    diff = commands.add_parser("diff", help="mostrar qué cambiaría un snapshot, sin escribir")
    diff.add_argument("archivo", type=Path, help="snapshot JSON producido por PREP")
    commands.add_parser("check-integrity", help="listar asociaciones abiertas sobre inactive")
    args = parser.parse_args(argv)

    env = os.environ if environ is None else environ
    conninfo = env.get(DATABASE_URL)
    if not conninfo:
        print(f"error: falta la variable de entorno {DATABASE_URL}", file=sys.stderr)
        return 2

    document: dict[str, Any] = {}
    policy: RequiredLocales | None = None
    if args.command != "check-integrity":
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
        repository = repository_factory(conninfo)
        if args.command == "check-integrity":
            return _check_integrity(repository)
        assert policy is not None
        if args.command == "diff":
            return _diff(document, repository, policy)
        return _incorporate(document, repository, policy)
    except InvalidConnectionString as error:
        print(f"error: {DATABASE_URL}: {error}", file=sys.stderr)
        return 2
    except PersistenceError as error:  # la transacción ya se deshizo
        print(f"error: falló la base de datos: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # la transacción ya se deshizo; es un error operativo
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


def _incorporate(
    document: Mapping[str, Any], repository: CurrencyRepository, policy: RequiredLocales
) -> int:
    result = incorporate_snapshot(document, repository, policy)
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
        f"country_snapshot_version={result.country_snapshot_version}; "
        f"{result.new_currencies} monedas nuevas, {result.updated_currencies} actualizadas, "
        f"{result.names} localizaciones, {result.new_associations} asociaciones nuevas, "
        f"{result.updated_associations} asociaciones actualizadas)"
    )
    return 0


def _diff(
    document: Mapping[str, Any], repository: CurrencyRepository, policy: RequiredLocales
) -> int:
    result = preview_snapshot(document, repository, policy)
    if result.outcome is Outcome.REJECTED:
        print(f"RECHAZADO snapshot_version={result.snapshot_version}", file=sys.stderr)
        for violation in result.violations:
            print(f"  - {violation.rule}: {violation.message}", file=sys.stderr)
        return 1
    if result.outcome is Outcome.NOOP or result.diff is None:
        print(f"NO-OP snapshot_version={result.snapshot_version} ya incorporado: sin cambios")
        return 0
    lines = result.diff.lines()
    print(f"DIFF snapshot_version={result.snapshot_version}: {len(lines)} cambio(s)")
    for line in lines:
        print(f"  {line}")
    return 0


def _check_integrity(repository: CurrencyRepository) -> int:
    violations = check_integrity(repository)
    if not violations:
        print("INTEGRO: ninguna asociación active abierta sobre un Country o Currency inactive")
        return 0
    print(f"INTEGRIDAD VIOLADA: {len(violations)} asociación(es) (RF-19)", file=sys.stderr)
    for item in violations:
        reasons = []
        if item.country_not_active:
            reasons.append("Country inactive")
        if item.currency_not_active:
            reasons.append("Currency inactive")
        print(
            f"  - {item.country_currency_id}: country_id={item.country_id} "
            f"currency_id={item.currency_id}: {' y '.join(reasons)}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    # Único punto que conoce los adaptadores: la raíz de composición (`bootstrap`).
    from gi_common_reference.bootstrap import (
        currency_required_locales,
        postgres_currency_repository,
        read_currency_snapshot,
    )

    raise SystemExit(
        main(
            repository_factory=postgres_currency_repository,
            snapshot_reader=read_currency_snapshot,
            policy_loader=currency_required_locales,
        )
    )
