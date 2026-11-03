"""Parser y evaluador de códigos UCUM sobre la tabla oficial empaquetada (D8, RF-15, RF-17).

Un código UCUM se interpreta con la gramática del estándar (términos con `.` y `/` asociativos a la
izquierda, exponentes enteros con signo, paréntesis, anotaciones `{…}` y factores enteros), con
sensibilidad a mayúsculas y usando el atributo `Code` de cada átomo. El resultado es una escala
exacta (`Fraction`) respecto de las siete unidades base y un vector de dimensiones. Las definiciones
de los átomos (`<value Unit= value=>`) son expresiones UCUM que se evalúan recursivamente y se
guardan en caché.

Alcance deliberado (RF-15): se rechazan átomos y prefijos desconocidos, prefijos sobre átomos no
métricos, unidades arbitrarias y toda unidad especial salvo `Cel` y `[degF]`, que solo se admiten
como código completo (sin prefijo, exponente, anotación ni operadores). Un valor irracional (`[pi]`)
no es representable exactamente y se rechaza. El texto del código nunca se normaliza (RF-17).
"""

import re
from dataclasses import dataclass
from fractions import Fraction

from gi_common_reference.units.domain.model import UcumAtom, UcumTable

BASE_UNITS = ("m", "s", "g", "rad", "K", "C", "cd")
Dimension = tuple[int, ...]

_NUMBER = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_DIGITS = "0123456789"
_MAX_EXPONENT_DIGITS = 3
_IRRATIONAL = frozenset({"[pi]"})
# Desplazamiento (en K) de las dos unidades especiales admitidas; no lo trae la tabla.
_SPECIAL_OFFSETS = {"Cel": Fraction("273.15"), "[degF]": Fraction("459.67")}
_NO_DIMENSION: Dimension = (0,) * len(BASE_UNITS)


class UcumError(ValueError):
    """El código UCUM no es válido o no es representable; el mensaje dice por qué."""


@dataclass(frozen=True)
class UcumQuantity:
    """Escala exacta y dimensión de un código. Una especial usa `K = (x + offset) × scale`."""

    scale: Fraction
    dimension: Dimension
    offset: Fraction = Fraction(0)
    special: bool = False


@dataclass(frozen=True)
class _Value:
    scale: Fraction
    dimension: Dimension


_ONE = _Value(Fraction(1), _NO_DIMENSION)


def _multiply(left: _Value, right: _Value) -> _Value:
    dimension = tuple(a + b for a, b in zip(left.dimension, right.dimension, strict=True))
    return _Value(left.scale * right.scale, dimension)


def _divide(left: _Value, right: _Value) -> _Value:
    dimension = tuple(a - b for a, b in zip(left.dimension, right.dimension, strict=True))
    return _Value(left.scale / right.scale, dimension)


def _power(base: _Value, exponent: int) -> _Value:
    return _Value(base.scale**exponent, tuple(d * exponent for d in base.dimension))


class UcumEvaluator:
    """Evalúa códigos UCUM contra una `UcumTable`; guarda en caché cada evaluación."""

    def __init__(self, table: UcumTable) -> None:
        self.table = table
        self.max_atom_length = max(len(code) for code in table.atoms)
        self.max_prefix_length = max(len(code) for code in table.prefixes)
        self._quantities: dict[str, UcumQuantity] = {}
        self._failures: dict[str, str] = {}
        self._expressions: dict[str, _Value] = {}
        self._atoms: dict[str, _Value] = {}

    def evaluate(self, code: str) -> UcumQuantity:
        """Escala y dimensión de `code`; `UcumError` si no es un código admitido."""
        cached = self._quantities.get(code)
        if cached is not None:
            return cached
        if code in self._failures:
            raise UcumError(self._failures[code])
        try:
            quantity = self._evaluate(code)
        except UcumError as error:
            self._failures[code] = str(error)
            raise
        self._quantities[code] = quantity
        return quantity

    # --- evaluación ---------------------------------------------------------------------------

    def _evaluate(self, code: str) -> UcumQuantity:
        atom = self.table.atoms.get(code)
        if atom is not None and atom.is_special:
            return self._special(atom)
        value = self._expression(code)
        return UcumQuantity(value.scale, value.dimension)

    def _special(self, atom: UcumAtom) -> UcumQuantity:
        offset = _SPECIAL_OFFSETS.get(atom.code)
        function = atom.function
        if offset is None or function is None:
            raise UcumError(f"la unidad especial {atom.code} no está soportada")
        reference = self._expression(function.unit)
        scale = _number(function.value, atom.code) * reference.scale
        return UcumQuantity(scale, reference.dimension, offset, True)

    def _expression(self, text: str) -> _Value:
        cached = self._expressions.get(text)
        if cached is None:
            cached = _Parser(self, text).main()
            self._expressions[text] = cached
        return cached

    def atom_value(self, code: str) -> _Value:
        """Valor de un átomo no especial ni arbitrario, desde su definición en la tabla."""
        cached = self._atoms.get(code)
        if cached is not None:
            return cached
        atom = self.table.atoms[code]
        if atom.is_arbitrary:
            raise UcumError(f"la unidad {code} es arbitraria y no se admite")
        if atom.is_special:
            raise UcumError(
                f"la unidad especial {code} solo se admite como código completo, sin prefijo, "
                "exponente, anotación ni operadores"
            )
        if code in _IRRATIONAL:
            raise UcumError(f"el valor de {code} es irracional y no es representable exactamente")
        if atom.dimension is not None:
            if code not in BASE_UNITS:
                raise UcumError(f"la unidad base {code} no está entre las siete admitidas")
            dimension = tuple(1 if base == code else 0 for base in BASE_UNITS)
            value = _Value(Fraction(1), dimension)
        else:
            if atom.value is None or atom.unit is None:
                raise UcumError(f"la unidad {code} no tiene una definición evaluable")
            definition = self._expression(atom.unit)
            value = _Value(_number(atom.value, code) * definition.scale, definition.dimension)
        self._atoms[code] = value
        return value


def _number(text: str, code: str) -> Fraction:
    if _NUMBER.fullmatch(text) is None:
        raise UcumError(f"el valor «{text}» de {code} no es un número decimal")
    return Fraction(text)


@dataclass(frozen=True)
class _Candidate:
    consumed: int
    prefix: str | None
    atom: str


class _Parser:
    """Descenso recursivo de la gramática UCUM, evaluando a medida que avanza."""

    def __init__(self, evaluator: UcumEvaluator, text: str) -> None:
        self.evaluator = evaluator
        self.text = text
        self.index = 0

    def main(self) -> _Value:
        if not self.text:
            raise UcumError("el código UCUM está vacío")
        if self.text[0] == "/":
            self.index = 1
            value = _divide(_ONE, self.term())
        else:
            value = self.term()
        if self.index != len(self.text):
            raise self.error("carácter inesperado")
        return value

    def error(self, message: str) -> UcumError:
        return UcumError(f"código UCUM «{self.text}» inválido: {message} (posición {self.index})")

    def peek(self) -> str:
        return self.text[self.index] if self.index < len(self.text) else ""

    def term(self) -> _Value:
        value = self.component()
        while self.peek() in (".", "/"):
            operator = self.text[self.index]
            self.index += 1
            right = self.component()
            value = _multiply(value, right) if operator == "." else _divide(value, right)
        return value

    def component(self) -> _Value:
        char = self.peek()
        if not char:
            raise self.error("falta un componente")
        if char == "(":
            self.index += 1
            value = self.term()
            if self.peek() != ")":
                raise self.error("falta el paréntesis de cierre")
            self.index += 1
            return value
        if char == "{":
            self.annotation()
            return _ONE
        simple = self.simple_unit()
        if simple is not None:
            exponent = self.exponent()
            value = simple if exponent is None else _power(simple, exponent)
            if self.peek() == "{":
                self.annotation()
            return value
        if char in _DIGITS:
            start = self.index
            while self.peek() and self.peek() in _DIGITS:
                self.index += 1
            return _Value(Fraction(int(self.text[start : self.index])), _NO_DIMENSION)
        raise self.error("unidad desconocida o carácter inesperado")

    def annotation(self) -> None:
        self.index += 1
        while True:
            char = self.peek()
            if not char:
                raise self.error("anotación sin cerrar")
            if char == "}":
                self.index += 1
                return
            if not 33 <= ord(char) <= 126 or char == "{":
                raise self.error("carácter no admitido en la anotación")
            self.index += 1

    def exponent(self) -> int | None:
        start = self.index
        sign = 1
        if self.peek() in ("+", "-"):
            sign = -1 if self.peek() == "-" else 1
            self.index += 1
        digits_at = self.index
        while self.peek() and self.peek() in _DIGITS:
            self.index += 1
        digits = self.text[digits_at : self.index]
        if not digits:
            if self.index != start:
                raise self.error("exponente sin dígitos")
            return None
        if len(digits) > _MAX_EXPONENT_DIGITS:
            raise self.error("exponente fuera de rango")
        return sign * int(digits)

    # --- unidad simple: átomo o prefijo + átomo -------------------------------------------------

    def candidates(self) -> list[_Candidate]:
        rest = self.text[self.index :]
        table = self.evaluator.table
        found: list[tuple[int, int, _Candidate]] = []
        limit = min(len(rest), self.evaluator.max_atom_length)
        for length in range(limit, 0, -1):
            if rest[:length] in table.atoms:
                found.append((length, 0, _Candidate(length, None, rest[:length])))
        for prefix_length in range(1, self.evaluator.max_prefix_length + 1):
            prefix = rest[:prefix_length]
            if prefix not in table.prefixes:
                continue
            tail = rest[prefix_length:]
            for length in range(min(len(tail), self.evaluator.max_atom_length), 0, -1):
                if tail[:length] in table.atoms:
                    consumed = prefix_length + length
                    found.append((consumed, 1, _Candidate(consumed, prefix, tail[:length])))
        found.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in found]

    def boundary_ok(self, consumed: int) -> bool:
        following = self.text[self.index + consumed : self.index + consumed + 1]
        return following == "" or following in "./){+-" + _DIGITS

    def simple_unit(self) -> _Value | None:
        first_error: UcumError | None = None
        for candidate in self.candidates():
            if not self.boundary_ok(candidate.consumed):
                continue
            try:
                value = self.resolve(candidate)
            except UcumError as error:
                first_error = first_error or error
                continue
            self.index += candidate.consumed
            return value
        if first_error is not None:
            raise first_error
        return None

    def resolve(self, candidate: _Candidate) -> _Value:
        table = self.evaluator.table
        atom = table.atoms[candidate.atom]
        if candidate.prefix is not None and not atom.is_metric:
            raise UcumError(
                f"código UCUM «{self.text}» inválido: el átomo {atom.code} no métrico no admite "
                f"el prefijo {candidate.prefix}"
            )
        try:
            value = self.evaluator.atom_value(atom.code)
        except UcumError as error:
            raise UcumError(f"código UCUM «{self.text}» inválido: {error}") from error
        if candidate.prefix is None:
            return value
        prefix = _number(table.prefixes[candidate.prefix].value, candidate.prefix)
        return _Value(prefix * value.scale, value.dimension)
