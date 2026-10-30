# 003-countries — Catálogo global de países

Status: draft

## Contexto y objetivo

**Situación actual**: Persons y Tenants persisten country_code como texto validado únicamente por formato. Esto constituye legado a migrar. El estado objetivo es que los consumidores persistan exclusivamente country_id; los códigos ISO quedan como atributos y claves públicas de resolución de Countries.

Countries es el catálogo **global y canónico** de países/áreas de GI, propiedad
exclusiva de `gi-common-reference`. Proporciona una identidad GI estable
(`country_id`) y atributos normalizados basados en estándares internacionales,
consumidos en modo lectura mediante contratos públicos. El catálogo se actualiza
solo desde datasets aprobados, versionados y trazables; nunca mediante edición
manual cotidiana.

## Usuarios

- **Módulos consumidores** (Core, Tenants, Persons, CRM, ERP, verticales): resuelven
  y validan referencias de país; almacenan `country_id`.
- **Mantenedor del catálogo** (rol humano de `gi-common-reference`): revisa y
  aprueba datasets y aplica versiones del catálogo.
- **PREP** (`gi-common-reference-prep`): produce los datasets candidatos con su
  evidencia de procedencia.

## Historias de usuario

- HU-1. Como consumidor, quiero resolver un país por `country_id` para mostrar o
  validar una referencia que ya almacené.
- HU-2. Como consumidor, quiero resolver un país por su código ISO alpha-2 o
  alpha-3 para traducir datos externos o heredados a `country_id`.
- HU-3. Como consumidor, quiero listar los países vigentes para poblar selectores.
- HU-4. Como consumidor, quiero saber si un `country_id` existe y está vigente
  antes de aceptarlo en mi dominio.
- HU-5. Como mantenedor, quiero aplicar una nueva versión del dataset de forma
  revisable, repetible y sin romper referencias existentes.
- HU-6. Como auditor, quiero saber qué versión del dataset está cargada y de qué
  fuentes proviene cada dato.

## Definiciones

- **Country (registro)**: un país o área geográfica que tiene, o tuvo, un código
  _oficialmente asignado_ en ISO 3166-1. Incluye Estados soberanos, territorios
  dependientes y áreas especiales (p. ej. AQ, BV, HK, PR). Un registro **no** es
  una declaración de soberanía ni de reconocimiento político.
- **Activo**: el registro corresponde a una entrada vigente de ISO 3166-1.
- **Inactivo**: el registro existió en el catálogo pero su entrada fue retirada de
  ISO 3166-1 (pasó a ISO 3166-3) o fue retirado por decisión GI aprobada. Se
  conserva para siempre y sigue siendo resoluble por `country_id`.
- **Dataset aprobado**: snapshot completo del catálogo, versionado, con
  procedencia, validado y aprobado por revisión humana en `gi-common-reference`.
- **Versión del catálogo**: identificador de la versión del dataset aprobado
  actualmente aplicada.

## Decisiones

### Aprobadas previamente (input)

- D-1. Countries es GLOBAL, sin `tenant_id`, propiedad única de `gi-common-reference`.
- D-2. `country_id` es UUID, controlado por GI, estable y es la única identidad
  que los consumidores deben almacenar.
- D-3. Banderas en SVG, referenciadas por `alpha2`, nunca almacenadas como binario
  en el registro.
- D-4. Persistencia en PostgreSQL/Supabase con schema propio.
- D-5. PREP es fuente de evidencia y preparación, no autoridad de modelo.
- D-6. Sin CRUD administrativo para consumidores.

### Tomadas por esta spec

- D-7. **Política de inclusión**: entran todos los códigos _oficialmente asignados_
  de ISO 3166-1 vigentes. Quedan fuera: códigos de uso de usuario (p. ej. `XK`),
  códigos excepcional o transitoriamente reservados (p. ej. `EU`, `UK`), y áreas
  M49 sin código ISO (p. ej. Sark, M49 680). Agregar cualquiera de ellos requiere
  decisión explícita posterior.
- D-8. **Autoridad de inclusión y de códigos es ISO 3166-1**, no UN M49. Evidencia:
  la extracción M49 de PREP (248 registros) no contiene `TW`, que sí está asignado
  en ISO 3166-1; M49 es autoridad solo de la clasificación geográfica.
- D-9. **Dataset inicial**: solo entradas vigentes de ISO 3166-1, todas activas. No se
  precargan entidades históricas de ISO 3166-3 (SU, YU, AN, …).
- D-10. **Región y subregión M49 forman parte del propio registro** (código + nombre),
  sin entidad separada. Es la representación más simple y útil para filtrar y
  mostrar; una entidad de regiones podrá derivarse más adelante sin romper el
  contrato. La _región intermedia_ M49 (p. ej. 005 South America) queda fuera de
  v1; su incorporación futura es un cambio aditivo.
- D-11. **`country_id` lo asigna Reference, no PREP**, una única vez al incorporar un
  país por primera vez, y queda registrado en el dataset aprobado versionado en
  `gi-common-reference`. Nunca se recalcula en la carga a partir de atributos
  mutables; por tanto es idéntico en todos los entornos.
- D-12. **Recodificación vs. nueva entidad**: si ISO cambia los códigos de una misma
  entidad (precedentes: TP→TL, ROM→ROU), se conserva el `country_id` y se
  actualizan los códigos. Si ISO retira una entidad y crea otras (división, fusión,
  precedentes: AN→CW/SX/BQ, CS→RS/ME), la retirada pasa a inactiva y las nuevas
  reciben `country_id` nuevos. La clasificación de cada caso es parte de la
  revisión humana del dataset.
- D-13. Los consumidores **no** crean FKs ni dependen de tablas/vistas internas de
  Reference; integran por contrato (regla de AGENTS.md). Permitir una FK
  inter-schema requiere decisión arquitectónica explícita.
- D-14. Claves públicas de búsqueda: `country_id`, `alpha2` y `alpha3`. Búsqueda por
  código numérico queda diferida (el dato se expone como atributo; agregar la
  búsqueda después es aditivo).

## Modelo funcional del registro Country

| Atributo                            | Significado                                                                   | Oblig.                                     | Único                          | Estabilidad                      | Autoridad                      | Ante actualización                              |
| ----------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------ | -------------------------------- | ------------------------------ | ----------------------------------------------- |
| `country_id`                        | Identidad GI                                                                  | Sí                                         | Sí, global y nunca reutilizado | Inmutable                        | GI (Reference)                 | Nunca cambia                                    |
| `alpha2`                            | ISO 3166-1 alpha-2, 2 letras A–Z mayúsculas                                   | Sí                                         | Entre activos                  | Casi estable                     | ISO 3166-1                     | Se actualiza según D-12                         |
| `alpha3`                            | ISO 3166-1 alpha-3, 3 letras A–Z mayúsculas                                   | Sí                                         | Entre activos                  | Casi estable                     | ISO 3166-1                     | Se actualiza según D-12                         |
| `numeric_code`                      | ISO 3166-1 numérico, 3 dígitos con ceros a la izquierda (texto, no número)    | Sí                                         | Entre activos                  | Casi estable                     | ISO 3166-1; M49 debe coincidir | Se actualiza según D-12                         |
| `name`                              | Nombre corto de uso común para mostrar                                        | Sí                                         | No exigido                     | Descriptivo                      | CLDR (ver Q-1)                 | Se actualiza libremente                         |
| `official_name`                     | Nombre formal completo                                                        | No (ISO no lo define para todas las áreas) | No                             | Descriptivo                      | ISO 3166-1 _full name_         | Se actualiza libremente                         |
| `region_code` / `region_name`       | Región M49 (p. ej. `019` Americas)                                            | No (p. ej. AQ no tiene)                    | No                             | Descriptivo                      | UN M49                         | Se actualiza libremente                         |
| `subregion_code` / `subregion_name` | Subregión M49 (p. ej. `419`)                                                  | No                                         | No                             | Descriptivo                      | UN M49                         | Se actualiza libremente                         |
| `calling_code`                      | Código de país E.164 principal, 1–3 dígitos sin `+` (p. ej. `54`; NANP = `1`) | No (p. ej. BV)                             | No (US/CA comparten `1`)       | Descriptivo                      | ITU-T E.164                    | Se actualiza libremente                         |
| `is_active`                         | Vigencia según definiciones                                                   | Sí                                         | —                              | Cambia solo por dataset aprobado | ISO 3166-1 + decisión GI       | Ver RF-20 a RF-22                               |
| `created_at` / `updated_at`         | Timestamps técnicos                                                           | Sí                                         | —                              | Técnicos                         | Sistema                        | `updated_at` cambia solo si cambia el contenido |

## Requisitos funcionales

### Identidad e integridad

- RF-1. THE SYSTEM SHALL mantener un único catálogo Countries global, sin `tenant_id` ni partición por tenant o módulo.
- RF-2. THE SYSTEM SHALL identificar cada registro con un `country_id` UUID inmutable, que nunca se reasigna a otro país ni se reutiliza.
- RF-3. THE SYSTEM SHALL garantizar que entre registros activos no existan dos con el mismo `alpha2`, `alpha3` o `numeric_code`.
- RF-4. THE SYSTEM SHALL garantizar que `alpha2`, `alpha3` y `numeric_code` de un registro correspondan a la misma entrada ISO 3166-1.
- RF-5. THE SYSTEM SHALL rechazar registros cuyos códigos no cumplan el formato del modelo (letras mayúsculas A–Z, dígitos con ceros a la izquierda).
- RF-6. THE SYSTEM SHALL garantizar que cada par código/nombre de región y de subregión esté completo o ausente, que la subregión solo exista con región, y que un mismo código M49 tenga el mismo nombre en todo el catálogo.
- RF-7. THE SYSTEM SHALL no eliminar físicamente nunca un registro Country.

### Contratos de consulta

- RF-8. WHEN un consumidor resuelve por `country_id` existente, THE SYSTEM SHALL devolver el Country con su estado, sea activo o inactivo.
- RF-9. WHEN un consumidor resuelve por `alpha2` o `alpha3`, THE SYSTEM SHALL comparar sin distinguir mayúsculas y devolver el registro activo que lo posee.
- RF-10. IF ningún registro activo posee el código pero exactamente uno inactivo sí, THEN THE SYSTEM SHALL devolver ese registro indicando que está inactivo.
- RF-11. IF el identificador o código no existe, THEN THE SYSTEM SHALL devolver un resultado explícito de "no encontrado", distinguible de un error técnico.
- RF-12. IF la entrada tiene formato inválido (UUID mal formado, código con longitud o caracteres no válidos), THEN THE SYSTEM SHALL devolver un error de validación distinguible de "no encontrado".
- RF-13. WHEN un consumidor lista Countries, THE SYSTEM SHALL devolver por defecto solo los activos, en orden determinista por `alpha2`, con opción explícita de incluir inactivos.
- RF-14. WHEN un consumidor valida un `country_id`, THE SYSTEM SHALL responder uno de tres estados: `active`, `inactive` o `not_found`, sin imponer al consumidor si acepta inactivos.
- RF-15. THE SYSTEM SHALL devolver en toda resolución como mínimo: `country_id`, `alpha2`, `alpha3`, `numeric_code`, `name`, `official_name`, región, subregión, `calling_code` e `is_active` (los opcionales como ausentes cuando no existen).
- RF-16. THE SYSTEM SHALL permitir consultar la versión del catálogo actualmente aplicada.
- RF-17. THE SYSTEM SHALL versionar cada contrato público; agregar campos o consultas es compatible, y quitar o cambiar el significado de un campo requiere nueva versión mayor con análisis de migración.
- RF-18. THE SYSTEM SHALL no exponer a los consumidores operaciones de alta, modificación ni baja de Countries.

### Banderas

- RF-19. THE SYSTEM SHALL entregar, junto con cada versión del catálogo, un asset SVG de bandera por cada registro activo, identificable por su `alpha2`; la ausencia para un registro activo solo se admite si el dataset la declara explícitamente.

### Ciclo de vida y carga

- RF-20. WHEN se aplica un dataset aprobado, THE SYSTEM SHALL crear los registros nuevos, actualizar los modificados y conservar el `country_id` de los ya conocidos.
- RF-21. IF un dataset no contiene algún `country_id` ya existente en el catálogo, THEN THE SYSTEM SHALL rechazarlo completo; un retiro se expresa como registro inactivo, nunca como ausencia.
- RF-22. THE SYSTEM SHALL cambiar el estado activo/inactivo de un registro únicamente mediante un dataset aprobado.
- RF-23. WHEN se aplica dos veces el mismo dataset, THE SYSTEM SHALL dejar el catálogo sin cambios, incluido `updated_at`.
- RF-24. IF un dataset falla cualquier validación, THEN THE SYSTEM SHALL no aplicar ningún cambio (todo o nada).
- RF-25. IF se intenta aplicar un dataset de versión anterior a la aplicada, THEN THE SYSTEM SHALL rechazarlo salvo una acción explícita de reversión.
- RF-26. THE SYSTEM SHALL operar las consultas sin acceder a fuentes externas en tiempo de ejecución.

### Dataset y procedencia (frontera Reference ↔ PREP)

- RF-27. THE SYSTEM SHALL aceptar solo datasets con identificador de versión único, contenido completo del catálogo, `country_id` para cada registro y suma de verificación del contenido.
- RF-28. THE SYSTEM SHALL exigir procedencia que declare, por fuente usada: nombre, edición o versión, fecha de obtención, referencia de ubicación, suma de verificación del artefacto de origen y licencia.
- RF-29. THE SYSTEM SHALL exigir que cada atributo provenga de su fuente de autoridad según el modelo, y que todo conflicto entre fuentes (p. ej. numérico ISO ≠ M49) bloquee el dataset en lugar de resolverse en silencio.
- RF-30. WHEN se propone una nueva versión, THE SYSTEM SHALL disponer de un diff legible contra la versión aplicada (altas, cambios de atributos, cambios de estado) para revisión humana antes de su aprobación.

Reparto de responsabilidades:

| PREP                                                              | Reference                                                  |
| ----------------------------------------------------------------- | ---------------------------------------------------------- |
| Adquirir fuentes, normalizar, cruzar y validar                    | Definir modelo, política de inclusión e invariantes        |
| Producir snapshot candidato + procedencia + reporte de validación | Asignar/mapear `country_id` (D-11) y clasificar casos D-12 |
| Proponer diff contra la versión previa                            | Revisar, aprobar, versionar en el repo y aplicar           |
| No decide identidad ni inclusión                                  | Expone contratos y versión del catálogo                    |

## Requisitos no funcionales

- RNF-1. La aplicación de un dataset es reproducible: el mismo dataset produce el mismo catálogo en cualquier entorno.
- RNF-2. Toda versión aplicada es trazable a un dataset aprobado, su procedencia y su aprobación en el historial del repositorio.
- RNF-3. Las consultas solo requieren acceso de lectura; la escritura queda restringida al proceso de carga controlado.
- RNF-4. No se aplica un modelo RLS por tenant: todos los consumidores autorizados leen el mismo catálogo.
- RNF-5. Las invariantes RF-2 a RF-7 están protegidas por la persistencia, no solo por código de aplicación.

## Casos límite

- CL-1. Antártida (AQ): sin región ni subregión M49 → campos ausentes, registro válido.
- CL-2. Taiwán (TW): asignado en ISO 3166-1, ausente en M49 → se incluye; su clasificación queda según Q-2.
- CL-3. Códigos compartidos de telefonía (US/CA/PR → `1`; RU/KZ → `7`): válidos, `calling_code` no es único.
- CL-4. Área sin código E.164 (p. ej. BV): `calling_code` ausente.
- CL-5. `alpha2` `NA` (Namibia): nunca debe interpretarse como nulo o "no aplica".
- CL-6. Códigos numéricos con ceros a la izquierda (`004`, `020`): se preservan.
- CL-7. Reasignación futura por ISO de un código antes usado por un registro inactivo: el código pasa al nuevo registro activo; la búsqueda por código devuelve el activo (RF-9) y el inactivo sigue resoluble por `country_id`.
- CL-8. Entrada en minúsculas o con espacios (`" ar "`): mayúsculas/minúsculas se toleran (RF-9); espacios u otros caracteres son error de validación (RF-12).
- CL-9. Consumidor con un `country_id` de un país hoy inactivo: la resolución sigue funcionando (RF-8) y la validación devuelve `inactive` (RF-14).

## Fuera de alcance

- Subdivisiones (ISO 3166-2: provincias, estados, departamentos, municipios), ciudades, localidades, códigos postales.
- Monedas, idiomas, nombres localizados en varios idiomas, zonas horarias, datos fiscales.
- Región intermedia M49 y entidad propia de regiones (D-10).
- Historial de alias o códigos anteriores (ISO 3166-3) y precarga de entidades históricas (D-9).
- Telefonía avanzada: NANP, prefijos internos, planes compartidos.
- Geopolítica o reconocimiento político más allá de ISO 3166-1.
- CRUD administrativo y configuración por tenant (p. ej. país predeterminado del tenant, que pertenece a Tenants).
- Migración de `country_code` a `country_id` en Persons, Tenants u otros: la decide y ejecuta cada consumidor en su repo; esta spec solo garantiza el contrato que la habilita (RF-9).
- Diseño interno de PREP y un pipeline genérico de versionado para otros catálogos (candidato a spec posterior).
- Cambios en cualquier otro repositorio.

## Criterios de aceptación

- CA-1. El catálogo cargado contiene exactamente las entradas vigentes de ISO 3166-1 de la edición declarada en la procedencia, todas activas, sin `XK`, `EU` ni áreas sin código ISO (RF-1, D-7, D-9).
- CA-2. Ningún registro tiene `tenant_id`; un mismo `country_id` resuelve igual para cualquier consumidor (RF-1, RNF-4).
- CA-3. Intentar persistir un duplicado activo de `alpha2`, `alpha3` o `numeric_code`, un código mal formado o una región incoherente falla en persistencia (RF-3 a RF-6, RNF-5).
- CA-4. Resolver por `country_id`, `alpha2` (`ar`, `AR`) y `alpha3` devuelve el mismo registro con todos los campos de RF-15 (RF-8, RF-9, RF-15).
- CA-5. Resolver un código inexistente devuelve "no encontrado"; un código mal formado devuelve error de validación; ambos son distinguibles (RF-11, RF-12).
- CA-6. La validación de un `country_id` activo, inactivo e inexistente devuelve `active`, `inactive` y `not_found` respectivamente (RF-14).
- CA-7. Aplicar el mismo dataset dos veces no cambia ningún dato ni `updated_at` (RF-23).
- CA-8. Aplicar un dataset que omite un `country_id` existente, que falla una validación o que es de versión anterior se rechaza sin cambios parciales (RF-21, RF-24, RF-25).
- CA-9. Una nueva versión que modifica `name` o códigos de un país conserva su `country_id` en todos los entornos (RF-2, RF-20, D-11, RNF-1).
- CA-10. Las consultas funcionan sin conectividad a ISO, UN, ITU ni CLDR (RF-26).
- CA-11. Cada registro activo tiene bandera SVG resoluble por `alpha2` o ausencia declarada (RF-19).
- CA-12. La versión del catálogo consultable coincide con la del dataset aprobado y su procedencia (RF-16, RF-27, RF-28).
- CA-13. No existe operación pública de escritura de Countries para consumidores (RF-18).

## Evidencia revisada (solo lectura)

- PREP: `scripts/extract_un_m49.py` y `work/un-m49-countries.json` (248 filas con ISO alpha-2/alpha-3; falta `TW`; `AQ` sin región). Fuentes locales: M49 overview HTML y CLDR 48.2 _supplemental_ (contiene alias de territorios, sin nombres localizados ni telefonía). Directorios `sources/itu` y `sources/flag-icons` vacíos. PREP no es repositorio git.
- Persons: `country_code` alpha-2 por regex en identificadores, domicilios y datos fiscales; valor por defecto `AR`; sin FK.
- Tenants: `country_code` alpha-2 por regex en perfil, identificadores y domicilios; sin FK.
- Core: sin referencias a países.

Consecuencias: ningún contrato existente se rompe; la migración de los consumidores a `country_id` es trabajo suyo, habilitado por RF-9. PREP aún no dispone de fuentes ISO 3166-1, ITU ni de banderas, necesarias para producir el dataset inicial.

## Supuestos

- S-1. La lista ISO 3166-1 (códigos y nombres) puede obtenerse de una publicación oficial verificable con licencia compatible.
- S-2. Las banderas provendrán de una fuente con licencia que permita su redistribución, declarada en la procedencia.
- S-3. El canal técnico de los contratos (librería, API, vista) y la forma física de tabla, índices, empaquetado de assets y carga se deciden en el Plan.

## Trabajo futuro (posibles specs)

- Pipeline común de actualización/versionado de catálogos de Reference.
- Nombres localizados (CLDR) y alias históricos de códigos.
- Región intermedia M49 o entidad de regiones.
- ISO 3166-2 (subdivisiones), si un consumidor lo necesita.

## Preguntas abiertas

- Q-1. [NEEDS CLARIFICATION] ¿En qué idioma está `name` (español o inglés) y cuál es su fuente exacta? Propuesta por defecto: nombre CLDR en español, porque el producto opera en `es-AR`; `official_name` quedaría en inglés (ISO no publica español). Impacta RF-15 y la coherencia entre ambos nombres.
- Q-2. [NEEDS CLARIFICATION] Para áreas ISO sin entrada en M49 (hoy solo `TW`), ¿la región y subregión quedan ausentes o se toman de la contención territorial de CLDR (que ubica a TW en `030` Eastern Asia)? Propuesta por defecto: ausentes, para no mezclar autoridades.
- Q-3. [NEEDS CLARIFICATION] ¿El esquema de versión del dataset debe ser semántico (mayor = cambio de identidad o retiro; menor = cambio descriptivo) o basta con un identificador monótono? Propuesta por defecto: monótono, con el tipo de cambio visible en el diff (RF-30).
