# gi-common-reference

Módulo COMMON de GI responsable de referencias y catálogos globales reutilizables por otros módulos y aplicaciones del ecosistema.

Su objetivo es proporcionar una fuente única, estable y consistente para información de referencia compartida, evitando que cada consumidor mantenga copias o interpretaciones propias.

Los datos de este módulo son globales: no dependen de un tenant ni incorporan lógica específica de los módulos que los consumen.

## Catálogos

### Countries

`countries` es el catálogo global de países de GI.

Proporciona identidades estables y datos normalizados basados en estándares internacionales, incluyendo códigos como `alpha2`, `alpha3` y código numérico, además de información geográfica y otros datos de referencia aprobados para el catálogo.

Módulos como Persons, Tenants, CRM, ERP u otros pueden referenciar un país mediante `country_id`, pero la propiedad y mantenimiento del catálogo permanece en `gi-common-reference`.

## Consumo

Los catálogos se exponen mediante contratos públicos de consulta.

Los consumidores pueden utilizar esta información, pero no modificar directamente el catálogo ni depender de sus estructuras internas de persistencia.

`gi-common-reference` no expone un CRUD de mantenimiento para los catálogos globales.

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
