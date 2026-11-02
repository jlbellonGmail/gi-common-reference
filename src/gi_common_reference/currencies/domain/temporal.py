"""Semántica temporal de CountryCurrency como funciones puras (D-18, RF-44 a RF-52).

La vigencia es un período de días calendario **semiabierto** `[inicio, fin)`: incluye el día de
inicio y excluye el de fin. Un extremo ausente (`None`) no está acotado. Con esta semántica una
transición el mismo día (una moneda termina cuando otra empieza) no produce solapamiento ni hueco
(CL-20). `status` no interviene aquí: es el ciclo de vida del registro y es independiente de la
vigencia (RF-51); quien llama decide qué registros considerar.

El SQL de la migración 0004 (`daterange(valid_from, valid_to, '[)')`, exclusión `&&`) implementa la
misma semántica; los vectores de las pruebas se comparten para que no diverjan.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from gi_common_reference.currencies.domain.model import CountryCurrencyRecord


@dataclass(frozen=True)
class Period:
    """Vigencia `[start, end)`; `None` es un extremo no acotado."""

    start: date | None
    end: date | None

    @property
    def is_ordered(self) -> bool:
        """Cuando ambos extremos existen, el inicio es anterior al fin (RF-44)."""
        return self.start is None or self.end is None or self.start < self.end

    @property
    def is_open(self) -> bool:
        """Sin fin declarado."""
        return self.end is None

    def contains(self, day: date) -> bool:
        return (self.start is None or self.start <= day) and (self.end is None or day < self.end)

    def overlaps(self, other: "Period") -> bool:
        """Dos períodos ordenados se solapan si comparten al menos un día (RF-45)."""
        starts_before_other_ends = self.start is None or other.end is None or self.start < other.end
        other_starts_before_this_ends = (
            other.start is None or self.end is None or other.start < self.end
        )
        return starts_before_other_ends and other_starts_before_this_ends


def period_of(record: CountryCurrencyRecord) -> Period:
    return Period(record.valid_from, record.valid_to)


def extreme_change_allowed(before: date | None, after: date | None) -> bool:
    """RF-47: un extremo ausente puede completarse una vez; uno fijado no cambia ni se vacía."""
    return before is None or before == after


def history_violations(before: CountryCurrencyRecord, after: CountryCurrencyRecord) -> list[str]:
    """Motivos por los que `after` reescribe la historia de `before` (RF-7, RF-47)."""
    found: list[str] = []
    if before.country_id != after.country_id or before.currency_id != after.currency_id:
        found.append("cambia el país o la moneda de una asociación publicada")
    if not extreme_change_allowed(before.valid_from, after.valid_from):
        found.append(
            f"modifica el inicio de vigencia ya fijado ({before.valid_from} → {after.valid_from})"
        )
    if not extreme_change_allowed(before.valid_to, after.valid_to):
        found.append(
            f"modifica el fin de vigencia ya fijado ({before.valid_to} → {after.valid_to})"
        )
    return found


def overlapping_pairs(
    records: Sequence[CountryCurrencyRecord],
) -> list[tuple[CountryCurrencyRecord, CountryCurrencyRecord]]:
    """Pares de asociaciones `active` del mismo (país, moneda) con vigencias solapadas (RF-45).

    Monedas distintas del mismo país, o la misma moneda en países distintos, no se comparan
    (RF-18). Los registros `inactive` no participan (RF-47, CL-26).
    """
    by_pair: dict[tuple[str, str], list[CountryCurrencyRecord]] = {}
    for record in records:
        if record.status == "active" and period_of(record).is_ordered:
            by_pair.setdefault((record.country_id, record.currency_id), []).append(record)
    found: list[tuple[CountryCurrencyRecord, CountryCurrencyRecord]] = []
    for group in by_pair.values():
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                if period_of(first).overlaps(period_of(second)):
                    found.append((first, second))
    return found


def in_force_on(
    records: Iterable[CountryCurrencyRecord], day: date, *, include_inactive: bool = False
) -> list[CountryCurrencyRecord]:
    """Asociaciones cuya vigencia contiene `day` (RF-48); por defecto solo las `active`."""
    return [
        record
        for record in records
        if (include_inactive or record.status == "active") and period_of(record).contains(day)
    ]


def history_order_key(record: CountryCurrencyRecord) -> tuple[int, date, str]:
    """Orden del historial (RF-49): inicio de vigencia con los ausentes primero, luego el id."""
    start = record.valid_from
    return (0 if start is None else 1, start or date.min, record.country_currency_id)
