# AGENTS.md — gi-common-reference

`gi-common-reference` es el módulo COMMON propietario de referencias y catálogos globales reutilizables por el ecosistema GI.

Este archivo define las reglas permanentes del repositorio.  
Las reglas generales de desarrollo, gobernanza y SDD son las provistas por AI-NATIVE.

## Alcance y propiedad

- Este módulo posee únicamente referencias globales de uso transversal.
- `countries` pertenece a este módulo y es GLOBAL: no lleva `tenant_id`.
- Core, Tenants, Persons, CRM, ERP, otros COMMON y las verticales pueden consumir sus referencias, pero no trasladar aquí su lógica de negocio.
- Un catálogo específico de un tenant o de un dominio funcional pertenece a su módulo propietario.
- Compartir datos entre varios módulos no implica, por sí solo, que deban pertenecer a este repositorio.

## Contratos

- Los consumidores deben integrarse mediante contratos públicos y estables.
- Tablas, migraciones, repositorios, clases y demás detalles internos no son contratos públicos salvo declaración explícita.
- Los consumidores deben referenciar identidades estables; por ejemplo, Persons puede almacenar `country_id` sin adquirir propiedad sobre `countries`.
- Todo cambio que afecte un contrato público debe analizar compatibilidad y migración antes de implementarse.

## Arquitectura y datos

- Servicio: Python.
- Persistencia: PostgreSQL/Supabase, en schema propio dentro de la base compartida de GI.
- Cada dato debe tener un único módulo propietario.
- No duplicar datos pertenecientes a otros módulos.
- No introducir `tenant_id` en referencias globales sin una decisión arquitectónica explícita.
- Las invariantes estructurales deben protegerse con constraints de base de datos cuando corresponda.
- La persistencia interna no debe convertirse en una dependencia directa de los consumidores.

## Forma de trabajo

- Seguir el workflow y los gates definidos por AI-NATIVE.
- Desarrollo normal en `develop`; `main` queda reservado para releases/versiones.
- Las features no triviales deben estar respaldadas por una spec aprobada.
- Implementar únicamente el alcance de la spec activa.
- Las decisiones específicas de una feature pertenecen a `specs/NNN-*`.
- `status.md` es el estado vivo y verificable de cada spec; no utilizar `MEMORY.md`.
- El estado del repositorio y sus artefactos prevalece sobre memoria conversacional o contexto histórico.

## Límites

**Siempre:** preservar propiedad de dominio, separación global/tenant, contratos públicos e integridad de datos.

**Requiere decisión explícita:** agregar un nuevo catálogo global, cambiar contratos públicos, modificar identidad persistida o trasladar responsabilidades entre módulos.

**Nunca:** incorporar lógica propia de consumidores, convertir implícitamente un catálogo global en tenant-specific, duplicar datos de otro módulo o implementar una feature no aprobada.

## Verificación

Todo cambio debe pasar las verificaciones exigidas por AI-NATIVE y por la spec activa.

Las pruebas deben cubrir, según corresponda, contratos públicos, reglas de dominio, persistencia, constraints y migraciones.

Una validación no ejecutada debe declararse explícitamente; el trabajo no debe presentarse como completamente verificado.

## Evolución

Mantener este archivo pequeño y estable.

Solo incorporar aquí reglas permanentes que afecten al repositorio en su conjunto.

Las reglas especializadas y recurrentes pueden ir en `.agents/rules/` cuando exista una necesidad real. No crear reglas preventivamente.

Si una spec necesita contradecir una regla de este archivo, primero debe resolverse y documentarse el cambio arquitectónico.
