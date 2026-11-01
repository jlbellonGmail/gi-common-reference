# Spec 001 — Locales

- **Estado:** approved
- **Tipo:** Feature (spec base del dominio Reference)
- **Depende de:** ninguna
- **Habilita:** `002-regions-subregions`, `003-countries` y cualquier catálogo global con textos localizados
- **Enmiendas:** `sdd-change` 2026-10-20 — agrega RF-33, RNF-8, CA-20, CA-21, S-24 y S-25 (ningún identificador existente cambia de número)

## Contexto y objetivo

`gi-common-reference` es el propietario de los catálogos globales de GI. Los catálogos siguientes (Regions/Subregions, Countries) necesitan nombres en varios idiomas, y esos textos no deben vivir en sus entidades principales ni identificarse con strings libres como `"ES"`, `"spa"` o `"spanish"`.

Esta spec define `Locale`: un catálogo global, persistente, versionado y de solo lectura que da a cada locale una identidad estable (`locale_id` + código publicado) basada en un estándar interoperable. Sobre esa identidad se apoyará toda representación localizada de Reference.

En v1, un locale representa **únicamente el idioma** de una representación localizada (`es`, `en`, `pt`…). Región, script y demás subtags quedan fuera de esta versión.

**Por qué ahora:** sin una identidad canónica de locale, cada catálogo inventaría su propia representación del idioma, con duplicados equivalentes (`ES` / `es` / `spa`, `iw` / `he`) e integridad imposible de garantizar.

## Usuarios

- **Catálogos de Reference** (002, 003 y posteriores): referencian `locale_id` en sus entidades localizadas.
- **Módulos consumidores** (Core, Tenants, Persons, CRM, ERP, otros COMMON, verticales): resuelven un código de locale a `locale_id` y piden datos localizados.
- **Mantenedores del catálogo** (vía `gi-common-reference-prep`): preparan y publican snapshots versionados.

## Historias de usuario

- HU-1. Como consumidor, tengo el código de un locale y quiero obtener su `locale_id` para pedir datos localizados.
- HU-2. Como consumidor, quiero listar los locales disponibles para saber en qué idiomas puedo pedir datos.
- HU-3. Como autor de una spec de catálogo (002/003), quiero referenciar `locale_id` desde mi entidad localizada con integridad garantizada.
- HU-4. Como mantenedor, quiero publicar un snapshot nuevo que agregue o corrija locales sin romper los IDs ya publicados.
- HU-5. Como consumidor que almacenó un `locale_id`, quiero que siga siendo válido y resoluble en todas las versiones futuras del catálogo.

## Definiciones

- **Locale (v1):** idioma de una representación localizada, identificado solo por un subtag de idioma (p. ej. `es`, `en`, `fil`). No incluye región ni script. No es un país ni un tenant.
- **Registro IANA de referencia:** versión concreta del IANA Language Subtag Registry (identificada por su `File-Date`) que usa un snapshot y contra la que se valida.
- **Artefacto IANA de referencia:** copia del registro IANA de referencia, o representación normativa equivalente, incluida por PREP dentro del snapshot. Es la única fuente del registro que usa `gi-common-reference`.
- **Forma preferida IANA:** para un subtag y una versión del registro, el propio subtag si no tiene *Preferred-Value*, o su *Preferred-Value* si lo tiene. Depende de la versión del registro y puede cambiar entre versiones.
- **Código publicado:** subtag de idioma (BCP 47, RFC 5646) con el que un locale se publicó por primera vez. Junto con `locale_id` forma su identidad histórica: único en el catálogo e inmutable para siempre, aunque versiones posteriores del registro lo deprequen o cambien su forma preferida IANA.
- **Snapshot:** artefacto autocontenido producido por PREP e incorporado por `gi-common-reference`. Incluye `snapshot_version`, digest de contenido, `File-Date` del registro IANA de referencia, contenido completo del catálogo de locales, artefacto IANA de referencia y provenance (RF-30, RF-31).
- **`snapshot_version`:** versión de un snapshot, asignada por PREP, con orden total y comparación determinística. Junto con el digest de contenido identifica al snapshot.
- **Locale publicado:** locale presente en al menos un snapshot ya incorporado.
- **Locale nuevo:** locale de un snapshot cuyo código no figura en ningún snapshot incorporado antes. Llega con un `locale_id` asignado por PREP que nunca se usó en el catálogo.
- **`status`:** estado general del registro dentro del catálogo, según la convención común de los catálogos globales (ver "Convención de estado").
- **Deprecación del estándar:** hecho declarado por el registro IANA de referencia (`Deprecated`) sobre el código publicado de un locale. Es información del estándar, no un valor de `status`.
- **`replacement`:** `locale_id` del locale cuyo código publicado es el *Preferred-Value* que el registro IANA de referencia declara para el código publicado de un locale. Solo existe si hay deprecación del estándar con *Preferred-Value*.

## Reglas de publicación de un código nuevo (canonicalización)

Se aplican **solo a locales nuevos**, contra el registro IANA de referencia del snapshot que los publica. No se vuelven a exigir sobre locales ya publicados (ver RF-26).

Subconjunto admitido de BCP 47 en v1: **`language`** (un único subtag, sin `-`). La autoridad es el registro IANA de referencia, no una regla de longitud propia de esta spec.

1. El código es un subtag de tipo `language` registrado en el registro IANA de referencia (ISO 639).
2. Formado por 2 o 3 letras ASCII en **minúsculas** (`es`, `fil`). PREP entrega los códigos ya en minúsculas; el sistema no normaliza códigos de snapshots (RF-28).
3. Solo valen los subtags que el registro IANA de referencia registra como `language`. Los códigos ISO 639 alternativos que IANA no registra como subtag (`spa`, `eng`, los códigos bibliográficos como `ger`) no son válidos ni se traducen a otro código.
4. El código debe ser su propia forma preferida IANA: un subtag con *Preferred-Value* no se publica; se publica su *Preferred-Value* (`iw` → `he`, `in` → `id`, `ji` → `yi`), aunque implique pasar de 2 a 3 letras o de 3 a 2. Ninguna longitud tiene prioridad sobre el *Preferred-Value*.
5. Excluidos: subtags de *Scope: special* (`und`, `mul`, `mis`, `zxx`) y el rango de uso privado `qaa`–`qtz`.
6. No admitidos en v1: región (`-AR`, `-419`), script (`-Hant`, `-Latn`), variantes, extensiones (`-u-`, `-t-`), uso privado (`x-`), extlang y tags grandfathered. Cualquier `-` o `_` en el código lo deja fuera del subconjunto.

## Convención de estado

Locale aplica la convención común de los catálogos globales de `gi-common-reference`, que esta spec establece por ser la primera (S-10) y que Region, Subregion, Country, Currency y los catálogos posteriores deben adoptar sin variantes:

| Atributo | Valores | Semántica común |
|---|---|---|
| `status` | `active` | Publicado, resoluble y apto para nuevas referencias. |
| | `inactive` | Publicado y resoluble para no romper referencias existentes; no recomendado para nuevas referencias. |

- No existen `is_active`, `enabled`, `state` ni valores propios de Locale.
- Ningún valor de `status` implica borrado: un registro publicado nunca deja de existir.
- La deprecación del estándar y el `replacement` son información aparte, propia de Locale, que no se codifica en `status`. Su única relación con `status` es la regla RF-27: la deprecación del estándar implica `inactive`; `inactive` no implica deprecación del estándar.

## Requisitos funcionales

### Identidad y modelo

- RF-1. EL SISTEMA DEBERÁ mantener `Locale` como catálogo global, sin `tenant_id` ni ningún atributo de propiedad de consumidor, tenant, país o persona.
- RF-2. EL SISTEMA DEBERÁ identificar cada locale con un `locale_id` único, inmutable y que no dependa del texto del código para su estabilidad, asignado por PREP (RF-17).
- RF-3. EL SISTEMA DEBERÁ asociar a cada locale exactamente un código publicado, único en todo el catálogo e inmutable, que cumplió las reglas de publicación al incorporarse el snapshot que lo publicó por primera vez.
- RF-4. SI un snapshot incluye un locale nuevo cuyo código no cumple las reglas de publicación contra su registro IANA de referencia, o dos locales nuevos con el mismo código, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot. Publicar como locale nuevo la forma preferida IANA de un código publicado con deprecación del estándar (p. ej. `he` con `iw` ya publicado) es válido.
- RF-5. EL SISTEMA DEBERÁ registrar por cada locale su `status` (`active` o `inactive`), si tiene deprecación del estándar y, solo si la tiene con *Preferred-Value*, su `replacement`.
- RF-6. EL SISTEMA NO DEBERÁ persistir textos traducibles (nombres de idiomas, etiquetas) en la entidad `Locale`.

### Contratos públicos de lectura

- RF-7. CUANDO un consumidor pida un locale por `locale_id`, EL SISTEMA DEBERÁ devolver su `locale_id`, código publicado, `status`, la deprecación del estándar y el `replacement` (si existen), o un resultado explícito de "no encontrado".
- RF-8. CUANDO un consumidor pida un locale por código, EL SISTEMA DEBERÁ normalizar a minúsculas (RFC 5646 no distingue mayúsculas) y devolver el locale con ese código publicado, cualquiera sea su `status`; si ninguno lo tiene y el artefacto IANA de referencia del snapshot vigente declara un *Preferred-Value* para ese código, devolver el locale cuyo código publicado sea ese *Preferred-Value*.
- RF-9. SI el código pedido no es un subtag de idioma bien formado (2 o 3 letras ASCII, sin `-`, `_` ni espacios), ENTONCES EL SISTEMA DEBERÁ devolver un error de validación distinguible de "no encontrado".
- RF-10. SI el código pedido está bien formado pero no se resuelve por RF-8, ENTONCES EL SISTEMA DEBERÁ devolver "no encontrado" sin aplicar fallback a otro locale.
- RF-11. CUANDO un consumidor liste locales, EL SISTEMA DEBERÁ devolver todos los locales publicados con su `status`, permitir restringir el resultado a `status = active` y devolverlos en orden determinístico.
- RF-12. EL SISTEMA DEBERÁ exponer los contratos de Locale solo como lectura; no existirá operación pública de alta, modificación ni baja.
- RF-13. EL SISTEMA DEBERÁ exponer en los contratos la `snapshot_version` del snapshot vigente del catálogo de locales.

### Snapshots, versionado y ciclo de vida

- RF-14. EL SISTEMA DEBERÁ modificar el catálogo únicamente mediante la incorporación de snapshots versionados, validados y con provenance; no consulta IANA ni ninguna fuente externa, ni al incorporar ni en runtime, y no cambia datos por su cuenta.
- RF-15. SI un snapshot omite un locale publicado, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo (los locales publicados no se eliminan).
- RF-16. SI un snapshot cambia el código publicado de un `locale_id`, asigna un código publicado a otro `locale_id` o asigna un `locale_id` nuevo a un código publicado, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo.
- RF-17. CUANDO un snapshot incluya un locale nuevo, EL SISTEMA DEBERÁ exigir que traiga un `locale_id` asignado por PREP, no usado antes en el catálogo ni repetido en el snapshot, e incorporarlo sin modificarlo; SI no lo cumple, ENTONCES rechazará el snapshot. El sistema nunca genera `locale_id`.
- RF-18. CUANDO un snapshot cambie metadatos no identitarios (`status`, deprecación del estándar, `replacement`), EL SISTEMA DEBERÁ aplicarlos conservando `locale_id` y código publicado.
- RF-19. CUANDO se incorpore un snapshot cuyo registro IANA de referencia declara la deprecación del estándar del código publicado de un locale, EL SISTEMA DEBERÁ conservar su `locale_id` y código publicado, mantenerlo resoluble por ambos y aplicar la deprecación, el `status` (RF-27) y el `replacement` que el snapshot declara; no creará el locale del `replacement`: debe estar publicado o incluido en el mismo snapshot.
- RF-20. SI un snapshot falla cualquier validación, ENTONCES EL SISTEMA DEBERÁ dejar el catálogo exactamente en el estado anterior (incorporación atómica).
- RF-21. CUANDO llegue un snapshot ya incorporado, sea o no el último (caso A de RF-32), EL SISTEMA DEBERÁ tratarlo como no-op: no modifica el catálogo vigente, no crea un snapshot histórico nuevo, no altera el orden de versiones ni vuelve el estado atrás. CUANDO el mismo snapshot se incorpore en distintos entornos, DEBERÁ producir el mismo estado con los mismos `locale_id` (idempotencia y determinismo).
- RF-22. SI un `replacement` apunta a un `locale_id` que no está publicado ni incluido en el mismo snapshot, a sí mismo o forma un ciclo, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot antes de incorporarlo.
- RF-26. EL SISTEMA DEBERÁ validar cada snapshot exclusivamente contra su artefacto IANA de referencia (RF-30) y rechazarlo si: un locale nuevo incumple RF-4; el código publicado de algún locale no está registrado como `language` en ese registro; o la deprecación del estándar o el `replacement` de algún locale no coinciden con lo que ese registro declara para su código publicado. No exigirá que el código publicado de un locale ya publicado siga siendo su forma preferida IANA.
- RF-27. SI el registro IANA de referencia declara la deprecación del estándar del código publicado de un locale y el snapshot no lo deja con `status = inactive`, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot.
- RF-28. SI un snapshot contiene algún código que no está en minúsculas (p. ej. `He`, `ES`, `Pt`), ENTONCES EL SISTEMA DEBERÁ rechazarlo completo sin normalizarlo. La tolerancia a mayúsculas es solo del lookup público (RF-8).
- RF-29. SI un snapshot declara un registro IANA de referencia con `File-Date` anterior al del último snapshot incorporado, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo. Un `File-Date` igual o posterior es válido si el snapshot cumple las demás reglas.
- RF-30. EL SISTEMA DEBERÁ exigir que cada snapshot sea autocontenido respecto del registro IANA: debe incluir el artefacto IANA de referencia, con al menos `Type`, `Subtag`, `Deprecated`, `Preferred-Value`, `Scope` y el `File-Date` del registro, más provenance y un digest de integridad de esa fuente. SI falta el artefacto, le faltan esos datos, su `File-Date` no coincide con el declarado por el snapshot o el digest IANA recalculado no coincide con el declarado, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot. Los campos `Deprecated` y `Preferred-Value` de una entrada son opcionales, pero si están no pueden estar vacíos (RF-33).
- RF-31. EL SISTEMA DEBERÁ exigir que cada snapshot incluya `snapshot_version`, digest de contenido, `File-Date`, contenido completo del catálogo, artefacto IANA de referencia y provenance, y recalcular el digest de contenido; SI falta alguno o el digest recalculado no coincide con el declarado, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo. Cada digest se calcula de forma determinística (el mismo artefacto produce siempre el mismo digest) sobre una representación que no incluye su propio valor declarado.
- RF-32. CUANDO llegue un snapshot que cumple RF-31, EL SISTEMA DEBERÁ clasificarlo contra el historial de snapshots incorporados antes de cualquier otra validación (incluida RF-29):
  - A. `snapshot_version` igual a la de un snapshot incorporado y mismo digest → snapshot ya incorporado: no-op idempotente (RF-21), aunque después se hayan incorporado versiones posteriores.
  - B. `snapshot_version` igual a la de un snapshot incorporado y digest distinto → rechazo completo: una `snapshot_version` nunca representa más de un contenido.
  - C. `snapshot_version` no incorporada y anterior a la última incorporada → rechazo completo por regresión; no se insertan snapshots entre versiones ya incorporadas.
  - D. `snapshot_version` posterior a la última incorporada, consecutiva o no → continúa con las demás validaciones.
- RF-33. SI el artefacto IANA de referencia de un snapshot contiene, en cualquier entrada, un campo `Deprecated` o `Preferred-Value` presente pero sin valor, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot completo por artefacto IANA incompleto (RF-30). Se evalúa en la etapa de RF-30, después de la clasificación de RF-32: no altera los casos A, B ni C. La presencia de `Deprecated` es lo que define la deprecación del estándar de una entrada, y la de `Preferred-Value`, su forma preferida; ningún código interpreta un campo vacío.

### Contrato para catálogos dependientes

RF-23 a RF-25 son un contrato normativo que 001 establece para los catálogos que introduzcan entidades localizadas; 001 no crea ninguna. No se verifican en 001: cada spec que introduzca una entidad `<Entidad>Locale` (002, 003 y posteriores) deberá adoptar explícitamente este contrato, definir sus RF y criterios de aceptación concretos, y verificar la FK hacia Locale, la unicidad `(entidad_id, locale_id)` y que el runtime sirva solo textos persistidos.

- RF-23. EL SISTEMA DEBERÁ representar todo texto localizado de un catálogo de Reference en una entidad asociativa `<Entidad>Locale` que referencie `locale_id`, con a lo sumo una fila por par (entidad, locale).
- RF-24. EL SISTEMA DEBERÁ impedir, mediante constraints de base de datos, que una entidad localizada de Reference referencie un `locale_id` inexistente.
- RF-25. EL SISTEMA DEBERÁ servir en runtime solo textos localizados persistidos y versionados; ninguna consulta invocará traducción automática ni modelos de IA.

## Requisitos no funcionales

- RNF-1. Determinismo: la misma versión de snapshot y la misma consulta devuelven siempre el mismo resultado.
- RNF-2. Sin dependencias externas: resolver o listar locales no requiere red, servicios de traducción, IA ni consultar IANA. Los códigos publicados y los alias por *Preferred-Value* que necesita RF-8 se derivan, al incorporar, del artefacto IANA de referencia del snapshot; es el único origen de verdad del registro.
- RNF-3. Integridad en la base de datos: unicidad de `locale_id` y de código publicado, formato del código (minúsculas, 2–3 letras), y existencia del `locale_id` referenciado por `replacement` se protegen con constraints, no solo con lógica de aplicación.
- RNF-4. Aislamiento: los consumidores dependen solo de los contratos públicos, nunca de tablas, migraciones ni clases internas.
- RNF-5. Trazabilidad: todo snapshot incorporado con éxito se conserva como artefacto completo, versionado e inmutable (`snapshot_version`, digest de contenido, contenido del catálogo, provenance, `File-Date` y artefacto IANA de referencia con su digest); nunca se modifica ni se reemplaza retroactivamente, y cada snapshot posterior representa un estado nuevo del catálogo. La conservación sirve a auditoría; no se expone una API pública de consulta histórica.
- RNF-6. Independencia: Locale no depende de Country, Region/Subregion, Currency ni de ningún catálogo que lo consuma (sin ciclos `Locale → X → Locale`).
- RNF-7. Extensibilidad compatible: admitir más adelante región o script solo podrá agregar locales nuevos con `locale_id` nuevos; no cambiará el id ni el código publicado de los locales de idioma ya publicados.
- RNF-8. Inmutabilidad en la base de datos: EL SISTEMA DEBERÁ impedir, con constraints y triggers de base de datos y aunque la sentencia no pase por la aplicación, que el historial de snapshots y los locales publicados se modifiquen, eliminen o vacíen. En concreto: ni `UPDATE`, `DELETE` ni `TRUNCATE` sobre el historial de snapshots; ni `DELETE`, `TRUNCATE` ni cambio de `locale_id` o código publicado sobre los locales. Solo la metadata no identitaria de un locale (RF-18) puede actualizarse.

## Casos borde

- `ES`, `Es`, `es` → se resuelven a `es` (RF-8).
- `es-AR`, `es-419`, `pt-BR`, `zh-Hant`, `es_AR` → fuera del subconjunto v1: error de validación, sin fallback a `es` (RF-9).
- `x-klingon`, `i-klingon`, `en-u-ca-gregory` → error de validación (RF-9).
- `" es "`, cadena vacía → error de validación; no se recortan espacios (RF-9).
- `spa`, `eng`, `ger` → bien formados pero no registrados en IANA como subtag `language`: "no encontrado" en consulta, sin traducirse a `es`, `en` o `de` (RF-10), y rechazo si llegan como locale nuevo (RF-4).
- `zz` → bien formado, inexistente: "no encontrado" (RF-10).
- Locale nuevo cuyo subtag tiene *Preferred-Value* de otra longitud (2 → 3 letras o 3 → 2) → se rechaza; se publica el *Preferred-Value* (regla 4, RF-4).
- Consulta por `iw` sin locale con código publicado `iw` → se resuelve al locale `he` (RF-8).
- Código publicado que el registro deprecia más tarde (`iw` publicado; un registro posterior lo depreca con *Preferred-Value* `he`):
  - `iw` conserva `locale_id` y código publicado, queda `status = inactive`, con deprecación del estándar y `replacement` → `he` (RF-19, RF-27).
  - `he` se publica como locale nuevo en ese snapshot o uno anterior, con su propio `locale_id` y `status = active` (RF-4, RF-19).
  - La consulta por `iw` devuelve el locale `iw`, no `he` (RF-8).
  - Un snapshot con ese registro que no incluya el locale `he` se rechaza (RF-22).
- `iw` y `he` como locales nuevos en el mismo snapshot → `iw` se rechaza por no ser forma preferida IANA (RF-4).
- `He` en un snapshot (nuevo o publicado) → snapshot rechazado, sin normalizar a `he` (RF-28). En el lookup público, `He` se resuelve a `he` (RF-8).
- Locale nuevo sin `locale_id`, con un `locale_id` ya usado en el catálogo o repetido en el snapshot → rechazado (RF-17).
- Código publicado que llega con otro `locale_id` → rechazado (RF-16).
- Locale nuevo `he` y `replacement` de `iw` → `he` en el mismo snapshot → válido: el `locale_id` de `he` viene en el snapshot (RF-17, RF-22).
- Cadena de reemplazos (A publicado; un registro depreca A → B; uno posterior depreca B → C):
  - Por RFC 5646 §3.1.7, el registro actualiza el *Preferred-Value* de A a C al deprecar B. El snapshot que declara ese registro deja A con `replacement` → C y B `inactive` con `replacement` → C (RF-18, RF-26).
  - A y B conservan `locale_id` y código publicado; la relación A → B sigue en el snapshot N, que se conserva completo e inmutable (RNF-5). El snapshot N+1 (A → C, B → C) es un estado nuevo, no una edición de N.
  - Un snapshot que mantenga A → B con ese registro se rechaza (RF-26); los ciclos siempre se rechazan (RF-22).
- Deprecación del estándar sin *Preferred-Value* → `inactive`, sin `replacement` (RF-5, RF-27).
- Locale `inactive` por decisión del catálogo sin deprecación del estándar → resoluble, sin `replacement` (RF-5).
- Snapshot con `File-Date` anterior al del último snapshot incorporado → rechazado completo, aunque el resto sea válido; no hay rollback de la versión IANA (RF-29).
- Snapshot con el mismo `File-Date` que el último incorporado (p. ej. solo agrega locales) → válido si cumple las demás reglas (RF-29).
- Primer snapshot (catálogo vacío) → cualquier `File-Date`; no hay versión previa con la que comparar (RF-29).
- Snapshot sin artefacto IANA de referencia, con datos IANA incompletos, con `File-Date` del artefacto distinto del declarado o con digest IANA que no coincide → rechazado (RF-30).
- Reincorporar el último snapshot (misma `snapshot_version`, mismo digest) → no-op, sin versión nueva (RF-21, RF-32 caso A).
- N y N+1 incorporados; vuelve a llegar exactamente N → no-op: el catálogo sigue en N+1 y no se aplica RF-29 aunque su `File-Date` sea anterior (RF-21, RF-32 caso A).
- `snapshot_version` de cualquier snapshot incorporado con digest distinto → rechazado (RF-32 caso B).
- Versiones 10 y 12 incorporadas; llega por primera vez la 11 → rechazado por regresión (RF-32 caso C).
- `snapshot_version` posterior no consecutiva (p. ej. de 3 a 7) → válida si cumple las demás reglas (RF-32 caso D).
- Digest de contenido o digest IANA declarado que no coincide con el recalculado → rechazado (RF-30, RF-31).
- Código publicado que no aparece en el registro IANA de referencia (el registro no elimina subtags; indica un registro erróneo) → snapshot rechazado (RF-26).
- `und`, `mul`, `zxx`, `mis`, `qaa` → no admitidos como locales nuevos (regla 5).
- Macrolenguaje e idioma individual (`zh` y `cmn`, `ar` y `arb`) son subtags distintos sin *Preferred-Value* entre sí: son códigos distintos; incluirlos es decisión del dataset.
- `zh` no distingue chino tradicional y simplificado en v1: un catálogo que necesite ambas formas requiere ampliar el subconjunto (RNF-7).
- Catálogo vacío (antes del primer snapshot): las consultas devuelven listas vacías o "no encontrado", nunca error interno.
- Artefacto IANA con `Deprecated:` o `Preferred-Value:` sin valor en alguna entrada → snapshot rechazado por artefacto incompleto (RF-33, RF-30), aunque el resto sea válido.
- `Deprecated:` o `Preferred-Value:` cuyo valor está en una línea de continuación → el campo está presente y con valor (RF-33).
- Entrada sin `Deprecated`, `Preferred-Value` ni `Scope` → válida; la ausencia de un campo opcional nunca rechaza el snapshot (RF-30, RF-33).
- Un caso B o C cuyo artefacto IANA tiene un campo vacío se reporta como B o C, no como RF-33 (RF-32 precede a RF-30 y RF-33).
- `UPDATE`, `DELETE` o `TRUNCATE` por SQL directo sobre el historial de snapshots, o `DELETE`/`TRUNCATE` sobre los locales → rechazado por la base (RNF-8). Los alias derivados se reemplazan enteros en cada incorporación, así que no están protegidos.

## Fuera de alcance

- Locales con región, script, variantes, extensiones o uso privado (posible versión futura, RNF-7).
- Country, CountryLocale, Region, RegionLocale, Subregion, SubregionLocale, Currency, CountryCurrency (se definen en sus specs; esta spec solo fija la regla RF-23–RF-25).
- Nombres localizados de los propios locales (p. ej. "Spanish" / "Español").
- Contenido concreto del dataset inicial (lo aporta PREP respetando este contrato).
- Seguir automáticamente el `replacement` al resolver un locale.
- API pública de consulta de estados históricos del catálogo (la historia se conserva para auditoría, RNF-5).
- Algoritmo o formato con que PREP genera `locale_id` (se define en PLAN).
- Forma física y serialización del snapshot y del artefacto IANA, formato de `snapshot_version` y procedimiento de cálculo del digest (se definen en PLAN).
- Observar el registro IANA o reaccionar a sus cambios fuera de la incorporación de snapshots.
- Traducción dinámica con IA en runtime.
- Idioma preferido de usuario o de tenant.
- i18n de interfaces, formatting de fechas/números/monedas, negociación HTTP de idiomas, lógica de frontend.
- Fallback entre locales: corresponde a cada consumidor.
- CRUD público de locales.
- Validar otros campos vacíos del artefacto IANA (`Description`, `Comments`…) o el formato de la fecha de `Deprecated`: solo `Deprecated` y `Preferred-Value` tienen semántica en 001 (RF-33).
- Proteger el catálogo frente al dueño del schema o un superusuario (`DROP TABLE`, `ALTER TABLE … DISABLE TRIGGER`, `session_replication_role`): es un control operativo del acceso a la base, no de la base misma (RNF-8).

## Criterios de aceptación

- CA-1. Locale existe como catálogo global persistente sin `tenant_id` (RF-1).
- CA-2. Cada locale tiene un `locale_id` y un código publicado únicos e inmutables (RF-2, RF-3).
- CA-3. Las reglas de publicación están documentadas y probadas con los casos borde de esta spec: se aplican solo a locales nuevos, rechazan región, script u otros subtags, y el *Preferred-Value* prevalece con independencia de su longitud (RF-4, RF-8, RF-9, RF-26).
- CA-4. Se puede obtener un locale por id, por código y listar locales, solo en lectura (RF-7–RF-13).
- CA-5. No existe ninguna operación pública de escritura sobre Locale (RF-12).
- CA-6. El catálogo solo cambia por snapshots versionados, validados contra su registro IANA de referencia, atómicos e idempotentes (RF-14, RF-20, RF-21, RF-26).
- CA-7. Un snapshot que elimine un locale publicado, cambie su código publicado, reutilice un id/código, declare deprecación o `replacement` distintos de su registro o deje `active` un locale con deprecación del estándar es rechazado (RF-15–RF-17, RF-26, RF-27).
- CA-8. Un código publicado deprecado después por IANA conserva `locale_id`, código publicado y resolubilidad; queda `inactive` con deprecación del estándar y `replacement` registrados aparte, y su forma preferida IANA puede publicarse como locale nuevo `active` (RF-4, RF-19, RF-27).
- CA-9. El runtime de Locale no invoca traducción, IA ni consulta IANA (RNF-2).
- CA-10. Locale no tiene dependencias hacia Country, Region/Subregion ni Currency (RNF-6).
- CA-11. El estado general de Locale se expresa solo con `status` (`active` | `inactive`), según la convención común, sin atributos ni valores propios; la deprecación del estándar y el `replacement` se exponen por separado (RF-5, RF-7).
- CA-12. Una cadena de deprecaciones A → B → C produce `replacement` A → C y B → C, sin ciclos ni cambios de identidad, y el snapshot anterior con A → B se conserva sin cambios (RF-18, RF-22, RF-26, RNF-5).
- CA-13. Los `locale_id` vienen asignados por PREP en el snapshot; el sistema no los genera ni los modifica, y el mismo snapshot produce los mismos ids en cualquier entorno (RF-17, RF-21).
- CA-14. Un snapshot con algún código fuera de minúsculas es rechazado; el lookup público sí tolera mayúsculas (RF-8, RF-28).
- CA-15. Un snapshot con `File-Date` del registro IANA anterior al del último snapshot incorporado es rechazado; con `File-Date` igual o posterior se acepta si cumple las demás reglas (RF-29).
- CA-16. La incorporación y el lookup funcionan sin red: un snapshot sin artefacto IANA válido es rechazado, y RF-8 y RF-26 usan solo el artefacto incluido en el snapshot (RF-8, RF-14, RF-26, RF-30, RNF-2).
- CA-17. Reincorporar cualquier snapshot ya incorporado (el último o uno anterior) es un no-op; reutilizar una `snapshot_version` con otro digest, incorporar una versión nueva anterior a la última o declarar un digest que no coincide con el recalculado se rechazan; una versión posterior no consecutiva se acepta (RF-21, RF-30, RF-31, RF-32).
- CA-18. La entidad Locale no contiene campos de texto traducible o localizado (`name`, `display_name`, `localized_name`, `description`, `label` ni equivalentes): solo su identidad y la metadata técnica y de ciclo de vida definida en esta spec (RF-6).
- CA-19. El contrato para catálogos dependientes (RF-23–RF-25) queda establecido en esta spec; 001 no incluye pruebas de entidades localizadas inexistentes y la verificación de FK, unicidad `(entidad_id, locale_id)` y runtime se exige en cada spec que introduzca una (RF-23–RF-25).
- CA-20. Un snapshot cuyo artefacto IANA tiene un `Deprecated` o `Preferred-Value` vacío es rechazado; con esos campos ausentes o con valor, se acepta si cumple las demás reglas; y la regla está documentada en el contrato para PREP (RF-30, RF-33).
- CA-21. Ni `UPDATE`, `DELETE` ni `TRUNCATE` por SQL directo pueden alterar el historial de snapshots; ni `DELETE`, `TRUNCATE` ni cambio de identidad, los locales publicados; la metadata no identitaria sigue siendo actualizable (RNF-8, RF-18).

## Supuestos y decisiones

- S-1. Referencia normativa: BCP 47 (RFC 5646) y el IANA Language Subtag Registry para el subtag de idioma y su canonicalización. Motivo: estándar interoperable de facto (HTTP, CLDR, ICU, navegadores).
- S-2. Subconjunto v1 = solo `language` (decisión de alcance del responsable, clarify 2026-10-19). Motivo: los catálogos dependientes solo necesitan distinguir el idioma de sus textos; región y script se podrán agregar como cambio compatible (RNF-7).
- S-3. El lookup público acepta cualquier combinación de mayúsculas/minúsculas, pero no recorta espacios ni acepta separadores. Motivo: BCP 47 no distingue mayúsculas; tolerar más abre ambigüedad. Los snapshots, en cambio, deben traer los códigos ya en minúsculas y el sistema no normaliza datos de publicación (RF-28; confirmado por el responsable, 2026-10-19).
- S-4. La identidad (`locale_id` ↔ código publicado) es biyectiva y permanente; la evolución del registro se modela con deprecación del estándar + `replacement`, nunca reescribiendo códigos.
- S-5. No se mapean códigos ISO 639 alternativos a un subtag IANA (`spa` → `es`): ese alias no existe en el registro IANA (es una convención de CLDR) y se trata como código no registrado.
- S-6. Al resolver un locale con deprecación del estándar solo se expone su `replacement`; seguirlo es decisión del consumidor.
- S-7. El dataset inicial lo define PREP respetando este contrato; no forma parte de la spec.
- S-8. Los nombres localizados de los propios locales (aplicar RF-23 sobre Locale) quedan para una spec posterior si surge la necesidad.
- S-9. Se excluyen los subtags *Scope: special* y el rango de uso privado: no representan un idioma concreto en el que publicar textos.
- S-10. Convención de estado de los catálogos globales: atributo `status` (decisión del responsable, clarify 2026-10-19). No había convención previa en el repositorio; Locale es el primer catálogo y la fija para 002, 003, 004 y posteriores. Cambiarla requiere decisión explícita.
- S-11. Valores comunes `active` | `inactive` (confirmado por el responsable, 2026-10-19). Motivo: es la taxonomía mínima que cubre el ciclo de vida de cualquier catálogo de referencia sin borrar registros; un catálogo que necesite más valores debe justificarlo con una necesidad de dominio y extender la convención común, no crear una propia.
- S-12. La deprecación del estándar no es un valor de `status`: se registra como información del estándar (deprecación y, si existe, `replacement`) e implica `status = inactive` (RF-27). `inactive` no implica deprecación del estándar.
- S-13. La forma preferida IANA la determina el registro IANA de referencia del snapshot; no se aplica una preferencia propia "2 letras antes que 3" (decisión del responsable, clarify 2026-10-19). Motivo: el registro puede fijar un *Preferred-Value* de distinta longitud que el subtag deprecado.
- S-14. Identidad publicada separada de la forma preferida IANA (decisión del responsable, clarify 2026-10-19): las reglas de publicación se aplican solo al publicar un locale nuevo; después, el código publicado es identidad histórica y la evolución del registro solo cambia deprecación del estándar, `replacement` y `status`.
- S-15. El `replacement` siempre coincide con el *Preferred-Value* que declara el registro IANA de referencia del snapshot, también en cadenas, sin excepción propia de GI (confirmado por el responsable, 2026-10-19). Motivo: RFC 5646 §3.1.7 exige que, si YY (*Preferred-Value* de XX) pasa a tener *Preferred-Value* ZZ, el de XX pase también a ZZ. `locale_id` y código publicado no cambian; `replacement` es metadata versionada por snapshot (RF-18) y la relación anterior queda en el snapshot previo, conservado íntegro (RNF-5).
- S-16. `locale_id` se asigna en PREP y viaja en el snapshot; `gi-common-reference` solo lo valida e incorpora (decisión del responsable, clarify 2026-10-19). Motivo: ids idénticos entre entornos, incorporación determinística y `replacement` hacia locales nuevos del mismo snapshot.
- S-17. Todo snapshot incorporado se conserva completo e inmutable para auditoría, sin API pública histórica (decisión del responsable, clarify 2026-10-19).
- S-18. La versión del registro IANA de referencia es monotónica: el `File-Date` de cada snapshot es igual o posterior al del último incorporado; no hay rollback (decisión del responsable, clarify 2026-10-19). Motivo: impedir que desaparezca una deprecación del estándar ya conocida, que un locale obligado a `inactive` vuelva a `active` o que retrocedan *Preferred-Value* y `replacement`, manteniendo una evolución monotónica y determinística.
- S-19. Los snapshots son autocontenidos respecto del registro IANA: PREP obtiene la fuente, fija la versión e incluye el artefacto con provenance y digest; `gi-common-reference` valida y deriva los datos de RF-8 solo desde ese artefacto (decisión del responsable, clarify 2026-10-19).
- S-20. Un snapshot se identifica por `snapshot_version` + digest de contenido; `snapshot_version` la asigna PREP y es estrictamente creciente para snapshots nuevos, sin exigir versiones consecutivas (decisión del responsable, clarify 2026-10-19).
- S-21. El sistema recalcula el digest de contenido y el digest IANA y rechaza el snapshot si alguno no coincide con el declarado; cada digest es determinístico y se calcula sobre una representación que excluye su propio valor. Algoritmo, canonicalización y campos cubiertos se definen en PLAN (confirmado por el responsable, 2026-10-19).
- S-22. Reincorporar un snapshot ya incorporado, aunque no sea el último, es un no-op; la monotonía de `snapshot_version` solo aplica a snapshots nuevos (decisión del responsable, clarify 2026-10-19). Motivo: distinguir un snapshot conocido de una regresión real.
- S-23. RF-23–RF-25 son un contrato para catálogos dependientes: 001 lo establece y cada spec que introduzca una entidad localizada lo adopta y lo verifica. Se conservan sus identificadores por estabilidad (decisión del responsable, clarify 2026-10-19).
- S-24. Un campo `Deprecated` o `Preferred-Value` presente pero vacío es ambiguo (¿deprecado sin fecha?, ¿forma preferida vacía?). Se rechaza en vez de interpretarlo, de modo que haya una única regla: la deprecación del estándar de una entrada es la presencia de `Deprecated` (decisión del responsable, sdd-change 2026-10-20). Motivo: dos lecturas distintas del mismo campo producían resultados distintos en la validación del catálogo y en los alias. El registro real usado como fixture (`File-Date` 2026-09-17) no tiene ningún campo vacío.
- S-25. `TRUNCATE` no dispara los triggers por fila, así que sin triggers `BEFORE TRUNCATE` por sentencia el historial y los locales se podían vaciar eludiendo la inmutabilidad (RNF-5, RNF-8). La migración 0001 se edita en su lugar, sin una 0002, porque nada se ha desplegado ni incorporado todavía; las bases locales ya migradas con la versión anterior deben recrearse (decisión del responsable, sdd-change 2026-10-20).

## Preguntas abiertas

Ninguna.
