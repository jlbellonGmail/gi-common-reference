# 004-currency — Catálogo global de monedas

- **Estado:** aprobada y implementada; plan y tasks completos (clarify 2026-10-19; clarify 3 y 4 2026-10-31, reconciliado con 001, 002 y 003 aprobadas en `develop` e integradas las decisiones del responsable F1–F12)
- **Tipo:** Feature (spec del dominio Reference)
- **Depende de:** `001-locales` (identidad `locale_id`, convención común de `status`, regla de localización RF-23–RF-25 de 001), `003-countries` (identidad `country_id`, para la asociación CountryCurrency). Ambas están cerradas y aprobadas: 004 las consume y no las modifica.
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
- HU-7. Como consumidor, quiero saber qué moneda(s) correspondían a un país en una fecha dada, y conservar la historia de las transiciones (p. ej. HRK → EUR), para interpretar datos históricos.

## Definiciones

- **Currency:** unidad monetaria o de cuenta con código alfabético _asignado_ en ISO 4217, dentro de las categorías incluidas por D-7.
- **`status`:** estado del registro según la convención común de los catálogos globales fijada por 001 (S-10, S-11 de 001): `active` | `inactive`. Currency no define atributos ni valores propios.
  - `active`: figura en la lista vigente de ISO 4217 (List One); resoluble y apta para nuevas referencias.
  - `inactive`: estuvo publicada y fue retirada de ISO 4217 (List Three) o por decisión GI aprobada; resoluble para no romper referencias, no recomendada para nuevas.
- **Resultado de validación:** respuesta de una consulta sobre una referencia: `active`, `inactive` o `not_found`. `not_found` es un resultado de consulta, **nunca** un valor de `status`.
- **Unidades menores:** cantidad de dígitos decimales estándar que ISO 4217 declara para la moneda (0, 2, 3, 4…). ISO declara "no aplicable" (N.A.) para algunas unidades (p. ej. XAU, XDR); "no aplicable" es distinto de `0`.
- **Reemplazo:** conjunto de cardinalidad 0..N de Currency sucesoras de una Currency `inactive`, vacío cuando la fuente normativa no declara sucesión de forma confiable (D-17). Es información aparte de `status`, igual que en 001, 002 y 003.
- **Localización de Currency** (conceptualmente `CurrencyLocale`, regla RF-23 de 001): texto traducible de una Currency (su nombre) en un Locale concreto.
- **CountryCurrency:** asociación entre un Country y una Currency, con `status` y vigencia temporal propios. Pertenece a 004 (D-16); no es atributo de ninguno de los dos.
- **`status` de CountryCurrency:** ciclo de vida del **registro** publicado en el catálogo (D-14). `active`: el registro es una afirmación válida del catálogo, incluida una asociación histórica ya cerrada. `inactive`: el registro fue retirado como afirmación (p. ej. la fuente dejó de declararla o se corrigió su período); se conserva para trazabilidad y no participa de las consultas por defecto.
- **Vigencia temporal:** período real durante el cual la relación Country–Currency corresponde. Es independiente de `status` y **no lo sustituye** (D-18): una asociación `active` con vigencia cerrada es historia válida; una `inactive` no es una afirmación vigente aunque su período no esté cerrado.
- **Fecha de referencia:** día calendario con el que se consulta la vigencia; si el consumidor no la indica es el día de la consulta.
- **Snapshot / publicado:** mismo significado que en 001 y 002, aplicado a este catálogo (snapshot = dataset aprobado y versionado).
- **Conjunto obligatorio de locales de Currency v1:** `en` y `es` (D-19). Es una regla de completitud de este catálogo en su versión 1, no una política transversal de Locale.

## Decisiones

### Heredadas (AGENTS.md, 001, 002, 003)

- D-1. Currency es GLOBAL, sin `tenant_id` ni `organization_id`, propiedad única de `gi-common-reference`.
- D-2. Sin CRUD para consumidores; el catálogo solo cambia mediante snapshots aprobados, con las mismas propiedades de incorporación que 001 (RF-14 a RF-22, RF-31, RF-32) y 003 (RF-20 a RF-30): `snapshot_version` entera positiva, digest de contenido recalculado y clasificación contra el historial (reglas A/B/C/D de RF-32 de 001), sin reversión.
- D-3. Los consumidores integran por contrato, no por FK inter-repositorio ni por estructuras internas (AGENTS.md; D-13 de 003).
- D-4. Los textos traducibles de Currency se representan como localizaciones asociadas a Locale (RF-23 a RF-25 de 001); Currency no tiene nombres como atributo canónico.

### Tomadas por esta spec

- D-5. **Identidad asignada por Reference.** `currency_id` se asigna una única vez al incorporar la moneda, queda registrado en el snapshot aprobado y es idéntico en todos los entornos (mismo criterio que D-11 de 003: PREP puede proponer candidatos, que no son autoritativos hasta que el mantenedor aprueba el snapshot; el sistema nunca lo genera). Su formato es UUID, como `locale_id`, `region_id` y `country_id` (X-4); el tipo físico y la validación se detallan en el Plan.
- D-6. **Un código alfabético nuevo es una moneda nueva.** En ISO 4217 un código nuevo implica una unidad monetaria distinta (VEF→VES, MRO→MRU, HRK→EUR); se crea una Currency nueva y la anterior pasa a `inactive` con reemplazo cuando corresponda. Los códigos de una Currency publicada no cambian.
- D-7. **Categorías incluidas:** todas las de ISO 4217 List One vigente — monedas nacionales, supranacionales (EUR, XOF, XAF, XCD), códigos de fondos (BOV, CHE, CHW, USN, CLF, COU, MXV, UYI), unidades especiales del FMI y otros organismos (XDR, XSU, XUA), unidades del mercado de bonos (XBA–XBD) y metales preciosos (XAU, XAG, XPT, XPD). **Excluidas deliberadamente:** `XTS` (reservado para pruebas) y `XXX` (ausencia de moneda), que no son unidades monetarias. Incluirlas después requiere decisión explícita y es aditivo.
- D-8. **Snapshot inicial:** solo List One vigente, todo `active`. No se exige precargar List Three; las monedas históricas podrán incorporarse después de forma aditiva (RF-43). (decisión del responsable, clarify 2026-10-19)
- D-9. **CountryCurrency se deriva de las entidades de ISO 4217 List One** que corresponden a un Country, y su historia territorio–moneda de la fuente complementaria (D-20). Entidades ISO sin Country (p. ej. "EUROPEAN UNION", "INTERNATIONAL MONETARY FUND (IMF)", "SISTEMA UNITARIO DE COMPENSACION REGIONAL DE PAGOS SUCRE") no generan asociación. Los códigos de fondos se asocian igual que los demás, porque ISO los declara así.
- D-10. **Sin "moneda principal" en v1.** ISO no la define; la moneda predeterminada de un tenant pertenece a Tenants. Un Country puede tener varias monedas simultáneas sin que ninguna sea principal. Los atributos de CountryCurrency en v1 son `status` y la vigencia temporal (D-18); otros atributos podrán agregarse después de forma aditiva.
- D-11. **Símbolos y formato monetario fuera de v1** (`$`, `US$`, `€`, separadores, máscaras, presentación por locale). No forman parte de la identidad normativa; incorporarlos después como datos localizados es aditivo.
- D-12. **Claves públicas de resolución:** `currency_id` y código alfabético. El código numérico se expone como atributo; buscar por él queda **fuera de v1** (decisión confirmada por el responsable, F7). El código numérico forma parte de los datos normativos publicados y se devuelve en toda resolución (RF-29). Agregar después la resolución por código numérico es compatible y aditivo (RNF-8); que 003 sí la ofrezca no obliga a 004.
- D-13. **Versionado independiente:** el catálogo Currency (incluidas sus localizaciones y CountryCurrency) tiene versión y ciclo de snapshot propios, validados contra las versiones aplicadas de Locale y Countries (mismo criterio que S-10 de 002).
- D-14. **Convención de estado común** (decisión del responsable, clarify 2026-10-19): Currency y CountryCurrency usan `status` = `active` | `inactive` según 001; no existen `is_active`, `enabled`, `state`, `vigente` ni variantes.
- D-15. **Unicidad de códigos.** El código alfabético queda ligado a una única Currency en todo el catálogo, incluidas las inactivas (mismo principio que RF-16 de 001 y S-8 de 002). El código numérico es único solo entre activas, porque ISO lo ha reasignado (S-5).
- D-16. **Propiedad de CountryCurrency:** pertenece a 004-currency. Depende de Country y de Currency; Country no depende de Currency (X-6; confirmado por D-18 de 003).
- D-17. **Reemplazo 0..N** (clarify 3, mismo patrón que RF-52 y S-9 de 003): una Currency `inactive` puede tener cero, uno o varios sucesores, porque ISO retira unidades dividiéndolas (precedente: CSK → CZK y SKK). El snapshot lo declara como arreglo sin orden significativo; se persiste y se devuelve ordenado por `currency_id`. Se rechaza un identificador repetido, un elemento nulo, el propio `currency_id`, un ciclo y un conjunto no vacío en una Currency `active`. Elegirlo ahora evita migrar el contrato cuando se incorporen retiros (RF-33). Confirmado por el responsable (F3).
- D-18. **CountryCurrency es temporal** (F8–F10). La asociación Country–Currency es N:N (un Country puede tener 0..N monedas y una Currency 0..N Country; no hay unicidad de moneda por país) y lleva vigencia temporal con la semántica de RF-44 a RF-52. `status` expresa el ciclo de vida del registro publicado; la vigencia expresa durante qué período real la relación corresponde; ninguna sustituye a la otra. La historia se preserva: nunca se borra ni se sobrescribe un período publicado y cerrado (RF-7, RF-47). La representación física (campos, tipos, intervalos, restricciones, índices) la decide el Plan.
- D-19. **Locales obligatorios de Currency v1: `en` y `es`** (F4). Es una regla de completitud propia de 004 v1: no modifica 001, no la convierte en política transversal de Locale ni obliga a otros catálogos. Se expresa por `locale_id`, nunca como texto en el modelo (RF-13).
- D-20. **Autoridad y fuentes** (F6, F11). ISO 4217 es la autoridad primaria de código alfabético, código numérico, unidades menores, categorías incluidas y vigencia normativa de la moneda. Se aprueba CLDR como fuente complementaria **solo** para (a) nombres localizados y (b) la historia territorio–moneda de CountryCurrency; PREP registra la procedencia de cada dato (fuente, edición, fecha de obtención, ubicación, verificación de integridad, licencia). Una fuente complementaria nunca redefine `country_id` ni `currency_id`: toda entidad externa se mapea contra el Country publicado por 003 y, si no puede vincularse sin ambigüedad, el snapshot se rechaza (RF-40).

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
| Reemplazos | Currency sucesoras, 0..N (D-17) | Conjunto, vacío por defecto; no vacío solo si `inactive` | — | Cambia solo por snapshot | ISO 4217 List Three + revisión |

### Localización de Currency

Conceptualmente `CurrencyLocale`: Currency ↔ CurrencyLocale ↔ Locale. Su única responsabilidad en v1 es el **nombre** de la moneda por Locale (p. ej. `en` "Argentine Peso", `es` "peso argentino"); a lo sumo uno por par (Currency, Locale). `CurrencyLocale` consume `locale_id` de 001. No incluye símbolos, símbolos estrechos, máscaras, separadores, formato monetario, pluralización ni reglas de presentación (D-11).

### CountryCurrency

Conceptualmente: Currency ↔ CountryCurrency ↔ Country. Asociación entre un `country_id` (contrato de 003) y un `currency_id`, con:

| Atributo | Significado | Obligatorio | Estabilidad | Autoridad |
|---|---|---|---|---|
| Identidad de la asociación | Distingue períodos distintos del mismo par; su forma la decide el Plan | Sí | Inmutable | GI (Reference) |
| `country_id`, `currency_id` | Extremos de la relación | Sí | Inmutables | 003 / GI |
| `status` | `active` / `inactive` (ciclo de vida del registro) | Sí | Cambia solo por snapshot | Fuente + decisión GI |
| Inicio de vigencia | Primer día en que la relación corresponde; ausente = inicio no declarado por la fuente | No | Se puede completar una vez; luego inmutable (RF-47) | ISO 4217 / CLDR |
| Fin de vigencia | Primer día en que la relación ya no corresponde; ausente = sin fin declarado | No | Se puede fijar una vez; luego inmutable (RF-47) | ISO 4217 / CLDR |

Una asociación `active` con inicio y fin ausentes equivale a "la fuente declara la relación sin acotarla". Sin indicador de moneda principal (D-10).

## Requisitos funcionales

### Identidad e integridad

- RF-1. EL SISTEMA DEBERÁ mantener Currency, sus localizaciones y CountryCurrency como catálogo global, sin `tenant_id`, `organization_id` ni partición por tenant, organización o módulo.
- RF-2. EL SISTEMA DEBERÁ dar a cada Currency una identidad GI (`currency_id`) estable, global e inmutable, que no se reasigna ni se reutiliza y no depende de sus códigos, nombres ni `status`.
- RF-3. EL SISTEMA DEBERÁ impedir que dos Currency compartan código alfabético, y que dos Currency `active` compartan código numérico.
- RF-4. EL SISTEMA DEBERÁ rechazar un código alfabético que no sean tres letras latinas mayúsculas, un código numérico que no sean tres dígitos en su representación normativa y unidades menores que no sean un entero no negativo ni "no aplicable".
- RF-5. SI un snapshot cambia un código de una Currency publicada, o asigna un código alfabético publicado a otro `currency_id`, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo (D-6, D-15).
- RF-6. EL SISTEMA DEBERÁ admitir reemplazos (D-17) solo en una Currency `inactive`, que apunten a Currency existentes, distintas de sí misma, sin repetidos ni nulos y sin formar ciclos; un sucesor puede estar a su vez `inactive`.
- RF-7. EL SISTEMA NO DEBERÁ eliminar nunca una Currency, una localización ni una asociación CountryCurrency publicadas.
- RF-8. EL SISTEMA NO DEBERÁ incluir en este catálogo cotizaciones, tipos de cambio, conversiones, precios, saldos ni configuración por cliente.
- RF-9. EL SISTEMA DEBERÁ registrar el estado de cada Currency y de cada CountryCurrency como `status` = `active` | `inactive` (D-14), sin otro atributo ni valor con la misma semántica.
- RF-10. EL SISTEMA DEBERÁ cambiar `status` solo mediante un snapshot aprobado, en cualquier dirección, con el cambio visible en el diff de revisión; reactivar una Currency queda sujeto a RF-3 y limpia su conjunto de reemplazos (RF-6).
- RF-11. CUANDO ISO 4217 asigne un código alfabético nuevo, aunque sustituya a otro, EL SISTEMA DEBERÁ incorporarlo como Currency nueva con `currency_id` nuevo (D-6).

### Localización

- RF-12. EL SISTEMA DEBERÁ representar el nombre de cada Currency como localización asociada a un Locale existente, a lo sumo una por par (Currency, Locale), con integridad referencial garantizada (RF-23, RF-24 de 001).
- RF-13. EL SISTEMA DEBERÁ exigir que cada Currency publicada tenga nombre en los locales `en` y `es` (D-19), identificados por `locale_id` en una lista versionada de `gi-common-reference`. SI alguno de esos locales no existe o está `inactive` en el catálogo Locale aplicado, ENTONCES EL SISTEMA DEBERÁ rechazar el snapshot (RF-33 de 002). Esta regla es propia de Currency v1 y no altera 001 (S-10).
- RF-14. SI un snapshot agrega una localización con un locale inexistente o `inactive`, ENTONCES EL SISTEMA DEBERÁ rechazarlo; las localizaciones ya publicadas cuyo locale pase después a `inactive` se conservan y siguen resolviéndose (RF-33 de 002).
- RF-15. CUANDO una consulta indique un locale, EL SISTEMA DEBERÁ devolver el nombre en ese locale o, si no existe, la Currency con el nombre ausente, sin fallback a otro locale; SI el locale no existe o está mal formado, ENTONCES DEBERÁ devolver un error de validación (RF-18, RF-19 de 002).
- RF-16. EL SISTEMA DEBERÁ exigir que un nombre no esté vacío ni tenga espacios al inicio o al final.

### CountryCurrency

- RF-17. EL SISTEMA DEBERÁ representar la relación país–moneda solo mediante CountryCurrency, entre un `country_id` y un `currency_id` existentes, con integridad referencial garantizada; un mismo par puede tener varias asociaciones solo si sus períodos de vigencia son distintos y no se solapan (RF-45).
- RF-18. EL SISTEMA DEBERÁ permitir que un Country tenga cero, una o varias Currency, también simultáneamente, y que una Currency tenga cero, uno o varios Country; no existe unicidad de Currency por Country (D-18).
- RF-19. EL SISTEMA DEBERÁ garantizar que ninguna CountryCurrency `active` con vigencia abierta (sin fin) referencie un Country `inactive` ni una Currency `inactive`; una asociación `active` con vigencia cerrada puede referenciarlos, porque es historia (D-18). Cómo se preserva cuando Countries y Currency se versionan por separado se decide en el Plan (S-8).
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
- RF-29. EL SISTEMA DEBERÁ devolver en toda resolución de Currency como mínimo: `currency_id`, código alfabético, código numérico, unidades menores (o "no aplicable"), indicador de fondos, `status`, reemplazos (conjunto, posiblemente vacío) y nombre según RF-15.
- RF-30. CUANDO un consumidor pida las monedas de un `country_id`, EL SISTEMA DEBERÁ devolver las Currency con asociación `active` cuya vigencia contiene la fecha de referencia (RF-48), en orden por código alfabético, con opción de incluir asociaciones `inactive` y de excluir las Currency que son códigos de fondos (como en RF-27, CL-5); un Country existente sin monedas devuelve lista vacía, y un `country_id` inexistente devuelve "no encontrado".
- RF-31. CUANDO un consumidor pida los países de un `currency_id`, EL SISTEMA DEBERÁ devolver los `country_id` con asociación `active` cuya vigencia contiene la fecha de referencia, con las mismas reglas que RF-30.
- RF-32. EL SISTEMA DEBERÁ permitir consultar la versión aplicada del catálogo Currency.
- RF-33. EL SISTEMA DEBERÁ versionar cada contrato público; agregar campos o consultas es compatible, y quitar o cambiar el significado de un campo requiere nueva versión mayor con análisis de migración.
- RF-34. EL SISTEMA NO DEBERÁ exponer a los consumidores operaciones de alta, modificación ni baja de Currency, sus localizaciones ni CountryCurrency.
- RF-35. EL SISTEMA DEBERÁ permitir que los consumidores referencien una Currency almacenando solo `currency_id`; los códigos ISO son claves de resolución, no sustitutos de la identidad, y ningún consumidor necesita FK inter-repositorio ni acceso a estructuras internas.

### Ciclo de vida e incorporación de snapshots

- RF-36. CUANDO se incorpore un snapshot aprobado, EL SISTEMA DEBERÁ crear las Currency, localizaciones y asociaciones nuevas, actualizar las modificadas y conservar el `currency_id` de las ya publicadas.
- RF-37. SI un snapshot omite una Currency, localización o asociación publicada, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo; un retiro se expresa como `status = inactive`, nunca como ausencia.
- RF-38. CUANDO ISO 4217 retire una moneda, EL SISTEMA DEBERÁ pasarla a `inactive`, cerrar la vigencia de sus asociaciones abiertas conservándolas `active` como historia (RF-19, RF-46) y, si la fuente declara sucesoras de forma confiable, registrarlas como reemplazos (D-17).
- RF-39. EL SISTEMA DEBERÁ incorporar cada snapshot de forma atómica dentro del catálogo Currency (todo o nada; S-8) e idempotente, y clasificar cada snapshot que cumple RF-41 contra el historial incorporado antes de cualquier otra validación (reglas A/B/C/D de RF-32 de 001): A) misma `snapshot_version` y mismo digest, no-op que deja el catálogo observable idéntico; B) misma `snapshot_version` y digest distinto, rechazo; C) `snapshot_version` no incorporada y anterior a la última, rechazo por regresión; D) posterior, continúa. No existe reversión explícita: revertir contenido requiere un snapshot nuevo de versión posterior (S-6 de 003).
- RF-40. SI un snapshot referencia un `country_id` inexistente en el catálogo Countries aplicado, o una entidad ISO que debería corresponder a un Country no puede vincularse sin ambigüedad, ENTONCES EL SISTEMA DEBERÁ rechazarlo en lugar de resolverlo en silencio.
- RF-41. EL SISTEMA DEBERÁ aceptar solo snapshots con `snapshot_version` entera positiva (orden total, saltos permitidos), contenido completo del catálogo Currency (monedas, localizaciones, asociaciones), `currency_id` para cada Currency, digest de contenido que el sistema recalcula, procedencia por fuente (nombre, edición, fecha de obtención, ubicación, verificación de integridad del origen, licencia) y las versiones de Locale y Countries contra las que se validó; SI falta algo, el digest recalculado no coincide o la procedencia declara un conflicto entre fuentes sin resolver (p. ej. nombre ISO ≠ CLDR, o una entidad ISO sin Country inequívoco), ENTONCES DEBERÁ rechazarlo completo; y disponer de un diff legible contra la versión aplicada para revisión humana antes de aprobarlo.
- RF-42. EL SISTEMA DEBERÁ resolver las consultas sin acceder a fuentes externas en tiempo de ejecución.
- RF-43. CUANDO se incorporen monedas históricas de ISO 4217 List Three, EL SISTEMA DEBERÁ agregarlas como Currency `inactive` con `currency_id` nuevos, sin modificar identidades ni contratos existentes.

### Vigencia temporal de CountryCurrency

Define solo la semántica (D-18); campos, tipos, intervalos y restricciones físicas son del Plan.

- RF-44. EL SISTEMA DEBERÁ representar la vigencia de una CountryCurrency como un período de días calendario que **incluye** su día de inicio y **excluye** su día de fin (el fin es el primer día en que la relación ya no corresponde); cada extremo puede estar ausente (inicio no declarado / sin fin declarado) y, cuando ambos existen, el inicio debe ser anterior al fin. Con esta semántica una transición el mismo día (una moneda termina el día en que otra empieza) no produce solapamiento ni hueco.
- RF-45. EL SISTEMA DEBERÁ rechazar dos asociaciones `active` del mismo par (`country_id`, `currency_id`) cuyas vigencias se solapen, y NO DEBERÁ rechazar la coexistencia de asociaciones `active` de **distintas** Currency para un mismo Country con vigencias solapadas (monedas simultáneas, p. ej. PAB y USD en PA), ni de una misma Currency en varios Country. Un par puede tener varios períodos no solapados (p. ej. una moneda readoptada).
- RF-46. CUANDO una relación deja de corresponder (retiro de la moneda o del país, transición a otra moneda), EL SISTEMA DEBERÁ expresarlo fijando el fin de la vigencia, no cambiando `status` ni eliminando el registro; la asociación sigue `active` como historia y deja de formar parte de las consultas actuales por el solo efecto de la vigencia.
- RF-47. EL SISTEMA DEBERÁ preservar la historia: una vigencia publicada con ambos extremos no se modifica ni se elimina; un extremo ausente puede completarse una única vez por snapshot (cerrar una vigencia abierta, declarar un inicio antes desconocido) y luego es inmutable. Corregir un período ya publicado se expresa dejando el registro erróneo `inactive` y publicando una asociación nueva, ambos visibles en el diff de revisión.
- RF-48. CUANDO un consumidor consulte las monedas de un país o los países de una moneda, EL SISTEMA DEBERÁ aceptar una fecha de referencia opcional (por defecto, el día de la consulta) y devolver las asociaciones `active` cuya vigencia la contiene, considerando un extremo ausente como no acotado; una fecha mal formada devuelve error de validación (RF-25); una fecha sin asociaciones devuelve lista vacía, no "no encontrado".
- RF-49. CUANDO un consumidor pida el historial de un `country_id` o de un `currency_id`, EL SISTEMA DEBERÁ devolver todas las asociaciones `active` (con opción de incluir `inactive`) con su vigencia, sin filtrar por fecha, en orden determinístico (inicio de vigencia, con los ausentes primero, y luego código alfabético).
- RF-50. EL SISTEMA DEBERÁ devolver, en toda asociación, `status`, inicio y fin de vigencia y los identificadores de ambos extremos, de modo que el consumidor distinga una asociación vigente, una histórica cerrada, una futura y un registro retirado.
- RF-51. EL SISTEMA NO DEBERÁ derivar `status` de la vigencia ni la vigencia de `status`, ni modificar ninguno por el simple transcurso del tiempo: el catálogo cambia solo por snapshot (RF-10) y "vigente hoy" se calcula al consultar.
- RF-52. SI un snapshot contiene un inicio no anterior al fin, solapamiento prohibido por RF-45, una modificación prohibida por RF-47, una asociación `active` con vigencia abierta sobre un Country o Currency `inactive` (RF-19), o una vigencia de procedencia en conflicto con otra fuente sin resolver, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo. La procedencia de la vigencia (fuente complementaria, D-20) se registra en el snapshot.

## Requisitos no funcionales

- RNF-1. Reproducibilidad: el mismo snapshot produce el mismo catálogo y los mismos `currency_id` en cualquier entorno.
- RNF-2. Trazabilidad: toda versión aplicada es rastreable a su snapshot, procedencia y aprobación en el historial del repositorio.
- RNF-3. Las consultas requieren solo lectura; la escritura queda restringida al proceso de incorporación controlado.
- RNF-4. Sin aislamiento por tenant: todos los consumidores autorizados leen el mismo catálogo.
- RNF-5. Las invariantes estructurales (RF-2 a RF-7, RF-9, RF-12, RF-17, RF-19, RF-44, RF-45) se protegen en la persistencia y no solo en código de aplicación (AGENTS.md); el mecanismo se decide en el Plan.
- RNF-6. Dirección de dependencias: Currency depende solo de Locale; CountryCurrency depende de Country y de Currency; Country no depende de Currency; Locale no depende de Currency (RNF-6 de 001). Orden: 001 → 002 → 003 → 004.
- RNF-7. Determinismo: la misma versión del catálogo, la misma consulta y la misma fecha de referencia devuelven siempre el mismo resultado; la fecha por defecto es el único elemento dependiente del reloj y se explicita en la consulta.
- RNF-8. Extensibilidad compatible: agregar símbolos, moneda principal, búsqueda por código numérico, atributos de asociación o monedas históricas es aditivo y no modifica `currency_id` ni el significado de los contratos existentes.

## Casos límite

- CL-1. Unidades sin unidades menores (XAU, XAG, XDR): "no aplicable", distinguible de `0`.
- CL-2. Monedas con 0 decimales (JPY, CLP), con 3 (KWD, BHD, TND) y con 4 (CLF, UYW): se representan tal cual.
- CL-3. Códigos numéricos con ceros a la izquierda (`008` ALL, `032` ARS): se preserva su representación normativa.
- CL-4. Moneda usada por muchos países (EUR, USD, XOF, XAF, XCD): una asociación por país.
- CL-5. País con varias monedas (PA: PAB + USD; CH: CHF + CHE + CHW; BO: BOB + BOV): todas asociadas; el consumidor puede excluir fondos (RF-27).
- CL-6. País sin moneda (AQ, "No universal currency"): lista vacía, no "no encontrado".
- CL-7. Moneda sin país (XDR, XSU, XUA, XBA–XBD, XAU): válida, sin asociaciones.
- CL-8. Retiro con adopción de otra moneda (HR: HRK → EUR): HRK `inactive` con reemplazo EUR; HR–HRK `active` con vigencia cerrada (fin = 2023-01-01, historia); HR–EUR `active` con inicio 2023-01-01; hoy solo EUR corresponde a HR, y el 2022-06-01 solo HRK; un `currency_id` de HRK ya almacenado sigue resolviéndose y su validación devuelve `inactive`.
- CL-9. Redenominación (VEF → VES): VES es una Currency nueva; VEF `inactive` con reemplazo VES (D-6, RF-11).
- CL-10. Cambio de unidades menores decidido por ISO (precedente: ISK de 2 a 0): se conserva `currency_id` y el cambio aparece en el diff (RF-41).
- CL-11. Reasignación por ISO de un código numérico usado por una Currency `inactive` (precedente: 891 de YUM pasó a CSD): pasa a la nueva Currency `active`; la anterior sigue resoluble por `currency_id` y por su código alfabético.
- CL-12. Entrada `usd` se tolera; ` USD`, `US`, `US$` o una cadena vacía devuelven error de validación (RF-25).
- CL-13. Countries retira un país con asociaciones `active` abiertas: ninguna asociación `active` con vigencia abierta puede quedar sobre el país `inactive` (RF-19); se cierran sus vigencias y quedan como historia. La coordinación entre ambos catálogos se decide en el Plan (S-8).
- CL-14. Asociación que la fuente deja de declarar como afirmación (error de datos, no cambio real) mientras país y moneda siguen vigentes: la asociación pasa a `inactive`; ambos registros no cambian. Un cambio real se expresa cerrando la vigencia (RF-46).
- CL-15. Catálogo vacío (antes del primer snapshot): listas vacías o "no encontrado", nunca error técnico (igual que 001 y 002).
- CL-16. Consulta con un locale válido no obligatorio y sin traducción: Currency devuelta con el nombre ausente, sin fallback (RF-15).
- CL-17. Snapshot con `snapshot_version` ya incorporada y digest distinto, o anterior a la última sin haber sido incorporada: rechazado completo; el mismo snapshot reenviado es un no-op (RF-39).
- CL-18. Retiro de una unidad dividida en varias sucesoras (precedente: CSK → CZK y SKK): la Currency `inactive` lleva varios reemplazos; sin sucesión declarada de forma confiable, el conjunto queda vacío (D-17).
- CL-19. Currency `inactive` reactivada por snapshot: pasa a `active`, su conjunto de reemplazos queda vacío y se revalida la unicidad del código numérico entre activas (RF-3, RF-10).
- CL-20. Transición el mismo día (HRK termina 2023-01-01, EUR empieza 2023-01-01): no hay solapamiento ni hueco; la consulta del 2022-12-31 devuelve HRK y la del 2023-01-01, EUR (RF-44).
- CL-21. Monedas simultáneas con vigencias solapadas en un mismo Country (PA: PAB y USD): permitido; ninguna es principal (RF-45, D-10).
- CL-22. Misma Currency readoptada por el mismo Country tras una interrupción: dos asociaciones del mismo par con períodos no solapados, ambas `active`; períodos solapados del mismo par: rechazo (RF-45).
- CL-23. Asociación con inicio no declarado (la fuente solo sabe que está vigente): devuelve el período con inicio ausente y se considera vigente en cualquier fecha hasta su fin; con fin ausente, sin límite superior (RF-44, RF-48).
- CL-24. Asociación con inicio posterior a la fecha de referencia (futura): no aparece en las monedas actuales y sí en la consulta con fecha ≥ inicio y en el historial (RF-48, RF-49).
- CL-25. Fecha de referencia anterior a toda asociación del país, o país sin asociaciones: lista vacía; fecha mal formada: error de validación (RF-48).
- CL-26. Corrección de un período ya publicado (p. ej. fecha de fin errónea): el registro erróneo pasa a `inactive` y se publica uno nuevo; modificar el fin en el lugar se rechaza (RF-47).
- CL-27. Asociación `active` con vigencia cerrada cuya moneda está `inactive` (HR–HRK): válida y resoluble; una asociación `active` con vigencia abierta sobre una moneda `inactive` se rechaza (RF-19).
- CL-28. Pasa el tiempo y una vigencia con fin futuro termina: `status` no cambia y no se requiere snapshot; la asociación deja de aparecer en las consultas actuales por el cálculo de la vigencia (RF-51).

## Fuera de alcance

- Tasas de cambio, cotizaciones actuales o históricas, conversión monetaria, proveedores financieros.
- Contabilidad, precios, saldos, wallets, medios de pago, reglas tributarias.
- Configuración monetaria por tenant u organización (p. ej. moneda predeterminada, que pertenece a Tenants).
- Moneda principal de un país (D-10).
- Símbolos, símbolos estrechos, máscaras, separadores, formato monetario, pluralización y reglas de presentación (D-11, `CurrencyLocale` solo contiene el nombre).
- Intercambio y mercado: tipos de cambio, cotizaciones, bancos centrales, mercados, precios, saldos, wallets, contabilidad, proveedores FX y conversión monetaria (RF-8); pertenecen a otros dominios.
- Precarga de ISO 4217 List Three en v1 (D-8) y fechas de retiro propias de Currency (la vigencia temporal pertenece solo a CountryCurrency, D-18).
- Búsqueda por código numérico (D-12).
- Definir una política transversal de locales obligatorios (D-19 es solo de Currency v1).
- CRUD administrativo; diseño interno de PREP; formato físico del snapshot; pipeline común de versionado de catálogos.
- Modificar 001, 002 o 003 desde esta spec (dependencias cerradas y aprobadas).
- Cambios en otros repositorios.

## Criterios de aceptación

- CA-1. El catálogo cargado contiene exactamente las monedas de ISO 4217 List One de la edición declarada, salvo `XTS` y `XXX`, todas con `status = active` (RF-1, D-7, D-8). Mientras no exista el dataset real de PREP (S-9), se verifica contra un snapshot sintético sellado y marcado como no productivo; la verificación contra el dataset real queda pendiente y debe declararse.
- CA-2. Ningún registro de Currency, de sus localizaciones ni de CountryCurrency tiene `tenant_id` ni `organization_id`, y un mismo `currency_id` resuelve igual para cualquier consumidor (RF-1, RNF-4).
- CA-3. Intentar persistir un código alfabético repetido, un código numérico repetido entre activas, un código mal formado, unidades menores inválidas, un reemplazo en ciclo o en una Currency `active`, dos asociaciones `active` del mismo par con vigencias solapadas, una vigencia con inicio no anterior al fin o un `status` fuera de `active`/`inactive` falla en la persistencia, no solo en la aplicación (RF-3, RF-4, RF-6, RF-9, RF-17, RF-44, RF-45, RNF-5).
- CA-4. Resolver por `currency_id` y por código alfabético (`usd`, `USD`) devuelve el mismo registro con los campos de RF-29 (RF-22, RF-23, RF-29).
- CA-5. Un código inexistente devuelve "no encontrado", uno mal formado devuelve error de validación y una falla técnica simulada devuelve error técnico; los tres son distinguibles (RF-24, RF-25, RF-26).
- CA-6. Validar un `currency_id` `active`, `inactive` e inexistente devuelve `active`, `inactive` y `not_found`; `not_found` no aparece nunca como `status` de un registro (RF-9, RF-28).
- CA-7. EUR está asociada a varios países, PA a varias monedas, AQ devuelve lista vacía y XDR no tiene países (RF-18, RF-30, RF-31).
- CA-8. Country no tiene atributo de moneda y Currency no tiene atributo de país (RF-20).
- CA-9. Un snapshot que simula HRK → EUR conserva el `currency_id` de HRK, lo deja `inactive` con reemplazo EUR, cierra la vigencia de HR–HRK (queda `active`, historia) y HR queda asociado de forma vigente solo a EUR (RF-36, RF-38, RF-46, CL-8, CL-20).
- CA-10. Se rechaza sin cambios parciales en el catálogo Currency un snapshot de Currency que cambia un código de una Currency publicada, omite una Currency, localización o asociación, referencia un `country_id` inexistente, deja una asociación `active` sobre un registro `inactive`, repite una `snapshot_version` con otro digest, es anterior a la última o declara un digest que no coincide con el recalculado (RF-5, RF-19, RF-37, RF-39, RF-40, RF-41).
- CA-11. Incorporar dos veces el mismo snapshot (misma `snapshot_version` y digest) deja el catálogo observable idéntico (RF-39).
- CA-12. Una Currency sin nombre en algún locale obligatorio, o con una localización nueva en un locale `inactive`, impide incorporar el snapshot; una consulta con locale sin traducción devuelve el nombre ausente sin fallback (RF-13, RF-14, RF-15).
- CA-13. No existe operación pública de escritura para consumidores ni dato de cotización, tipo de cambio o saldo (RF-8, RF-34).
- CA-14. Las consultas funcionan sin conectividad a ISO, CLDR ni otra fuente externa, y la versión consultable coincide con la del snapshot aprobado y su procedencia (RF-32, RF-41, RF-42).
- CA-15. Incorporar después una moneda de List Three la agrega como `inactive` con `currency_id` nuevo, sin alterar las existentes (RF-43).
- CA-16. Con un snapshot sintético se resuelven ARS, USD y EUR por `currency_id` y por código alfabético, y se obtiene su nombre en `en` y en `es`; una Currency sin nombre en `en` o `es` impide incorporar el snapshot (RF-13, RF-22, RF-23, RF-29, D-19).
- CA-17. Las monedas actuales de un Country y los Country actuales de una Currency se obtienen con la fecha de referencia por defecto; PA devuelve PAB y USD simultáneamente y una Currency aparece en varios Country (RF-18, RF-30, RF-31, RF-45, CL-21).
- CA-18. La consulta por fecha de HR devuelve HRK el 2022-12-31 y EUR el 2023-01-01, sin hueco ni solapamiento; una fecha mal formada devuelve error de validación (RF-44, RF-48, CL-20, CL-25).
- CA-19. El historial de HR conserva HR–HRK (`active`, cerrada) y HR–EUR (`active`, abierta) tras incorporar la transición; ninguna asociación publicada desaparece y una vigencia cerrada no puede modificarse ni reabrirse (RF-7, RF-47, RF-49, CL-26).
- CA-20. `status` y vigencia son independientes: una asociación cerrada sigue `active`, una `inactive` no aparece en consultas por defecto y el transcurso del tiempo no cambia ninguna (RF-46, RF-51, CL-28).
- CA-21. Dos asociaciones `active` del mismo par con vigencias solapadas se rechazan en la persistencia y en el snapshot; dos monedas distintas solapadas en el mismo Country se aceptan (RF-45, RF-52, CL-21, CL-22).
- CA-22. Una Currency retirada (p. ej. HRK) sigue resoluble por `currency_id` y su validación devuelve `inactive`; reactivarla vacía sus reemplazos (RF-10, RF-22, RF-28, CL-8, CL-19).
- CA-23. Los datos publicados incluyen el código numérico con ceros a la izquierda; no existe consulta por código numérico en v1 (D-12, CL-3).
- CA-24. 001, 002 y 003 no fueron modificadas por 004 (diff de las rutas de esas features vacío respecto de `develop`) y Country no tiene dependencia hacia Currency (RF-20, RNF-6).

## Supuestos

- S-1. La lista ISO 4217 (List One y List Three) puede obtenerse de la publicación oficial de la agencia de mantenimiento (SIX), con licencia compatible; PREP la incorpora con procedencia.
- S-2. Los nombres en inglés provienen de ISO 4217 y los de otros locales de CLDR; la historia territorio–moneda proviene de CLDR (D-20). Todo se declara en la procedencia.
- S-3. 001 y 003 se aplican antes que este catálogo; sin ellos no hay `locale_id` ni `country_id` válidos.
- S-4. El canal técnico de los contratos, los nombres de campo, la forma física de las entidades, el formato de las identidades, los mecanismos de restricción y el de incorporación se deciden en el Plan, reutilizando lo que defina 003.
- S-5. El código numérico es único solo entre activas porque ISO lo ha reasignado (891: YUM → CSD); el alfabético, en cambio, queda ligado a una sola Currency (D-15). Si ISO reasignara alguna vez un código alfabético, incorporarlo requiere decisión explícita.
- S-6. La reactivación (`inactive` → `active`) se admite solo por snapshot aprobado y revisado (RF-10): la convención de 001 no la prohíbe, y una asociación país–moneda puede volver a declararse.
- S-7. Se usa "snapshot" (001, 002, README) en lugar de "dataset" (003) para el mismo concepto.
- S-8. La spec no exige una operación única entre snapshots de catálogos distintos. El orden de incorporación, la coordinación entre Countries y Currency y el mecanismo técnico que preserva RF-19 se deciden en el Plan. La atomicidad de RF-39 se refiere a un snapshot dentro de su propio catálogo. Restricción para el Plan: el mecanismo no puede introducir una dependencia de Countries hacia Currency ni obligar a que un snapshot de Countries conozca CountryCurrency (D-16, D-18 de 003, RNF-6); 003 solo declara que no hay FK hacia Currency (RNF-7 de 003).
- S-9. El dataset real (ISO 4217 List One, nombres, entidades ISO → Country) lo produce PREP, que no es accesible en este entorno (mismo caso que S-7 de 003). La feature se verifica con fixtures y un snapshot de ejemplo sintéticos, sellados y marcados como no productivos; el contenido real se incorpora en un cambio posterior. Esta spec define el contrato y el mecanismo.
- S-10. Los locales obligatorios de Currency v1 (RF-13, D-19) son los `locale_id` de `en` y `es`, decisión del responsable (F4), coherente con 002 (RF-31, S-7) y 003 (S-4). Se expresan por `locale_id` en una lista versionada en `gi-common-reference`, nunca como texto en el modelo. Es una regla propia de 004 v1; si 001 formalizara una política transversal distinta, adoptarla sería un cambio posterior de 004 y no bloquea esta feature.
- S-11. La fecha de referencia por defecto es el día calendario de la consulta; la zona horaria para determinarlo y el tipo físico de los extremos de vigencia los decide el Plan (D-18), sin cambiar la semántica de RF-44.

## Dependencias con otras specs

Todas cerradas. 001, 002 y 003 están aprobadas en `develop`; 004 las consume y no las modifica.

- DEP-1. **Locales obligatorios.** Cerrada por D-19 y S-10: Currency v1 exige `en` y `es` como regla propia, igual que 002 y 003 por separado. No depende de una política transversal de Locale y no bloquea el Plan. Una política transversal futura sería una mejora de gobernanza de 001, fuera de este Goal.

## Inconsistencias transversales históricas (clarify 2026-10-19, estado al 2026-10-31)

El detalle original (X-1 a X-8) se retira como ruido: verificado contra `develop`, ninguna bloquea 004 ni requiere trabajo sobre dependencias cerradas.

- X-1, X-2, X-3, X-4, X-8: resueltas en 003 (D-2, D-11, D-16, RF-31–RF-38, RF-6) antes de la aprobación; `currency_id` adopta UUID (D-5).
- X-5 (retirar un país con asociaciones activas): se resuelve dentro de 004 con RF-19 y RF-46; sin acción en 003. Restricción al Plan en S-8.
- X-6 (002 menciona que 003 depende de 004 «para CountryCurrency»): texto histórico de 002; CountryCurrency pertenece a 004 y Country no depende de Currency (D-16, RNF-6, D-18 de 003). Es una inexactitud documental de una spec cerrada, no bloquea ni se corrige desde 004.
- X-7: cerrada por DEP-1.

## Decisiones confirmadas por el responsable (clarify 4, 2026-10-31)

| Id | Decisión | Dónde se refleja |
|---|---|---|
| F1 | `status` = `active` \| `inactive`; `not_found` solo resultado de consulta; sin `is_active`/`enabled`/`state`/`vigente` | D-14, RF-9, Definiciones |
| F2 | `currency_id` UUID | D-5 |
| F3 | Reemplazo 0..N; reactivar limpia reemplazos | D-17, RF-6, RF-10, CL-18, CL-19 |
| F4 | Locales obligatorios de Currency v1: `en`, `es`; sin tocar 001 ni volverla política transversal | D-19, RF-13, S-10 |
| F5 | `CurrencyLocale` solo con el nombre; sin símbolos, máscaras ni formato | Modelo, D-11, Fuera de alcance |
| F6 | ISO 4217 autoridad primaria con procedencia | D-20, RF-41 |
| F7 | Código numérico publicado, sin búsqueda en v1; agregarla es aditivo | D-12, RNF-8 |
| F8, F9 | CountryCurrency pertenece a 004; N:N; sin unicidad por país; Country no depende de Currency | D-16, D-18, RF-17, RF-18, RNF-6 |
| F10 | Vigencia temporal separada de `status`; historia preservada | D-18, RF-44 a RF-52, CL-20 a CL-28 |
| F11 | CLDR como fuente complementaria (nombres, historia territorio–moneda) con procedencia; nunca redefine `country_id` | D-20, S-2, RF-40 |
| F12 | Sin exchange rates, cotizaciones, mercados, precios, saldos ni conversión | RF-8, Fuera de alcance |

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

## Registro de clarificación 3 (2026-10-31)

Detección contra `develop`, donde 001–003 están aprobadas y 003 se reconcilió el 2026-10-30/31 después del clarify anterior. Se verificaron las referencias cruzadas de esta spec (RF-14–22, RF-23–25, RF-31/32 de 001; RF-18, RF-19, RF-31, RF-33 de 002; RF-20–30, D-11, D-14, D-18 de 003).

- **Contradicción resuelta:** RF-39 admitía "reversión explícita"; 001 (S-18, RF-32) y 003 (S-6, RF-25) la eliminaron. RF-39 adopta las reglas A/B/C/D; RF-41, CA-10, CA-11 y CL-17 se alinean (D-2).
- **Requisito implícito:** RF-41 pasa a exigir `snapshot_version` entera positiva, digest recalculado, `currency_id` en cada Currency y rechazo de conflictos de fuente sin resolver (RF-27 a RF-29 de 003).
- **Reemplazo 0..N** (D-17, RF-6, RF-29, RF-38, CL-18) y su limpieza al reactivar (RF-10, CL-19).
- **Brecha:** RF-30 no ofrecía excluir fondos aunque CL-5 lo daba por hecho; agregado.
- **Dependencia desbloqueada:** DEP-1 ya no bloquea (S-10); RF-13 cubre además un conjunto con locale `inactive`.
- **Supuesto:** el dataset real de PREP no está disponible; verificación con fixtures sintéticos (S-9, CA-1).
- **Restricción al Plan:** RF-19 debe cumplirse sin dependencia de Country hacia Currency (S-8).
- **D-5 / X-4:** formato UUID por evidencia; X-1 a X-8 re-estadiadas.
- **D-12:** corregida la justificación obsoleta ("igual que D-14 de 003"); decisión mantenida y listada para confirmar.
- Sin cambios de numeración de RF/CA existentes; los elementos nuevos son D-17, S-9, S-10, CL-17 a CL-19.
- Nota de ejecución: esta pasada no pudo cargar `clarify.md` ni ejecutar `sdd validate` porque el lock apuntaba a un release no descargado; resuelto en el clarify 4.

## Registro de clarificación 4 (2026-10-31)

Ejecutada con la toolchain real (`ai-native` CLI v3.4.3, PLATFORM v3.4.3 tras sincronizar con `develop`). Integra las decisiones F1–F12 del responsable contra los contratos reales de 001–003 en `develop`.

- **Brecha cerrada:** CountryCurrency no tenía vigencia temporal ni distinguía historia de `status`; el modelo «a lo sumo una asociación por par» la impedía. Se agrega D-18, la sección «Vigencia temporal de CountryCurrency» (RF-44 a RF-52), HU-7, CL-20 a CL-28, CA-16 a CA-24 y S-11.
- **Efectos en requisitos previos:** RF-17, RF-18, RF-19, RF-30, RF-31, RF-38, CL-8, CL-13, CL-14, CA-3, CA-9 y RNF-5/7 se ajustan; la numeración de RF/CA existentes no cambia.
- **F4:** `en`/`es` pasa de valor provisional a regla propia de Currency v1 (D-19, RF-13, S-10, DEP-1).
- **F6, F11:** autoridad y fuente complementaria explicitadas (D-20).
- **F7:** el diferimiento de la búsqueda por código numérico queda confirmado (D-12).
- **Ruido retirado:** tabla X-1 a X-8 reducida a estado; «Decisiones para confirmar» sustituida por las decisiones confirmadas.
- **Fuera de este Goal:** cualquier `sdd-change` sobre 001, 002 o 003.

## Preguntas abiertas

Ninguna. Sin marcadores de aclaración pendientes propios de 004.
