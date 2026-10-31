# Spec 003 — Countries

- **Estado:** approved (2026-10-30, por la instrucción del responsable de esta ejecución de completar 003 de punta a punta, tras una revisión de detección independiente cuyos hallazgos HIGH y MEDIUM se aplicaron; las decisiones de S-13 fueron aprobadas por el responsable el 2026-10-31 con una única condición: el reemplazo debe soportar relaciones 0..N, incorporada en RF-52)
- **Tipo:** Feature (catálogo global de Reference)
- **Depende de:** `001-locales` (identidad `locale_id`, convención común de `status`, contrato de localización RF-23–RF-25 de 001, esquema de snapshots), `002-regions-subregions` (identidad `region_id` / `subregion_id`, contrato RF-29, RF-30 y RF-35 de 002)
- **Habilita:** `004-currency` (contrato e identidad `country_id` para CountryCurrency; los `country_id` reales existen cuando se incorpora el dataset de PREP, S-7)
- **Enmiendas:** `sdd-change` 2026-10-30 — reconcilia el draft original con 001 y 002 aprobadas (ver "Registro de reconciliación"). Los identificadores RF-1 a RF-30 conservan su número; los requisitos nuevos continúan desde RF-31 (RF-52 es el último). `sdd-change` 2026-10-31 — reemplazo 0..N, condición de la aprobación de S-13: se agrega RF-52 y se reformulan RF-15, RF-22, RF-40 y RF-45 sin renumerar.

## Contexto y objetivo

**Situación actual**: Persons y Tenants persisten `country_code` como texto validado únicamente por formato. Es legado a migrar. El estado objetivo es que los consumidores persistan exclusivamente `country_id`; los códigos ISO quedan como atributos normativos y claves públicas de resolución de Countries.

Countries es el catálogo **global y canónico** de países/áreas de GI, propiedad exclusiva de `gi-common-reference`. Da a cada país una identidad GI estable (`country_id`), sus códigos normativos (ISO 3166-1), su clasificación geográfica por referencia a las entidades canónicas de Regions/Subregions (002), su código de llamada (ITU-T E.164) y su bandera SVG, y expone sus nombres en varios idiomas mediante `CountryLocale` sobre la identidad `locale_id` de Locale (001). Se consume en modo lectura mediante contratos públicos y se actualiza solo con snapshots aprobados, versionados y trazables; nunca por edición manual cotidiana.

**Por qué ahora:** Locale (001) y Region/Subregion (002) ya están aprobados e incorporados en `develop`. Countries es el primer catálogo que combina ambos y el que las referencias de Persons, Tenants y 004-currency necesitan estables antes de seguir acumulando texto en `country_code`.

## Usuarios

- **Módulos consumidores** (Core, Tenants, Persons, CRM, ERP, otros COMMON, verticales): resuelven y validan referencias de país, almacenan `country_id` y piden nombres en un locale.
- **Catálogos de Reference posteriores** (004-currency): referencian `country_id` con integridad garantizada.
- **Mantenedor del catálogo** (rol humano de `gi-common-reference`): revisa y aprueba snapshots y aplica versiones del catálogo.
- **PREP** (`gi-common-reference-prep`): produce los snapshots candidatos con su evidencia de procedencia.

## Historias de usuario

- HU-1. Como consumidor, quiero resolver un país por `country_id` para mostrar o validar una referencia que ya almacené.
- HU-2. Como consumidor, quiero resolver un país por su código ISO alpha-2, alpha-3 o numérico para traducir datos externos o heredados a `country_id`.
- HU-3. Como consumidor, quiero listar los países vigentes con su nombre en mi locale para poblar selectores.
- HU-4. Como consumidor, quiero saber si un `country_id` existe y está vigente antes de aceptarlo en mi dominio.
- HU-5. Como consumidor, quiero obtener la bandera de un país.
- HU-6. Como mantenedor, quiero aplicar una nueva versión del catálogo de forma revisable, repetible y sin romper referencias existentes, distinguiendo recodificación, retiro, división/fusión y alta.
- HU-7. Como auditor, quiero saber qué versión del catálogo está cargada, de qué fuentes proviene cada dato y qué recodificaciones sufrió cada país.
- HU-8. Como autor de 004-currency, quiero que `country_id` sea estable y resoluble en todas las versiones futuras para asociarle monedas.

## Definiciones

- **Country (registro)**: un país o área geográfica que tiene, o tuvo, un código _oficialmente asignado_ en ISO 3166-1. Incluye Estados soberanos, territorios dependientes y áreas especiales (p. ej. AQ, BV, HK, PR). Un registro **no** es una declaración de soberanía ni de reconocimiento político.
- **Identidad canónica:** `country_id`. La determina la continuidad de la entidad según la fuente de autoridad (ISO 3166-1), no la estabilidad de sus códigos, nombres ni clasificación.
- **Códigos normativos:** `alpha2`, `alpha3` y `numeric_code` de ISO 3166-1. Son claves públicas de resolución y atributos del país; **no** son su identidad. Forman una tripleta que identifica una misma entrada ISO.
- **`status`:** estado general del registro según la **convención común de los catálogos globales** de `gi-common-reference`, fijada por 001: atributo `status`, valores `active` | `inactive`, misma semántica. Country no define atributos ni valores propios.
  - `active`: corresponde a una entrada vigente de ISO 3166-1; publicado, resoluble y apto para nuevas referencias.
  - `inactive`: la entrada fue retirada de ISO 3166-1 (pasó a ISO 3166-3) o fue retirada por decisión GI aprobada; publicado y resoluble para no romper referencias, no recomendado para nuevas.
- **Reemplazo:** relación 0..N desde un Country `inactive` hacia los Country que lo suceden (`replacement_country_ids`): un conjunto sin orden semántico ni duplicados, vacío cuando la fuente no declara sucesión. Es información aparte de `status`, igual que en 001 y 002; Countries la amplía de 0..1 a 0..N porque una división tiene varios sucesores (AN → CW, SX, BQ). No cambia el modelo de 001 ni de 002.
- **Recodificación:** ISO mantiene la misma entidad y cambia uno o más de sus códigos normativos (precedentes: TP/TMP/626 → TL/TLS/626, ROM → ROU, ZR → CD). Misma identidad, otros códigos.
- **Cambio de identidad:** ISO declara una entidad distinta (alta, división, fusión, sustitución, desaparición y creación de otra; precedentes: AN → CW/SX/BQ, CS → RS/ME). Se crea un `country_id` nuevo; la entidad anterior sigue resoluble, pasa a `inactive` cuando corresponda y registra como reemplazos a todos los sucesores que declara la fuente de autoridad: uno en una fusión o sustitución, varios en una división, ninguno si no declara sucesión.
- **Código histórico:** código que un país tuvo antes de una recodificación. Se conserva en la traza (RF-46), no como código vigente.
- **CountryLocale:** nombre de un Country en un Locale concreto: `name` y, cuando corresponda, `official_name`. Aplica el contrato RF-23–RF-25 de 001.
- **Conjunto obligatorio de locales:** lista de `locale_id` del catálogo Locale para los que todo Country publicado debe tener `name`. Es política del catálogo Countries, no parte del modelo de la entidad.
- **Snapshot:** documento autocontenido respecto de los datos del catálogo, completo, versionado y con provenance, que PREP prepara y el mantenedor aprueba; es la única vía de cambio del catálogo. Mismo significado que en 001 y 002. Su `snapshot_version` es la **versión del catálogo** Countries. Los assets de bandera no viajan dentro del documento: son archivos del repositorio referenciados por suma de verificación (RF-49).
- **Bandera:** asset SVG versionado en el repositorio, referenciado desde el snapshot por un manifiesto con ruta relativa y suma de verificación; nunca almacenado como binario en el registro Country.
- **Excepción de bandera:** declaración explícita en el snapshot, con motivo, de que un Country `active` no tiene asset de bandera.

## Decisiones

### Aprobadas previamente (input)

- D-1. Countries es GLOBAL, sin `tenant_id`, propiedad única de `gi-common-reference`.
- D-2. `country_id` es UUID, identidad canónica GI, estable, controlada por Reference, nunca reutilizada; es la única identidad que los consumidores deben almacenar. `alpha2`, `alpha3` y `numeric_code` son códigos normativos y claves de resolución, no reemplazan a `country_id`.
- D-3. Banderas en SVG, nunca almacenadas como binario en el registro Country (RF-19).
- D-4. Persistencia en PostgreSQL/Supabase con schema propio.
- D-5. PREP es fuente de evidencia y preparación, no autoridad de modelo.
- D-6. Sin CRUD administrativo para consumidores.

### Tomadas por esta spec

- D-7. **Política de inclusión**: entran todos los códigos _oficialmente asignados_ de ISO 3166-1 vigentes. Quedan fuera: códigos de uso de usuario (p. ej. `XK`), códigos excepcional o transitoriamente reservados (p. ej. `EU`, `UK`) y áreas M49 sin código ISO (p. ej. Sark, M49 680). Agregar cualquiera requiere decisión explícita posterior. Su cumplimiento es un control de la revisión humana y de PREP: el sistema solo impone el formato de los códigos (RF-5) y no mantiene una lista de exclusión.
- D-8. **Autoridad de inclusión y de códigos es ISO 3166-1**, no UN M49. M49 es autoridad solo de la clasificación geográfica (que vive en 002). Evidencia reportada por el draft original y no reverificada en esta sesión (S-7): la extracción M49 de PREP (248 registros) no contenía `TW`, asignado en ISO 3166-1.
- D-9. **Dataset inicial**: solo entradas vigentes de ISO 3166-1, todas `active`. No se precargan entidades históricas de ISO 3166-3 (SU, YU, AN…). El formato de snapshot admite `inactive` desde el primer día.
- D-10. **(Reemplaza la D-10 original.) Región y subregión se referencian por identidad canónica**: un Country puede tener `region_id` y `subregion_id` definidos por 002. Countries no persiste `region_code`, `region_name`, `subregion_code` ni `subregion_name`, no recrea Region/Subregion y no introduce región intermedia (fuera de alcance de 002, confirmado por HITL 2026-10-28). Cardinalidad: un Country tiene a lo sumo una Region y una Subregion; la Subregion implica su Region.
- D-11. **`country_id` lo controla Reference.** Se asigna una única vez, cuando un país se incorpora por primera vez; viaja en el snapshot y queda registrado en el repositorio al aprobarse. El sistema nunca lo genera ni lo modifica al incorporar ni en runtime, y no lo recalcula a partir de atributos mutables; por tanto es idéntico en todos los entornos (mismo criterio que S-16 de 001 y D1 del plan de 002). PREP o la herramienta de preparación pueden proponer UUID candidatos, que no son autoritativos hasta que el mantenedor aprueba el snapshot en `gi-common-reference`; ese procedimiento pertenece al pipeline.
- D-12. **Recodificación vs. cambio de identidad**: si ISO cambia los códigos de una misma entidad, se conserva el `country_id` y se registra una recodificación. Si ISO retira una entidad y crea otras (división, fusión), la retirada pasa a `inactive` y las nuevas reciben `country_id` nuevos. La clasificación de cada caso es parte de la revisión humana del snapshot.
- D-13. Los consumidores **no** crean FKs ni dependen de tablas/vistas internas de Reference; integran por contrato (regla de AGENTS.md). Permitir una FK inter-schema requiere decisión arquitectónica explícita.
- D-14. **(Enmienda.)** Claves públicas de búsqueda: `country_id`, `alpha2`, `alpha3` y `numeric_code`. La búsqueda por código numérico entra en v1 (decisión de dominio de esta reconciliación: los tres son claves de resolución). Buscar por códigos históricos o por `calling_code` queda fuera.
- D-15. **Localización por `CountryLocale`** (001): `name` y `official_name` no son atributos de Country. Los nombres son datos persistidos y aprobados; ni el runtime ni el snapshot dependen de IA o de traducción automática. IA puede asistir la preparación o revisión de datos, nunca la resolución productiva.
- D-16. **Convención de estado común**: `status` = `active` | `inactive` (001). No existe `is_active`. El reemplazo (`replacement_country_ids`, 0..N) se expone aparte.
- D-17. **Versionado independiente** (mismo criterio que S-10 de 002): Countries tiene `snapshot_version` y ciclo de snapshot propios, con las mismas reglas de digest, clasificación y atomicidad que 001 y 002. Cada snapshot registra contra qué versión de Locale se validó y declara la versión de Region/Subregion con la que se construyó.
- D-18. **Currency queda fuera.** Countries no depende de Currency ni de CountryCurrency; esa asociación pertenece a 004 (D-16 de 004) y depende de `country_id`.
- D-19. **Mensajes de error localizados no pertenecen a Countries.** El catálogo expone resultados y códigos de error estables y legibles por máquina; traducirlos es responsabilidad de la capa consumidora.

## Modelo funcional

Atributos conceptuales. Los nombres de campo de los contratos (salvo `country_id`, `locale_id`, `region_id`, `subregion_id` y `status`), la representación física, los tipos y la implementación de las restricciones se deciden en el Plan.

### Country

| Atributo | Significado | Oblig. | Único | Estabilidad | Autoridad | Ante actualización |
| --- | --- | --- | --- | --- | --- | --- |
| `country_id` | Identidad GI | Sí | Sí, global y nunca reutilizado | Inmutable | GI (Reference) | Nunca cambia |
| `alpha2` | ISO 3166-1 alpha-2, 2 letras A–Z mayúsculas | Sí | Entre `active` | Casi estable | ISO 3166-1 | Solo por recodificación declarada (RF-41) |
| `alpha3` | ISO 3166-1 alpha-3, 3 letras A–Z mayúsculas | Sí | Entre `active` | Casi estable | ISO 3166-1 | Solo por recodificación declarada |
| `numeric_code` | ISO 3166-1 numérico, 3 dígitos con ceros a la izquierda (texto, no número) | Sí | Entre `active` | Casi estable | ISO 3166-1 (contrastado con M49 por PREP, RF-29) | Solo por recodificación declarada |
| `region_id` | Region canónica de 002 | No (p. ej. AQ, TW) | No | Descriptivo | UN M49 vía 002 | Se actualiza por snapshot |
| `subregion_id` | Subregion canónica de 002; implica `region_id` y pertenencia | No | No | Descriptivo | UN M49 vía 002 | Se actualiza por snapshot |
| `calling_code` | Código de país E.164 asignado por ITU-T a la entidad (el principal si la provenance declara más de uno), 1–3 dígitos sin `+` ni cero inicial (p. ej. `54`; NANP = `1`) | No (p. ej. BV) | No (US/CA comparten `1`) | Descriptivo | ITU-T E.164 | Se actualiza por snapshot |
| `status` | `active` \| `inactive` (convención común) | Sí | — | Cambia solo por snapshot aprobado | ISO 3166-1 + decisión GI | RF-22 |
| `replacement_country_ids` | conjunto 0..N de `country_id` sucesores, sin duplicados ni orden semántico; no vacío solo si `inactive` | No (vacío por defecto) | — | Descriptivo | ISO 3166-3 + decisión GI | RF-40, RF-52 |

Trazabilidad técnica por país: snapshot que lo introdujo, snapshot en que obtuvo sus códigos vigentes y último snapshot que cambió su contenido (RF-51). No hay `created_at`/`updated_at` dependientes del reloj (RNF-1).

### CountryLocale

| Atributo | Significado | Oblig. |
| --- | --- | --- |
| `country_id` | Country localizado | Sí |
| `locale_id` | Locale de 001 | Sí |
| `name` | Nombre corto de uso común para mostrar | Sí |
| `official_name` | Nombre formal completo en ese locale | No (ISO no lo define para todas las áreas ni locales) |

A lo sumo una fila por par (`country_id`, `locale_id`).

### Bandera (manifiesto)

Por país: referencia al asset SVG (ruta relativa, suma de verificación, tipo de medio) y la fuente declarada en la procedencia. Fuera del registro Country.

## Requisitos funcionales

### Identidad e integridad

- RF-1. EL SISTEMA DEBERÁ mantener un único catálogo Countries global, con sus localizaciones y referencias de bandera, sin `tenant_id` ni partición por tenant, consumidor o módulo.
- RF-2. EL SISTEMA DEBERÁ identificar cada registro con un `country_id` UUID inmutable, independiente de sus códigos, nombres y clasificación, que nunca se reasigna a otro país ni se reutiliza.
- RF-3. EL SISTEMA DEBERÁ garantizar que entre registros `active` no existan dos con el mismo `alpha2`, `alpha3` o `numeric_code`, validándolo sobre el estado final del snapshot completo (RF-44).
- RF-4. EL SISTEMA DEBERÁ tratar `alpha2`, `alpha3` y `numeric_code` de un país como una tripleta indivisible de la misma entrada ISO 3166-1: los tres son obligatorios, viajan juntos y solo cambian mediante una recodificación declarada que expresa la tripleta completa anterior y la nueva (RF-41); en una recodificación cambian uno o más componentes. EL SISTEMA NO DEBERÁ aceptar un cambio no declarado de ningún componente.
- RF-5. EL SISTEMA DEBERÁ rechazar códigos que no cumplan el formato del modelo (`alpha2` 2 letras A–Z mayúsculas, `alpha3` 3 letras A–Z mayúsculas, `numeric_code` 3 dígitos como texto con ceros a la izquierda, `calling_code` 1–3 dígitos sin cero inicial) y NO DEBERÁ normalizarlos ni interpretarlos al incorporar: `NA` es un código válido y nunca un nulo; `004` nunca se reduce a `4`.
- RF-6. **(Reformulado: ya no hay región ni subregión como texto.)** EL SISTEMA DEBERÁ garantizar, mediante constraints de base de datos, que `region_id` y `subregion_id` sean opcionales, que `subregion_id` solo exista junto a `region_id`, que ambos referencien entidades existentes de 002 y que, si hay `subregion_id`, el par (`region_id`, `subregion_id`) corresponda a una Subregion perteneciente a esa Region (contrato RF-29 y RF-30 de 002). EL SISTEMA NO DEBERÁ persistir código ni nombre de región o subregión.
- RF-7. EL SISTEMA NO DEBERÁ eliminar físicamente nunca un Country, una localización, una referencia de bandera ni una traza; un retiro se expresa como `status = inactive`.

### Contratos de consulta

- RF-8. CUANDO un consumidor resuelva por `country_id` existente, EL SISTEMA DEBERÁ devolver el Country con su `status`, sea `active` o `inactive`.
- RF-9. CUANDO un consumidor resuelva por `alpha2` o `alpha3`, EL SISTEMA DEBERÁ comparar sin distinguir mayúsculas y devolver el registro `active` que lo posee; CUANDO resuelva por `numeric_code`, DEBERÁ comparar el texto exacto de 3 dígitos.
- RF-10. SI ningún registro `active` posee el código pero uno o más `inactive` sí, ENTONCES EL SISTEMA DEBERÁ devolver el `inactive` que lo obtuvo en el snapshot más reciente y, si hay empate, el de menor `country_id`, indicando su `status`. La resolución usa solo el código vigente; los códigos históricos no se resuelven.
- RF-11. SI el identificador o código no existe, ENTONCES EL SISTEMA DEBERÁ devolver un resultado explícito de "no encontrado", distinguible de un error técnico.
- RF-12. SI un código de consulta tiene formato inválido (longitud o caracteres no válidos, espacios), ENTONCES EL SISTEMA DEBERÁ devolver un error de validación distinguible de "no encontrado". Alineado con 001 y 002, un `country_id` mal formado en la consulta por id es "no encontrado", no error de validación.
- RF-13. CUANDO un consumidor liste Countries, EL SISTEMA DEBERÁ devolver por defecto solo los `active`, en orden determinista por `alpha2` en orden binario de bytes (independiente del locale de la base) y desempate por `country_id`, con opción explícita de incluir `inactive` y de filtrar por `region_id` y `subregion_id`.
- RF-14. CUANDO un consumidor valide un `country_id`, EL SISTEMA DEBERÁ permitirle distinguir tres estados: `active`, `inactive` o no encontrado, sin imponerle si acepta inactivos.
- RF-15. EL SISTEMA DEBERÁ devolver en toda resolución como mínimo: `country_id`, `alpha2`, `alpha3`, `numeric_code`, `status`, `replacement_country_ids`, `region_id`, `subregion_id`, `calling_code` y, cuando se pide un `locale_id`, los textos localizados del RF-38 (los opcionales como ausentes cuando no existen).
- RF-16. EL SISTEMA DEBERÁ permitir consultar la versión del catálogo Countries actualmente aplicada (`snapshot_version`) y devolverla en cada contrato; con el catálogo vacío es ausente, nunca un error interno.
- RF-17. EL SISTEMA DEBERÁ versionar cada contrato público; agregar campos o consultas es compatible, y quitar o cambiar el significado de un campo requiere nueva versión mayor con análisis de migración.
- RF-18. EL SISTEMA NO DEBERÁ exponer a los consumidores operaciones de alta, modificación ni baja de Countries ni de sus localizaciones.

### Banderas

- RF-19. **(Reformulado.)** EL SISTEMA DEBERÁ exigir que cada snapshot declare, para cada Country `active`, una referencia a su asset SVG de bandera (ruta relativa, suma de verificación y fuente) o una excepción de bandera explícita con motivo; un `active` sin ninguna de las dos se rechaza. Los `inactive` pueden conservar su bandera.
- RF-49. EL SISTEMA DEBERÁ verificar, al incorporar, que cada asset referenciado existe en el repositorio, que su suma de verificación coincide con la declarada, que es un SVG bien formado, que el tipo de medio declarado en el manifiesto es `image/svg+xml`, que no excede el tamaño máximo fijado en el Plan y que no contiene DTD ni entidades, scripts, manejadores de eventos, `foreignObject` ni elementos embebidos, ni referencias a recursos que no sean fragmentos locales `#id`; si no, DEBERÁ rechazar el snapshot completo.
- RF-50. CUANDO un consumidor pida la bandera de un `country_id`, EL SISTEMA DEBERÁ devolver el asset SVG, verificando al servirlo que su suma coincide con la registrada, o un resultado explícito de que ese país no tiene bandera (excepción declarada), distinguible de "país no encontrado". EL SISTEMA NO DEBERÁ consultar fuentes externas para obtenerla.

### Localización (contrato RF-23–RF-25 de 001)

- RF-31. EL SISTEMA DEBERÁ almacenar los nombres en `CountryLocale` (`country_id`, `locale_id`, `name`, `official_name` opcional) con a lo sumo una fila por par (país, `locale_id`).
- RF-32. EL SISTEMA DEBERÁ exigir que `name` no esté vacío ni tenga espacios al inicio o al final, y que `official_name`, si existe, cumpla lo mismo.
- RF-33. EL SISTEMA DEBERÁ impedir, mediante constraints de base de datos, una localización que referencie un Country o un `locale_id` inexistente, y NO DEBERÁ usar códigos de idioma en texto (`es`, `en`) como clave de relación ni en el modelo: la relación con el idioma es siempre `locale_id`.
- RF-34. EL SISTEMA NO DEBERÁ persistir `name`, `official_name` ni otro texto dependiente del idioma en la entidad Country.
- RF-35. EL SISTEMA DEBERÁ exigir que cada Country publicado tenga `name` para cada `locale_id` del conjunto obligatorio de locales de Countries, versionado en `gi-common-reference`; en v1 contiene los `locale_id` cuyos códigos canónicos en 001 son `en` y `es`. Cambiarlo requiere decisión explícita. SI un snapshot no lo cumple, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo, aunque PREP ya lo haya validado.
- RF-36. SI un snapshot agrega una localización nueva con un `locale_id` en `status = inactive`, o el conjunto obligatorio contiene un locale `inactive`, ENTONCES EL SISTEMA DEBERÁ rechazarlo; las localizaciones ya publicadas con un locale que luego pasa a `inactive` se conservan y siguen resolviéndose («nueva» = par (país, locale) no publicado; cambiar el texto de un par ya publicado no lo es). SI un snapshot incluye una localización cuyo `locale_id` no existe en el catálogo de Locale vigente, ENTONCES DEBERÁ rechazarlo completo.
- RF-37. EL SISTEMA DEBERÁ servir en runtime solo textos persistidos y versionados; ninguna consulta invocará traducción automática ni modelos de IA.
- RF-38. CUANDO una consulta incluya un `locale_id`, EL SISTEMA DEBERÁ devolver junto a cada país su `name` y su `official_name` en ese locale; SI no existe localización o el `official_name` no existe, ENTONCES DEBERÁ devolverlos ausentes, sin fallback a otro locale. SI el `locale_id` no está bien formado o no existe en el catálogo de Locale, ENTONCES DEBERÁ devolver un error de validación distinguible de "no encontrado".

### Ciclo de vida, estado y carga

- RF-20. CUANDO se incorpore un snapshot, EL SISTEMA DEBERÁ crear los registros nuevos, actualizar los modificados y conservar el `country_id` de los ya conocidos.
- RF-21. SI un snapshot omite algún Country, localización o referencia de bandera ya publicados, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo; un retiro se expresa como `inactive`, nunca como ausencia. Pasar una bandera a excepción declarada, o al revés, no es una omisión; quitar la entrada de bandera de un país que la tenía sí lo es. SI un snapshot repite un `country_id` o usa en un país nuevo un `country_id` ya usado antes, ENTONCES DEBERÁ rechazarlo (RF-2, RF-45).
- RF-22. EL SISTEMA DEBERÁ cambiar `status` y reemplazos únicamente mediante un snapshot aprobado, y NO DEBERÁ aceptar un cambio de `status` de otra forma. Un país `inactive` puede volver a `active` por snapshot (sin reemplazos) si el estado final cumple RF-3 y RF-48; un cambio de nombre con los mismos códigos no requiere recodificación.
- RF-23. CUANDO se incorpore dos veces el mismo snapshot, EL SISTEMA DEBERÁ dejar el catálogo sin ningún cambio (idempotencia); el mismo snapshot, con los mismos assets de bandera del repositorio, produce el mismo estado lógico en cualquier entorno.
- RF-24. SI un snapshot falla cualquier validación, ENTONCES EL SISTEMA DEBERÁ dejar el catálogo exactamente en el estado anterior (incorporación atómica, todo o nada).
- RF-25. **(Reformulado: reemplaza «versión anterior salvo reversión explícita».)** CUANDO llegue un snapshot que cumple RF-27 (schema y digest recalculado), EL SISTEMA DEBERÁ clasificarlo contra el historial de snapshots incorporados antes de cualquier otra validación, con las reglas A/B/C/D de RF-32 de 001: A) misma `snapshot_version` y mismo digest → no-op idempotente; B) misma `snapshot_version` y digest distinto → rechazo; C) `snapshot_version` no incorporada y anterior a la última → rechazo por regresión; D) posterior → continúa. Una reversión de contenido se hace con un snapshot nuevo de versión posterior.
- RF-26. EL SISTEMA DEBERÁ operar incorporación y consultas sin acceder a fuentes externas (ISO, UN, CLDR, ITU, red, servicios de traducción ni IA).
- RF-39. EL SISTEMA DEBERÁ registrar el estado de cada Country solo como `status` (`active` | `inactive`); no existirán `is_active`, `enabled`, `state`, `deprecated` ni otro atributo o valor propio.
- RF-40. **(Reformulado por RF-52.)** SI un Country `active` tiene reemplazos, o algún reemplazo apunta a un Country que no está publicado ni incluido en el mismo snapshot, a sí mismo, está repetido dentro del conjunto o forma un ciclo en el grafo de reemplazos, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot.
- RF-41. CUANDO un snapshot declare una recodificación (país, tripleta anterior, tripleta nueva y referencia de provenance de la fuente de autoridad), EL SISTEMA DEBERÁ conservar el `country_id`, reemplazar sus códigos vigentes y registrar de forma consultable el país, la tripleta anterior, la tripleta nueva, la versión del snapshot y la provenance (RF-46). Una recodificación solo cambia códigos: no modifica `status`, reemplazo, clasificación ni localizaciones por sí misma.
- RF-42. SI una recodificación declarada no tiene provenance, es de un país no publicado, su tripleta anterior no coincide con la vigente o no cambia ningún código, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot. SI un snapshot cambia algún código de un país publicado sin declararlo como recodificación, ENTONCES DEBERÁ rechazarlo completo.
- RF-43. SI un snapshot asigna a un país un código que es vigente o histórico de **otro** `country_id`, ENTONCES EL SISTEMA DEBERÁ rechazarlo, salvo que declare esa reasignación con referencia de provenance de la fuente de autoridad y el resultado cumpla RF-3. Una reasignación declarada que no corresponde se rechaza.
- RF-44. EL SISTEMA DEBERÁ validar RF-3 y RF-43 sobre el estado final del snapshot completo, de modo que un intercambio de códigos entre países en un mismo snapshot declarado no produzca colisiones intermedias ni estados parciales.
- RF-45. CUANDO la fuente de autoridad trate una entidad como nueva (alta, división, fusión hacia una entidad nueva, sustitución), EL SISTEMA DEBERÁ exigir un `country_id` nunca usado antes en el catálogo; una absorción por un país ya existente (p. ej. DD → DE) no crea ninguno: el absorbido pasa a `inactive` con el existente como único elemento de `replacement_country_ids`; una división (AN → CW/SX/BQ) crea un `country_id` nuevo por cada sucesor y el retirado pasa a `inactive` con todos ellos como reemplazos; ni una recodificación (RF-41) ni un cambio de `status` crean un `country_id` nuevo. CUANDO un snapshot retire un país, DEBERÁ conservar su `country_id` y sus códigos, que siguen resolviendo por RF-8 y RF-10.
- RF-46. EL SISTEMA DEBERÁ registrar de forma consultable cada recodificación (país, tripleta anterior, tripleta nueva, versión del snapshot, provenance), de forma inmutable, en tablas legibles por el rol de lectura y documentadas en la operación; no forman parte de la API pública (como D10 del plan de 002).
- RF-47. EL SISTEMA DEBERÁ registrar en cada snapshot incorporado la versión del catálogo Locale contra la que validó sus localizaciones y exigir que declare la versión del catálogo Region/Subregion con la que fue construido (RF-37 de 002); SI esa versión no está incorporada o es posterior a la vigente, ENTONCES DEBERÁ rechazarlo. La declaración es trazabilidad (contra qué se revisó); la seguridad la da RF-48, que valida contra el catálogo vigente al incorporar. EL SISTEMA DEBERÁ conservar consultables la versión declarada, la vigente al incorporar y la versión de la política de locales usada.
- RF-48. SI un snapshot deja un Country `active` con un `region_id` o `subregion_id` que no existe o está `inactive` en el catálogo de 002 vigente, o con un par incoherente, ENTONCES EL SISTEMA DEBERÁ rechazarlo. Los Country `inactive` pueden conservar una clasificación `inactive`. Es intencional que, si 002 deja `inactive` un destino ya referenciado por un `active`, todo snapshot posterior de Countries sea rechazado hasta corregir esa clasificación: cada snapshot es el estado completo y debe ser coherente.

- RF-51. EL SISTEMA DEBERÁ registrar por cada Country el snapshot que lo introdujo, el snapshot en que obtuvo sus códigos vigentes y el último snapshot que cambió su contenido, de forma determinística (sin reloj).
- RF-52. EL SISTEMA DEBERÁ soportar para cada Country `inactive` un conjunto de reemplazos de cardinalidad 0..N (`replacement_country_ids`): cero cuando la fuente no declara sucesión, uno en una fusión o sustitución, varios en una división. El snapshot lo declara como arreglo cuyo orden carece de significado; el sistema lo persiste y lo devuelve en orden ascendente de `country_id`, y reenviar los mismos sucesores en otro orden no cuenta como un cambio del país. EL SISTEMA DEBERÁ rechazar un identificador repetido dentro del conjunto, un elemento `null` y, por RF-40, un conjunto no vacío en un Country `active`. Un Country `inactive` que vuelve a `active` limpia su conjunto (RF-22). Un sucesor puede estar a su vez `inactive` (cadenas de sucesión) siempre que el grafo no tenga ciclos. La persistencia protege estas invariantes (RNF-5).

### Dataset y procedencia (frontera Reference ↔ PREP)

- RF-27. EL SISTEMA DEBERÁ aceptar solo snapshots con `snapshot_version` entera positiva (con orden total y saltos permitidos), contenido completo del catálogo (países, localizaciones, referencias de bandera, recodificaciones y reasignaciones de este snapshot), `country_id` para cada registro, provenance y digest de contenido, y recalcular el digest; SI falta algo o el digest recalculado no coincide, ENTONCES DEBERÁ rechazarlo completo.
- RF-28. EL SISTEMA DEBERÁ exigir procedencia que declare, por fuente usada: nombre, edición o versión, fecha de obtención, referencia de ubicación, suma de verificación del artefacto de origen y licencia; incluyendo la fuente de cada grupo de datos (identidad y códigos, nombres, código de llamada, banderas).
- RF-29. EL SISTEMA DEBERÁ exigir que cada atributo declare su fuente de autoridad según el modelo (identidad y códigos: ISO 3166-1; nombres: CLDR u otra fuente declarada; código de llamada: ITU-T E.164; clasificación: UN M49 vía 002), y que la provenance declare los conflictos entre fuentes (p. ej. numérico ISO ≠ M49) como resueltos: SI declara un conflicto sin resolver, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot en lugar de resolverlo en silencio.
- RF-30. CUANDO se proponga un snapshot, EL SISTEMA DEBERÁ poder producir, sin modificar el catálogo, un diff legible contra la versión aplicada (altas, cambios de atributos, de códigos, de clasificación, de nombres, de estado y de bandera) para revisión humana antes de su aprobación.

Reparto de responsabilidades:

| PREP | Reference |
| --- | --- |
| Adquirir fuentes, normalizar, cruzar y validar | Definir modelo, política de inclusión e invariantes |
| Producir snapshot candidato + provenance + reporte de validación | Controlar `country_id` (D-11) y clasificar casos D-12 en la revisión |
| Proponer diff contra la versión previa | Revisar, aprobar, versionar en el repo y aplicar |
| No decide inclusión ni el modelo | Expone contratos y versión del catálogo |

## Requisitos no funcionales

- RNF-1. Determinismo y reproducibilidad: el mismo snapshot produce el mismo catálogo en cualquier entorno, y la misma versión y consulta devuelven siempre el mismo resultado; el estado lógico no depende del reloj.
- RNF-2. Trazabilidad: todo snapshot incorporado se conserva completo e inmutable (versión, digest, contenido, provenance, versión de Locale y de Region/Subregion usadas, política de locales usada) y sus recodificaciones quedan consultables; la historia de aprobación es la del repositorio.
- RNF-3. Las consultas solo requieren acceso de lectura; la escritura queda restringida al proceso de carga controlado.
- RNF-4. No se aplica un modelo RLS por tenant: todos los consumidores autorizados leen el mismo catálogo.
- RNF-5. Las invariantes RF-2 a RF-7, RF-31 a RF-34, RF-39, RF-40 y RF-52 (dominio de `status`; reemplazos solo en `inactive`, sin duplicados, sin el propio país y todos existentes), la exclusividad bandera/excepción (RF-19) y la inmutabilidad frente a `DELETE` y `TRUNCATE` de países, localizaciones, banderas, historial de snapshots y trazas están protegidas por la persistencia (constraints y triggers), no solo por código de aplicación.
- RNF-6. Aislamiento: los consumidores dependen solo de los contratos públicos, nunca de tablas, migraciones ni clases internas.
- RNF-7. Dirección de dependencias: Countries depende de Locale y de Region/Subregion solo por datos e identidades; Locale y Region/Subregion no dependen de Countries; Countries no depende de Currency ni de ningún consumidor (sin ciclos).
- RNF-8. Sin red en runtime ni en pruebas.
- RNF-9. Los errores se expresan con códigos estables legibles por máquina, sin mensajes localizados (D-19).
- RNF-10. Extensibilidad compatible: agregar región intermedia, búsqueda por códigos históricos u otros atributos es un cambio aditivo que no altera `country_id` ni los contratos existentes.

## Casos límite

- CL-1. Antártida (AQ): sin `region_id` ni `subregion_id` → ausentes, registro válido.
- CL-2. Taiwán (TW): asignado en ISO 3166-1, ausente en M49 → se incluye con región y subregión ausentes (S-5); no se toma ninguna clasificación de otra autoridad.
- CL-3. Códigos de llamada compartidos (US/CA/PR → `1`; RU/KZ → `7`): válidos, `calling_code` no es único.
- CL-4. Área sin código E.164 (p. ej. BV): `calling_code` ausente.
- CL-5. `alpha2` `NA` (Namibia): nunca se interpreta como nulo ni "no aplica", ni en el snapshot, ni en la base, ni en la consulta (`na`, `NA`).
- CL-6. Códigos numéricos con ceros a la izquierda (`004`, `020`): se preservan como texto; `4` es error de validación.
- CL-7. Reasignación futura por ISO de un código usado antes por un país `inactive` o histórico: exige reasignación declarada con provenance (RF-43); resuelta, la búsqueda por código devuelve el `active` (RF-9) y el `inactive` sigue resoluble por `country_id`.
- CL-8. Entrada en minúsculas (`ar`) en la consulta: se tolera; `" ar "`, `a-r` o `AR1`: error de validación. Un snapshot con `ar` en minúsculas se rechaza sin normalizarse (RF-5).
- CL-9. Consumidor con un `country_id` de un país hoy `inactive`: la resolución sigue funcionando (RF-8) y la validación devuelve `inactive` (RF-14).
- CL-10. Recodificación TP/TMP/626 → TL/TLS/626 (cambian `alpha2` y `alpha3`; el numérico se declara igual): mismo `country_id`, `status` y nombres sin cambios, traza registrada; una consulta por `TP` es "no encontrado" (RF-10, RF-41).
- CL-11. Cambio de `alpha2` sin declarar recodificación, o recodificación sin provenance o con tripleta anterior incorrecta → snapshot rechazado (RF-42).
- CL-12. División (AN → CW/SX/BQ) → tres `country_id` nuevos; AN `inactive` con `replacement_country_ids` = {CW, SX, BQ}; fusión o sustitución con un solo sucesor → un único elemento; sin sucesión declarada → conjunto vacío (RF-40, RF-45, RF-52).
- CL-13. Dos países intercambian `alpha2` en un mismo snapshot, ambos declarados → aceptado si el estado final cumple RF-3 (RF-44); sin declarar → rechazado.
- CL-14. País `active` sin bandera ni excepción declarada → rechazado; con excepción y motivo → aceptado; SVG con `<script>` o `href` externo → rechazado (RF-19, RF-49).
- CL-15. Snapshot sin `name` en un locale obligatorio → rechazado completo; locale no obligatorio sin traducción → permitido; `official_name` ausente → permitido (RF-35, RF-31).
- CL-16. Consulta con un `locale_id` válido sin traducción → país devuelto con nombres ausentes, sin fallback; `locale_id` inexistente → error de validación (RF-38).
- CL-17. Subregion de 002 que cambia de Region con el mismo código y deja incoherente a un Country: 002 rechaza su snapshot salvo incorporación atómica conjunta (RF-35 de 002); Countries aporta la FK compuesta que lo hace posible (RF-6) y un snapshot de Countries que corrige el par se incorpora normalmente.
- CL-18. Country `active` apuntando a una Subregion `inactive` de 002 → rechazado (RF-48).
- CL-19. Catálogo vacío (antes del primer snapshot) → listas vacías o "no encontrado", versión ausente, nunca error interno.
- CL-20. `snapshot_version` repetida con otro digest, anterior a la última o digest declarado que no coincide → rechazado (RF-25, RF-27).
- CL-21. `XK`, `EU`, `UK` o Sark en un snapshot → fuera de la política D-7: control de la revisión humana y de PREP, no del sistema; incluirlos exige una decisión explícita previa.
- CL-22. Reemplazos con un identificador repetido (`[CW, CW]`) o con un `null` → snapshot rechazado; los mismos sucesores en otro orden (`[SX, BQ, CW]` y `[BQ, CW, SX]`) → el mismo contenido: no genera cambio del país ni diff (RF-52).
- CL-23. Ciclo de sucesión (A → B → A, o A → B → C → A) → rechazado; cadena A → B → C con B y C `inactive` → aceptada; un sucesor `active` o `inactive` es válido mientras exista (RF-40, RF-52).

## Fuera de alcance

- Subdivisiones (ISO 3166-2: provincias, estados, departamentos, municipios), ciudades, localidades, códigos postales.
- **Currency y CountryCurrency** (004): Countries no incorpora monedas ni atributos de moneda (D-18).
- Región intermedia M49 y cualquier jerarquía regional propia: pertenece a 002 (RNF-10).
- Crear o modificar Region/Subregion: pertenece a 002.
- Idiomas, zonas horarias, datos fiscales, i18n de mensajes de error (D-19).
- Historial de alias o códigos anteriores resolubles por consulta (ISO 3166-3) y precarga de entidades históricas (D-9). La traza de recodificación sí se conserva (RF-46).
- Telefonía avanzada: NANP, prefijos internos, planes compartidos, más de un código de llamada por país.
- Geopolítica o reconocimiento político más allá de ISO 3166-1.
- Semántica de la sucesión más allá del conjunto de sucesores: proporciones, fechas, orden o tipo de sucesión (división, fusión, sustitución). Agregarlos es un cambio aditivo posterior.
- CRUD administrativo y configuración por tenant (p. ej. país predeterminado del tenant, que pertenece a Tenants).
- Migración de `country_code` a `country_id` en Persons, Tenants u otros: la decide y ejecuta cada consumidor en su repo.
- Contenido concreto del dataset inicial (los ~249 países, sus nombres CLDR, códigos E.164 y los ~249 assets de bandera con su licencia), que produce PREP y se incorpora en un cambio posterior; esta spec define el contrato y el mecanismo.
- Diseño interno de PREP, pipeline genérico de publicación y la coordinación de publicaciones conjuntas con Region/Subregion (S-8).
- Cambios en cualquier otro repositorio.

## Criterios de aceptación

- CA-1. Country, CountryLocale y las referencias de bandera existen como entidades persistentes globales sin `tenant_id`, y Country no contiene `name`, `official_name`, códigos ni nombres de región/subregión (RF-1, RF-6, RF-34).
- CA-2. Cada Country tiene un `country_id` UUID único e inmutable; dos `active` no comparten `alpha2`, `alpha3` ni `numeric_code`; un duplicado `active`, un código mal formado o un par región/subregión incoherente falla en persistencia (RF-2, RF-3, RF-5, RF-6, RNF-5).
- CA-3. Resolver por `country_id`, `alpha2` (`ar`, `AR`), `alpha3` y `numeric_code` devuelve el mismo registro con todos los campos de RF-15, y `na`/`NA` resuelve Namibia (RF-8, RF-9, RF-15, CL-5).
- CA-4. Los códigos numéricos conservan sus ceros (`004`) en snapshot, persistencia y respuesta (RF-5, CL-6).
- CA-5. Un código inexistente devuelve "no encontrado"; un código mal formado devuelve error de validación (un `country_id` mal formado es "no encontrado", RF-12); ambos son distinguibles; un código `inactive` devuelve el país indicando su `status`; un código histórico es "no encontrado" (RF-10–RF-12).
- CA-6. La consulta de un `country_id` activo, inactivo e inexistente permite distinguir `active`, `inactive` y no encontrado (RF-14).
- CA-7. El listado devuelve por defecto solo `active`, en orden por `alpha2`, con opción de incluir `inactive` y filtrar por región/subregión (RF-13).
- CA-8. Con `locale_id`, la respuesta incluye `name` y `official_name` persistidos; sin traducción quedan ausentes sin fallback; un `locale_id` inexistente es error de validación; ningún camino invoca traducción ni IA (RF-37, RF-38).
- CA-9. Una localización huérfana, con `locale_id` inexistente, duplicada por (país, locale) o con `name` vacío o con espacios en los bordes falla en persistencia; un snapshot sin `name` en algún locale obligatorio, o que agrega nombres con un locale `inactive`, es rechazado (RF-31–RF-36).
- CA-10. El estado se expresa solo con `status` (`active` | `inactive`), idéntico en nombre, valores y semántica a Locale y Region/Subregion; los reemplazos (0..N) se exponen aparte y solo existen en `inactive` (RF-39, RF-40, RF-52).
- CA-11. El catálogo solo cambia por snapshots versionados, atómicos e idempotentes: reincorporar es no-op; un snapshot que omite un país, falla una validación, repite una versión con otro digest o es anterior a la última se rechaza sin cambios parciales (RF-20–RF-25, RF-27).
- CA-12. Una recodificación declarada con provenance conserva el `country_id`, `status` y nombres, cambia los códigos vigentes y queda consultable; un cambio de código no declarado, una recodificación sin provenance o con tripleta anterior incorrecta, y una reutilización de código no declarada se rechazan sin cambios parciales; un intercambio declarado se acepta (RF-41–RF-44, RF-46).
- CA-13. Una división o fusión crea `country_id` nuevos, deja el anterior `inactive` y registra como reemplazos a todos los sucesores declarados, ninguno si no declara sucesión (RF-40, RF-45, RF-52).
- CA-14. Cada Country `active` del snapshot tiene un SVG verificable (existente, con suma de verificación coincidente, bien formado y sin contenido activo) o una excepción declarada; la bandera se obtiene por `country_id` o se informa su ausencia declarada (RF-19, RF-49, RF-50).
- CA-15. El snapshot incorporado registra la versión de Locale usada y la de Region/Subregion declarada; un snapshot con una versión de Region/Subregion no incorporada, o con una clasificación `inactive`/inexistente/incoherente en un `active`, se rechaza (RF-47, RF-48).
- CA-16. La procedencia declara fuentes con nombre, edición, fecha, ubicación, suma de verificación y licencia, y un conflicto sin resolver bloquea el snapshot; el diff contra la versión aplicada se obtiene sin modificar el catálogo (RF-28–RF-30).
- CA-17. Incorporación y consultas funcionan sin conectividad a ISO, UN, ITU, CLDR ni IA, y la versión consultable coincide con la del snapshot aprobado (RF-16, RF-26, RNF-8).
- CA-18. No existe operación pública de escritura de Countries para consumidores (RF-18, RNF-3).
- CA-19. Countries no tiene dependencias de código ni FKs hacia Currency ni consumidores, y Locale y Region/Subregion no dependen de Countries (RNF-7, D-18).
- CA-20. Los errores usan códigos estables sin mensajes localizados (RNF-9, D-19).
- CA-21. Una división incorpora un Country `inactive` con tres sucesores, que se persisten y se devuelven en `replacement_country_ids` en orden ascendente por `country_id`; una fusión devuelve uno; un retiro sin sucesión devuelve un conjunto vacío; un `active` nunca tiene reemplazos; reenviar los sucesores en otro orden es un no-op; un duplicado, un `null`, un sucesor inexistente o un ciclo se rechazan sin cambios parciales (RF-40, RF-52, CL-22, CL-23).

## Supuestos y decisiones de la reconciliación

- S-1. La lista ISO 3166-1 (códigos y nombres) puede obtenerse de una publicación oficial verificable con licencia compatible; PREP la provee en el snapshot.
- S-2. Las banderas provendrán de una fuente con licencia que permita su redistribución, declarada en la provenance (RF-28).
- S-3. El canal técnico de los contratos, la forma física de tablas e índices, el empaquetado de assets y la carga se deciden en el Plan.
- S-4. **Conjunto obligatorio de locales v1 = `en` y `es`** (mismo criterio que S-7 de 002, resuelve Q-1 del draft). Motivo: el producto opera en `es-AR`, CLDR publica ambos y ISO publica `en`. El `name` es el nombre corto CLDR de cada locale; `official_name` es opcional por locale (ISO publica nombres formales en inglés y francés, no en español). Se expresa por `locale_id`, nunca como texto en el modelo.
- S-5. **TW sin clasificación** (resuelve Q-2 del draft). Para áreas ISO sin entrada M49 (hoy solo `TW`), `region_id` y `subregion_id` quedan ausentes, para no mezclar autoridades (D-8). Asignarla después es un cambio de snapshot, sin impacto de esquema.
- S-6. **Esquema de versión** (resuelve Q-3 del draft). `snapshot_version` es un entero positivo monótono con orden total, como en 001 y 002 (D5, D7 del plan de 001); el tipo de cambio es visible en el diff (RF-30), no en el número. Se elimina la «reversión explícita» del draft original: una reversión es un snapshot posterior.
- S-7. El dataset concreto lo produce PREP; PREP no es accesible en este entorno de desarrollo (`gi-common-reference-prep` no existe en la ruta de proyectos) y el draft original ya señalaba que carecía de fuentes ISO 3166-1, ITU y banderas. Esta feature se verifica con fixtures sintéticos y un snapshot de ejemplo sellado, claramente marcados como no productivos.
- S-8. **Coordinación con 002 (RF-35).** Si una reclasificación futura de 002 deja incoherente el par de algún Country, 002 la rechaza salvo incorporación atómica conjunta con el snapshot de Countries que lo corrige. Esta spec garantiza la FK compuesta que lo hace detectable y que un snapshot de Countries pueda corregir el par. **Limitación aceptada de esta feature (a confirmar por el responsable, S-13):** 003 no entrega una incorporación componible en una transacción con 002; hasta que una feature posterior la aporte, una reclasificación de 002 que afecte a un Country queda bloqueada por RF-35 de 002. Agregarla es aditivo y no cambia ningún contrato de 003.
- S-9. **Replacement 0..N.** Se adopta el patrón de 001 y 002 (aparte de `status`, solo en `inactive`) pero con cardinalidad 0..N en lugar de 0..1, porque ISO retira entidades dividiéndolas en varias (AN → CW/SX/BQ) y un único sucesor no podría expresarlo. Fue la condición con la que el responsable aprobó S-13 (2026-10-31). El contrato `v1` de Countries aún no se había publicado ni consumido (rama de feature sin merge), así que el campo nace como `replacement_country_ids`, sin migración de consumidores. Con el dataset inicial (todo `active`) no se usa; existe para no tener que migrar el modelo cuando ISO retire una entidad.
- S-10. **Búsqueda por `numeric_code` en v1** (D-14): la unicidad entre `active` ya está garantizada por RF-3, por lo que la consulta es aditiva y de bajo costo; evita que consumidores con datos M49 o heredados numéricos sigan acoplados a texto.
- S-11. Autoridad de los códigos. El sistema no consulta ISO en runtime (RF-26): «contrastado con ISO 3166-1» significa que el snapshot declara cada recodificación y reasignación con una referencia de provenance, que PREP la verificó y que el mantenedor la aprobó, como en S-11 de 002. El sistema exige y comprueba esa declaración y la consistencia estructural; no puede verificar por sí mismo la decisión de ISO.
- S-12. Las banderas son assets versionados en el repositorio y verificados por suma de verificación, de modo que resolverlas no requiere red ni fuentes externas (RF-26) y su evolución queda trazada en el historial del repositorio (RNF-2).

- S-13. **Decisiones de dominio tomadas en esta reconciliación, aprobadas por el responsable el 2026-10-31, con la condición de que el reemplazo soporte 0..N (incorporada en S-9 y RF-52):** D-14/S-10 (búsqueda por `numeric_code` en v1), S-4 (locales obligatorios `en` y `es`), S-5 (TW sin clasificación; 002 delegó esta decisión en 003), S-6 (versión monótona, sin reversión), S-8 (sin incorporación componible con 002) y S-9 (`replacement_country_ids`, 0..N). Todas son reversibles por snapshot o por un cambio aditivo.

## Registro de reconciliación con 001 y 002

| Punto del draft original | Contradicción | Resolución |
| --- | --- | --- |
| `name` / `official_name` dentro de Country | 001 RF-23 exige `<Entidad>Locale`; 001 RF-6 y 002 RF-8 prohíben textos en la entidad | D-15, RF-31–RF-38, modelo CountryLocale |
| Q-1 (idioma de `name`) | Dependía de un único idioma | S-4: dos locales obligatorios por `locale_id`; la pregunta desaparece |
| `region_code` / `region_name` / `subregion_*` embebidos, D-10 y RF-6 | 002 define `region_id` / `subregion_id` canónicos (C-1 de 002) | D-10 reemplazada, RF-6 reformulado, RF-48 |
| «Región intermedia fuera de v1» | Confirmado por 002 | Fuera de alcance, RNF-10 |
| `is_active` | 001 S-10, S-11 fijan `status` | D-16, RF-39 |
| Q-2 (clasificación de TW) | Dependía de la autoridad | S-5, CL-2 |
| Q-3 (versionado semántico o monótono) | 001/002 ya usan `snapshot_version` entera con A/B/C/D | S-6, RF-25, RF-27 |
| «Reversión explícita» (RF-25 original) | 001 RF-32 caso C no admite regresión | RF-25 |
| `created_at` / `updated_at` | No deterministas entre entornos (RNF-1) | Trazabilidad por versión de snapshot |
| Lookup solo por `alpha2`/`alpha3` (D-14) | Los tres códigos son claves de resolución | D-14, RF-9, S-10 |
| Dataset «aprobado» sin versión de Locale / Region | RF-37 y RF-38 de 002 piden registrar y declarar versiones | RF-47 |
| Recodificación solo como «actualizar códigos» (D-12, RF-20) | 002 exige recodificación declarada con provenance | RF-41–RF-44, RF-46 |
| Banderas «por alpha2» | `alpha2` puede recodificarse | RF-19, RF-49, RF-50: manifiesto con ruta y suma de verificación |
| Currency | Pertenece a 004 | D-18, fuera de alcance |
| 002 anticipaba que 003 dependería de 004 para CountryCurrency | 004 (spec en `feature/004-currency`, D-16) define CountryCurrency y depende de Country | Dependencia invertida: Countries no depende de Currency (D-18, RNF-7) |
| `replacement` singular (0..1) como en 001 y 002 | La aprobación de S-13 exige 0..N: una división tiene varios sucesores | RF-52, S-9, CL-12, CA-13, CA-21 (solo Countries; 001 y 002 no cambian) |

## Evidencia revisada (solo lectura)

- 001 y 002 en `develop` (`ad0762b`), incorporadas al worktree: contratos de `locale_id`, `status`, RF-23–RF-25, snapshot, digest, clasificación A/B/C/D, políticas de locales obligatorios, FK compuesta (D8 de 002), triggers de inmutabilidad y privilegios.
- Código existente: módulos `locales` y `regions` (hexagonales), `architecture.json`, migraciones 0001 y 0002, contratos OpenAPI y de snapshot, fixtures y pruebas.
- Persons y Tenants (evidencia del draft original, no reverificada en esta sesión): `country_code` alpha-2 por regex, sin FK; Core sin referencias a países.
- PREP: no accesible en esta sesión; se conserva la evidencia del draft original sobre `scripts/extract_un_m49.py` y `work/un-m49-countries.json` (248 filas; falta `TW`; `AQ` sin región) como dato histórico, no verificado ahora.

## Preguntas abiertas

Ninguna.
