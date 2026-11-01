"""Tipos compartidos del dominio de Locale."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    """Motivo de rechazo de un snapshot: `rule` es el requisito de la spec (p. ej. `RF-30`)."""

    rule: str
    message: str


@dataclass(frozen=True)
class LocaleRecord:
    """Un locale tal como viaja en un snapshot o como está persistido (sin textos, RF-6)."""

    locale_id: str
    code: str
    status: str
    iana_deprecated: bool
    replacement_locale_id: str | None
