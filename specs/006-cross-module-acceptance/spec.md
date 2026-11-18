# 006-cross-module-acceptance — Aceptación funcional transversal de 001–005 y grafo de dependencias

- **Estado:** aprobada para implementación autónoma (encargo del responsable, 2026-11-18: «adoptar AI-NATIVE v4.0.1 y demostrar con pruebas funcionales reales que los cinco módulos funcionan individualmente y en conjunto»); merge = decisión humana.
- **Tipo:** Feature de verificación (pruebas, evidencia y documentación). **No agrega ni cambia comportamiento de producto.**
- **Depende de:** `001-locales`, `002-regions-subregions`, `003-countries`, `004-currency`, `005-units-of-measure` (todas cerradas; 006 las consume como caja negra y no las modifica).
- **Nivel SDD:** normal.

## Contexto y objetivo

Cada catálogo tiene su suite y, 004 y 005, su aceptación caja negra. Pero ninguna prueba ejercita los cinco **juntos** tal como se operan: la aceptación de 004 siembra Countries con SQL, y la de 005 solo incorpora Locale. Tampoco existe una declaración verificable del grafo de dependencias entre catálogos: AI-NATIVE v4.0.1 no ofrece comandos de Native Acceptance ni de Dependency Graph.

006 entrega (a) una aceptación funcional **caja negra y transversal** —Postgres real descartable, migraciones por subproceso, cada catálogo incorporado con **su propia CLI** en el orden del grafo, y la API real por HTTP—, (b) el grafo de dependencias como artefacto declarativo **verificado contra el sistema real**, y (c) un manual de aceptación manual para el responsable humano.

## Usuarios

- **Responsable humano / mantenedor:** ejecuta el manual y decide el merge.
- **Revisor independiente:** contrasta evidencia con criterios.
- **Consumidores (Persons, CRM, ERP, verticales):** se benefician de la garantía de que las identidades publicadas por un catálogo son navegables desde los demás.

## Requisitos (EARS)

- RF-1. El sistema de aceptación SHALL crear una base Postgres 16 nueva y descartable por ejecución y aplicar `alembic upgrade head` como subproceso con el rol dueño del schema.
- RF-2. El sistema de aceptación SHALL incorporar los cinco catálogos con sus CLIs instaladas, como subprocesos, en el orden `locales → regions → countries → currencies → units`, con snapshots sintéticos deterministas derivados de `tests/fixtures/*`.
- RF-3. WHEN los cinco catálogos están incorporados, el sistema de aceptación SHALL consultar la API real (uvicorn, rol `reference_reader`) por HTTP.
- RF-4. El repositorio SHALL declarar el grafo de dependencias en `docs/dependency-graph.json` (módulos, tablas propias, migración, CLI, dependencias directas y orden de incorporación).
- RF-5. IF el grafo declarado difiere de las FKs reales entre tablas de módulos distintos, de las dependencias declaradas en las specs, de la cadena de migraciones o de `architecture.json`, THEN la aceptación SHALL fallar.
- RF-6. Toda prueba de 006 SHALL correr sin acceso de red fuera de `localhost` (guard de red de 004) y sin tocar bases productivas.
- RF-7. 006 SHALL NOT modificar código de producto, migraciones, contratos, specs 001–005 ni pruebas existentes.
- RF-8. El runner SHALL dejar la evidencia (entorno, sha256 de entradas, comandos, transcripciones HTTP, resultados, manifiesto) en `acceptance/cross-module/evidence/`.
- RF-9. El repositorio SHALL incluir un manual de aceptación funcional ejecutable por un humano sin investigar la implementación.

## Criterios de aceptación

- CA-1. `alembic current` = `0005 (head)`; cada tabla de `reference` tiene un único módulo dueño; ninguna columna `tenant_id`; `anon`/`authenticated`/`PUBLIC` sin privilegios; `reference_reader` solo `SELECT`. Prueba: `test_01`.
- CA-2. Grafo declarado = FKs reales entre módulos = specs («Depende de») = cadena 0001→0005 = `architecture.json`; orden topológico; ningún módulo importa el paquete de otro. Prueba: `test_02` (+2 mutaciones).
- CA-3. Las cinco CLIs incorporan v1 en orden (exit 0); `diff` (countries, currencies, units) no escribe; una versión por catálogo. Prueba: `test_03`.
- CA-4. Reincorporar los cinco snapshots idénticos es un no-op (dump lógico idéntico). Prueba: `test_04`.
- CA-5. Un consumidor navega por identidades estables: Locale `es` → País AR → Región 019 / Subregión 419 (padre coherente) → monedas de AR (ARS) → países de USD (US, PR), cada uno resoluble → unidades de `mass` → conversión 1 lb → kg = `0.45359237` exacta. Prueba: `test_05`.
- CA-6. El mismo `locale_id` localiza los seis recursos (región, subregión, país, moneda, unidad, magnitud): `en`/`es` con sus nombres, `fr` (activo, sin traducciones) sin fallback, `locale_id` mal formado o inexistente → 4xx. Prueba: `test_06` ×6.
- CA-7. Cada CLI rechaza (exit 1, `RECHAZADO`, motivo explícito, sin escribir) una referencia a otro módulo inexistente o a una versión no incorporada: país→región inexistente, Countries→Regions v2, asociación→país inexistente, Currency→Countries v2, nombre de unidad y de región en locale inexistente. Prueba: `test_07`.
- CA-8. Con SQL directo (rol dueño) la base rechaza: toda FK entre módulos (7 tablas + `country.region_id`) con 23503; cambio de referencia publicada y borrado de identidades referenciadas con 23001/23503. Prueba: `test_08`.
- CA-9. En base nueva, incorporar un catálogo antes que su dependencia falla sin escribir (4 casos + 2 parciales); en orden pasa; `downgrade base` + `upgrade head` es reversible y vuelve a aceptar los cinco. Prueba: `test_09`.
- CA-10. La API es de solo lectura (POST/PUT/PATCH/DELETE → 405; `/v1/conversions` solo POST) y `reference_reader` no puede escribir (42501). Prueba: `test_10`.
- CA-11. El OpenAPI servido de cada módulo = `contracts/*-api.v1.openapi.json`. Prueba: `test_11` ×5.
- CA-12. Conversiones exactas en el sistema integrado (lineal y afín: lb→kg, °C→°F, K→°C, km→m) y rechazo 4xx de magnitudes incompatibles. Prueba: `test_12` ×4, `test_12b`.
- CA-13. Ningún proceso (CLIs, alembic, API) intentó salir de `localhost`. Prueba: `test_13`.
- CA-14. 006 no modifica código, migraciones, contratos, specs 001–005 ni pruebas existentes. Prueba: `test_14`.
- CA-15. Deriva entre módulos: Countries v2 retira PR con PR–USD abierta → `currencies check-integrity` exit 1 con la asociación; Currency v2 sobre Countries v1 rechazada; Currency v2 sobre Countries v2 con la vigencia cerrada → exit 0 y `check-integrity` exit 0; la API refleja PR `inactive`, USD vigente solo en US y PR en el historial. Prueba: `test_15`.

## Casos límite y no-objetivos

- **Banderas de Countries:** el paquete instalado no trae SVG hasta el dataset de PREP (003, S-7). Countries se incorpora con excepciones de bandera declaradas (mismo criterio que la prueba de CLI de 003). `GET /v1/countries/{id}/flag` queda **fuera** de la caja negra transversal (cubierto por las suites de 003 con un almacén inyectado).
- **Datasets reales** (ISO 3166/4217, CLDR, M49, UCUM/UNECE completos) y **Supabase `gi-dev`**: fuera de alcance; siguen como pendientes declarados de 003–005.
- **CRUD:** los catálogos son de solo lectura por API. Alta, cambio y retiro (borrado lógico, `status = inactive`) ocurren solo por incorporación de snapshots versionados; el borrado físico está prohibido por triggers (CA-8, CA-10).
- **CI:** el repositorio no tiene CI; la evidencia es local y reproducible.
- No se crean comandos de AI-NATIVE ni se simulan sus capacidades.
