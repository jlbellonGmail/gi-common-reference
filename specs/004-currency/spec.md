# 004-currency — Catálogo global de monedas

- **Estado:** draft (clarify 2026-10-19)
- **Tipo:** Feature (spec del dominio Reference)
- **Depende de:** `001-locales` (identidad `locale_id`, convención común de `status`, regla de localización RF-23–RF-25 de 001), `003-countries` (identidad `country_id`, para la asociación CountryCurrency)
- **Habilita:** cualquier módulo que necesite referenciar una moneda (ERP, CRM, Tenants, verticales)

## Contexto y objetivo

Ningún módulo de GI dispone hoy de una referencia canónica de monedas; cada consumidor que la necesite terminaría guardando strings libres (`"ARS"`, `"$"`, `"peso"`) sin integridad ni trazabilidad.

Currency es el catálogo **global y canónico** de monedas de GI, propiedad exclusiva de `gi-common-reference`, basado en ISO 4217. Da a cada moneda una identidad GI estable (`currency_id`) y sus atributos normativos (códigos, unidades menores, vigencia), consumidos en modo lectura mediante contratos públicos. La relación con países es many-to-many mediante la asociación conceptual CountryCurrency, sin que Country duplique datos de Currency ni Currency dependa de Country. El catálogo solo cambia mediante snapshots aprobados, versionados y trazables.

Currency representa el catálogo de monedas, no el mercado cambiario.

## Usuarios

- **Módulos consumidores** (ERP, CRM, Tenants, Persons, otros COMMON, verticales): resuelven y validan monedas; almacenan `currency_id`.
- **Mantenedor del catálogo** (rol humano de `gi-common-reference`): revisa, aprueba e incorpora versiones del catálogo.
- **PREP** (`gi-common-reference-prep`): produce snapshots candidatos con procedencia.

## Historias de usuario

- HU-1. Como consumidor, quiero resolver una moneda por `currency_id` para mostrar o validar una referencia que ya almacené, aunque la moneda ya no esté vigente.
- HU-2. Como consumidor, quiero resolver una moneda por su código alfabético ISO 4217 para traducir datos externos (`USD`) a `currency_id`.
- HU-3. Como consumidor, quiero listar las monedas vigentes para poblar selectores.
- HU-4. Como consumidor, quiero conocer las unidades menores de una moneda para representar importes correctamente.
- HU-5. Como consumidor, quiero obtener las monedas de un país y los países que usan una moneda.
- HU-6. Como mantenedor, quiero incorporar una nueva versión del catálogo (p. ej. un retiro o una redenominación) sin romper referencias existentes.

## Definiciones

- **Currency:** unidad monetaria o de cuenta con código alfabético _asignado_ en ISO 4217, dentro de las categorías incluidas por D-7.
- **`status`:** estado del registro según la convención común de los catálogos globales fijada por 001 (S-10, S-11 de 001): `active` | `inactive`. Currency no define atributos ni valores propios.
  - `active`: figura en la lista vigente de ISO 4217 (List One); resoluble y apta para nuevas referencias.
  - `inactive`: estuvo publicada y fue retirada de ISO 4217 (List Three) o por decisión GI aprobada; resoluble para no romper referencias, no recomendada para nuevas.
- **Resultado de validación:** respuesta de una consulta sobre una referencia: `active`, `inactive` o `not_found`. `not_found` es un resultado de consulta, **nunca** un valor de `status`.
- **Unidades menores:** cantidad de dígitos decimales estándar que ISO 4217 declara para la moneda (0, 2, 3, 4…). ISO declara "no aplicable" (N.A.) para algunas unidades (p. ej. XAU, XDR); "no aplicable" es distinto de `0`.
- **Reemplazo:** referencia opcional desde una Currency `inactive` a la Currency que la sucede, cuando la fuente normativa permite establecerlo de forma confiable. Es información aparte de `status`, igual que en 001 y 002.
- **Localización de Currency** (conceptualmente `CurrencyLocale`, regla RF-23 de 001): texto traducible de una Currency (su nombre) en un Locale concreto.
- **CountryCurrency:** asociación conceptual entre un Country y una Currency que ISO 4217 declara para esa entidad. No es atributo de ninguno de los dos.
- **Snapshot / publicado:** mismo significado que en 001 y 002, aplicado a este catálogo (snapshot = dataset aprobado y versionado).
- **Conjunto obligatorio de locales:** locales para los que toda entidad localizada de Reference debe tener texto. Es política transversal de Locale, no de Currency (DEP-1).

## Decisiones

### Heredadas (AGENTS.md, 001, 002, 003)

- D-1. Currency es GLOBAL, sin `tenant_id` ni `organization_id`, propiedad única de `gi-common-reference`.
- D-2. Sin CRUD para consumidores; el catálogo solo cambia mediante snapshots aprobados, con las mismas propiedades de incorporación que 001 (RF-14 a RF-22) y 003 (RF-20 a RF-30).
- D-3. Los consumidores integran por contrato, no por FK inter-repositorio ni por estructuras internas (AGENTS.md; D-13 de 003).
- D-4. Los textos traducibles de Currency se representan como localizaciones asociadas a Locale (RF-23 a RF-25 de 001); Currency no tiene nombres como atributo canónico.

### Tomadas por esta spec

- D-5. **Identidad asignada por Reference.** `currency_id` se asigna una única vez al incorporar la moneda, queda registrado en el snapshot aprobado y es idéntico en todos los entornos (mismo criterio que D-11 de 003). Su formato físico se decide en el Plan, alineado con 001–003 (X-4).
- D-6. **Un código alfabético nuevo es una moneda nueva.** En ISO 4217 un código nuevo implica una unidad monetaria distinta (VEF→VES, MRO→MRU, HRK→EUR); se crea una Currency nueva y la anterior pasa a `inactive` con reemplazo cuando corresponda. Los códigos de una Currency publicada no cambian.
- D-7. **Categorías incluidas:** todas las de ISO 4217 List One vigente — monedas nacionales, supranacionales (EUR, XOF, XAF, XCD), códigos de fondos (BOV, CHE, CHW, USN, CLF, COU, MXV, UYI), unidades especiales del FMI y otros organismos (XDR, XSU, XUA), unidades del mercado de bonos (XBA–XBD) y metales preciosos (XAU, XAG, XPT, XPD). **Excluidas deliberadamente:** `XTS` (reservado para pruebas) y `XXX` (ausencia de moneda), que no son unidades monetarias. Incluirlas después requiere decisión explícita y es aditivo.
- D-8. **Snapshot inicial:** solo List One vigente, todo `active`. No se exige precargar List Three; las monedas históricas podrán incorporarse después de forma aditiva (RF-43). (decisión del responsable, clarify 2026-10-19)
- D-9. **CountryCurrency se deriva de las entidades de ISO 4217 List One** que corresponden a un Country. Entidades ISO sin Country (p. ej. "EUROPEAN UNION", "INTERNATIONAL MONETARY FUND (IMF)", "SISTEMA UNITARIO DE COMPENSACION REGIONAL DE PAGOS SUCRE") no generan asociación. Los códigos de fondos se asocian igual que los demás, porque ISO los declara así.
- D-10. **Sin "moneda principal" en v1.** ISO no la define; la moneda predeterminada de un tenant pertenece a Tenants. Un atributo propio de la asociación podrá agregarse después de forma aditiva.
- D-11. **Símbolos y formato monetario fuera de v1** (`$`, `US$`, `€`, separadores, máscaras, presentación por locale). No forman parte de la identidad normativa; incorporarlos después como datos localizados es aditivo.
- D-12. **Claves públicas de resolución:** `currency_id` y código alfabético. El código numérico se expone como atributo; buscar por él queda diferido (aditivo), igual que D-14 de 003.
- D-13. **Versionado independiente:** el catálogo Currency (incluidas sus localizaciones y CountryCurrency) tiene versión y ciclo de snapshot propios, validados contra las versiones aplicadas de Locale y Countries (mismo criterio que S-10 de 002).
- D-14. **Convención de estado común** (decisión del responsable, clarify 2026-10-19): Currency y CountryCurrency usan `status` = `active` | `inactive` según 001; no existen `is_active`, `enabled`, `state`, `vigente` ni variantes.
- D-15. **Unicidad de códigos.** El código alfabético queda ligado a una única Currency en todo el catálogo, incluidas las inactivas (mismo principio que RF-16 de 001 y S-8 de 002). El código numérico es único solo entre activas, porque ISO lo ha reasignado (S-5).
- D-16. **Propiedad de CountryCurrency:** pertenece a 004-currency. Depende de Country y de Currency; Country no depende de Currency (X-6).

## Modelo funcional

Atributos conceptuales. Los nombres de campo de los contratos (salvo `currency_id`, `country_id` y `status`), la representación física, los tipos y la implementación de las restricciones se deciden en el Plan.

### Currency

| Atributo | Significado | Obligatorio | Unicidad | Estabilidad | Autoridad |
|---|---|---|---|---|---|
| `currency_id` | Identidad GI | Sí | Global, nunca reutilizada | Inmutable | GI (Reference) |
| Código alfabético | ISO 4217, tres letras latinas mayúsculas | Sí | En todo el catálogo (D-15) | Inmutable (D-6) | ISO 4217 |
| Código numérico | ISO 4217, tres dígitos en su representación normativa (ceros a la izquierda preservados) | Sí | Entre activas (D-15) | Inmutable (D-6) | ISO 4217 |
| Unidades menores | Dígitos decimales estándar, o "no aplicable" | Sí (valor o "no aplicable") | — | Cambia solo por snapshot | ISO 4217 |
| Indicador de fondos | ISO lo declara código de fondos | Sí | — | Cambia solo por snapshot | ISO 4217 |
| `status` | `active` / `inactive` | Sí | — | Cambia solo por snapshot | ISO 4217 + decisión GI |
| Reemplazo | Currency sucesora | No (solo si `inactive`) | — | Cambia solo por snapshot | ISO 4217 List Three + revisión |

### Localización de Currency

Nombre de la moneda por Locale (p. ej. `en` "Argentine Peso", `es` "peso argentino"); a lo sumo uno por par (Currency, Locale).

### CountryCurrency

Asociación entre un `country_id` y un `currency_id`, con `status` propio; a lo sumo una por par. Sin otros atributos en v1 (D-10).

## Requisitos funcionales

### Identidad e integridad

- RF-1. EL SISTEMA DEBERÁ mantener Currency, sus localizaciones y CountryCurrency como catálogo global, sin `tenant_id`, `organization_id` ni partición por tenant, organización o módulo.
- RF-2. EL SISTEMA DEBERÁ dar a cada Currency una identidad GI (`currency_id`) estable, global e inmutable, que no se reasigna ni se reutiliza y no depende de sus códigos, nombres ni `status`.
- RF-3. EL SISTEMA DEBERÁ impedir que dos Currency compartan código alfabético, y que dos Currency `active` compartan código numérico.
- RF-4. EL SISTEMA DEBERÁ rechazar un código alfabético que no sean tres letras latinas mayúsculas, un código numérico que no sean tres dígitos en su representación normativa y unidades menores que no sean un entero no negativo ni "no aplicable".
- RF-5. SI un snapshot cambia un código de una Currency publicada, o asigna un código alfabético publicado a otro `currency_id`, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo (D-6, D-15).
- RF-6. EL SISTEMA DEBERÁ admitir un reemplazo solo en una Currency `inactive`, que apunte a otra Currency existente, distinta de sí misma y sin formar ciclos.
- RF-7. EL SISTEMA NO DEBERÁ eliminar nunca una Currency, una localización ni una asociación CountryCurrency publicadas.
- RF-8. EL SISTEMA NO DEBERÁ incluir en este catálogo cotizaciones, tipos de cambio, conversiones, precios, saldos ni configuración por cliente.
- RF-9. EL SISTEMA DEBERÁ registrar el estado de cada Currency y de cada CountryCurrency como `status` = `active` | `inactive` (D-14), sin otro atributo ni valor con la misma semántica.
- RF-10. EL SISTEMA DEBERÁ cambiar `status` solo mediante un snapshot aprobado, en cualquier dirección, con el cambio visible en el diff de revisión; reactivar una Currency queda sujeto a RF-3.
- RF-11. CUANDO ISO 4217 asigne un código alfabético nuevo, aunque sustituya a otro, EL SISTEMA DEBERÁ incorporarlo como Currency nueva con `currency_id` nuevo (D-6).

### Localización

- RF-12. EL SISTEMA DEBERÁ representar el nombre de cada Currency como localización asociada a un Locale existente, a lo sumo una por par (Currency, Locale), con integridad referencial garantizada (RF-23, RF-24 de 001).
- RF-13. EL SISTEMA DEBERÁ exigir que cada Currency publicada tenga nombre en cada locale del conjunto obligatorio que defina la política transversal de Locale (DEP-1); 004 no define ese conjunto.
- RF-14. SI un snapshot agrega una localización con un locale inexistente o `inactive`, ENTONCES EL SISTEMA DEBERÁ rechazarlo; las localizaciones ya publicadas cuyo locale pase después a `inactive` se conservan y siguen resolviéndose (RF-33 de 002).
- RF-15. CUANDO una consulta indique un locale, EL SISTEMA DEBERÁ devolver el nombre en ese locale o, si no existe, la Currency con el nombre ausente, sin fallback a otro locale; SI el locale no existe o está mal formado, ENTONCES DEBERÁ devolver un error de validación (RF-18, RF-19 de 002).
- RF-16. EL SISTEMA DEBERÁ exigir que un nombre no esté vacío ni tenga espacios al inicio o al final.

### CountryCurrency

- RF-17. EL SISTEMA DEBERÁ representar la relación país–moneda solo mediante CountryCurrency, entre un `country_id` y un `currency_id` existentes, con integridad referencial garantizada y a lo sumo una asociación por par.
- RF-18. EL SISTEMA DEBERÁ permitir que un Country tenga cero, una o varias Currency, y que una Currency tenga cero, uno o varios Country.
- RF-19. EL SISTEMA DEBERÁ garantizar que ninguna CountryCurrency `active` referencie un Country `inactive` ni una Currency `inactive`. Cómo se preserva cuando Countries y Currency se versionan por separado se decide en el Plan (S-8).
- RF-20. EL SISTEMA NO DEBERÁ agregar a Country ningún atributo de moneda, ni a Currency ningún atributo de país.
- RF-21. EL SISTEMA DEBERÁ mantener CountryCurrency como parte del catálogo Currency (D-16): se versiona e incorpora con él y Country no depende de ella.

### Contratos de consulta

- RF-22. CUANDO un consumidor resuelva por un `currency_id` existente, EL SISTEMA DEBERÁ devolver la Currency con su `status`, sea `active` o `inactive`.
- RF-23. CUANDO un consumidor resuelva por código alfabético, EL SISTEMA DEBERÁ comparar sin distinguir mayúsculas y devolver la Currency que lo posee, con su `status`.
- RF-24. SI el `currency_id` o el código no existe, ENTONCES EL SISTEMA DEBERÁ devolver un resultado explícito "no encontrado".
- RF-25. SI la entrada tiene formato inválido (identidad mal formada, código con longitud o caracteres no válidos), ENTONCES EL SISTEMA DEBERÁ devolver un error de validación.
- RF-26. SI la consulta no puede completarse por una falla técnica, ENTONCES EL SISTEMA DEBERÁ devolver un error técnico; nunca la presentará como "no encontrado" ni como error de validación. Los contratos distinguen así cinco resultados: entidad `active`, entidad `inactive`, "no encontrado", entrada inválida y error técnico.
- RF-27. CUANDO un consumidor liste monedas, EL SISTEMA DEBERÁ devolver por defecto solo las `active`, en orden determinístico por código alfabético, con opción explícita de incluir las `inactive` y de excluir los códigos de fondos.
- RF-28. CUANDO un consumidor valide un `currency_id`, EL SISTEMA DEBERÁ devolver el resultado de validación `active`, `inactive` o `not_found`, sin decidir si el consumidor acepta inactivas.
- RF-29. EL SISTEMA DEBERÁ devolver en toda resolución de Currency como mínimo: `currency_id`, código alfabético, código numérico, unidades menores (o "no aplicable"), indicador de fondos, `status`, reemplazo (si existe) y nombre según RF-15.
- RF-30. CUANDO un consumidor pida las monedas de un `country_id`, EL SISTEMA DEBERÁ devolver las Currency con asociación `active`, en orden por código alfabético, con opción de incluir asociaciones `inactive`; un Country existente sin monedas devuelve lista vacía, y un `country_id` inexistente devuelve "no encontrado".
- RF-31. CUANDO un consumidor pida los países de un `currency_id`, EL SISTEMA DEBERÁ devolver los `country_id` con asociación `active`, con las mismas reglas que RF-30.
- RF-32. EL SISTEMA DEBERÁ permitir consultar la versión aplicada del catálogo Currency.
- RF-33. EL SISTEMA DEBERÁ versionar cada contrato público; agregar campos o consultas es compatible, y quitar o cambiar el significado de un campo requiere nueva versión mayor con análisis de migración.
- RF-34. EL SISTEMA NO DEBERÁ exponer a los consumidores operaciones de alta, modificación ni baja de Currency, sus localizaciones ni CountryCurrency.
- RF-35. EL SISTEMA DEBERÁ permitir que los consumidores referencien una Currency almacenando solo `currency_id`; los códigos ISO son claves de resolución, no sustitutos de la identidad, y ningún consumidor necesita FK inter-repositorio ni acceso a estructuras internas.

### Ciclo de vida e incorporación de snapshots

- RF-36. CUANDO se incorpore un snapshot aprobado, EL SISTEMA DEBERÁ crear las Currency, localizaciones y asociaciones nuevas, actualizar las modificadas y conservar el `currency_id` de las ya publicadas.
- RF-37. SI un snapshot omite una Currency, localización o asociación publicada, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo; un retiro se expresa como `status = inactive`, nunca como ausencia.
- RF-38. CUANDO ISO 4217 retire una moneda, EL SISTEMA DEBERÁ pasarla a `inactive`, pasar a `inactive` sus asociaciones y, si la fuente declara sucesora de forma confiable, registrarla como reemplazo.
- RF-39. EL SISTEMA DEBERÁ incorporar cada snapshot de forma atómica dentro del catálogo Currency (todo o nada; S-8) e idempotente (incorporar dos veces el mismo deja el catálogo observable idéntico), y rechazar uno de versión anterior a la aplicada salvo acción explícita de reversión.
- RF-40. SI un snapshot referencia un `country_id` inexistente en el catálogo Countries aplicado, o una entidad ISO que debería corresponder a un Country no puede vincularse sin ambigüedad, ENTONCES EL SISTEMA DEBERÁ rechazarlo en lugar de resolverlo en silencio.
- RF-41. EL SISTEMA DEBERÁ aceptar solo snapshots con versión única, contenido completo, verificación de integridad, procedencia por fuente (nombre, edición, fecha de obtención, ubicación, verificación de integridad del origen, licencia) y las versiones de Locale y Countries contra las que se validó; y disponer de un diff legible contra la versión aplicada para revisión humana antes de aprobarlo.
- RF-42. EL SISTEMA DEBERÁ resolver las consultas sin acceder a fuentes externas en tiempo de ejecución.
- RF-43. CUANDO se incorporen monedas históricas de ISO 4217 List Three, EL SISTEMA DEBERÁ agregarlas como Currency `inactive` con `currency_id` nuevos, sin modificar identidades ni contratos existentes.

## Requisitos no funcionales

- RNF-1. Reproducibilidad: el mismo snapshot produce el mismo catálogo y los mismos `currency_id` en cualquier entorno.
- RNF-2. Trazabilidad: toda versión aplicada es rastreable a su snapshot, procedencia y aprobación en el historial del repositorio.
- RNF-3. Las consultas requieren solo lectura; la escritura queda restringida al proceso de incorporación controlado.
- RNF-4. Sin aislamiento por tenant: todos los consumidores autorizados leen el mismo catálogo.
- RNF-5. Las invariantes estructurales (RF-2 a RF-7, RF-9, RF-12, RF-17, RF-19) se protegen en la persistencia y no solo en código de aplicación (AGENTS.md); el mecanismo se decide en el Plan.
- RNF-6. Dirección de dependencias: Currency depende solo de Locale; CountryCurrency depende de Country y de Currency; Country no depende de Currency; Locale no depende de Currency (RNF-6 de 001). Orden: 001 → 002 → 003 → 004.
- RNF-7. Determinismo: la misma versión del catálogo y la misma consulta devuelven siempre el mismo resultado.
- RNF-8. Extensibilidad compatible: agregar símbolos, moneda principal, búsqueda por código numérico, atributos de asociación o monedas históricas es aditivo y no modifica `currency_id` ni el significado de los contratos existentes.

## Casos límite

- CL-1. Unidades sin unidades menores (XAU, XAG, XDR): "no aplicable", distinguible de `0`.
- CL-2. Monedas con 0 decimales (JPY, CLP), con 3 (KWD, BHD, TND) y con 4 (CLF, UYW): se representan tal cual.
- CL-3. Códigos numéricos con ceros a la izquierda (`008` ALL, `032` ARS): se preserva su representación normativa.
- CL-4. Moneda usada por muchos países (EUR, USD, XOF, XAF, XCD): una asociación por país.
- CL-5. País con varias monedas (PA: PAB + USD; CH: CHF + CHE + CHW; BO: BOB + BOV): todas asociadas; el consumidor puede excluir fondos (RF-27).
- CL-6. País sin moneda (AQ, "No universal currency"): lista vacía, no "no encontrado".
- CL-7. Moneda sin país (XDR, XSU, XUA, XBA–XBD, XAU): válida, sin asociaciones.
- CL-8. Retiro con adopción de otra moneda (HR: HRK → EUR): HRK `inactive` con reemplazo EUR; HR–HRK `inactive`; HR–EUR `active`; un `currency_id` de HRK ya almacenado sigue resolviéndose y su validación devuelve `inactive`.
- CL-9. Redenominación (VEF → VES): VES es una Currency nueva; VEF `inactive` con reemplazo VES (D-6, RF-11).
- CL-10. Cambio de unidades menores decidido por ISO (precedente: ISK de 2 a 0): se conserva `currency_id` y el cambio aparece en el diff (RF-41).
- CL-11. Reasignación por ISO de un código numérico usado por una Currency `inactive` (precedente: 891 de YUM pasó a CSD): pasa a la nueva Currency `active`; la anterior sigue resoluble por `currency_id` y por su código alfabético.
- CL-12. Entrada `usd` se tolera; ` USD`, `US`, `US$` o una cadena vacía devuelven error de validación (RF-25).
- CL-13. Countries retira un país con asociaciones `active`: ninguna asociación `active` puede quedar sobre el país `inactive` (RF-19); la coordinación entre ambos catálogos se decide en el Plan (S-8).
- CL-14. Asociación que ISO deja de declarar mientras país y moneda siguen vigentes: la asociación pasa a `inactive`; ambos registros no cambian.
- CL-15. Catálogo vacío (antes del primer snapshot): listas vacías o "no encontrado", nunca error técnico (igual que 001 y 002).
- CL-16. Consulta con un locale válido no obligatorio y sin traducción: Currency devuelta con el nombre ausente, sin fallback (RF-15).

## Fuera de alcance

- Tasas de cambio, cotizaciones actuales o históricas, conversión monetaria, proveedores financieros.
- Contabilidad, precios, saldos, wallets, medios de pago, reglas tributarias.
- Configuración monetaria por tenant u organización (p. ej. moneda predeterminada, que pertenece a Tenants).
- Moneda principal de un país (D-10); símbolos, máscaras, separadores y formato monetario (D-11).
- Precarga de ISO 4217 List Three en v1 (D-8) y fechas de retiro.
- Búsqueda por código numérico (D-12).
- Definir el conjunto obligatorio de locales (pertenece a 001, DEP-1).
- CRUD administrativo; diseño interno de PREP; formato físico del snapshot; pipeline común de versionado de catálogos.
- Modificar 001, 002 o 003 desde esta spec (ver "Inconsistencias transversales").
- Cambios en otros repositorios.

## Criterios de aceptación

- CA-1. El catálogo cargado contiene exactamente las monedas de ISO 4217 List One de la edición declarada, salvo `XTS` y `XXX`, todas con `status = active` (RF-1, D-7, D-8).
- CA-2. Ningún registro de Currency, de sus localizaciones ni de CountryCurrency tiene `tenant_id` ni `organization_id`, y un mismo `currency_id` resuelve igual para cualquier consumidor (RF-1, RNF-4).
- CA-3. Intentar persistir un código alfabético repetido, un código numérico repetido entre activas, un código mal formado, unidades menores inválidas, un reemplazo en ciclo o en una Currency `active`, una asociación duplicada o un `status` fuera de `active`/`inactive` falla en la persistencia, no solo en la aplicación (RF-3, RF-4, RF-6, RF-9, RF-17, RNF-5).
- CA-4. Resolver por `currency_id` y por código alfabético (`usd`, `USD`) devuelve el mismo registro con los campos de RF-29 (RF-22, RF-23, RF-29).
- CA-5. Un código inexistente devuelve "no encontrado", uno mal formado devuelve error de validación y una falla técnica simulada devuelve error técnico; los tres son distinguibles (RF-24, RF-25, RF-26).
- CA-6. Validar un `currency_id` `active`, `inactive` e inexistente devuelve `active`, `inactive` y `not_found`; `not_found` no aparece nunca como `status` de un registro (RF-9, RF-28).
- CA-7. EUR está asociada a varios países, PA a varias monedas, AQ devuelve lista vacía y XDR no tiene países (RF-18, RF-30, RF-31).
- CA-8. Country no tiene atributo de moneda y Currency no tiene atributo de país (RF-20).
- CA-9. Un snapshot que simula HRK → EUR conserva el `currency_id` de HRK, lo deja `inactive` con reemplazo EUR, y HR queda asociado de forma `active` solo a EUR (RF-36, RF-38, CL-8).
- CA-10. Se rechaza sin cambios parciales en el catálogo Currency un snapshot de Currency que cambia un código de una Currency publicada, omite una Currency, localización o asociación, referencia un `country_id` inexistente, deja una asociación `active` sobre un registro `inactive` o es de versión anterior (RF-5, RF-19, RF-37, RF-39, RF-40).
- CA-11. Incorporar dos veces el mismo snapshot deja el catálogo observable idéntico (RF-39).
- CA-12. Una Currency sin nombre en algún locale obligatorio, o con una localización nueva en un locale `inactive`, impide incorporar el snapshot; una consulta con locale sin traducción devuelve el nombre ausente sin fallback (RF-13, RF-14, RF-15).
- CA-13. No existe operación pública de escritura para consumidores ni dato de cotización, tipo de cambio o saldo (RF-8, RF-34).
- CA-14. Las consultas funcionan sin conectividad a ISO, CLDR ni otra fuente externa, y la versión consultable coincide con la del snapshot aprobado y su procedencia (RF-32, RF-41, RF-42).
- CA-15. Incorporar después una moneda de List Three la agrega como `inactive` con `currency_id` nuevo, sin alterar las existentes (RF-43).

## Supuestos

- S-1. La lista ISO 4217 (List One y List Three) puede obtenerse de la publicación oficial de la agencia de mantenimiento (SIX), con licencia compatible; PREP la incorpora con procedencia.
- S-2. Los nombres en inglés provienen de ISO 4217 y los de otros locales de CLDR, declarados en la procedencia.
- S-3. 001 y 003 se aplican antes que este catálogo; sin ellos no hay `locale_id` ni `country_id` válidos.
- S-4. El canal técnico de los contratos, los nombres de campo, la forma física de las entidades, el formato de las identidades, los mecanismos de restricción y el de incorporación se deciden en el Plan, reutilizando lo que defina 003.
- S-5. El código numérico es único solo entre activas porque ISO lo ha reasignado (891: YUM → CSD); el alfabético, en cambio, queda ligado a una sola Currency (D-15). Si ISO reasignara alguna vez un código alfabético, incorporarlo requiere decisión explícita.
- S-6. La reactivación (`inactive` → `active`) se admite solo por snapshot aprobado y revisado (RF-10): la convención de 001 no la prohíbe, y una asociación país–moneda puede volver a declararse.
- S-7. Se usa "snapshot" (001, 002, README) en lugar de "dataset" (003) para el mismo concepto.
- S-8. La spec no exige una operación única entre snapshots de catálogos distintos. El orden de incorporación, la coordinación entre Countries y Currency y el mecanismo técnico que preserva RF-19 se deciden en el Plan. La atomicidad de RF-39 se refiere a un snapshot dentro de su propio catálogo.

## Dependencias abiertas en otras specs

- DEP-1. **Conjunto obligatorio de locales.** 001 no define una política transversal; 002 fija el suyo (`en`, `es`; RF-31, S-7 de 002). Currency adopta el conjunto que defina la política transversal de Locale (RF-13) y no inventa uno propio. Requiere `/sdd-change 001-locales` para definir esa política, y luego `/sdd-change 002-regions-subregions` para que 002 la referencie. No bloquea el Plan de 004; sí bloquea incorporar el primer snapshot de Currency.

## Inconsistencias transversales detectadas (clarify 2026-10-19)

Convención correcta: la de 001 (estado, localización), adoptada por 002 y por 004. No se modificó ninguna spec anterior.

| Id | Inconsistencia | Convención correcta | Acción |
|---|---|---|---|
| X-1 | 003 usa `is_active` (modelo, RF-15) | `status` = `active` \| `inactive` (S-10, S-11 de 001) | `/sdd-change 003-countries` |
| X-2 | 003 guarda `name` y `official_name` en Country | Localizaciones asociadas a Locale (RF-23 de 001) | `/sdd-change 003-countries` |
| X-3 | 003 guarda código y nombre de región/subregión en Country | Referenciar `region_id` / `subregion_id` (sección "Contrato esperado por 003" de 002) | `/sdd-change 003-countries` (ya señalado por 002) |
| X-4 | 003 fija `country_id` UUID en la spec; 001 y 002 difieren el formato al Plan (S-4 de 002) | Identidad estable en spec; formato en Plan, uniforme para todo Reference | Decidirlo en el Plan; si se fija como convención transversal, registrarla en 001 |
| X-5 | 003 no prevé que retirar un país afecta a las asociaciones CountryCurrency `active` | Rige la invariante RF-19 de 004; la coordinación entre catálogos se decide en el Plan de 004 (S-8) | Mencionar la interacción en `/sdd-change 003-countries`, sin fijar mecanismo |
| X-6 | 002 indica que 003 depende de 004 "para CountryCurrency" | CountryCurrency pertenece a 004; Country no depende de Currency (D-16, RNF-6) | `/sdd-change 002-regions-subregions` |
| X-7 | 001 no define el conjunto obligatorio de locales; 002 define uno propio | Política transversal en 001 | DEP-1 |
| X-8 | 003 usa "dataset"; 001, 002 y README usan "snapshot" | "snapshot" | Ajustar en el `/sdd-change` de 003 |

## Registro de clarificación (2026-10-19)

- Diseño físico diferido al Plan: formato de `currency_id` (antes UUID), tipos, representación de "no aplicable", nombres de estructuras, constraints concretos, timestamps (RF-39 ahora habla del catálogo observable) y formato del snapshot (S-4).
- `status` = `active` | `inactive` adoptado según 001 (D-14, RF-9); `not_found` definido como resultado de consulta (Definiciones, RF-28, CA-6).
- Error técnico distinguido de "no encontrado" y de entrada inválida (RF-26).
- Código alfabético único en todo el catálogo (D-15); la resolución por código ya no necesita desempate (RF-23).
- Localización alineada con 001/002: sin fallback, locales inactivos, nombre válido (RF-14 a RF-16).
- Q-1 resuelta: los locales obligatorios los define la política de Locale (RF-13, DEP-1).
- Q-2 resuelta: List Three no se exige en v1; su incorporación posterior es aditiva (D-8, RF-43).
- Propiedad de CountryCurrency en 004 (D-16, RF-21); invariante de asociación activa (RF-19).
- Categorías ISO incluidas y excluidas explicitadas (D-7).

## Registro de clarificación 2 (2026-10-19)

- Eliminada la exigencia de atomicidad entre catálogos distintos en RF-19, CL-13 y X-5; queda solo la invariante funcional y la coordinación pasa al Plan (S-8). CA-10 se limita al snapshot de Currency.
- RF renumerados en orden secuencial y referencias internas actualizadas. Las referencias a RF de 001, 002 y 003 conservan su numeración original.

## Preguntas abiertas

Ninguna propia de 004. Queda la dependencia externa DEP-1.
