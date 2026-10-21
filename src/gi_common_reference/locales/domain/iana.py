"""Parser del artefacto IANA de referencia (formato record-jar, RFC 5646 §3.1.1).

Lee únicamente el texto que viaja dentro del snapshot; nunca consulta la red (RNF-2).
"""

import re
from dataclasses import dataclass
from datetime import date
from functools import cached_property

SEPARATOR = "%%"
FIELD = re.compile(r"([A-Za-z][A-Za-z-]*):[ \t]*(.*)")


class IanaFormatError(ValueError):
    """El artefacto no cumple la estructura mínima exigida por el contrato (RF-30)."""


@dataclass(frozen=True)
class IanaEntry:
    """Entrada del registro. `Deprecated`, `Preferred-Value` y `Scope` son opcionales."""

    type: str
    subtag: str
    deprecated: str | None
    preferred_value: str | None
    scope: str | None

    @property
    def is_deprecated(self) -> bool:
        """Regla única: el campo `Deprecated` está presente (el parser no admite que esté vacío)."""
        return self.deprecated is not None

    def covers(self, code: str) -> bool:
        """Un subtag con rango (`qaa..qtz`) cubre los códigos de su misma longitud entre ambos."""
        low, separator, high = self.subtag.lower().partition("..")
        if not separator:
            return self.subtag.lower() == code
        return len(code) == len(low) and low <= code <= high


@dataclass(frozen=True)
class IanaRegistry:
    file_date: date
    entries: tuple[IanaEntry, ...]

    @cached_property
    def _languages(self) -> dict[str, IanaEntry]:
        return {
            e.subtag.lower(): e
            for e in self.entries
            if e.type == "language" and ".." not in e.subtag
        }

    @cached_property
    def _language_ranges(self) -> tuple[IanaEntry, ...]:
        return tuple(e for e in self.entries if e.type == "language" and ".." in e.subtag)

    def language(self, code: str) -> IanaEntry | None:
        """Entrada `Type: language` con exactamente ese subtag (los rangos no cuentan)."""
        return self._languages.get(code.lower())

    def language_aliases(self) -> dict[str, str]:
        """Subtags de idioma con *Preferred-Value*, para resolver `iw` → `he` (D8, RF-8)."""
        return {
            entry.subtag.lower(): entry.preferred_value.lower()
            for entry in self.entries
            if entry.type == "language" and ".." not in entry.subtag and entry.preferred_value
        }

    def is_private_use(self, code: str) -> bool:
        """El código cae en un rango de uso privado (`Scope: private-use`, p. ej. `qaa..qtz`)."""
        code = code.lower()
        return any(e.scope == "private-use" and e.covers(code) for e in self._language_ranges)


def parse_registry(text: str) -> IanaRegistry:
    """Parsea el texto del registro; lanza `IanaFormatError` si falta lo estructural.

    Obligatorio: el `File-Date` del encabezado y, en cada entrada, `Type` y `Subtag` (o `Tag`,
    que usan las entradas `grandfathered` y `redundant`). `Deprecated` y `Preferred-Value` son
    opcionales, pero si están no pueden estar vacíos.
    """
    records = _records(text)
    header = records[0]
    file_date = _file_date(header)
    entries: list[IanaEntry] = []
    seen_languages: set[str] = set()
    for fields in records[1:]:
        entry = _entry(fields)
        if entry.type == "language":
            key = entry.subtag.lower()
            if key in seen_languages:
                raise IanaFormatError(f"subtag de idioma duplicado: {entry.subtag}")
            seen_languages.add(key)
        entries.append(entry)
    return IanaRegistry(file_date=file_date, entries=tuple(entries))


def _records(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = [{}]
    last: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip() == SEPARATOR:
            records.append({})
            last = None
            continue
        if not line.strip():
            continue
        if line[0] in " \t":
            if last is None:
                raise IanaFormatError(f"línea {number}: continuación sin campo previo")
            # Si el valor de la primera línea está vacío, la continuación es el valor completo: no
            # se antepone un espacio artificial.
            previous = records[-1][last]
            records[-1][last] = f"{previous} {line.strip()}" if previous else line.strip()
            continue
        match = FIELD.fullmatch(line)
        if match is None:
            raise IanaFormatError(f"línea {number}: no es un campo 'Nombre: valor'")
        name, value = match.group(1).lower(), match.group(2).strip()
        last = name
        records[-1].setdefault(name, value)
    return records


def _file_date(header: dict[str, str]) -> date:
    raw = header.get("file-date")
    if raw is None:
        raise IanaFormatError("falta File-Date en el encabezado del artefacto")
    try:
        return date.fromisoformat(raw) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else _bad(raw)
    except ValueError:
        return _bad(raw)


def _bad(raw: str) -> date:
    raise IanaFormatError(f"File-Date inválido: {raw!r}")


def _entry(fields: dict[str, str]) -> IanaEntry:
    entry_type = fields.get("type")
    if not entry_type:
        raise IanaFormatError(f"entrada sin Type: {_describe(fields)}")
    subtag = fields.get("subtag") or fields.get("tag")
    if not subtag:
        raise IanaFormatError(f"entrada sin Subtag ni Tag: {_describe(fields)}")
    for name, label in (("deprecated", "Deprecated"), ("preferred-value", "Preferred-Value")):
        if name in fields and not fields[name]:
            raise IanaFormatError(f"entrada con {label} vacío: {_describe(fields)}")
    return IanaEntry(
        type=entry_type,
        subtag=subtag,
        deprecated=fields.get("deprecated"),
        preferred_value=fields.get("preferred-value"),
        scope=fields.get("scope"),
    )


def _describe(fields: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in list(fields.items())[:3])
