# gi-common-reference

Módulo COMMON de GI responsable de referencias y catálogos globales reutilizables por otros módulos y aplicaciones del ecosistema.

Su objetivo es proporcionar una fuente única, estable y consistente para información de referencia compartida, evitando que cada consumidor mantenga copias o interpretaciones propias.

Los datos de este módulo son globales: no dependen de un tenant ni incorporan lógica específica de los módulos que los consumen.

## Catálogos

### Regions y Subregions

`regions` es el catálogo global de regiones y subregiones geográficas UN M49 (p. ej. `019` Americas → `419` Latin America and the Caribbean), con identidades estables (`region_id`, `subregion_id`) independientes de su código M49 y nombres por `locale_id` del catálogo de Locale. Se consulta en `GET /v1/regions` y `GET /v1/subregions` (contrato en `contracts/regions-api.v1.openapi.json`). Spec: [`specs/002-regions-subregions`](specs/002-regions-subregions/spec.md).

### Countries

`countries` es el catálogo global de países de GI.

Proporciona identidades estables (`country_id`) y datos normalizados basados en estándares internacionales: códigos ISO 3166-1 (`alpha2`, `alpha3` y código numérico, que son claves de resolución y no la identidad), clasificación por `region_id` y `subregion_id` del catálogo Regions, código de llamada E.164, nombres por `locale_id` del catálogo de Locale, bandera SVG y, para un país retirado, sus sucesores (`replacement_country_ids`, 0..N). Se consulta en `GET /v1/countries` (contrato en `contracts/countries-api.v1.openapi.json`). Spec: [`specs/003-countries`](specs/003-countries/spec.md).

Módulos como Persons, Tenants, CRM, ERP u otros pueden referenciar un país mediante `country_id`, pero la propiedad y mantenimiento del catálogo permanece en `gi-common-reference`.

## Consumo

Los catálogos se exponen mediante contratos públicos de consulta.

Los consumidores pueden utilizar esta información, pero no modificar directamente el catálogo ni depender de sus estructuras internas de persistencia.

`gi-common-reference` no expone un CRUD de mantenimiento para los catálogos globales.

### Currency

`currencies` es el catálogo global de monedas ISO 4217 de GI, con identidad estable `currency_id` (independiente de los códigos), nombres por `locale_id` (`en` y `es` obligatorios en v1) y la relación N:N con países (CountryCurrency) **con vigencia temporal**: `status` (`active` | `inactive`) es el ciclo de vida del registro y el período `[valid_from, valid_to)` es cuándo la relación corresponde, de modo que se conserva la historia (p. ej. HRK → EUR en HR) y un país puede tener varias monedas a la vez. Se consulta en `GET /v1/currencies*` (contrato en `contracts/currencies-api.v1.openapi.json`). No contiene tipos de cambio ni cotizaciones. Spec: [`specs/004-currency`](specs/004-currency/spec.md).

## Versionado y actualización

La preparación de los catálogos se realiza fuera de este repositorio, mediante `gi-common-reference-prep`.

`gi-common-reference-prep` es responsable de obtener datos desde fuentes oficiales, normalizarlos, validarlos y generar snapshots JSON versionados y reproducibles.

`gi-common-reference` no consulta esas fuentes externas durante su funcionamiento normal. Incorpora únicamente versiones previamente preparadas, verificadas y aprobadas.

El flujo es:

`Fuentes oficiales → gi-common-reference-prep → snapshot versionado → gi-common-reference → consumidores`

Para `countries`, una publicación puede incluir artefactos como:

- `countries.v1.json`
- `provenance.json`

Cada versión publicada del catálogo es inmutable. Una actualización genera una nueva versión en lugar de modificar silenciosamente una anterior.

Esto permite que los cambios sean trazables, reproducibles y verificables antes de llegar a los módulos consumidores.

## Arquitectura

`gi-common-reference` mantiene separada la responsabilidad de los catálogos globales respecto de los módulos que los consumen.

Que un módulo utilice una referencia no significa que sea propietario de ella.

Por ejemplo, Persons puede almacenar un `country_id`, pero la identidad y definición de ese país continúa perteneciendo a `gi-common-reference`.

Los consumidores deben integrarse mediante contratos públicos y no mediante dependencias directas sobre tablas, migraciones o estructuras internas.

## Tecnología

- Python
- PostgreSQL / Supabase
- Schema propio dentro de la base de datos compartida de GI
- Desarrollo y gobernanza mediante AI-NATIVE

## Desarrollo

El desarrollo normal se realiza sobre `develop`.

`main` representa versiones publicadas del módulo.

Las nuevas funcionalidades y cambios relevantes se desarrollan mediante specs siguiendo el workflow definido por AI-NATIVE.

Las reglas permanentes para agentes y colaboradores están definidas en [`AGENTS.md`](AGENTS.md).

Requisitos del entorno (Docker, Node, release de AI-NATIVE), instalación reproducible y verificación: [`docs/desarrollo.md`](docs/desarrollo.md). Despliegue y operación (roles, migraciones, API, incorporación de snapshots): [`docs/operacion.md`](docs/operacion.md).
