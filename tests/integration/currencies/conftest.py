"""Revisión de esquema que valida cada prueba de integración de 004 (agregado por 005).

`tests/integration/currencies/test_dependency_direction.py::test_every_table_belongs_to_exactly_one_catalog`
(004, cerrada) exige que el schema tenga exactamente las tablas de 001–004. Es una garantía sobre
el esquema que deja `0004`: 005 agrega, por diseño aprobado, las tablas de Units. Esa prueba se
ejecuta sobre `0004` sin modificar su archivo ni el `conftest` compartido (mismo mecanismo que 004
usó para 003); la garantía equivalente sobre `head` pertenece a 005
(`tests/integration/units/test_dependency_direction.py`).
"""

from collections.abc import Callable

import pytest
from alembic import command

from tests.conftest import alembic_config

SCHEMA_REVISION = {
    "tests/integration/currencies/test_dependency_direction.py"
    "::test_every_table_belongs_to_exactly_one_catalog": "0004",
}


@pytest.fixture
def database_url(database_factory: Callable[[], str], request: pytest.FixtureRequest) -> str:
    """Base nueva en `head`, o en la revisión que la prueba valida si está fijada."""
    url = database_factory()
    revision = SCHEMA_REVISION.get(request.node.nodeid)
    if revision is not None:
        command.downgrade(alembic_config(url), revision)
    return url
