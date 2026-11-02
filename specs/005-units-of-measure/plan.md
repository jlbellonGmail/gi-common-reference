# Plan 005 — Units of Measure

- **Estado:** approved (2026-11-02, derivado de la spec; mismo alcance, sin requisitos nuevos)
- **Spec:** [spec.md](spec.md)
- **Perfil:** `python-service`; misma estructura que [004-currency](../004-currency/plan.md)

## Precondición (verificada 2026-11-02)

`feature/005-units-of-measure` parte de `develop` `0be253d` con 001–004 aprobadas e implementadas y AI-NATIVE v3.4.3 (CLI v3.4.3, lock v3.4.3). 005 toma, sin cambiarlo:

- `locale_id` UUID (`reference.locale`, `status`), `reference.locale_snapshot` y el lock de incorporación de Locale.
- Convenciones de snapshot de 001/004: `snapshot_version` entera positiva con saltos, digest SHA-256 del JSON canónico sin `content_digest`, clasificación A/B/C/D, incorporación atómica con locks, historial inmutable con el artefacto completo (`artifact jsonb`).
- Sobre de respuesta `{snapshot_version, data}` / `{snapshot_version, error: {code, message}}`, 404/422/503 (D20 de 004).

Ningún archivo de 001–004 se modifica funcionalmente. Archivos compartidos que se extienden (composición): `architecture.json`, `bootstrap.py`, `app.py`, `pyproject.toml` y las pruebas de frontera/composición que enumeran módulos.

## Arquitectura

Módulo nuevo `units`, hexagonal como `currencies`:

```text
units/interfaces (HTTP: consultas GET + POST /v1/conversions; CLI incorporate|diff)
  → units/application (consultas, conversión, incorporación, diff)
     → units/domain (modelo, decimales/racionales, UCUM, catálogo/admisión, conversión, digest, puertos)
        ← units/infrastructure (Postgres, lector de snapshot, política de locales, tabla UCUM empaquetada)
```

- La validación de un snapshot es una función **pura** del dominio: `(snapshot, estado vigente, vista de Locale, política, tabla UCUM) → plan | violaciones`. La base repite las invariantes como constraints y triggers (RNF-4).
- La conversión es una función **pura** del dominio sobre un `ConversionCatalog` inmutable construido desde el artefacto de una versión (D6).
- `units` no importa `locales`, `regions`, `countries` ni `currencies` (ni al revés). Depende de Locale solo por datos (FK a `reference.locale`, lectura de `reference.locale` y `reference.locale_snapshot`).

## Decisiones

| # | Decisión | Alternativa descartada y motivo | Cubre |
|---|---|---|---|
| D1 | `quantity_kind_id` y `unit_id` UUID que viajan en el snapshot; el sistema los valida y registra, nunca los genera. La asociación se identifica por el par (`quantity_kind_id`, `unit_id`) | UUIDv5 del código: identidad dependiente de un código (RF-2) | RF-2, RF-10, D-5 |
| D2 | Snapshot = un documento JSON completo: `quantity_kinds`, `units`, `quantity_kind_units`, `quantity_kind_names`, `unit_names`, `provenance`. Mismo digest y clasificación que 001/004. Claves opcionales presentes con `null` | Delta o un archivo por entidad: no detecta omisiones (RF-43) | RF-41–RF-44 |
| D3 | **Factores y desplazamientos como texto canónico** (RF-13): decimal `^-?(0\|[1-9][0-9]*)(\.[0-9]*[1-9])?$` sin `-0`; factor `>0`, decimal o fracción `p/q` coprimos con `q>1` cuyo denominador tiene un primo distinto de 2 y 5. CHECK en SQL con función `reference.uom_is_canonical_factor(text)` / `uom_is_canonical_decimal(text)` (usa `gcd` de numeric). En Python, `fractions.Fraction` exacta | `numeric` en la base: 5/9 no es representable; `float`: inexacto | RF-11, RF-13, D-9, D-10 |
| D4 | `quantity_kind.conversion_type IN ('linear','affine')`; trigger: una asociación de magnitud `linear` tiene `offset = '0'` | Inferir el tipo de los datos: no protege contra un desplazamiento accidental en un intervalo | RF-12, D-8, CL-1 |
| D5 | **Referencia por FK compuesta diferida**: `quantity_kind.reference_unit_id NOT NULL` + `FOREIGN KEY (quantity_kind_id, reference_unit_id) REFERENCES quantity_kind_unit DEFERRABLE INITIALLY DEFERRED` (el par existe → exactamente una referencia por magnitud). Constraint trigger diferido `uom_check_kind`: la asociación de referencia tiene factor `1` y offset `0`; si la magnitud está `active`, la asociación de referencia y su unidad también. Disparado desde `quantity_kind`, `quantity_kind_unit` y `unit` | Flag `is_reference` en la asociación: necesita índice parcial + trigger para "exactamente una" y el prefijo `is_` choca con D-14 de 004 | RF-8, D-13 |
| D6 | **Conversión desde el artefacto de la versión.** `unit_snapshot.artifact` guarda el snapshot completo e inmutable; el servicio construye un `ConversionCatalog` desde el artefacto de la versión pedida (o la vigente) y lo cachea por versión en memoria (inmutable ⇒ caché sin invalidación salvo por versión). Por solicitud: una consulta de la versión vigente (si no se pide) y, en fallo de caché, una lectura del artefacto. Nuevas e históricas usan el mismo camino ⇒ mismo resultado | Tablas de historia por entidad: mecanismo nuevo (D-11). Convertir desde las tablas vigentes: no reproduce versiones viejas | RF-29–RF-31, RNF-2, RNF-6, D-11 |
| D7 | **Aritmética:** valor `^-?(0\|[1-9][0-9]{0,29})(\.[0-9]{1,30})?$` → `Fraction`; resultado exacto por `Fraction`; rango `0 < \|x\| < 10^-40` o `\|x\| >= 10^40` → `result_not_representable`; si la expansión decimal termina con ≤34 dígitos significativos, se emite exacta; si no, `Decimal(n)/Decimal(d)` con contexto `prec=34, ROUND_HALF_EVEN` (división IEEE correctamente redondeada) y `exact=false`. Formato `f` sin exponente ni ceros finales; `-0` → `0` | Contexto `decimal` en todo el cálculo: redondeos intermedios | RF-21, RF-26–RF-28, D-9, CL-7–CL-9 |
| D8 | **UCUM**: el `ucum-essence.xml` oficial v2.2 se empaqueta sin modificar en `units/infrastructure/ucum/` con `NOTICE.md` (copyright Regenstrief, UCUM License v1.1, URL). La infraestructura lo carga y verifica su sha256 fijado; el dominio recibe una `UcumTable` (prefijos, átomos con `Code`, `isMetric`, `isSpecial`, `isArbitrary`, `value`, `Unit`, función). Parser de la gramática UCUM (§ términos, `.`/`/`, exponentes con signo, paréntesis, anotaciones, factores enteros), evaluación recursiva perezosa a (escala `Fraction`, vector de 7 dimensiones). Especiales admitidas: `Cel` (offset 273.15, 1 K) y `[degF]` (offset 459.67, 5/9 K); otras especiales y arbitrarias → rechazo. Una especial solo como código completo | Transcribir una tabla propia: obra derivada prohibida por la licencia y riesgo de error. Biblioteca externa: dependencia nueva sin necesidad | RF-15–RF-17, D-12, S-4 |
| D9 | Verificación cruzada (RF-16) con unidad U y referencia R de la magnitud: dimensiones iguales; `factor = sU/sR`; `offset = oU − oR·sR/sU` en `affine` y `0` en `linear` | Comparar solo dimensión: no detecta factores erróneos | RF-16, CA-13 |
| D10 | Códigos: `ucum_code text NULL UNIQUE`, `unece_code text NULL UNIQUE CHECK ^[A-Z0-9]{2,3}$`, `quantity_kind.code UNIQUE CHECK ^[a-z][a-z0-9_]{1,63}$`; triggers de inmutabilidad (códigos no nulos inmutables; `code`, `conversion_type`, `reference_unit_id` de la magnitud inmutables) | Índices únicos parciales por `status`: D-14 liga el código también a inactivas | RF-3–RF-5, D-14 |
| D11 | Localizaciones: `quantity_kind_locale (quantity_kind_id, locale_id, name)` y `unit_locale (unit_id, locale_id, name, plural NULL)`, PK del par, FK a `reference.locale`, CHECK de recorte. Política `units/infrastructure/required-locales.v1.json` (`en`, `es`, mismos `locale_id` que 004) | Reutilizar la de Currency: acopla catálogos (D-18) | RF-18–RF-20, D-15, D-16 |
| D12 | `unit_snapshot (snapshot_version PK, content_digest, locale_snapshot_version FK, required_locales_version, ucum_table_version, provenance jsonb, artifact jsonb, incorporated_at)`, sin UPDATE/DELETE/TRUNCATE. Versión vigente = `max(snapshot_version)` | — | RF-36, RF-44, RF-46, RNF-2 |
| D13 | Locks: exclusivo `gi-common-reference.units.incorporation` + compartido sobre el de Locale (mismo mecanismo y claves que 004). `SET CONSTRAINTS ALL IMMEDIATE` antes del commit; una violación de constraint es rechazo (salida 1) | — | RF-19, RF-44 |
| D14 | Provenance por rol: `definitions` (BIPM/NIST), `ucum`, `names` siempre; `unece` si algún código UNECE. Campos: `name, edition, retrieved_at, location, checksum, license`; `unresolved_conflicts: []` | — | RF-41, D-17 |
| D15 | **API** (`/v1/openapi/units.json`, `contracts/units-api.v1.openapi.json`): ver tabla. Rutas fijas antes que `{id}`. Rechazos de conversión = 422 con código estable (la solicitud referencia datos en el cuerpo, no un recurso de la URL); `catalog_version_not_available` 422; falla técnica 503 | 404 para unidades del cuerpo: mezcla recurso de URL con validación de solicitud | RF-21–RF-40, D-19 |
| D16 | `app.py` despacha `/v1/units*`, `/v1/quantity-kinds*`, `/v1/conversions*` y `/v1/openapi/units.json` a la API de Units; el resto sin cambios | — | RNF-5 |
| D17 | `units` replica los helpers chicos de 004 (JSON canónico/digest, conninfo, lector de schema) y una prueba compara el digest con los vectores de 001 | Kernel compartido: reestructura 001–004 | RNF-1 |
| D18 | Aceptación: no hay comando nativo en v3.4.3; criterios ejecutados como caja negra (CLI subproceso + HTTP + Postgres real) con runner `tools/acceptance/units_acceptance.py` y evidencia en `acceptance/units/evidence/` | Afirmar PASS sin ejecutar | CA-1–CA-18 |

## Datos (schema `reference`, migración 0005)

Sin `tenant_id`/`organization_id` (RF-1); sin FK de 001–004 hacia Units (RNF-5). Todas las columnas `NOT NULL` salvo las marcadas.

- **`unit_snapshot`:** D12.
- **`quantity_kind`:** `quantity_kind_id uuid PK`, `code`, `conversion_type`, `reference_unit_id`, `status`, `first_snapshot_version`, `last_changed_snapshot_version`.
- **`unit`:** `unit_id uuid PK`, `ucum_code` (opc.), `unece_code` (opc.), `symbol` (CHECK `symbol <> '' AND symbol = btrim(symbol)`), `status`, versiones.
- **`quantity_kind_unit`:** PK (`quantity_kind_id`, `unit_id`), FK a ambas, `factor`, `offset` (CHECKs D3), `status`, versiones; índice (`unit_id`).
- **`quantity_kind_locale`**, **`unit_locale`:** D11.
- **Triggers:** sin `DELETE`/`TRUNCATE` en las seis tablas; inmutables: identidades, pares, `code`, `conversion_type`, `reference_unit_id`, `first_snapshot_version`, códigos UCUM/UNECE ya no nulos; `uom_linear_offset` (D4); `uom_check_kind` diferido (D5).
- **Privilegios:** `reference_reader` solo `SELECT`; `reference_loader` `SELECT`, `INSERT` y `UPDATE` de columnas mutables (`status`, `symbol`, códigos nulos→valor, `factor`, `offset`, `name`, `plural`, `last_changed_snapshot_version`). Nada para `PUBLIC`/`anon`/`authenticated`; condicionales a que los roles existan, como 0001–0004.
- `downgrade` → `0004` elimina solo lo de 0005.

## Snapshot (contrato con PREP, `contracts/units-snapshot.v1.schema.json`)

```json
{ "snapshot_version": 1, "content_digest": "sha256:…",
  "provenance": {"sources": [{"role": "definitions", "name": "…", "edition": "…", "retrieved_at": "2026-11-02",
                               "location": "…", "checksum": "sha256:…", "license": "…"}],
                 "unresolved_conflicts": []},
  "quantity_kinds": [{"quantity_kind_id": "uuid", "code": "mass", "conversion_type": "linear",
                      "reference_unit_id": "uuid", "status": "active"}],
  "units": [{"unit_id": "uuid", "ucum_code": "kg", "unece_code": "KGM", "symbol": "kg", "status": "active"}],
  "quantity_kind_units": [{"quantity_kind_id": "uuid", "unit_id": "uuid", "factor": "1", "offset": "0", "status": "active"}],
  "quantity_kind_names": [{"quantity_kind_id": "uuid", "locale_id": "uuid", "name": "Mass"}],
  "unit_names": [{"unit_id": "uuid", "locale_id": "uuid", "name": "kilogram", "plural": "kilograms"}] }
```

Ejemplo sellado `contracts/units-snapshot.v1.example.json`, **no productivo** (S-3), con el catálogo inicial de S-6 de la spec; sus códigos UCUM superan la verificación cruzada (D9) y sus códigos UNECE fueron verificados contra Rec 20 (excluidos los marcados como deprecados, p. ej. `HAR`). Copia empaquetada equivalente del schema.

## Incorporación (`python -m gi_common_reference.units.interfaces.cli incorporate|diff <archivo>`)

Una transacción con los locks de D13; ante el primer paso que falla se informan sus violaciones, rollback, salida 1; 0 incorporado o no-op; 2 error operativo.

1. Schema + digest recalculado. 2. Clasificación A/B/C/D. 3. Contexto: Locale vigente; `en`/`es` de la política existen, `active` y con el código esperado. 4. Identidad y completitud: UUID sin repetir; nada publicado ausente (RF-43); pares de asociaciones y localizaciones únicos. 5. Códigos: formatos, unicidad (D-14), inmutabilidad y completado único (RF-5). 6. Magnitudes: tipo y referencia inmutables, referencia es asociación propia con `1`/`0`, activa con referencia activa (RF-8). 7. Asociaciones: factor/offset canónicos (RF-13), `linear` ⇒ offset `0` (RF-12), unidades/magnitudes existentes. 8. UCUM: sintaxis y tabla (RF-15), verificación cruzada (RF-16). 9. Localizaciones (RF-18, RF-19). 10. Procedencia (RF-41). 11. Escritura: `unit_snapshot` (con artefacto) → unidades → magnitudes → asociaciones → nombres → `SET CONSTRAINTS ALL IMMEDIATE` → commit.

`diff`: pasos 1–10 sin escribir ni tomar el lock exclusivo; imprime altas, `status`, símbolo, códigos, factores/offsets (antes → después), nombres y violaciones (RF-45).

## API pública

| Endpoint | Respuesta | Cubre |
|---|---|---|
| `GET /v1/quantity-kinds?include_inactive=&code=&locale_id=` | 200 lista por `code` | RF-32 |
| `GET /v1/quantity-kinds/{quantity_kind_id}?locale_id=` | 200 · 404 `quantity_kind_not_found` · 422 `invalid_quantity_kind_id` | RF-33 |
| `GET /v1/units?quantity_kind_id=&ucum_code=&unece_code=&include_inactive=&locale_id=` | 200 lista por (`symbol` `COLLATE "C"`, `unit_id`) · 404 magnitud del filtro inexistente · 422 | RF-34 |
| `GET /v1/units/version` | 200 `{snapshot_version}` | RF-36 |
| `GET /v1/units/{unit_id}?locale_id=` | 200 con `quantity_kinds: [{quantity_kind_id, status, reference}]` · 404 `unit_not_found` · 422 `invalid_unit_id` | RF-35 |
| `POST /v1/conversions` | 200 `{snapshot_version, data: {result, exact, unit_id, quantity_kind_id, catalog_version}}` · 422 con código · 503 | RF-21–RF-31 |
| Otros métodos | 405 | RF-38 |

- `QuantityKind` = `{quantity_kind_id, code, conversion_type, reference_unit_id, status, name}`; `Unit` = `{unit_id, ucum_code, unece_code, symbol, status, name, plural, quantity_kinds: [{quantity_kind_id, status, reference}]}`. Sin factores (fuera de alcance).
- Cuerpo de conversión: `{quantity_kind_id?, value, from_unit_id, to_unit_id, catalog_version?}`; extra o mal tipado → 422 `invalid_request`. Códigos de rechazo: `invalid_request`, `invalid_value`, `invalid_quantity_kind_id`, `invalid_unit_id`, `invalid_catalog_version`, `quantity_kind_required` (contexto insuficiente), `quantity_kind_not_found`, `unit_not_found`, `inactive_quantity_kind`, `inactive_unit` (unidad o asociación inactiva), `incompatible_units` (unidad no asociada a la magnitud = conversión no soportada), `catalog_version_not_available`, `result_not_representable`; `technical_error` 503. `locale_id`: `invalid_locale_id`, `unknown_locale` 422.
- `snapshot_version` del sobre = versión vigente; `catalog_version` = versión usada por la conversión.

## Estrategia de pruebas

- Sin red (`pytest-socket`), como 001–004.
- **Unit dominio:** decimales y forma canónica; aritmética (todos los casos de §13 del brief, half-even en el límite de 34 dígitos, rango, `-0`, ida y vuelta sobre todos los pares del ejemplo); UCUM: parser (válidos e inválidos de CL-12), evaluación contra el `ucum-essence.xml` empaquetado (kg, `kg/har`, `[mi_i]/h`, `[gal_us]`, `%`, `{each}`, `Cel`, `[degF]`), verificación cruzada; catálogo: cada paso 3–10, plan y diff; conversión con catálogo en memoria (magnitud requerida, incompatibles, inactivas, versión).
- **Integración (Postgres 16 en testcontainers):** SQL directo contra cada constraint/trigger de 0005 (CA-9), privilegios, upgrade/downgrade; incorporación de punta a punta (primer snapshot, no-op, rechazos con dump idéntico, versión posterior con retiro y cambio de factor, histórico reproducible, dos bases iguales); lector SQL = lector en memoria.
- **Contrato:** API con datos incorporados (todos los endpoints y códigos), OpenAPI publicado = generado, los cuatro OpenAPI existentes sin cambios; schema publicado = empaquetado; ejemplo válido con digest correcto; wheel instalado con schema, política y tabla UCUM; fronteras de arquitectura extendidas a `units`.
- **Aceptación (D18):** `tests/acceptance/test_units_acceptance.py` + runner con evidencia (`01-environment`, `02-inputs-sha256`, `03-commands`, `04-http-transcripts`, `05-acceptance-results`, `06-manifest-sha256`).

## Cobertura de requisitos

| Requisito | Dónde |
|---|---|
| RF-1, RF-2, RF-6, RF-7, RF-9 | Datos, triggers, D1 |
| RF-3–RF-5 | D10, paso 5 |
| RF-8, RF-12 | D4, D5, paso 6 |
| RF-10, RF-11, RF-13, RF-14 | D3, datos, paso 7 |
| RF-15–RF-17 | D8, D9, paso 8 |
| RF-18–RF-20 | D11, paso 9, API |
| RF-21–RF-31 | D6, D7, API `POST /v1/conversions` |
| RF-32–RF-40 | API, D15, D16 |
| RF-41–RF-46 | D2, D12, D13, D14, pasos 1–11 |
| RNF-1–RNF-8 | D6, D17, privilegios, pruebas en dos bases, `architecture.json` |
| CA-1–CA-18 | Aceptación (D18) + suites |

## Slices y DAG

```text
T1 esqueleto ─┬→ T2 migración 0005 ──────────────────────┬→ T6 incorporación + repositorio + CLI ─┬→ T9 aceptación → T10 docs
              ├→ T3 contrato snapshot + digest + política ┤                                       │
              ├→ T4 numérico + conversión (dominio) ──────┤                                       │
              └→ T5 UCUM + validación de catálogo ────────┘→ T7 consultas/conversión + lector → T8 API ┘
```

## Riesgos

- **Licencia UCUM:** el archivo se redistribuye sin modificar con aviso; cualquier edición lo invalida (prueba de sha256).
- **Datos reales (S-3):** solo un ejemplo no productivo; CA-18 parte real diferida y declarada.
- **UNECE:** verificado contra una copia derivada de Rec 20 (`datasets/unece-units-of-measure`, sha256 `e2d06370…b76e`), no contra la publicación oficial UNECE; PREP debe verificar contra la fuente oficial.
- **Caché por versión:** correcta porque las versiones son inmutables; memoria acotada por número de versiones consultadas (catálogo de decenas de unidades).

## Rollout y rollback

- **Rollout:** `alembic upgrade head` (0005) → desplegar API → incorporar el snapshot de PREP con `reference_loader` y la CLI de `units`.
- **Rollback:** antes del primer consumidor, `alembic downgrade 0004`; después, corrección hacia adelante con un snapshot nuevo.
