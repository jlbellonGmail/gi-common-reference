# Aceptación de 005-units-of-measure

Aceptación **caja negra** de los criterios de la spec `specs/005-units-of-measure/spec.md`, ejecutada el 2026-11-02 sobre el sistema real y **sin datos productivos** (S-3). La revisión de código probada figura en `evidence/01-environment.txt`.

## Qué se ejecutó y qué no

AI-NATIVE v3.4.3 **no expone un comando de Native Acceptance** (ver «Pendiente para AI-NATIVE v4.0.0»). Por eso los criterios se ejecutan como pruebas de caja negra con evidencia reproducible (D18 del plan):

- una base PostgreSQL 16 descartable (testcontainers) con `alembic upgrade head`;
- Locale sintético incorporado con **su CLI** (prerrequisito cerrado 001); Regions, Countries y Currency no intervienen (Units no depende de ellos);
- Units incorporado con **su CLI como subproceso** (`python -m gi_common_reference.units.interfaces.cli incorporate|diff`), con el rol `reference_loader`: el **ejemplo sellado** `contracts/units-snapshot.v1.example.json` (v1: 14 magnitudes, 50 unidades), una **v2 sintética** (alta de la unidad `sack`, sin UCUM, y retiro de `oz`) y una **v3 sintética** (cambio del factor de `sack`, 60 → 50); la v2 y la v3 son dos versiones porque un factor con código UCUM no puede cambiar (verificación cruzada, RF-16) y `sack` no existía en la v1;
- consultas a la **API real** (`uvicorn`, `/v1/quantity-kinds*`, `/v1/units*`, `/v1/conversions`) **por HTTP**, con el rol `reference_reader`;
- la CLI y la API corren con un **guard de red** (`sitecustomize`) que registra y bloquea todo acceso a hosts que no sean locales; un canario demuestra que el guard bloquea de verdad.

El **oráculo** son las cadenas esperadas literales de la spec (CA-1 a CA-3: `1`, `1000`, `10000`, `1000`, `60`, `273.15`, `0`, `1`, `15`) y de `tests/acceptance/test_units_acceptance.py`; ninguna se calcula con el código bajo prueba. Única excepción declarada: la cota de ida y vuelta de CA-8 (CL-9) se recalcula en la prueba con `Fraction` a partir de los factores del ejemplo.

**No se ejecutó contra Supabase `gi-dev`**: no hay credenciales ni se autorizó escribir en un entorno compartido durante este trabajo. Queda como verificación opcional del responsable (HITL).

## Resultado por criterio

Valores de estado: `PASS` = ejecutado en caja negra en esta aceptación; `SUITE_VERIFIED` = verificado por las suites de integración/unitarias/contrato que corren en la suite global (se cita el archivo), **no** en caja negra; `DEFERRED_TO_PREP_DATASET` = no ejecutado.

| Criterio | Estado | Evidencia |
|---|---|---|
| CA-1 | PASS | caso 02: `1000 g→kg = 1`, `1 t→kg = 1000`, `1 ha→m² = 10000`, `1 m³→L = 1000`, `1 h→min = 60` |
| CA-2 | PASS | caso 02: `0 °C→K = 273.15` (Temperature), `32 °F→°C = 0`, `1 °C→K = 1` (TemperatureDifference) |
| CA-3 | PASS | caso 02: `150 kg/ha→g/m² = 15` |
| CA-4 | PASS | caso 03: `kg→L` (`incompatible_units`), unidades de magnitudes distintas, sin magnitud (`quantity_kind_required`) |
| CA-5 | PASS | caso 08: `oz` inactiva en la vigente (`inactive_unit`) y, con `catalog_version=1`, el resultado de entonces |
| CA-6 | PASS | caso 10: UCUM con sintaxis inválida, átomo desconocido, prefijo sobre no métrico, factor declarado distinto del normativo y código publicado cambiado: la CLI sale con 1 y la huella de las seis tablas no cambia. No se ejecutan por HTTP todas las formas de CL-12: el resto de las formas está en `tests/unit/units/domain/test_ucum.py` y `tests/unit/units/domain/test_catalog.py` |
| CA-7 | PASS | casos 08 y 09: la misma conversión histórica da `data` idéntico (bytes de JSON canónico) antes y después de incorporar la v2 y la v3 (`sack`: 120 en la v2, 100 en la vigente) |
| CA-8 | PASS | caso 07: ida y vuelta por HTTP sobre todos los pares ordenados de cada magnitud del ejemplo × 4 valores; cota CL-9 recalculada con `Fraction`. El número de solicitudes y de vueltas omitidas (resultado de ida que no es un valor de entrada admisible por tener más de 30 decimales) consta en `evidence/03-commands.json` |
| CA-9 | SUITE_VERIFIED | `tests/integration/units/test_migration_0005.py` (una prueba SQL por invariante). En caja negra solo se comprueba que el rol lector no puede escribir (caso 12) |
| CA-10 | SUITE_VERIFIED | `tests/integration/units/test_incorporation.py` (dos bases con el mismo snapshot, reenvío, avance de versión). En caja negra el caso 09 comprueba además que las identidades del catálogo inicial se conservan tras la v2 y la v3 |
| CA-11 | PASS (parte HTTP) | caso 05: nombres `en`/`es` de magnitud y unidad, `null` sin fallback, `invalid_locale_id` y `unknown_locale` (422). El rechazo de un snapshot sin `en`/`es` o con un locale `inactive` es **SUITE_VERIFIED**: `tests/unit/units/test_incorporate.py`, `tests/integration/units/test_incorporation.py` |
| CA-12 | PASS | caso 06: °C es una sola identidad en dos magnitudes con transformaciones distintas (`0 °C→K`: `273.15` y `0`); ninguna unidad aparece dos veces |
| CA-13 | SUITE_VERIFIED | `tests/unit/units/domain/test_conversion.py`, `test_ucum.py`, `test_catalog.py` (factores exactos `0.45359237`, `5/9`, `5/18`, half-even en el dígito 34, escala UCUM = factor) |
| CA-14 | PASS | casos 01, 08, 09 y 10: reenvío no-op; misma versión con otro digest, versión anterior, digest adulterado y omisión de una unidad publicada rechazados con la base intacta; versión posterior con alta, retiro y cambio de factor, con `diff` que lo muestra y sin escribir. Además `tests/integration/units/test_incorporation.py` |
| CA-15 | PASS (muestra) | caso 11: OpenAPI servido = publicado, 404 vs 422 con su código, `invalid_parameter`, 405 en PUT/PATCH/DELETE (y GET en `/v1/conversions`), ruta fija `version` vs `{unit_id}`, sin `tenant_id`. La cobertura completa (todos los códigos, catálogo vacío, 503 sin credenciales) es **SUITE_VERIFIED**: `tests/contract/units/test_units_api.py` |
| CA-16 | PASS | caso 04: `-40`, `0`, `-0`→`0`, 30 enteros, 30 fraccionarios y los límites `10^-40` y `9…9×10^10`, aceptados; `1e3`, `+1`, `1,5`, `.5`, `5.`, `007`, ` 1`, `NaN`, `Infinity`, vacío, 31 dígitos y número/`true`/`null`/lista JSON, `invalid_value`. El rechazo `result_not_representable` fuera de rango no es alcanzable con el ejemplo: **SUITE_VERIFIED** en `tests/unit/units/domain/test_conversion.py` (10^40, 10^-40) y `tests/contract/units/test_units_api.py` (saco de 10^20) |
| CA-17 | PASS | casos 13 a 15: Units no importa Locale, Regions, Countries ni Currency (ni clientes de red) y ninguno de ellos importa Units; `git diff` contra la base vacío para `src`, migraciones, contratos y specs de 001–004; ninguna prueba preexistente modificada salvo las fronteras compartidas; ningún proceso salió de localhost |
| CA-18 (a) mecanismo | PASS | caso 01: el ejemplo sellado, no productivo, se incorpora por la CLI y supera la verificación UCUM y cruzada |
| CA-18 (b) contenido real | DEFERRED_TO_PREP_DATASET | **No ejecutado.** Ver más abajo |

| Resumen | Cantidad | Criterios |
|---|---|---|
| PASS ejecutado (caja negra) | 15 | CA-1 a CA-8, CA-11 (parte HTTP), CA-12, CA-14 a CA-17, CA-18(a) |
| SUITE_VERIFIED (no caja negra) | 3 | CA-9, CA-10, CA-13 |
| DEFERRED_TO_PREP_DATASET | 1 | CA-18(b) |
| FAIL | 0 | — |

CA-18 no se cuenta como PASS completo: su parte (a) se ejecutó y pasó; su parte (b) no se ejecutó.

| CA-18(b) diferida | |
|---|---|
| Motivo | El catálogo inicial real de PREP, con procedencia real, no existe en este entorno (S-3). |
| Propietario del gate | Quien publique el primer snapshot real de PREP (mantenedor de `gi-common-reference`). |
| Momento | Antes de incorporar ese snapshot en un entorno compartido (`gi-dev` o superior). |
| Qué verificar | Que el snapshot real se incorpora y supera la verificación UCUM y cruzada con procedencia real y que los códigos UNECE se contrastan con la publicación oficial (el ejemplo se verificó contra una copia derivada de Rec 20). |
| Bloquea el merge | No: la spec define esta feature como contrato y mecanismo y prevé expresamente la verificación con un ejemplo sellado no productivo. |

## Pendiente para AI-NATIVE v4.0.0

No se afirma ningún resultado de v4. Lo siguiente queda pendiente o se resolvió con un sustituto declarado:

- **Native Acceptance no está disponible en v3.4.3.** Los criterios se ejecutaron como pruebas de caja negra. El oráculo son las cadenas esperadas de `tests/acceptance/test_units_acceptance.py` y de este README; los datasets son el ejemplo sellado `contracts/units-snapshot.v1.example.json` y las variantes v2 y v3 generadas por `tests/fixtures/units_variants.py`. Todo está listo para conectarse a Native Acceptance cuando exista.
- **El Dependency Graph determinista no está disponible.** La dependencia 005→001 (Locale) solo se verifica con `architecture.json` y sus pruebas de frontera (`tests/contract/test_architecture_contract.py`, `test_layer_imports.py`, `test_composition_root.py`) y con el caso 13; no hay un grafo de dependencias determinista generado por la herramienta.
- **No hay aceptación sobre Supabase `gi-dev`**: sin credenciales ni autorización.

## Reproducir

```text
python tools/acceptance/units_acceptance.py --base origin/develop
```

Requiere Docker en ejecución y la rama `origin/develop` disponible (si no existe, usa `develop`). Escribe `evidence/01`–`06` y devuelve el código de salida de pytest.

## Casos y criterios

| Caso (`tests/acceptance/test_units_acceptance.py`) | Criterios |
|---|---|
| 01 `diff` sin escribir, incorporación del ejemplo sellado, reenvío no-op, 14 magnitudes y 50 unidades | CA-18(a), CA-14 |
| 02 conversiones básicas con las cadenas exactas de la spec | CA-1, CA-2, CA-3 |
| 03 incompatibles y contexto insuficiente | CA-4 |
| 04 formas de valor válidas e inválidas | CA-16 |
| 05 localización `en`/`es`, sin fallback, locale inválido | CA-11 |
| 06 °C una sola identidad en dos magnitudes | CA-12 |
| 07 ida y vuelta por HTTP sobre todos los pares | CA-8 |
| 08 v2: alta y retiro; unidad retirada rechazada; histórico idéntico | CA-5, CA-7, CA-14 |
| 09 v3: cambio de factor; histórico idéntico; identidades conservadas | CA-7, CA-10 (parte), CA-14 |
| 10 snapshots inválidos rechazados con la base intacta | CA-6, CA-14 |
| 11 contrato publicado, 404/422, 405, ruta fija, sin `tenant_id` | CA-15 |
| 12 el rol lector no escribe | CA-9 (parte) |
| 13 Units sin dependencias de otros catálogos ni clientes de red | CA-17 |
| 14 `git diff` de 001–004 vacío contra la base | CA-17 |
| 15 guard de red: ningún proceso salió de localhost (canario incluido) | CA-17 |
| 16 la tabla UCUM empaquetada es la oficial (sha256) | RNF-7 |

## Evidencia (`evidence/`)

| Archivo | Contenido |
|---|---|
| `01-environment.txt` | revisión de código probada, base `origin/develop`, versiones, imagen de Postgres, código de salida |
| `02-inputs-sha256.json` | SHA-256 de cada snapshot que se envió a la CLI y de la tabla UCUM |
| `03-commands.json` | cada comando ejecutado con código de salida, stdout y stderr (puertos, nombres de base y contraseñas normalizados) |
| `04-http-transcripts.json` | cada petición HTTP con su estado y cuerpo (las de la ida y vuelta de CA-8 se resumen en `03-commands.json`) |
| `05-acceptance-results.txt` | salida de pytest (`-v`) de los 16 casos |
| `06-manifest-sha256.txt` | SHA-256 de los archivos `01`–`05` |
