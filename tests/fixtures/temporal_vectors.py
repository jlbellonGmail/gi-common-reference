"""Vectores de la semántica temporal `[inicio, fin)` compartidos por el dominio y el SQL (T5/T2).

Las pruebas unitarias los comparan con `domain/temporal.py`; la prueba de integración los compara
con `daterange(..., '[)')` y `&&` de PostgreSQL, así las dos implementaciones no divergen (RF-44).
"""

from datetime import date

D = date
Bound = date | None

# (inicio A, fin A, inicio B, fin B, ¿se solapan?)
OVERLAP_VECTORS: tuple[tuple[Bound, Bound, Bound, Bound, bool], ...] = (
    (D(2020, 1, 1), D(2023, 1, 1), D(2023, 1, 1), D(2030, 1, 1), False),  # adyacentes
    (D(2023, 1, 1), D(2030, 1, 1), D(2020, 1, 1), D(2023, 1, 1), False),  # adyacentes, al revés
    (D(2020, 1, 1), D(2023, 1, 2), D(2023, 1, 1), D(2030, 1, 1), True),  # un día de solapamiento
    (D(2020, 1, 1), D(2030, 1, 1), D(2022, 1, 1), D(2023, 1, 1), True),  # contenido
    (D(2020, 1, 1), D(2021, 1, 1), D(2022, 1, 1), D(2023, 1, 1), False),  # disjuntos
    (None, None, D(2022, 1, 1), D(2023, 1, 1), True),  # no acotado cubre todo
    (None, None, None, None, True),
    (None, D(2023, 1, 1), D(2023, 1, 1), None, False),  # HRK hasta 2023-01-01, EUR desde esa fecha
    (None, D(2023, 1, 2), D(2023, 1, 1), None, True),
    (D(2023, 1, 1), None, D(2030, 1, 1), None, True),  # dos abiertos
    (None, D(2020, 1, 1), None, D(2010, 1, 1), True),  # dos sin inicio
    (None, D(2020, 1, 1), D(2020, 1, 1), D(2021, 1, 1), False),
    (D(2020, 1, 1), None, None, D(2020, 1, 1), False),  # fin de una = inicio de la otra
    (D(2020, 1, 1), None, None, D(2020, 1, 2), True),
)

# (inicio, fin, día, ¿lo contiene?)
CONTAINS_VECTORS: tuple[tuple[Bound, Bound, date, bool], ...] = (
    (D(2000, 1, 1), D(2023, 1, 1), D(2000, 1, 1), True),  # el inicio se incluye
    (D(2000, 1, 1), D(2023, 1, 1), D(1999, 12, 31), False),
    (D(2000, 1, 1), D(2023, 1, 1), D(2022, 12, 31), True),
    (D(2000, 1, 1), D(2023, 1, 1), D(2023, 1, 1), False),  # el fin se excluye
    (D(2023, 1, 1), None, D(2023, 1, 1), True),
    (D(2023, 1, 1), None, D(9999, 12, 30), True),
    (None, D(2023, 1, 1), D(1900, 1, 1), True),
    (None, D(2023, 1, 1), D(2023, 1, 1), False),
    (None, None, D(2026, 11, 1), True),
)
