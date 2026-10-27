# Spec 002 — Regions / Subregions

- **Estado:** draft (clarify 1 y 2 del 2026-10-19 aplicados; pendiente de aprobación humana formal. El 2026-10-27 el responsable pidió continuar con plan e implementación sin cambiar sus decisiones; la aprobación se confirma en el gate humano final)
- **Tipo:** Feature (catálogo global de Reference)
- **Depende de:** `001-locales` (identidad `locale_id`, convención común de `status`, regla de localización RF-23–RF-25 de 001)
- **Habilita:** `003-countries` (referencias `region_id` / `subregion_id`)

## Contexto y objetivo

`gi-common-reference` es el propietario de los catálogos globales de GI. Countries y otros consumidores necesitan clasificar países por región y subregión geográfica global (p. ej. Americas → Latin America and the Caribbean) y mostrar esos nombres en varios idiomas.

Esta spec define Region y Subregion como catálogos globales, persistentes, versionados y de solo lectura, con identidad estable propia y nombres resueltos por `Locale`. Así Country (003) y los consumidores referencian una clasificación por ID canónico en lugar de duplicar códigos y nombres regionales como texto.

**Por qué ahora:** si Countries se publica con región/subregión embebidas como texto, cada consumidor quedaría acoplado a nombres en un idioma y a códigos sin identidad propia; corregirlo después obligaría a migrar referencias ya almacenadas.

## Usuarios

- **Countries (003)** y futuros catálogos de Reference: referencian `region_id` / `subregion_id` con integridad garantizada.
- **Módulos consumidores** (Core, Tenants, Persons, CRM, ERP, otros COMMON, verticales): listan, resuelven y muestran regiones/subregiones en un locale.
- **Mantenedores del catálogo** (vía `gi-common-reference-prep`): preparan y publican snapshots versionados.

## Historias de usuario

- HU-1. Como consumidor, quiero listar las regiones y sus subregiones con nombres en mi locale para poblar filtros y agrupaciones.
- HU-2. Como consumidor, tengo un código M49 (p. ej. `419`) y quiero obtener la región o subregión canónica que le corresponde.
- HU-3. Como consumidor que almacenó un `region_id` o `subregion_id`, quiero que siga siendo válido y resoluble en todas las versiones futuras del catálogo.
- HU-4. Como autor de 003-countries, quiero garantizar que la subregión de un país pertenece a la región indicada.
- HU-5. Como mantenedor, quiero publicar un snapshot que agregue nombres, corrija metadatos o refleje una reclasificación o recodificación oficial sin romper IDs ya publicados.

## Definiciones

- **Region:** clasificación geográfica global de nivel superior (p. ej. M49 `019` Americas). No es un país, una división administrativa ni un tenant.
- **Subregion:** clasificación geográfica global contenida en exactamente una Region (p. ej. M49 `419` Latin America and the Caribbean dentro de `019`). **No** es una subdivisión administrativa interna de un país (provincia, estado, departamento).
- **Código canónico:** código numérico UN M49 de 3 dígitos, tratado como texto y con ceros a la izquierda (`002`, `019`, `419`). Es un identificador externo y versionable de la fuente de autoridad, usado para resolver; **no** es la identidad. La relación ID ↔ código es normalmente estable, pero puede cambiar por recodificación oficial.
- **Identidad canónica:** `region_id` / `subregion_id`. La determina la continuidad de la entidad según la fuente de autoridad, no la estabilidad de su código ni de su Region padre.
- **Localización (`RegionLocale` / `SubregionLocale`):** nombre de una Region/Subregion en un Locale concreto, conforme a la regla RF-23 de 001.
- **`status`:** estado general del registro según la **convención común de los catálogos globales** de `gi-common-reference`, fijada por 001-locales: atributo `status`, valores `active` | `inactive`, misma semántica. Region y Subregion no definen atributos ni valores propios.
- **Reemplazo:** referencia opcional desde una entidad `inactive` a la entidad del mismo tipo que la sucede según la fuente de autoridad. Es información aparte de `status`, igual que en 001.
- **Cambio de clasificación:** la fuente de autoridad mantiene la misma entidad y el mismo código M49 de una Subregion, pero cambia su Region padre. Misma identidad, mismo código, distinto padre.
- **Recodificación:** la fuente de autoridad mantiene la misma entidad pero le asigna otro código M49. Misma identidad, distinto código.
- **Cambio de identidad:** la fuente de autoridad declara una entidad canónicamente distinta (alta, sustitución, división, fusión, desaparición y creación de otra). Se crea un ID nuevo; la entidad anterior sigue resoluble, pasa a `inactive` cuando corresponda y registra reemplazo solo si hay una sucesión unívoca. Un cambio de código o de padre, por sí solo, no es un cambio de identidad.
- **Código histórico:** código que una entidad tuvo antes de una recodificación. Se conserva en la traza de recodificaciones (RF-39), no como código vigente.
- **Conjunto obligatorio de locales:** lista de `locale_id` del catálogo Locale para los que toda Region y Subregion publicada debe tener nombre. Es política del catálogo, no parte del modelo de las entidades.
- **Snapshot / publicado:** mismo significado que en 001-locales, aplicado a este catálogo.

## Requisitos funcionales

### Identidad y modelo

- RF-1. EL SISTEMA DEBERÁ mantener Region, Subregion y sus localizaciones como catálogos globales, sin `tenant_id` ni variantes por tenant, consumidor o país.
- RF-2. EL SISTEMA DEBERÁ asignar a cada Region un `region_id` y a cada Subregion un `subregion_id` únicos, inmutables, nunca reutilizados e independientes de su código, de sus nombres y de su Region padre; ni una recodificación ni una reclasificación los modifican.
- RF-3. EL SISTEMA DEBERÁ permitir a cada Region y Subregion un código canónico vigente opcional; cuando exista, DEBERÁ cumplir el formato de 3 dígitos y no podrá ser a la vez el código vigente de otra entidad `active` del mismo tipo.
- RF-4. EL SISTEMA DEBERÁ impedir que un mismo código vigente pertenezca a la vez a una Region `active` y a una Subregion `active` (en M49 cada código designa una única área).
- RF-5. EL SISTEMA DEBERÁ exigir que toda Subregion referencie exactamente una Region existente.
- RF-6. CUANDO un snapshot cambie la Region padre de una Subregion publicada manteniendo su código (cambio de clasificación), EL SISTEMA DEBERÁ conservar su `subregion_id` y su código y actualizar solo la relación jerárquica; ese cambio solo puede llegar por snapshot (RF-21), nunca por un consumidor.
- RF-7. EL SISTEMA DEBERÁ registrar por cada Region y Subregion su `status` con la convención común de los catálogos globales (`active` | `inactive`, ver Definiciones) y, solo si es `inactive`, un reemplazo opcional; no existirán `is_active`, `enabled`, `state`, `deprecated` ni otro atributo o valor propio.
- RF-8. EL SISTEMA NO DEBERÁ persistir nombres ni otros textos dependientes del idioma en Region ni en Subregion.

### Localización

- RF-9. EL SISTEMA DEBERÁ almacenar los nombres en `RegionLocale` (`region_id`, `locale_id`, `name`) y `SubregionLocale` (`subregion_id`, `locale_id`, `name`), con a lo sumo una fila por par (entidad, `locale_id`).
- RF-10. EL SISTEMA DEBERÁ impedir, mediante constraints de base de datos, una localización que referencie una Region, Subregion o `locale_id` inexistente.
- RF-11. EL SISTEMA DEBERÁ exigir que `name` no esté vacío ni tenga espacios al inicio o al final.
- RF-12. EL SISTEMA NO DEBERÁ usar códigos de idioma en texto (`es`, `en`) como clave de relación ni en el modelo; la relación con el idioma es siempre `locale_id`.
- RF-13. EL SISTEMA DEBERÁ exigir que cada Region y Subregion publicada tenga localización para cada `locale_id` del conjunto obligatorio de locales (RF-31).

### Contratos públicos de lectura

- RF-14. CUANDO un consumidor liste regiones, EL SISTEMA DEBERÁ devolver todas las publicadas con su `status`, permitir restringir a `status = active` y ordenarlas de forma determinística.
- RF-15. CUANDO un consumidor liste subregiones, EL SISTEMA DEBERÁ devolverlas con su `region_id` y `status`, permitir filtrar por `region_id` y por `status = active`, en orden determinístico.
- RF-16. CUANDO un consumidor pida una Region o Subregion por ID, EL SISTEMA DEBERÁ devolverla con su ID, código, `status`, reemplazo y (en Subregion) `region_id`, cualquiera sea su `status`, o un resultado explícito "no encontrado".
- RF-17. CUANDO un consumidor pida una Region o Subregion por código canónico, EL SISTEMA DEBERÁ comparar contra el código vigente y devolver la entidad `active` que lo posee; si ninguna `active` lo posee, la entidad `inactive` que lo obtuvo en el snapshot más reciente; si ninguna, "no encontrado". SI el código no tiene formato válido, ENTONCES DEBERÁ devolver un error de validación distinguible de "no encontrado".
- RF-18. CUANDO una consulta incluya un `locale_id`, EL SISTEMA DEBERÁ devolver junto a cada entidad su nombre en ese locale; SI no existe localización para ese locale, ENTONCES DEBERÁ devolver la entidad con el nombre ausente, sin fallback a otro locale.
- RF-19. SI el `locale_id` indicado no existe en el catálogo de Locale, ENTONCES EL SISTEMA DEBERÁ devolver un error de validación distinguible de "no encontrado".
- RF-20. EL SISTEMA DEBERÁ exponer los contratos solo como lectura (sin alta, modificación ni baja) e incluir la versión vigente del catálogo Region/Subregion (RF-37).

### Snapshots, versionado y ciclo de vida

- RF-21. EL SISTEMA DEBERÁ modificar el catálogo únicamente mediante la incorporación de snapshots versionados, validados y con provenance, separados del modelo de dominio y de los contratos.
- RF-22. SI un snapshot omite una Region, Subregion o localización publicada, o cambia el código vigente de un ID publicado sin declararlo como recodificación (RF-39), ENTONCES EL SISTEMA DEBERÁ rechazarlo completo.
- RF-23. CUANDO un snapshot agregue una Region o Subregion que la fuente de autoridad considera entidad nueva (cambio de identidad), EL SISTEMA DEBERÁ asignarle un ID nunca usado antes en su catálogo; ni un cambio de clasificación (RF-6) ni una recodificación (RF-39) crean un ID nuevo.
- RF-24. CUANDO un snapshot corrija metadatos no identitarios (`status`, reemplazo, texto de `name`), agregue localizaciones, aplique un cambio de clasificación o una recodificación, EL SISTEMA DEBERÁ aplicarlos conservando los IDs; una recodificación no modifica `status`, reemplazo, localizaciones ni Region padre.
- RF-25. SI un snapshot falla cualquier validación, ENTONCES EL SISTEMA DEBERÁ dejar el catálogo exactamente en el estado anterior (incorporación atómica).
- RF-26. CUANDO se incorpore dos veces el mismo snapshot, EL SISTEMA DEBERÁ producir el mismo estado del catálogo (idempotencia).
- RF-27. SI un reemplazo pertenece a una entidad `active`, apunta a una entidad inexistente, de otro tipo o a sí misma, o forma un ciclo, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot.
- RF-28. SI un snapshot incluye una localización cuyo `locale_id` no existe en el catálogo de Locale vigente, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo.
- RF-34. CUANDO se incorpore un cambio de clasificación, EL SISTEMA DEBERÁ registrar de forma consultable el `subregion_id`, la Region anterior, la Region nueva y la versión del snapshot que lo introdujo.
- RF-36. SI un snapshot deja una Subregion `active` dentro de una Region `inactive`, ENTONCES EL SISTEMA DEBERÁ rechazarlo.
- RF-37. EL SISTEMA DEBERÁ versionar el catálogo Region/Subregion (incluidas sus localizaciones) con un identificador de versión y un ciclo de snapshot propios, independientes de Countries y de cualquier otro catálogo.
- RF-38. EL SISTEMA DEBERÁ registrar en cada snapshot la versión del catálogo Locale contra la que se validaron sus localizaciones.

### Recodificación

- RF-39. CUANDO un snapshot declare una recodificación (ID, código anterior, código nuevo y referencia de provenance de la fuente de autoridad que la justifica), EL SISTEMA DEBERÁ conservar el ID, reemplazar su código vigente y registrar de forma consultable el ID, el código anterior, el código nuevo, la versión del snapshot y la referencia de provenance.
- RF-40. SI una recodificación declarada no tiene referencia de provenance, o su código anterior no coincide con el código vigente del ID, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot.
- RF-41. SI un snapshot asigna a un ID un código que es vigente o histórico de otro ID del catálogo, ENTONCES EL SISTEMA DEBERÁ rechazarlo, salvo que declare esa reasignación con referencia de provenance de la fuente de autoridad y el resultado cumpla RF-3 y RF-4.
- RF-42. EL SISTEMA DEBERÁ validar RF-3 y RF-4 sobre el estado final del snapshot completo, de modo que un intercambio de códigos entre entidades en un mismo snapshot no produzca colisiones intermedias ni estados parciales.

### Locales obligatorios

- RF-31. EL SISTEMA DEBERÁ mantener el conjunto obligatorio de locales del catálogo como lista de `locale_id` versionada en `gi-common-reference`; en v1 contiene los `locale_id` cuyos códigos canónicos en 001 son `en` y `es`. Cambiarlo requiere decisión explícita.
- RF-32. SI un snapshot no contiene localización para cada `locale_id` obligatorio de cada Region y Subregion publicada, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo, aunque PREP ya lo haya validado.
- RF-33. SI un snapshot agrega una localización nueva con un `locale_id` en `status = inactive`, o el conjunto obligatorio contiene un locale `inactive`, ENTONCES EL SISTEMA DEBERÁ rechazarlo; las localizaciones ya publicadas con un locale que luego pasa a `inactive` se conservan y siguen resolviéndose.

### Contrato esperado por 003-countries

- RF-29. EL SISTEMA DEBERÁ permitir que un catálogo de este módulo proteja por constraint de base de datos que el par (`region_id`, `subregion_id`) de un registro corresponda a una Subregion perteneciente a esa Region.
- RF-30. EL SISTEMA DEBERÁ garantizar que ningún `region_id` ni `subregion_id` referenciado por otro catálogo pueda eliminarse (consecuencia de RF-22; las referencias nunca quedan huérfanas).
- RF-35. SI un cambio de clasificación dejaría a un registro de otro catálogo de Reference con un par (`region_id`, `subregion_id`) incoherente, ENTONCES EL SISTEMA DEBERÁ rechazarlo, salvo que se incorpore en la misma operación atómica que el snapshot del catálogo dependiente que corrige esos registros.

Lo que 003 deberá cumplir de su lado (se formaliza en 003 vía `/sdd-change`, no en esta spec):

- Depender de `001-locales`, `002-regions-subregions` y, para CountryCurrency, de `004-currency`.
- Referenciar `region_id` y `subregion_id`; no persistir `region_code`, `region_name`, `subregion_code`, `subregion_name` ni traducciones regionales.
- Declarar en su propio snapshot la versión del catálogo Region/Subregion con la que fue construido y validado (RF-37).

## Requisitos no funcionales

- RNF-1. Determinismo: la misma versión de snapshot y la misma consulta devuelven siempre el mismo resultado.
- RNF-2. Sin dependencias de runtime externas: las consultas no acceden a UN M49, CLDR, red, servicios de traducción ni IA.
- RNF-3. Integridad en la base de datos: unicidad de IDs, códigos y pares (entidad, locale), pertenencia Subregion→Region y referencias a `locale_id` se protegen con constraints, no solo con lógica de aplicación.
- RNF-4. Aislamiento: los consumidores dependen solo de los contratos públicos, nunca de tablas, migraciones ni clases internas.
- RNF-5. Trazabilidad: cada snapshot incorporado conserva versión, provenance, versión de Locale usada (RF-38), reclasificaciones (RF-34) y recodificaciones (RF-39), consultables.
- RNF-6. Dirección de dependencias: Region/Subregion dependen solo de Locale; no dependen de Country, Currency ni de ningún consumidor (sin ciclos).
- RNF-7. Extensibilidad compatible: agregar un nivel M49 adicional (p. ej. región intermedia) será un cambio aditivo que no modifica `region_id`, `subregion_id` ni sus contratos.

## Casos borde

- Código `19` o `0019` → error de validación; `019` es válido (RF-17).
- Código `419` pedido como Region → "no encontrado" (es Subregion); pedido como Subregion → la devuelve (RF-4, RF-17).
- Subregion pedida con un `locale_id` válido no obligatorio y sin traducción → entidad devuelta con nombre ausente, sin fallback (RF-18).
- Locale que pasa a `inactive` en 001 → sus localizaciones existentes siguen válidas y resolubles; no se aceptan localizaciones nuevas con él (RF-33).
- Snapshot sin nombre en un locale obligatorio para alguna Subregion → rechazado completo (RF-32).
- M49 mueve una Subregion a otra Region con el mismo código → mismo `subregion_id`, nuevo padre, reclasificación registrada (RF-6, RF-34); si algún Country quedaría incoherente, se exige incorporación atómica con el snapshot de Countries (RF-35).
- M49 divide una Subregion en dos nuevas → dos IDs nuevos; la original pasa a `inactive` sin reemplazo único (RF-23, RF-27).
- M49 fusiona dos Subregiones en una nueva → un ID nuevo; ambas originales `inactive` con reemplazo hacia la nueva.
- M49 recodifica la misma Subregion (`123` → `456`) → mismo `subregion_id`, código vigente `456`, `status` y nombres sin cambios, recodificación registrada; los Countries que la referencian no se tocan (RF-39, RF-24).
- Snapshot que cambia el código de un ID sin declararlo como recodificación, o lo declara sin provenance → rechazado (RF-22, RF-40).
- Dos Subregiones intercambian códigos en el mismo snapshot, ambas declaradas → aceptado si el estado final cumple RF-3/RF-4 (RF-42).
- Snapshot asigna a una entidad nueva el código histórico de otra sin declarar la reasignación → rechazado (RF-41).
- Consulta por un código histórico (`123` tras recodificar a `456`) → "no encontrado"; el código histórico solo se consulta en la traza (RF-17, S-8).
- M49 retira un área sin sucesora → `inactive` sin reemplazo, resoluble por ID y código.
- Region pasa a `inactive` con Subregiones `active` → rechazado (RF-36).
- Antártida (AQ) no pertenece a ninguna región M49 → es asunto de 003 (región ausente); este catálogo no crea una Region ficticia.
- Taiwán (TW) ausente de M49 → su clasificación la decide 003; este catálogo no cambia.
- Snapshot con dos localizaciones de la misma Subregion para el mismo locale → rechazado completo (RF-9).
- Dos regiones con el mismo nombre en un locale → permitido por el modelo (la identidad es el ID); PREP debería reportarlo como anomalía.
- Catálogo vacío (antes del primer snapshot) → listas vacías o "no encontrado", nunca error interno.

## Fuera de alcance

- Países, monedas, zonas horarias, tenants y preferencias por tenant.
- Provincias, estados, departamentos, municipios y cualquier división administrativa interna de un país (ISO 3166-2).
- Región intermedia M49 (p. ej. `005` South America, `029` Caribbean) y cualquier jerarquía genérica o recursiva: evolución futura aditiva (RNF-7).
- Agrupaciones no geográficas de M49 (LDC, LLDC, SIDS, Developed/Developing) y el nivel World (`001`).
- Fallback entre locales: corresponde a cada consumidor.
- CRUD público y lógica específica de consumidores.
- Diseño interno del pipeline de PREP, incluida la coordinación de publicación con Countries, y contenido concreto del dataset inicial.
- Cambios en la spec de 003-countries.

## Criterios de aceptación

- CA-1. Region, Subregion y sus localizaciones existen como entidades persistentes globales sin `tenant_id` y sin nombres en las entidades principales (RF-1, RF-8).
- CA-2. Cada Region/Subregion tiene un ID único e inmutable; un código vigente, si existe, tiene 3 dígitos y no lo comparten dos entidades `active`, ni del mismo tipo ni entre Region y Subregion (RF-2–RF-4).
- CA-3. Persistir una Subregion sin Region válida, una localización huérfana, una localización con `locale_id` inexistente o duplicada por (entidad, locale) falla en persistencia (RF-5, RF-9, RF-10, RNF-3).
- CA-4. Se pueden listar regiones, listar subregiones (todas y por región), obtener cada una por ID y por código, y resolver nombres por `locale_id`, solo en lectura (RF-14–RF-20).
- CA-5. Las respuestas distinguen "no encontrado" de error de validación, y un locale sin traducción no aplica fallback (RF-17–RF-19).
- CA-6. El catálogo solo cambia por snapshots versionados, atómicos e idempotentes; un snapshot que elimine entidades o localizaciones, cambie un código sin recodificación declarada o reutilice un código sin reasignación declarada es rechazado; solo un cambio de identidad crea un ID nuevo (RF-21–RF-28, RF-41).
- CA-7. Un registro de prueba con (`region_id`, `subregion_id`) incoherente es rechazado por constraint, y una reclasificación que lo dejaría incoherente fuera de una incorporación atómica conjunta es rechazada (RF-29, RF-35).
- CA-8. Region/Subregion no tienen dependencias hacia Country, Currency ni consumidores (RNF-6).
- CA-9. El estado de Region y Subregion se expresa solo con `status` (`active` | `inactive`), idéntico en nombre, valores y semántica a Locale; el reemplazo se expone aparte (RF-7, RF-16, RF-27).
- CA-10. Un snapshot que cambia la Region padre de una Subregion con el mismo código conserva su `subregion_id` y código, y la reclasificación queda consultable con versión del snapshot (RF-6, RF-23, RF-34).
- CA-11. Un snapshot sin nombre en algún locale obligatorio, o que agregue nombres con un locale `inactive`, es rechazado; el conjunto obligatorio se expresa por `locale_id` (RF-13, RF-31–RF-33).
- CA-12. La versión del catálogo Region/Subregion es propia, se expone en los contratos y no depende de la versión de Countries (RF-20, RF-37, RF-38).
- CA-13. Una recodificación declarada con provenance conserva el ID, `status`, nombres y padre, cambia el código vigente y queda consultable con ID, código anterior, código nuevo, versión y provenance; una referencia almacenada por ID sigue resolviendo igual (RF-39, RF-24, RF-2).
- CA-14. Un cambio de código no declarado, una recodificación sin provenance o con código anterior incorrecto, y una reutilización de código no declarada son rechazados sin cambios parciales; un intercambio de códigos declarado en un mismo snapshot se acepta (RF-22, RF-40–RF-42, RF-25).

## Supuestos y decisiones

- S-1. Fuente de autoridad: **UN M49** (División de Estadística de la ONU), que publica códigos y nombres oficiales en árabe, chino, español, francés, inglés y ruso. Evidencia: PREP ya extrae M49 y 003 lo declara autoridad de la clasificación geográfica (D-8 de 003).
- S-2. Niveles v1: Region = región M49 (Africa, Americas, Asia, Europe, Oceania); Subregion = subregión M49; modelo Region 1 → N Subregion (decisión del responsable, clarify 2026-10-19). No hay necesidad concreta de 003 que exija el nivel intermedio: su draft lo deja fuera de v1 (D-10 de 003).
- S-3. Los contratos aceptan `locale_id`; un consumidor con un código de idioma lo resuelve primero mediante el contrato de Locale (RF-8 de 001). Aceptar el código directamente sería un cambio aditivo.
- S-4. El formato concreto de los IDs y su asignación por Reference se deciden en el plan, alineados con el contrato definitivo de 001.
- S-5. Convención de estado: se adopta sin redefinirla la convención común fijada por 001 (S-10, S-11 de 001: `status` = `active` | `inactive`; la deprecación/sustitución no es un valor de `status`). Si 001 cambia la convención antes de integrarse, 002 se ajusta para seguirla.
- S-6. Reclasificación vs. identidad (decisión del responsable, clarify 2026-10-19): el ID sigue a la entidad que la fuente de autoridad considera la misma; el padre es atributo de clasificación mutable solo por snapshot validado contra la fuente.
- S-7. Locales obligatorios v1 = `en` y `es` (decisión del responsable, clarify 2026-10-19), ambos publicados oficialmente por M49 y válidos en el subconjunto v1 de 001. Se expresan como `locale_id` en la política del catálogo, nunca como texto en el modelo.
- S-8. Recodificación (decisión del responsable, clarify 2 2026-10-19; reemplaza la S-8 anterior, que trataba todo código nuevo como cambio de identidad): la identidad sigue la continuidad de la entidad según la fuente de autoridad; un cambio de código, por sí solo, conserva el ID. Coincide con el criterio de D-12 de 003 para países. La búsqueda por código usa solo el código vigente; resolver códigos históricos sería un cambio aditivo.
- S-11. El sistema no consulta M49 en runtime (RNF-2): "validado contra la fuente de autoridad" significa que el snapshot declara cada recodificación y reasignación con una referencia de provenance, que PREP la verificó y que el mantenedor la aprobó. El sistema exige y comprueba esa declaración; no puede verificar por sí mismo la decisión de la ONU.
- S-9. No se aceptan localizaciones nuevas con locales `inactive` porque 001 los define como no aptos para nuevas referencias.
- S-10. Versionado independiente (decisión del responsable, clarify 2026-10-19): Region/Subregion tiene versión y ciclo de snapshot propios; PREP puede coordinar publicaciones conjuntas sin que compartan versión. El diseño del pipeline queda para su iniciativa.

## Conflictos detectados con otras specs

- C-1. **003-countries (draft)** modela región/subregión como atributos embebidos del registro Country (`region_code`/`region_name`, `subregion_code`/`subregion_name`, D-10, RF-6) y deja "entidad propia de regiones" fuera de alcance. Contradice esta spec. Debe corregirse en 003 mediante `/sdd-change` antes de planificarla; esta iniciativa no modifica 003.

## Precondición para el plan

El plan de 002 no puede aprobarse hasta que `001-locales` esté integrado en `develop` y se verifique allí, sin cambios incompatibles con esta spec:

- nombre y semántica de `locale_id`;
- convención común de `status` (nombre del atributo y vocabulario `active` | `inactive`);
- reglas de localización (RF-23–RF-25 de 001);
- tratamiento de locales `inactive` / deprecados por el estándar;
- convención de snapshot y versionado común a los catálogos globales, si 001 la establece.

Estado de esta verificación al 2026-10-19: **NOT_RUN**. `develop` (`ec2156c`) aún no contiene `specs/001-locales`; esta spec se alineó con el draft de 001 en su worktree, sin commitear.

Estado al 2026-10-27: **PASS**. `develop` (`fb5dc2d`) contiene `specs/001-locales` aprobada e implementada (`d739c99`), sin cambios incompatibles: `locale_id` UUID estable; `status` = `active` | `inactive` (S-10, S-11 de 001); RF-23–RF-25 de 001 como contrato para entidades localizadas; un locale `inactive` sigue resoluble y no se recomienda para nuevas referencias; snapshots con `snapshot_version` entera, digest de contenido canónico e incorporación atómica e idempotente (D5, D7, RF-20, RF-21 de 001). El detalle está en `plan.md`.

## Preguntas abiertas

Ninguna.
