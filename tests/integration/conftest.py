"""Fixtures de integración que dependen de la revisión de esquema que valida cada prueba.

`tests/integration/test_migration_0003.py::test_locale_and_regions_do_not_depend_on_countries`
(003, cerrada) exige que ninguna tabla ajena a Countries lo referencie. Es una garantía sobre el
esquema que deja `0003`: 004 agrega, por diseño aprobado (D-16), consumidores legítimos de
`country_id` (`country_currency`, `currency_snapshot`). Esa prueba se ejecuta sobre `0003` sin
modificar su archivo ni el `conftest` compartido; la garantía equivalente sobre `head` pertenece a
004 (`tests/integration/currencies/test_dependency_direction.py`).
"""

from collections.abc import Callable

import pytest
from alembic import command

from tests.conftest import alembic_config

SCHEMA_REVISION = {
    "tests/integration/test_migration_0003.py"
    "::test_locale_and_regions_do_not_depend_on_countries": "0003",
}


@pytest.fixture
def database_url(database_factory: Callable[[], str], request: pytest.FixtureRequest) -> str:
    """Base nueva en `head`, o en la revisión que la prueba valida si está fijada."""
    url = database_factory()
    revision = SCHEMA_REVISION.get(request.node.nodeid)
    if revision is not None:
        command.downgrade(alembic_config(url), revision)
    return url
