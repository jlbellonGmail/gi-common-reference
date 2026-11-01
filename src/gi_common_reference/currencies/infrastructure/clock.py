"""Reloj del sistema: el día calendario UTC (D14 del plan, S-11).

Es la única fuente de tiempo del servicio y solo decide la fecha de referencia por defecto de
las consultas; el catálogo nunca cambia por el transcurso del tiempo (RF-51). Un consumidor
sensible a la fecha debe pasar `as_of` explícita.
"""

from datetime import UTC, date, datetime


class SystemClock:
    def today(self) -> date:
        return datetime.now(UTC).date()
