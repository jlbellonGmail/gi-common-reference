# Aceptación de 004-currency

Aceptación **caja negra** de los criterios de la spec `specs/004-currency/spec.md`, ejecutada el 2026-11-01 sobre el sistema real y **sin datos productivos**.

## Qué se ejecutó y qué no

AI-NATIVE v3.4.3 **no expone un comando de Native Acceptance** (`ai-native help` lista `install`, `init`, `upgrade`, `detach`, `self-update` y `uninstall`). Por eso los criterios se ejecutan como pruebas de caja negra con evidencia reproducible (D24 del plan):

- una base PostgreSQL 16 descartable (testcontainers) con `alembic upgrade head`;
- Locale y Regions incorporados con **sus CLI** (prerrequisitos cerrados 001–002);
- Countries **sembrado** con filas sintéticas (003 está cerrada: se consume, no se reimplementa ni se modifica);
- Currency incorporado con **su CLI como subproceso** (`python -m gi_common_reference.currencies.interfaces.cli incorporate|diff|check-integrity`), con el rol `reference_loader`;
- consultas a la **API real** (`uvicorn`, `/v1/currencies*`) **por HTTP**, con el rol `reference_reader`;
- el CLI y la API corren con un **guard de red** (`sitecustomize`) que registra y bloquea todo acceso a hosts que no sean locales; un canario demuestra que el guard bloquea de verdad.

**No se ejecutó contra Supabase `gi-dev`** (como sí se hizo con 001): no hay credenciales ni se autorizó escribir en un entorno compartido durante este trabajo. Queda como verificación opcional del responsable (HITL).

## Verificación pendiente y declarada (CA-1, S-9)

El **dataset real** de ISO 4217 List One (nombres, entidades ISO → Country, historia territorio–moneda de CLDR) lo produce PREP y no está disponible en este entorno. CA-1 («el catálogo contiene exactamente las monedas de List One de la edición declarada, salvo `XTS` y `XXX`») se verificó contra un **snapshot sintético sellado y marcado como no productivo** (`contracts/currency-snapshot.v1.example.json`, 15 monedas). **La verificación contra el dataset real queda PENDIENTE.** Los códigos, nombres y fechas del snapshot sintético son ejemplos ilustrativos, no datos normativos.

## Reproducir

```text
python tools/acceptance/currency_acceptance.py --base origin/develop
```

Requiere Docker en ejecución y la rama `origin/develop` disponible. Escribe `evidence/01`–`06` y devuelve el código de salida de pytest.

## Casos y criterios

| Caso (`tests/acceptance/test_currency_acceptance.py`) | Criterios |
|---|---|
| 01 primer snapshot, reenvío no-op, todo `active`, sin `XTS`/`XXX` | CA-1, CA-2, CA-11, CA-14 |
| 02 resolver ARS, USD y EUR por código y por id, nombres `en`/`es`, `032`, «no aplicable» | CA-4, CA-16 |
| 03 monedas actuales de un Country y Countries de una Currency; Country sin moneda; moneda sin países | CA-7, CA-17 |
| 04 PA con PAB y USD simultáneas; USD en varios países | CA-17 |
| 05 transición HRK → EUR: `diff` sin escribir, incorporación, consulta por fecha (2022-12-31 → HRK, 2023-01-01 → EUR) | CA-9, CA-18 |
| 06 moneda retirada resoluble y validación `inactive` / `active` / `not_found` | CA-6, CA-22 |
| 07 preservación histórica: HR–HRK `active` y cerrada, HR–EUR abierta, `currency_id` conservado | CA-19 |
| 08 rechazos (misma versión otro digest, versión menor, digest alterado, país inexistente, nombre faltante, reescritura de un período cerrado) con la base idéntica | CA-10, CA-19 |
| 09 `currency_id` faltante y código numérico como número | CA-10 |
| 10 moneda de List Three agregada después, `inactive`, sin alterar las existentes | CA-15 |
| 11 sin camino de escritura para consumidores (405 y sin privilegios) | CA-13 |
| 12 la persistencia rechaza solapamiento temporal y reemplazo en moneda `active` | CA-3 |
| 13 sin dependencias runtime hacia ISO/CLDR: guard de red + análisis estático de imports y URLs | CA-14 |
| 14 001–003 no modificadas por 004 (`git diff` contra la base vacío) | CA-24 |
| 15 Country sin atributo de moneda y Currency sin atributo de país; sin `tenant_id` | CA-2, CA-8 |

## Evidencia (`evidence/`)

| Archivo | Contenido |
|---|---|
| `01-environment.txt` | revisión de código probada, base `origin/develop`, versiones, imagen de Postgres, código de salida |
| `02-inputs-sha256.json` | SHA-256 de cada snapshot que se envió a la CLI |
| `03-commands.json` | cada comando ejecutado con código de salida, stdout y stderr (puertos, nombres de base y contraseñas normalizados) |
| `04-http-transcripts.json` | cada petición HTTP con su estado y cuerpo |
| `05-acceptance-results.txt` | salida de pytest (`-v`) de los 15 casos |
| `06-manifest-sha256.txt` | SHA-256 de los archivos `01`–`05` |
