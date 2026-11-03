# 005-units-of-measure — Catálogo global de unidades de medida y servicio de conversión

- **Estado:** aprobada e implementada; plan y tasks completos (spec + clarify autónomo 2026-11-02; ver «Registro de clarificación»). Merge pendiente de decisión humana.
- **Tipo:** Feature (spec del dominio Reference)
- **Depende de:** `001-locales` (identidad `locale_id`, convención de `status`, regla de localización RF-23–RF-25 de 001). Cerrada y aprobada: 005 la consume y no la modifica.
- **No depende de:** `002-regions-subregions`, `003-countries`, `004-currency` (sin dependencia funcional ni de datos).
- **Habilita:** cualquier módulo que necesite referenciar una unidad o convertir cantidades (agricultura, inventario, compras, ventas, logística, producción, laboratorio, activos, mantenimiento), como consumidores, nunca como dependencias.
- **Fuente:** brief arquitectónico 005 (2026-11-02).

## Contexto y objetivo

Ningún módulo de GI dispone de una referencia canónica de unidades de medida; cada consumidor terminaría definiendo sus propios códigos, símbolos, nombres y factores, con conversiones divergentes e inverificables.

Units of Measure es el catálogo **global y canónico** de magnitudes (QuantityKind) y unidades (UnitOfMeasure) de GI, propiedad exclusiva de `gi-common-reference`, más un **servicio de conversión** centralizado, determinista y verificable. Los consumidores almacenan identidades estables (`quantity_kind_id`, `unit_id`) y consumen contratos públicos de solo lectura; los códigos normativos (UCUM, UNECE Rec 20) son claves de interoperabilidad, no la identidad. El catálogo solo cambia mediante snapshots aprobados, versionados y trazables, y toda conversión es reproducible contra la versión del catálogo que la produjo.

## Usuarios

- **Módulos consumidores:** listan magnitudes y unidades, resuelven unidades, convierten cantidades y almacenan `unit_id` / `quantity_kind_id`.
- **Interfaces futuras (GeneXus, React, Angular, móviles):** consumen los mismos contratos para selectores, ingreso y conversión; no forman parte de esta spec.
- **Mantenedor del catálogo** (rol humano de `gi-common-reference`): revisa, aprueba e incorpora versiones.
- **PREP** (`gi-common-reference-prep`): produce snapshots candidatos con procedencia.

## Historias de usuario

- HU-1. Como consumidor, quiero listar las magnitudes y las unidades válidas de una magnitud para poblar selectores.
- HU-2. Como consumidor, quiero resolver una unidad por `unit_id`, y traducir un código UCUM o UNECE externo a `unit_id`, con su símbolo normativo y su nombre localizado.
- HU-3. Como consumidor, quiero convertir una cantidad entre dos unidades de una magnitud y recibir un resultado decimal exacto o con redondeo declarado, sin implementar factores propios.
- HU-4. Como consumidor, quiero que una conversión imposible o semánticamente ambigua (kg → L, temperatura absoluta vs. intervalo) se rechace con un error explícito.
- HU-5. Como consumidor, quiero reproducir una conversión pasada con la versión del catálogo que la produjo, aunque las definiciones hayan cambiado después.
- HU-6. Como mantenedor, quiero incorporar una nueva versión del catálogo (alta, retiro, corrección de nombres) con diff revisable, sin romper referencias ni alterar resultados históricos.

## Definiciones

- **QuantityKind (magnitud):** tipo de magnitud medible con semántica propia (Mass, Length, Temperature, TemperatureDifference…). Dos magnitudes pueden compartir dimensión física sin ser intercambiables (Density y MassConcentration; Length y VolumePerArea).
- **UnitOfMeasure (unidad):** unidad global única con identidad `unit_id`; puede aplicarse a más de una magnitud sin duplicar su identidad (°C en Temperature y en TemperatureDifference).
- **QuantityKindUnit (asociación):** aplicabilidad de una unidad a una magnitud, con la transformación hacia la unidad de referencia de esa magnitud y su propio `status`.
- **Unidad de referencia:** unidad canónica de una magnitud; toda transformación de la magnitud se expresa hacia ella.
- **Transformación:** `ref = (valor + desplazamiento) × factor`, con `factor > 0`; inversa `valor = ref / factor − desplazamiento`. Es **lineal** cuando el desplazamiento es 0 y **afín** cuando no.
- **Tipo de conversión de una magnitud:** `linear` (todas sus asociaciones tienen desplazamiento 0) o `affine` (admite desplazamientos; p. ej. temperatura absoluta).
- **Código UCUM:** código de la Unified Code for Units of Measure, sensible a mayúsculas, que identifica la unidad para intercambio informático (`Cel`, `kg/har`). No es el símbolo gráfico (`°C`) ni el nombre.
- **Código UNECE:** código de la UNECE Recommendation 20 (`KGM`, `CEL`), opcional.
- **Símbolo:** representación gráfica normativa de la unidad (`kg`, `°C`, `m²`); no se traduce.
- **`status`:** convención común de 001 (`active` | `inactive`). `active`: apta para conversiones nuevas y nuevas referencias. `inactive`: retirada; sigue resoluble por identidad para no romper referencias, no admite conversiones nuevas.
- **Versión del catálogo:** `snapshot_version` del snapshot aplicado; cada conversión declara la versión usada.
- **Conversión nueva / histórica:** nueva = sin versión explícita, contra la versión vigente; histórica = con una versión incorporada explícita, contra las definiciones conservadas de esa versión.
- **Snapshot / publicado:** mismo significado que en 001–004 (dataset completo aprobado y versionado).

## Decisiones

### Heredadas (AGENTS.md, 001–004)

- D-1. El catálogo es GLOBAL, sin `tenant_id` ni `organization_id`, propiedad única de `gi-common-reference`.
- D-2. Sin CRUD para consumidores; el catálogo solo cambia mediante snapshots aprobados con las propiedades de incorporación de 001 y 004: `snapshot_version` entera positiva, digest de contenido recalculado, clasificación A/B/C/D contra el historial, atomicidad, idempotencia, sin reversión.
- D-3. Los consumidores integran por contrato (identidades y API), nunca por FK inter-repositorio ni estructuras internas.
- D-4. Los textos traducibles se representan como localizaciones asociadas a Locale (RF-23–RF-25 de 001), sin fallback a otro locale; la entidad principal no tiene nombres.
- D-5. Identidades UUID asignadas una sola vez y registradas en el snapshot aprobado (como `locale_id`, `country_id`, `currency_id`); el sistema nunca las genera.

### Tomadas por esta spec

- D-6. **Modelo mínimo de cinco entidades y un servicio.** QuantityKind, UnitOfMeasure, QuantityKindUnit, QuantityKindLocale, UnitOfMeasureLocale y el servicio de conversión. No se persisten pares de conversión ni matrices de factores: toda conversión pasa por la unidad de referencia de la magnitud.
- D-7. **Toda conversión exige magnitud explícita.** El consumidor indica `quantity_kind_id`; ambas unidades deben estar asociadas a ella. No se infiere la magnitud: la igualdad dimensional no autoriza conversiones (Density ≠ MassConcentration) y la misma unidad puede tener transformaciones distintas según la magnitud (°C absoluta vs. intervalo).
- D-8. **Transformaciones lineales y afines solamente**, con factor racional exacto positivo y desplazamiento decimal exacto. El desplazamiento solo existe en magnitudes `affine`; en una magnitud `linear` todo desplazamiento es 0. Por eso un intervalo de temperatura nunca recibe desplazamiento (RF-21).
- D-9. **Aritmética racional exacta y un único redondeo final.** El cálculo es exacto (sin `float` binario ni redondeo intermedio); el resultado se entrega exacto cuando su expansión decimal cabe en la precisión del contrato y, si no, redondeado una sola vez a 34 dígitos significativos con redondeo al par (half-even, precisión de decimal128 IEEE 754), indicando si es exacto.
- D-10. **Representación textual única de factores y desplazamientos.** Cada factor y desplazamiento tiene una sola forma canónica (RF-13), de modo que igualdad de texto ⇔ igualdad de valor, el digest es estable y el diff no muestra cambios espurios.
- D-11. **Versionado por snapshots existentes, sin mecanismo nuevo.** Cada snapshot incorporado se conserva íntegro e inmutable (como en 001–004); una conversión histórica usa las definiciones de esa versión. No se crean tablas de historia por entidad.
- D-12. **Validación UCUM con verificación cruzada.** Un código UCUM se valida por sintaxis y contra la tabla oficial de prefijos y átomos UCUM (`ucum-essence.xml`, versión fijada y verificada por digest, redistribuida **sin modificar** con su aviso de licencia, porque la licencia UCUM prohíbe obras derivadas); además se calcula desde el código la dimensión y la escala (y el desplazamiento de las unidades especiales admitidas, `Cel` y `[degF]`) y deben coincidir con la transformación declarada. Un átomo arbitrario, una unidad especial no admitida o un átomo inexistente rechaza el snapshot; actualizar la tabla es un cambio revisado de este repositorio. No es un intérprete de expresiones UCUM arbitrarias para convertir (fuera de alcance): la conversión usa solo definiciones del catálogo.
- D-13. **Unidad de referencia por asociación validada, inmutable.** Cada magnitud declara exactamente una unidad de referencia, que debe ser una asociación de esa magnitud con factor 1 y desplazamiento 0. La unidad de referencia y el tipo de conversión de una magnitud publicada no cambian: cambiarlos alteraría todos sus factores y se expresa como una magnitud nueva.
- D-14. **Códigos ligados a una sola unidad.** Un código UCUM o UNECE pertenece a una única unidad en todo el catálogo, incluidas las inactivas; una vez publicado no cambia ni se reasigna (puede completarse una vez si estaba ausente). El código de una magnitud es único e inmutable.
- D-15. **Localización con nombre y plural.** UnitOfMeasureLocale contiene nombre singular obligatorio y plural opcional; QuantityKindLocale, solo nombre. Formas plurales adicionales (categorías CLDR) quedan fuera de v1 y son aditivas.
- D-16. **Locales obligatorios de Units v1: `en` y `es`**, por `locale_id` en una lista versionada propia de este catálogo (mismo criterio que D-19 de 004); no es una política transversal de Locale.
- D-17. **Autoridad y fuentes.** Definiciones y factores: BIPM SI Brochure y NIST SP 811 (ISO 80000-1 como marco conceptual); códigos: UCUM (primario) y UNECE Rec 20 (opcional); nombres localizados: fuente declarada por PREP (p. ej. CLDR). PREP registra la procedencia por rol de fuente (nombre, edición, fecha de obtención, ubicación, verificación de integridad, licencia). QUDT es referencia conceptual, no fuente de datos.
- D-18. **Versionado independiente** del catálogo Units, validado contra la versión aplicada de Locale (como D-13 de 004).
- D-19. **Errores con códigos estables** dentro de la convención de las APIs existentes (sobre común, códigos en inglés minúscula, sin mensajes localizados); no se introduce un framework de errores nuevo.

## Modelo funcional

Atributos conceptuales. Nombres de campo de los contratos (salvo identidades y `status`), tipos y mecanismos físicos se deciden en el Plan.

### QuantityKind

| Atributo | Significado | Obligatorio | Unicidad | Estabilidad |
|---|---|---|---|---|
| `quantity_kind_id` | Identidad GI | Sí | Global | Inmutable |
| Código | Identificador textual estable (`mass`, `temperature_difference`) | Sí | Global | Inmutable (D-14) |
| Tipo de conversión | `linear` / `affine` (D-8) | Sí | — | Inmutable (D-13) |
| Unidad de referencia | Una asociación propia con factor 1 y desplazamiento 0 | Sí | Exactamente una | Inmutable (D-13) |
| `status` | `active` / `inactive` | Sí | — | Solo por snapshot |

### UnitOfMeasure

| Atributo | Significado | Obligatorio | Unicidad | Estabilidad |
|---|---|---|---|---|
| `unit_id` | Identidad GI | Sí | Global | Inmutable |
| Código UCUM | Sintaxis y mayúsculas UCUM preservadas | No (cuando corresponda) | Global, incluidas inactivas | Inmutable una vez fijado (D-14) |
| Código UNECE | Rec 20 | No | Global, incluidas inactivas | Inmutable una vez fijado (D-14) |
| Símbolo | Símbolo normativo visible, no traducible | Sí | — | Solo por snapshot |
| `status` | `active` / `inactive` | Sí | — | Solo por snapshot |

### QuantityKindUnit

| Atributo | Significado | Obligatorio | Estabilidad |
|---|---|---|---|
| `quantity_kind_id`, `unit_id` | Par único | Sí | Inmutables |
| Factor | Racional exacto > 0 en forma canónica | Sí | Solo por snapshot, con diff |
| Desplazamiento | Decimal exacto en forma canónica; 0 en magnitudes `linear` | Sí | Solo por snapshot, con diff |
| `status` | `active` / `inactive` | Sí | Solo por snapshot |

### Localizaciones

- QuantityKindLocale: (magnitud, locale) → nombre; a lo sumo una por par.
- UnitOfMeasureLocale: (unidad, locale) → nombre singular y plural opcional; a lo sumo una por par.

## Requisitos funcionales

### Identidad e integridad

- RF-1. EL SISTEMA DEBERÁ mantener magnitudes, unidades, asociaciones y localizaciones como catálogo global, sin `tenant_id`, `organization_id` ni partición por tenant, organización o módulo.
- RF-2. EL SISTEMA DEBERÁ dar a cada magnitud y a cada unidad una identidad UUID estable, global e inmutable, que no se reasigna ni se reutiliza y no depende de códigos, símbolos, nombres ni `status`.
- RF-3. EL SISTEMA DEBERÁ impedir que dos unidades compartan código UCUM o código UNECE, y que dos magnitudes compartan código, incluidas las `inactive` (D-14).
- RF-4. EL SISTEMA DEBERÁ rechazar un código de magnitud que no sea ASCII minúscula con dígitos y guion bajo (`^[a-z][a-z0-9_]{1,63}$`), un código UNECE que no sean 2 o 3 caracteres latinos mayúsculos o dígitos, un símbolo vacío o con espacios en los bordes, y un código UCUM inválido según RF-15.
- RF-5. SI un snapshot cambia un código publicado de una unidad o magnitud, asigna un código publicado a otra identidad, o cambia el tipo de conversión o la unidad de referencia de una magnitud publicada, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo; completar un código UCUM o UNECE ausente se admite una única vez.
- RF-6. EL SISTEMA NO DEBERÁ eliminar nunca una magnitud, unidad, asociación, localización ni snapshot publicados; un retiro se expresa con `status = inactive`.
- RF-7. EL SISTEMA DEBERÁ registrar el estado de magnitudes, unidades y asociaciones solo como `status` = `active` | `inactive`, sin otro atributo con esa semántica, y cambiarlo solo por snapshot aprobado con el cambio visible en el diff.
- RF-8. EL SISTEMA DEBERÁ garantizar que cada magnitud tenga exactamente una unidad de referencia, que sea una asociación de esa magnitud con factor 1 y desplazamiento 0, y que, si la magnitud está `active`, esa asociación y esa unidad también lo estén.
- RF-9. EL SISTEMA NO DEBERÁ incluir en este catálogo equivalencias dependientes de productos o envases (bolsa de 25 kg, caja de 12, pallet), conversiones monetarias, tipos de cambio ni datos por cliente.

### Asociaciones y transformaciones

- RF-10. EL SISTEMA DEBERÁ representar la aplicabilidad de una unidad a una magnitud solo mediante una asociación única por par (magnitud, unidad), con integridad referencial garantizada, y permitir que una misma unidad se asocie a varias magnitudes sin duplicar su identidad.
- RF-11. EL SISTEMA DEBERÁ definir cada asociación con un factor racional exacto mayor que 0 y un desplazamiento decimal exacto, según `ref = (valor + desplazamiento) × factor`.
- RF-12. SI una magnitud es `linear`, ENTONCES EL SISTEMA DEBERÁ exigir desplazamiento 0 en todas sus asociaciones; solo una magnitud `affine` admite desplazamientos distintos de 0.
- RF-13. EL SISTEMA DEBERÁ exigir la forma canónica de factores y desplazamientos: decimal sin ceros a la izquierda innecesarios ni ceros finales en la parte fraccionaria, sin signo `+`, sin exponente y sin `-0`; un factor no decimal finito se escribe como fracción `p/q` de enteros positivos coprimos con `q > 1`, y solo si su expansión decimal no termina. El desplazamiento es siempre decimal.
- RF-14. EL SISTEMA NO DEBERÁ persistir conversiones individuales, pares de conversión ni matrices de factores entre unidades.

### Códigos UCUM y UNECE

- RF-15. CUANDO se incorpore un snapshot, EL SISTEMA DEBERÁ validar cada código UCUM presente: sintaxis UCUM (términos con `.` y `/`, exponentes enteros, paréntesis, anotaciones `{…}`, factores enteros), sensibilidad a mayúsculas, prefijos y átomos existentes en la tabla UCUM versionada del sistema, prefijos solo sobre átomos métricos, y unidades especiales (con desplazamiento, como `Cel` y `[degF]`) solo como término único sin prefijo de escala ni exponente; SI no cumple, ENTONCES DEBERÁ rechazar el snapshot completo (D-12).
- RF-16. CUANDO una asociación tenga unidad y unidad de referencia con código UCUM, EL SISTEMA DEBERÁ verificar que la dimensión calculada desde ambos códigos coincida, que el factor declarado sea igual a la razón de sus escalas UCUM y que el desplazamiento declarado sea el de la unidad especial en una magnitud `affine` y 0 en una `linear`; SI no coincide, ENTONCES DEBERÁ rechazar el snapshot completo.
- RF-17. EL SISTEMA DEBERÁ conservar el código UCUM tal como fue publicado (sin normalizar mayúsculas ni sintaxis) y NO DEBERÁ derivarlo del símbolo.

### Localización

- RF-18. EL SISTEMA DEBERÁ representar los nombres de magnitudes y unidades como localizaciones asociadas a un Locale existente, a lo sumo una por par (entidad, Locale), con integridad referencial garantizada; nombres y plurales no vacíos ni con espacios en los bordes.
- RF-19. EL SISTEMA DEBERÁ exigir nombre en `en` y `es` para cada magnitud y unidad publicada (D-16); SI alguno de esos locales no existe o está `inactive` en el Locale aplicado, o una localización nueva usa un locale inexistente o `inactive`, ENTONCES DEBERÁ rechazar el snapshot; las localizaciones publicadas cuyo locale pase después a `inactive` se conservan.
- RF-20. CUANDO una consulta indique un locale, EL SISTEMA DEBERÁ devolver el nombre (y el plural, si existe) en ese locale o el nombre ausente, sin fallback a otro locale; SI el locale no existe o está mal formado, ENTONCES DEBERÁ devolver un error de validación. El símbolo y los códigos nunca cambian por locale.

### Conversión

- RF-21. CUANDO un consumidor solicite convertir un valor indicando magnitud, unidad origen y unidad destino, EL SISTEMA DEBERÁ calcular `valor_destino = ((valor + desp_origen) × factor_origen) / factor_destino − desp_destino` con las asociaciones de esa magnitud, sin redondeo intermedio, y devolver el resultado con la unidad destino y la versión del catálogo usada.
- RF-22. SI la magnitud no se indica, ENTONCES EL SISTEMA DEBERÁ rechazar la conversión por contexto semántico insuficiente, sin inferirla (D-7).
- RF-23. SI alguna de las unidades no está asociada a la magnitud indicada, ENTONCES EL SISTEMA DEBERÁ rechazar la conversión como incompatible, aunque las unidades compartan dimensión física (kg → L; kg/m³ → g/L como Density).
- RF-24. SI la magnitud o una unidad no existe en la versión usada, ENTONCES EL SISTEMA DEBERÁ rechazar la conversión con un error que distinga magnitud inexistente de unidad inexistente.
- RF-25. SI la magnitud, una unidad o una de sus asociaciones está `inactive` en la versión usada, ENTONCES EL SISTEMA DEBERÁ rechazar la conversión; una conversión nueva nunca reactiva una unidad retirada.
- RF-26. EL SISTEMA DEBERÁ aceptar el valor solo como texto decimal inequívoco (signo `-` opcional, hasta 30 dígitos enteros y hasta 30 fraccionarios, sin exponente, separador de miles, espacios ni valores especiales) y rechazar cualquier otra forma, incluido un número JSON, como valor inválido.
- RF-27. EL SISTEMA DEBERÁ devolver el resultado como texto decimal canónico (sin exponente, sin ceros fraccionarios finales, `0` para cero) exacto cuando el valor racional exacto tiene a lo sumo 34 dígitos significativos y, si no, redondeado una única vez a 34 dígitos significativos con redondeo al par, indicando en la respuesta si el resultado es exacto (D-9).
- RF-28. SI el resultado tiene valor absoluto mayor o igual que 10^40, o es distinto de cero con valor absoluto menor que 10^-40, ENTONCES EL SISTEMA DEBERÁ rechazar la conversión como no representable, nunca truncarla a 0 ni a infinito.
- RF-29. CUANDO un consumidor indique una versión del catálogo, EL SISTEMA DEBERÁ convertir con las definiciones y estados de esa versión; SI la versión no fue incorporada (o el catálogo está vacío), ENTONCES DEBERÁ rechazar la conversión como versión no disponible. Sin versión, usa la vigente.
- RF-30. EL SISTEMA DEBERÁ producir, para el mismo valor, magnitud, unidades y versión, siempre el mismo resultado, sin depender del reloj, del entorno ni del orden de las solicitudes.
- RF-31. EL SISTEMA DEBERÁ resolver una conversión sin escribir en la persistencia y sin acceder a fuentes externas; puede reutilizar en memoria las definiciones de una versión, porque una versión incorporada es inmutable.

### Contratos de consulta

- RF-32. CUANDO un consumidor liste magnitudes, EL SISTEMA DEBERÁ devolver por defecto solo las `active`, en orden determinístico por código, con opción de incluir `inactive`, de filtrar por código y de pedir nombres en un locale.
- RF-33. CUANDO un consumidor resuelva una magnitud por `quantity_kind_id`, EL SISTEMA DEBERÁ devolverla con código, tipo de conversión, unidad de referencia, `status` y nombre según RF-20, sea `active` o `inactive`; inexistente → "no encontrado"; identidad mal formada → error de validación.
- RF-34. CUANDO un consumidor liste unidades, EL SISTEMA DEBERÁ devolver por defecto solo las `active`, en orden determinístico, con filtros por magnitud (solo unidades con asociación `active` a ella salvo que pida inactivas), por código UCUM (exacto, sensible a mayúsculas), por código UNECE y por estado, y nombres en un locale; una magnitud inexistente en el filtro → "no encontrado".
- RF-35. CUANDO un consumidor resuelva una unidad por `unit_id`, EL SISTEMA DEBERÁ devolverla con código UCUM, código UNECE, símbolo, `status`, nombre y plural según RF-20, y sus asociaciones (magnitud, `status`, si es la referencia de la magnitud), sea `active` o `inactive`; inexistente → "no encontrado"; mal formada → error de validación.
- RF-36. EL SISTEMA DEBERÁ permitir consultar la versión aplicada del catálogo.
- RF-37. EL SISTEMA DEBERÁ distinguir en todos los contratos: resultado exitoso, "no encontrado", entrada inválida (con código estable por causa) y error técnico; una falla técnica nunca se presenta como "no encontrado" ni como entrada inválida.
- RF-38. EL SISTEMA NO DEBERÁ exponer a los consumidores operaciones de alta, modificación ni baja del catálogo; la conversión es un cálculo sin efectos persistentes.
- RF-39. EL SISTEMA DEBERÁ versionar cada contrato público; agregar campos o consultas es compatible, y quitar o cambiar el significado de un campo requiere nueva versión mayor con análisis de migración.
- RF-40. EL SISTEMA DEBERÁ ser independiente de cualquier tecnología de presentación: los contratos no contienen formato visual, máscaras ni texto de interfaz más allá de nombres localizados y símbolos.

### Ciclo de vida e incorporación de snapshots

- RF-41. EL SISTEMA DEBERÁ aceptar solo snapshots con `snapshot_version` entera positiva, contenido completo del catálogo (magnitudes, unidades, asociaciones, localizaciones), identidades para cada entidad, digest de contenido que el sistema recalcula, procedencia por rol de fuente (definiciones, UCUM, nombres y, si hay códigos UNECE, UNECE) con nombre, edición, fecha de obtención, ubicación, verificación de integridad y licencia, y conflictos de fuente resueltos; SI falta algo, el digest no coincide o hay conflictos sin resolver, ENTONCES DEBERÁ rechazarlo completo.
- RF-42. EL SISTEMA DEBERÁ clasificar cada snapshot contra el historial antes de cualquier otra validación (reglas A/B/C/D de 001): A) misma versión y digest, no-op; B) misma versión y otro digest, rechazo; C) versión no incorporada anterior a la última, rechazo; D) posterior, continúa.
- RF-43. SI un snapshot omite una magnitud, unidad, asociación o localización publicada, ENTONCES EL SISTEMA DEBERÁ rechazarlo completo.
- RF-44. EL SISTEMA DEBERÁ incorporar cada snapshot de forma atómica (todo o nada) e idempotente, crear lo nuevo, actualizar lo modificado, conservar las identidades publicadas y conservar el snapshot íntegro e inmutable para conversiones históricas (D-11).
- RF-45. EL SISTEMA DEBERÁ ofrecer, antes de aprobar, un diff legible y de solo lectura contra la versión aplicada: altas, cambios de `status`, de símbolo, de códigos completados, de factores y desplazamientos (valor anterior y nuevo) y de nombres.
- RF-46. EL SISTEMA DEBERÁ registrar, para cada versión incorporada, su digest, procedencia, versión de Locale contra la que se validó y fecha de incorporación.

## Requisitos no funcionales

- RNF-1. Reproducibilidad: el mismo snapshot produce el mismo catálogo y las mismas identidades en cualquier entorno; la misma solicitud de conversión con la misma versión produce el mismo resultado byte a byte.
- RNF-2. Trazabilidad: toda conversión declara la versión usada y toda versión es rastreable a su snapshot, digest y procedencia.
- RNF-3. Las consultas y conversiones requieren solo lectura; la escritura queda restringida al proceso de incorporación controlado.
- RNF-4. Las invariantes estructurales (RF-2 a RF-8, RF-10 a RF-13, RF-18) se protegen en la persistencia y no solo en código de aplicación (AGENTS.md); el mecanismo se decide en el Plan.
- RNF-5. Dirección de dependencias: Units depende solo de Locale; Locale, Regions, Countries y Currency no dependen de Units, y Units no depende de ellos salvo Locale.
- RNF-6. Rendimiento: una conversión no escribe en la base; las definiciones de una versión se cargan una vez y se reutilizan en memoria; sin consultas repetitivas innecesarias por solicitud.
- RNF-7. Simplicidad: sin microservicios, colas, contenedores de runtime, motores algebraicos ni tablas o procesos sin requisito que los justifique.
- RNF-8. Extensibilidad compatible: agregar unidades, magnitudes, átomos UCUM, códigos UNECE, formas plurales o exponer factores en la API es aditivo y no cambia identidades ni el significado de los contratos existentes.

## Casos límite

- CL-1. °C en Temperature (afín, desplazamiento 273.15) y en TemperatureDifference (lineal, desplazamiento 0): una sola identidad, dos asociaciones; 0 °C → 273.15 K como temperatura; 1 °C → 1 K como intervalo.
- CL-2. °F: 32 °F → 0 °C (temperatura); factor 5/9 no decimal finito expresado como fracción; 1 °F → K (intervalo) = 5/9 K → resultado redondeado y no exacto.
- CL-3. km/h → m/s: factor 5/18; 36 km/h → 10 m/s exacto; 1 km/h → 0.2777…8 (34 dígitos, no exacto).
- CL-4. Density vs MassConcentration comparten dimensión: kg/m³ en ambas; g/L solo en MassConcentration; kg/m³ → g/L como Density se rechaza, como MassConcentration da el mismo número.
- CL-5. Count vs DimensionlessRatio: `%` es razón adimensional; la unidad de conteo no pertenece a DimensionlessRatio ni `%` a Count; convertir entre ellas se rechaza.
- CL-6. Meses y años calendario no se incluyen en Duration (no son duraciones fijas).
- CL-7. Valor negativo (−40 °C → −40 °F), cero, `-0` (→ `0`), 30 dígitos enteros y 30 fraccionarios: aceptados; `1e3`, `+1`, `1,5`, `.5`, `5.`, `007`, ` 1`, `NaN`, `Infinity`, cadena vacía, número JSON: inválidos.
- CL-8. Resultado fuera de rango (≥ 10^40 o < 10^-40 distinto de 0): rechazado como no representable.
- CL-9. Ida y vuelta: convertir y volver da el valor original exactamente si ambas conversiones son exactas; si alguna redondea, la diferencia no supera la cota de esos redondeos (medio ulp a 34 dígitos significativos de cada resultado redondeado, propagado a la unidad original por la transformación exacta).
- CL-10. Unidad retirada: resoluble por `unit_id` con `status = inactive`; conversión nueva rechazada; conversión histórica con una versión en la que estaba `active` reproduce el resultado de entonces.
- CL-11. Corrección de factor de una unidad sin UCUM (o con tabla UCUM actualizada) en una versión posterior: la versión anterior sigue produciendo el resultado anterior; la nueva produce el nuevo; el diff muestra ambos valores.
- CL-12. Código UCUM mal formado (`kg//m`), con mayúsculas incorrectas (`KG`), átomo desconocido, prefijo sobre átomo no métrico (`k[lb_av]`), unidad especial compuesta (`Cel/s`) o con factor declarado que no coincide con UCUM: snapshot rechazado.
- CL-13. Mismo código UCUM en dos unidades, o el de una unidad publicada asignado a otra: rechazado.
- CL-14. Locale válido sin traducción: nombre ausente, sin fallback; locale mal formado o inexistente: error de validación.
- CL-15. Catálogo vacío: listas vacías, versión `null`, "no encontrado" por identidad y conversión rechazada como versión no disponible; nunca error técnico.
- CL-16. Mismo snapshot reenviado: no-op; misma versión con otro digest o versión anterior: rechazado.
- CL-17. Magnitud con una sola unidad (la de referencia): conversión de identidad devuelve el mismo valor normalizado.
- CL-18. Conversión de una unidad a sí misma en cualquier magnitud: devuelve el valor normalizado, exacto.

## Fuera de alcance

- UI/UX, CRUD administrativo, conversiones monetarias y tipos de cambio.
- Conversiones dependientes de productos, envases, densidad, humedad o composición (pertenecen a los dominios consumidores).
- Motor algebraico universal, interpretación de expresiones UCUM arbitrarias para convertir, análisis dimensional general.
- Transformaciones logarítmicas o no lineales (pH, dB, Np) y escalas no afines.
- Duraciones calendáricas (meses, años) y operaciones con fechas.
- Incertidumbre de medición, cifras significativas de la medición, validación de rangos físicos (p. ej. temperaturas bajo el cero absoluto).
- Telemetría, adquisición de mediciones y persistencia de conversiones.
- Exponer factores y desplazamientos en la API pública (posible extensión aditiva, RNF-8).
- Diseño interno de PREP y del pipeline de datos; cambios en otros repositorios.
- Modificar 001–004.

## Criterios de aceptación

Funcionales (brief §13), ejecutados por la API pública contra un catálogo incorporado por la CLI en PostgreSQL real:

- CA-1. 1000 g → kg = `1`; 1 t → kg = `1000`; 1 ha → m² = `10000`; 1 m³ → L = `1000`; 1 h → min = `60` (RF-21, RF-27).
- CA-2. 0 °C → K como Temperature = `273.15`; 32 °F → °C como Temperature = `0`; 1 °C → K como TemperatureDifference = `1` (RF-12, CL-1, CL-2).
- CA-3. 150 kg/ha → g/m² como MassPerArea = `15` (RF-21).
- CA-4. kg → L se rechaza como incompatible; una conversión con unidades de magnitudes distintas se rechaza; una conversión sin magnitud se rechaza por contexto insuficiente (RF-22, RF-23, CL-4, CL-5).
- CA-5. Una unidad `inactive` en la versión vigente rechaza la conversión nueva y la misma conversión con la versión anterior, donde estaba `active`, devuelve el resultado de entonces (RF-25, RF-29, CL-10).
- CA-6. Un snapshot con un código UCUM incorrecto (cada forma de CL-12) se rechaza al incorporar, sin cambios parciales (RF-15, RF-16).
- CA-7. Una conversión histórica con versión explícita es reproducible: el mismo resultado byte a byte antes y después de incorporar una versión que cambia el factor (RF-29, RF-30, CL-11).
- CA-8. Ida y vuelta consistentes según CL-9 sobre todos los pares de unidades de cada magnitud del catálogo de prueba (RF-27, CL-9).

Adicionales:

- CA-9. Integridad en la persistencia: código UCUM/UNECE/magnitud repetido, magnitud sin referencia o con dos, referencia con factor ≠ 1 o desplazamiento ≠ 0, desplazamiento ≠ 0 en magnitud `linear`, factor o desplazamiento no canónico, factor ≤ 0, asociación con unidad o magnitud inexistente, `status` fuera de `active`/`inactive`, cambio de identidad o de código publicado, cambio de referencia o tipo de conversión, borrado de cualquier fila: fallan en la persistencia, no solo en la aplicación (RNF-4).
- CA-10. Identidades estables: reincorporar y avanzar de versión conserva todas las identidades; dos bases con el mismo snapshot exponen el mismo catálogo (RF-2, RNF-1).
- CA-11. Localización: nombres `en`/`es` presentes; locale sin traducción → nombre `null` sin fallback; locale inválido → error de validación; falta de `en` o `es` o locale nuevo `inactive` → snapshot rechazado (RF-18–RF-20).
- CA-12. Sin duplicados: ninguna unidad aparece dos veces en el catálogo; °C es una sola identidad asociada a dos magnitudes con transformaciones distintas (RF-10, CL-1).
- CA-13. Exactitud de factores: cada asociación con UCUM coincide con la escala calculada; los factores exactos se conservan exactos (`0.45359237`, `5/9`, `5/18`); el redondeo half-even a 34 dígitos se verifica con casos en el límite (RF-13, RF-16, RF-27).
- CA-14. Versionado y cambios incrementales: reenvío no-op; misma versión con otro digest y versión anterior rechazadas; versión posterior con alta, retiro y cambio de factor aplicada con diff que lo muestra; omisión de una entidad publicada rechazada (RF-41–RF-45).
- CA-15. Contratos API: OpenAPI publicado = generado; todos los endpoints; 404 vs 422 (con su código) vs 503; métodos de escritura → 405; ninguna respuesta con `tenant_id`; catálogo vacío sin error técnico (RF-32–RF-40, CL-15).
- CA-16. Valores: casos válidos e inválidos de CL-7 y fuera de rango de CL-8 (RF-26, RF-28).
- CA-17. Dependencias: Units no importa ni referencia Regions, Countries ni Currency; 001–004 no fueron modificadas (diff de sus rutas vacío respecto de `develop`) (RNF-5).
- CA-18. Datos reales: el catálogo inicial de PREP, con procedencia real, se incorpora y supera la verificación UCUM. Mientras PREP no lo produzca (S-3), se verifica el mecanismo con un snapshot de ejemplo sellado, marcado como no productivo, y la parte de contenido real queda **diferida y declarada**, nunca contada como PASS.

## Supuestos

- S-1. 001 se aplica antes que este catálogo; sin él no hay `locale_id` válidos.
- S-2. El canal técnico, nombres de campo, forma física, tipos y mecanismos de restricción se deciden en el Plan, reutilizando las convenciones de 004.
- S-3. PREP (`gi-common-reference-prep`) no es accesible en este entorno (mismo caso que S-9 de 004). Esta feature define el contrato del snapshot y el mecanismo; el repositorio contiene un snapshot de ejemplo con valores normativos verificados por la tabla UCUM (RF-16) pero marcado como no productivo. El primer snapshot productivo lo publica PREP en un cambio posterior.
- S-4. La tabla UCUM es el archivo oficial `ucum-essence.xml` v2.2 (revisión 2024-06-17, obtenido de `github.com/ucum-org/ucum`, sha256 `dfccea1b…0b61`), usado sin modificar bajo la UCUM License v1.1 (redistribución con aviso de copyright y licencia). Las funciones de las unidades especiales admitidas (`Cel`: x + 273.15 K; `[degF]`: 5/9 (x + 459.67) K) se toman de la especificación UCUM y de NIST SP 811 porque el XML solo nombra la función.
- S-5. La precisión de 34 dígitos significativos (decimal128) cubre con margen las necesidades de los consumidores previstos; aumentarla es un cambio de contrato compatible solo si se agrega como opción.
- S-6. Catálogo inicial (selección, D-17): Mass (kg ref, g, mg, t, lb, oz), Length (m ref, mm, cm, km, in, ft, mi), Area (m² ref, cm², km², ha), Volume (m³ ref, cm³, mL, L, US gal), Duration (s ref, min, h, d, wk), Temperature (K ref, °C, °F), TemperatureDifference (K ref, °C, °F), Speed (m/s ref, km/h, mph), Density (kg/m³ ref, g/cm³, kg/L), MassConcentration (kg/m³ ref, g/L, mg/L), MassPerArea (kg/m² ref, g/m², kg/ha, t/ha), VolumePerArea (m³/m² ref, L/ha, mL/m²), Count (unidad «each» ref), DimensionlessRatio (`1` ref, %, ‰, ppm). Ajustarla es un cambio de datos de PREP, no de esta spec.

## Dependencias con otras specs

- DEP-1. 001-locales (cerrada): `locale_id` y la convención de localización. Única dependencia real.
- Sin dependencia con 002, 003 ni 004; verificado por CA-17.

## Registro de clarificación (2026-11-02, autónomo)

Resuelto con evidencia del repositorio y del brief, sin preguntas al responsable (ninguna decisión crítica abierta):

- **Magnitud obligatoria en la conversión (D-7):** el brief la incluye en la entrada y exige validar explícitamente la magnitud; inferirla haría ambigua la conversión de °C. Contexto insuficiente = magnitud ausente (RF-22).
- **Forma de la transformación (D-8, RF-11):** `(v + desp) × factor` permite desplazamientos decimales exactos (273.15, 459.67) con factor racional (5/9); la forma `v × f + d` exigiría desplazamientos periódicos para °F.
- **Factores racionales (RF-13):** 5/9 (°F) y 5/18 (km/h) no son decimales finitos; un decimal truncado violaría la exactitud exigida.
- **Precisión (D-9, RF-26–RF-28):** decimal128 (34 dígitos), half-even, un único redondeo final, límites explícitos de entrada y salida y bandera de exactitud.
- **Historia (D-11):** se reutiliza la conservación íntegra e inmutable de snapshots de 001–004; no se crea un mecanismo de versionado nuevo.
- **Validación UCUM (D-12):** se resuelve la tensión entre «rechazar UCUM incorrecto» y «no interpretar UCUM arbitrario» con validación sintáctica + tabla versionada de átomos + verificación cruzada de escala, sin usar UCUM para convertir.
- **Errores (D-19):** se mapean los errores conceptuales del brief a códigos estables del sobre existente; "conversión no soportada" y "magnitud incompatible" comparten causa (unidad no asociada a la magnitud) y código.
- **Endpoint de validación por identidad:** no se agrega (001 y 003 no lo tienen; `GET` por identidad ya devuelve `status`).
- **Resolución por código externo:** como filtro exacto del listado de unidades (los códigos UCUM contienen `/`, `[`, `]`).

## Preguntas abiertas

Ninguna.
