"""Conjunto obligatorio de locales del catálogo (RF-31, D9).

Es política del catálogo, no parte del modelo: una lista versionada de `locale_id`. El código de
cada locale viaja solo como guarda, para detectar una política que apunte a otro idioma; la
relación con el idioma es siempre el `locale_id` (S-7).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequiredLocale:
    locale_id: str
    code: str


@dataclass(frozen=True)
class RequiredLocales:
    version: int
    locales: tuple[RequiredLocale, ...]

    @property
    def locale_ids(self) -> frozenset[str]:
        return frozenset(item.locale_id for item in self.locales)
