# Tasks 001 — Locales

- [x] **T1. Esqueleto del servicio, infraestructura de pruebas sin red y contrato de arquitectura.** RNF-2, RNF-4, RNF-6
  - Done when: existen `pyproject.toml` (Python ≥3.12, dependencias de D2/D3/D1 y dev del plan), el paquete `src/gi_common_reference/locales/{domain,application,infrastructure,interfaces}` y `architecture.json`. `pytest` corre `tests/{unit,integration,contract}` con `pytest-socket` global (`--disable-socket`, `--allow-hosts=127.0.0.1,localhost`, `--allow-unix-socket`) y un fixture de sesión de Postgres en testcontainers. Una prueba confirma que una conexión a un host externo falla y que la conexión a Postgres funciona. El check `architecture` de AI-NATIVE da PASS: el dominio no importa infraestructura ni frameworks y `locales` no importa otros catálogos. `ruff` y `mypy` limpios.

- [x] **T2. Migración 0001: schema `reference`, tablas, constraints, triggers y privilegios.** RF-1, RF-2, RF-3, RF-5, RF-6, RF-15, RF-16, RF-22, RF-27, RNF-3, RNF-4, RNF-5, RNF-6, RNF-7
  - Done when: `alembic upgrade head` crea `locale_snapshot`, `locale` y `locale_alias` como en "Datos" del plan, con todos los `NOT NULL`, CHECKs, FKs (replacement diferida, `first_snapshot_version` no diferida) y triggers. Hay grants condicionales a `reference_reader`/`reference_loader` y `downgrade` funciona. Las pruebas de integración por SQL directo fallan como se espera ante:
    - `NULL` en cada columna `NOT NULL`;
    - `locale_id` duplicado;
    - `code` duplicado;
    - `snapshot_version` duplicada;
    - `snapshot_version` ≤ 0;
    - código fuera de `^[a-z]{2,3}$`;
    - `status` inválido;
    - `replacement` hacia sí mismo, inexistente o sin `iana_deprecated`;
    - `iana_deprecated` con `active`;
    - `first_snapshot_version` inexistente;
    - `DELETE` o cambio de `locale_id`/`code` en `locale`;
    - `UPDATE`/`DELETE` en `locale_snapshot`.
  - Además:
    - una consulta a `pg_constraint` confirma que el CHECK de formato de `code` existe en `reference.locale` con un nombre explícito y estable definido en la migración (RNF-7);
    - `has_schema_privilege` es falso para `anon`, `authenticated` y `public`;
    - `reference_reader` no puede escribir;
    - la allowlist de columnas de `locale` no contiene `tenant_id` ni campos de texto (CA-18).

- [x] **T3. Dominio: reglas de código y parser del artefacto IANA.** RF-3, RF-4, RF-9, RF-28
  - Done when: `domain/codes.py` y `domain/iana.py` pasan pruebas unitarias con todos los casos borde de código de la spec y con un fixture de artefacto IANA sintético y uno real:
    - formato y minúsculas sin normalizar;
    - reglas de publicación 1–6, incluidos *Scope: special*, el rango `qaa..qtz` y el *Preferred-Value* de distinta longitud;
    - `spa`/`eng`/`ger` no registrados;
    - forma bien formada para el lookup, con `-`, `_`, espacios y vacío rechazados.
  - El parser lee el formato record-jar y expone por subtag `Type`, `Deprecated`, `Preferred-Value`, `Scope`, además del `File-Date`.

- [x] **T4. Contrato del snapshot: JSON Schema, digests canónicos y lector.** RF-30, RF-31
  - Done when: existen `contracts/locale-snapshot.v1.schema.json` y las reglas de canonicalización con vectores de prueba. Hay pruebas unitarias para:
    - el schema rechaza la falta de cada campo obligatorio;
    - el digest de contenido (JSON canónico sin `content_digest`) y el digest IANA (bytes de `registry_text`) reproducen los vectores;
    - el mismo documento con otro orden de claves o espacios da el mismo digest;
    - un digest declarado incorrecto se detecta.
  - `infrastructure/snapshot_reader.py` lee un archivo local y no hace accesos de red.

- [x] **T5. Dominio: clasificación contra el historial y precedencia de validaciones.** RF-21, RF-29, RF-30, RF-32
  - Done when: hay una función pura que, tras RF-31, clasifica en A/B/C/D contra el historial antes de validar el artefacto, y luego aplica RF-30 y RF-29. Según el contrato del plan, los datos estructurales requeridos del artefacto IANA son `Type` y `Subtag` en cada entrada y el `File-Date` del registro. `Deprecated`, `Preferred-Value` y `Scope` son campos opcionales por entrada: su ausencia en una entrada no provoca rechazo por sí sola. Pruebas unitarias:
    - primer snapshot = D con cualquier versión;
    - primer snapshot con cualquier `File-Date` válido → aceptado;
    - N reenviado después de N+1 = A (no-op);
    - misma versión con otro digest = B;
    - 11 con 10 y 12 incorporados = C;
    - salto de 3 a 7 = D;
    - un caso B con artefacto IANA inválido se reporta como B;
    - artefacto IANA ausente → rechazo;
    - artefacto IANA sin `File-Date`, o con una entrada sin `Type` o sin `Subtag` → rechazo;
    - entradas sin `Deprecated`, `Preferred-Value` ni `Scope` → no se rechaza por esa ausencia;
    - `File-Date` del artefacto distinto del declarado o menor que el último = rechazo, igual = válido.

- [x] **T6. Dominio: validación del catálogo contra el estado vigente y el artefacto IANA.** RF-3, RF-4, RF-5, RF-15, RF-16, RF-17, RF-18, RF-19, RF-22, RF-26, RF-27, RF-28
  - Done when: hay una función pura que devuelve la lista de violaciones o el plan de cambios (locales nuevos y actualizaciones de metadata). Antes de comparar contra el estado vigente, exige RF-28 sobre todos los códigos del snapshot, tanto de locales nuevos como de locales ya publicados, sin normalizarlos. Pruebas unitarias con los casos borde de la spec:
    - locale ya publicado `he` que llega como `He` → snapshot completo rechazado por RF-28;
    - locale ya publicado `es` que llega como `ES` → snapshot completo rechazado por RF-28;
    - locale nuevo con código fuera de minúsculas → rechazo por RF-28;
    - omisión de un locale publicado;
    - cambio de código o de id;
    - `locale_id` faltante, repetido o reutilizado;
    - código nuevo que no es forma preferida;
    - dos locales nuevos iguales;
    - `iw` publicado y luego deprecado → `inactive` con `replacement` hacia `he` nuevo del mismo snapshot;
    - snapshot sin `he` → rechazo;
    - cadena A→B→C → `replacement` A→C y B→C, y A→B se rechaza;
    - deprecado sin *Preferred-Value*;
    - `inactive` sin deprecación;
    - deprecación o `replacement` distintos del artefacto;
    - deprecado `active`;
    - `replacement` a sí mismo, a un id inexistente o en ciclo;
    - código publicado ausente del artefacto.

- [x] **T7. Incorporación transaccional y CLI.** RF-14, RF-17, RF-18, RF-20, RF-21, RF-28, RNF-1, RNF-2, RNF-5
  - Done when: `application/incorporate.py`, `infrastructure/postgres_repository.py` y `interfaces/cli.py` incorporan un snapshot en una transacción con `pg_advisory_xact_lock`. El orden de escritura es `locale_snapshot` → locales nuevos → metadata → `locale_alias`, y la salida es distinta de cero ante cualquier violación. Pruebas de integración:
    - primer snapshot con `iw` publicado y `active`, incorporado;
    - snapshot posterior cuyo artefacto depreca `iw` con *Preferred-Value* `he`, con `iw` `inactive` y `replacement` → `he`, y `he` incorporado como locale nuevo en ese snapshot. Tras incorporarlo:
      - la metadata de `iw` (`status`, `iana_deprecated`, `replacement_locale_id`) queda actualizada y persistida;
      - el `locale_id` y el `code` de `iw` no cambian;
      - `locale_alias` contiene exactamente los alias del artefacto vigente, incluido `iw` → `he`;
    - N reenviado tras N+1 no cambia nada;
    - un snapshot con un locale ya publicado como `ES` es rechazado y deja el estado idéntico;
    - un fallo inyectado después de insertar `locale_snapshot` no deja esa fila;
    - el artefacto guardado recalcula su digest;
    - dos bases nuevas con el mismo snapshot tienen el mismo estado lógico y los mismos `locale_snapshot` sin `incorporated_at`;
    - la CLI completa el flujo con un guard que hace fallar toda conexión que no vaya a Postgres.

- [x] **T8. API pública read-only y contrato OpenAPI.** RF-7, RF-8, RF-9, RF-10, RF-11, RF-12, RF-13, RNF-1, RNF-2, RNF-4
  - Done when: `application/queries.py`, `interfaces/http.py` y `app.py` exponen los tres endpoints `/v1/locales` del plan con la forma `{snapshot_version, data|error}`. `contracts/locales-api.v1.openapi.json` coincide con el OpenAPI generado. RNF-4 queda cubierto así:
    - contrato público: `architecture.json` declara el módulo `locales` con `public` limitado a `src/gi_common_reference/locales/interfaces/http`;
    - arquitectura interna: con la capa HTTP ya existente, el check `architecture` de AI-NATIVE se vuelve a ejecutar y da PASS con esa declaración. El check solo verifica los imports estáticos internos del repo (capas y superficie pública del módulo); no inspecciona consumidores externos, tablas ni migraciones;
    - acceso directo a persistencia: lo cubren las pruebas de privilegios de T2 (`has_schema_privilege` falso para `anon`, `authenticated` y `public`; `reference_reader` no puede escribir), que siguen en PASS.
  - Pruebas de contrato con `httpx` sobre datos incorporados por T7:
    - por id: 200 y 404;
    - por código: `ES`/`es` → `es`, `iw` sin publicar → `he`, `iw` publicado → `iw`, `es-AR`/`es_AR`/`" es "` → 422, `spa`/`zz` → 404 sin fallback;
    - listado completo y con `status=active`, ordenado por `code`;
    - otros métodos → 405;
    - `snapshot_version` presente en todas las respuestas, `null` con catálogo vacío y nunca 500;
    - consultas repetidas y dos bases iguales devuelven las mismas respuestas;
    - la API responde con el guard de red activo;
    - la API se conecta con `reference_reader`.

## Enmienda `sdd-change` 2026-10-20

T1–T8 están cerradas y no se reescriben. Estas tareas nuevas registran la enmienda (RF-33, RNF-8) y los hallazgos L-A, L-B y L-C de la revisión del 2026-10-20 sobre la corrección de L-9.

- [x] **T9. Campos IANA vacíos en el contrato para PREP.** RF-30, RF-33, CA-20
  - Done when: el contrato para PREP y las pruebas dejan RF-33 verificable:
    - la descripción de `registry_text` en `locale-snapshot.v1.schema.json` dice que `Deprecated` y `Preferred-Value` son opcionales pero no pueden estar vacíos, y que un campo vacío rechaza el snapshot; el cambio está en la copia publicada y en la copia empaquetada, que siguen siendo equivalentes;
    - una prueba de contrato comprueba que ambas descripciones mencionan la regla;
    - las pruebas de parser y de admisión existentes cubren, citando RF-33: `Deprecated:` vacío, `Preferred-Value:` vacío, valor en línea de continuación, campos ausentes y caso B o C con un campo vacío reportado como B o C;
    - `ruff` y `mypy` limpios.
  - El parser y la validación ya rechazan `Deprecated:` y `Preferred-Value:` vacíos (`domain/iana.py`, con `is_deprecated` como única definición de "deprecado"); esta tarea cierra la trazabilidad y el contrato.

- [x] **T10. Verificación de la inmutabilidad ante `TRUNCATE`.** RNF-5, RNF-8, CA-21
  - Done when: `pytest tests/integration/test_migration_0001.py` pasa y demuestra que:
    - `pg_trigger` confirma un trigger `BEFORE TRUNCATE` por sentencia en `locale_snapshot` y en `locale`;
    - `TRUNCATE` falla en ambas, con y sin `CASCADE`, con tabla vacía y con datos;
    - `reference_loader` no puede hacer `TRUNCATE`;
    - `locale_alias` puede vaciarse y reemplazarse;
    - la metadata no identitaria de `locale` sigue siendo actualizable.
  - La migración 0001 ya tiene los triggers `BEFORE TRUNCATE` y sus pruebas (D13, S-25); esta tarea no agrega código, solo deja la verificación asentada.

- [x] **T11. Errores de conexión de la API sin texto del driver (hallazgo L-A).** RNF-4, RF-12
  - Done when: el lector de la API no deja salir texto del driver:
    - cualquier `psycopg.Error` al **conectar** se traduce a `ReaderUnavailable` con solo tipo y SQLSTATE (`describe_error`), igual que en el repositorio; los errores de las consultas posteriores a conectar no se traducen;
    - pruebas unitarias con `connect_timeout=<secreto>`, `sslmode=<secreto>` y host con `@` sin escapar: la excepción, la respuesta HTTP y el log no contienen el secreto, y la API responde 503, no 500;
    - los errores 500 inesperados siguen registrando el traceback.
  - Hoy `PostgresLocaleReader.session()` solo traduce `OperationalError`: un `ProgrammingError` al conectar escapa como 500 y su texto (p. ej. `bad value for connect_timeout: '<valor>'`) llega al log.

- [x] **T12. Errores de conexión de las migraciones sin texto del driver (hallazgo L-B).** RNF-4
  - Done when: `alembic` no deja salir texto del driver:
    - los errores al crear el engine y al conectar se re-lanzan como un `RuntimeError` con solo tipo y SQLSTATE, sin encadenar la causa; los errores de las propias migraciones (SQL, constraints) no se tocan;
    - pruebas con URL malformada, host inalcanzable y contraseña con `@`: el mensaje no contiene el secreto;
    - `docs/operacion.md` documenta que el error de migración muestra solo tipo y SQLSTATE.
  - `migrations/env.py` hoy deja salir el texto crudo del error de conexión, que con una contraseña con `@` sin escapar incluye un fragmento (`failed to resolve host '<fragmento>@host'`) de la credencial del rol dueño.

- [x] **T13. Pruebas del runbook independientes del orden (hallazgo L-C).** RNF-4
  - Done when: la suite del runbook no depende del orden:
    - cada prueba que crea o supone roles parte de un cluster sin ellos (contenedor propio, o creación y limpieza dentro de la prueba);
    - las pruebas pasan en cualquier orden, comprobado ejecutándolas en orden inverso;
    - se conserva la cobertura de los dos órdenes del runbook (roles antes y después de migrar).
  - Los roles son globales al cluster y las pruebas de `test_runbook.py` comparten un contenedor de módulo: ejecutadas en orden inverso, una falla con `role "reference_reader" already exists`.
