# Manual de aceptación funcional y técnica — gi-common-reference (001–005)

Guía para que un desarrollador o el responsable humano valide **a mano** los cinco catálogos de `gi-common-reference`, individualmente y en conjunto, **sin conocer la implementación**. Cada caso indica qué se comprueba, los comandos, el resultado esperado y el criterio PASS/FAIL.

Las salidas esperadas se copiaron de un ensayo real de este mismo manual (2026-11-18, revisión de la rama `feature/006-cross-module-acceptance`, integrada en `develop` por la PR #12).

> **Seguridad.** Todo ocurre en un PostgreSQL **descartable** en Docker (puerto 55432). No usar nunca una URL de Supabase, de producción ni de un entorno compartido. Los datos son **sintéticos y no productivos** (ver §4.6).

Contenido: [1 Introducción](#1-introducción) · [2 Glosario y nomenclatura](#2-glosario-y-nomenclatura) · [3 Prerrequisitos](#3-prerrequisitos) · [4 Preparar el entorno](#4-preparar-el-entorno-una-vez) · [5 Las dos terminales](#5-las-dos-terminales) · [6 Datos de prueba](#6-datos-de-prueba-referencia-informativa) · [7 Casos M-01 a M-13](#7-casos) · [8 Restaurar el entorno](#8-restaurar-el-entorno) · [9 Checklist y registro](#9-checklist-final-y-registro) · [10 Fuera del alcance](#10-fuera-del-alcance-de-este-manual-declarado) · [11 Relación con AI-NATIVE](#11-relación-con-ai-native-y-auditoría-posterior)

---

## 1. Introducción

### Qué es gi-common-reference

Es el módulo COMMON del ecosistema GI que **posee** las referencias globales de uso transversal: datos que muchos módulos necesitan y que deben significar lo mismo en todos ellos. Es un servicio Python con su propio schema (`reference`) en PostgreSQL. Los consumidores (Persons, CRM, ERP, verticales) **no** leen sus tablas: usan sus contratos públicos (API HTTP y OpenAPI) y guardan sólo identidades estables; por ejemplo, Persons guarda un `country_id` sin adquirir propiedad sobre los países.

### Los cinco catálogos

| Spec | Catálogo | Qué contiene | Depende de |
|---|---|---|---|
| 001 | **Locale** | idiomas/variantes (`en`, `es`, `fr`) con los que se traducen los demás catálogos | — |
| 002 | **Region/Subregion** | regiones y subregiones geográficas M49 de la ONU | Locale |
| 003 | **Countries** | países ISO 3166-1, su región/subregión y nombres traducidos | Locale, Region |
| 004 | **Currency** | monedas ISO 4217 y su asociación con países, con vigencia temporal | Locale, Countries |
| 005 | **Units of Measure** | magnitudes, unidades (UCUM/UNECE) y conversión entre unidades | Locale |

El orden de dependencias está declarado y verificado en [`dependency-graph.json`](dependency-graph.json). Por eso los catálogos se cargan siempre en el orden Locale → Regions → Countries → Currency → Units.

### Para qué sirven los catálogos globales

Evitan que cada módulo mantenga su propia lista de países, monedas o unidades (con códigos distintos, traducciones divergentes o datos obsoletos). Son **globales**: no tienen `tenant_id` y son iguales para todos los clientes del ecosistema. Son de **solo lectura** para los consumidores; sólo cambian por la incorporación controlada de una nueva versión del catálogo (snapshot).

### Qué es esta aceptación funcional y técnica

- **Funcional:** comprueba, desde fuera, que el sistema hace lo que prometen las specs (cargar catálogos, consultarlos, traducirlos, convertir unidades, rechazar datos incoherentes).
- **Técnica:** comprueba propiedades de la plataforma que sostienen esas promesas (migraciones, permisos de roles, triggers de protección, contratos OpenAPI publicados).

Se ejecuta como **caja negra**: sólo se usan las herramientas públicas (CLIs, API HTTP, `psql`), no se inspecciona código.

### Pruebas autónomas y pruebas manuales

| | Autónoma | Manual (este documento) |
|---|---|---|
| Quién ejecuta | `pytest` / runner, sin intervención | una persona, paso a paso |
| Dónde | `tests/acceptance/test_cross_module_acceptance.py` (runner `python tools/acceptance/cross_module_acceptance.py`) | PowerShell, Docker y `curl.exe` |
| Cobertura | más amplia (CA-1 a CA-15 de la spec 006, 28 pruebas) | un subconjunto representativo, legible por humanos |
| Evidencia | [`acceptance/cross-module/evidence/`](../acceptance/cross-module/evidence/) | el registro del responsable (§9) |

La aceptación manual **no sustituye** a la autónoma: permite que una persona vea con sus propios ojos que el sistema real se comporta como se afirma, y detecta problemas de reproducibilidad que una suite automatizada no ve (como los incidentes de §4.2 y §5).

### Antes de comenzar

1. Leer §1 a §6 una vez completas; los casos asumen esa preparación.
2. Verificar los prerrequisitos (§3).
3. Tener disponibles dos ventanas de PowerShell (§5).
4. Tener a mano dónde registrar el resultado de cada caso (§9).

### PASS, FAIL y nomenclatura M-nn

- Los casos se numeran **M-01 a M-13** («M» de *manual*). La numeración es estable: se cita en el checklist y en los registros.
- **PASS:** la salida observada coincide con la **Esperada** del caso, incluidos los códigos de salida y los códigos HTTP.
- **FAIL:** cualquier diferencia, error inesperado o paso que no se pudo ejecutar.
- Un caso **negativo** (que provoca un rechazo a propósito) es **PASS cuando el sistema rechaza con el motivo esperado**. Un código de salida `1` o un HTTP `4xx` no es por sí mismo PASS ni FAIL: se compara con lo esperado.
- Un FAIL no se «corrige» repitiendo el caso: se anota la salida observada y se continúa.

### Para qué sirve el checklist final

El checklist (§9) **no es una batería nueva de pruebas**: agrupa los resultados de M-01 a M-13 por módulo para ver de un vistazo si cada catálogo quedó cubierto y aceptado, y sirve como acta de la ejecución.

---

## 2. Glosario y nomenclatura

| Término | Significado (y ejemplo en este manual) |
|---|---|
| **SDD** | *Spec-Driven Development*: cada feature parte de una spec aprobada (`specs/NNN-*/spec.md`) con requisitos, criterios de aceptación y casos límite; el código implementa sólo esa spec. |
| **Acceptance** | Verificación de que la feature cumple sus criterios de aceptación, vista desde fuera. Aquí: la suite de la spec 006 y este manual. |
| **API** | Interfaz de programación. Aquí, la API HTTP de solo lectura que consumen otros módulos GI (p. ej. `GET /v1/countries/by-alpha2/AR`). |
| **HTTP** | Protocolo de las consultas a la API. Usa métodos (`GET` leer, `POST` enviar, `PUT` reemplazar, `DELETE` borrar) y códigos de estado (`200` OK, `405` método no permitido, `422` petición inválida). |
| **FastAPI** | Framework Python con el que está construida la API; además genera su descripción OpenAPI. |
| **Uvicorn** | Servidor web que ejecuta la aplicación FastAPI y escucha peticiones HTTP (aquí en `127.0.0.1:8000`). |
| **OpenAPI** | Documento JSON que describe formalmente los endpoints, parámetros y respuestas de una API: es el contrato publicado (`contracts/*-api.v1.openapi.json`). |
| **PostgreSQL** | Base de datos relacional donde vive el schema `reference`. En GI corre en Supabase; en este manual, en un contenedor descartable. |
| **Docker** | Herramienta que ejecuta contenedores aislados. Aquí levanta `postgres:16-alpine` sin instalar nada en el sistema. |
| **Alembic** | Herramienta de migraciones de esquema para SQLAlchemy/PostgreSQL. |
| **Migración** | Script versionado que cambia la **estructura** de la base (tablas, constraints, triggers, permisos). Aquí `0001` (Locale) a `0005` (Units), encadenadas. No carga datos de catálogo. |
| **Snapshot** | Archivo JSON con el **contenido completo** de un catálogo en una versión dada, más su procedencia y un digest. Es la única vía de alta, cambio o retiro de datos. |
| **`snapshot_version`** | Número entero positivo de la versión del snapshot. Debe crecer; reenviar la misma versión con el mismo contenido es un no-op y con contenido distinto se rechaza. Un snapshot rechazado no consume su número. |
| **UUID** | Identificador universal de 128 bits (p. ej. `fe4be564-5597-5c73-b0c0-18ad9209f207` = Argentina). Es la identidad estable que guardan los consumidores; no cambia aunque cambien códigos o nombres. |
| **Idempotencia** | Propiedad de una operación que, repetida con la misma entrada, deja el mismo resultado que una sola ejecución. |
| **NO-OP** | *No Operation*: el sistema reconoce que no hay nada que hacer y no escribe. |
| **`diff`** | Subcomando de las CLIs de Countries, Currency y Units que muestra qué cambiaría un snapshot **sin escribir**. Sirve para revisión humana previa. |
| **`incorporate`** | Subcomando de cada CLI que valida un snapshot y, si es válido, lo aplica de forma atómica (todo o nada). |
| **`check-integrity`** | Subcomando de la CLI de Currency que busca asociaciones país–moneda abiertas sobre un país o moneda inactivos (RF-19 de 004). Exit `0` = íntegro, `1` = violación. |
| **Locale** | Identificador de idioma/variante (`es`, `en`, `fr`). En las consultas se pasa por su UUID: `locale_id`. |
| **Internacionalización / localización** | Internacionalización: diseñar el sistema para soportar varios idiomas. Localización: el texto concreto en un idioma (p. ej. «kilogramo» en `es`). |
| **Integridad referencial** | Garantía de que toda referencia apunta a algo existente (un país no puede apuntar a una región inexistente). Se protege con claves foráneas y validaciones de snapshot. |
| **Quality Gate** | Control obligatorio que debe pasar antes de avanzar (formato, lint, tipos, `sdd validate`, suites). |
| **Independent Review** | Revisión del cambio por un revisor con contexto aislado del que lo construyó; emite APPROVED / CHANGES_REQUESTED / BLOCKED. |
| **HITL** | *Human In The Loop*: decisión humana obligatoria. Aquí, el merge de una PR y la aceptación final los decide una persona. |

**Nomenclatura de los artefactos:**

- **RF-n / RNF-n / CA-n / CL-n:** requisito funcional, requisito no funcional, criterio de aceptación y caso límite de una spec (secciones «Requisitos funcionales», «Requisitos no funcionales», etc.). La numeración es **por spec**: RF-6 de 003 no es RF-6 de 006. Los mensajes de rechazo citan el RF de la spec del catálogo que rechaza:
  - **RF-6 (003 Countries):** `region_id`/`subregion_id` deben referenciar entidades existentes de Region/Subregion y ser coherentes entre sí.
  - **RF-41 (004 Currency):** un snapshot debe declarar las versiones de Locale y Countries contra las que se validó, y esas versiones deben estar incorporadas, entre otros requisitos del snapshot (versión, digest, procedencia); si no, se rechaza completo.
  - **RF-19 (004 Currency):** ninguna asociación país–moneda `active` con vigencia abierta puede referenciar un país o moneda `inactive`.
- **N1, N2:** archivos de escenarios **negativos**: snapshots inválidos a propósito, que el sistema debe rechazar (M-05).
- **D1, D2:** archivos de escenarios de **deriva** (*drift*): cambios válidos en un catálogo que dejan inconsistente a otro, y su corrección (M-13).
- **Terminal A / Terminal B:** las dos ventanas de PowerShell de §5.

---

## 3. Prerrequisitos

| Requisito | Verificación | Esperado |
|---|---|---|
| Docker Desktop en ejecución | `docker version --format '{{.Server.Version}}'` | un número de versión, sin error |
| Python ≥ 3.12 | `python --version` | `Python 3.12` o superior |
| Git y el repositorio | `git -C D:\Proyectos\gi-common-reference status` | sin error |
| Puertos libres 55432 y 8000 | `netstat -ano \| findstr ":55432 :8000"` | ninguna línea `LISTENING` |
| `curl.exe` (Windows 10+) | `curl.exe --version` | una versión |

Todos los comandos están en **PowerShell**, desde la raíz de una copia del repositorio en la revisión a validar. En PowerShell se usa `curl.exe` (no `curl`, que es un alias de `Invoke-WebRequest`).

---

## 4. Preparar el entorno (una vez)

Toda esta sección se ejecuta en la **Terminal B** (§5).

### 4.1 Revisión a validar

```powershell
# Opción 1: la revisión ensayada originalmente (o usar el worktree D:\Proyectos\worktrees\gi-common-references\006-cross-module-acceptance)
git fetch origin
git switch feature/006-cross-module-acceptance
# Opción 2: la revisión actual de develop (006 ya está integrada)
#   git switch develop; git pull --ff-only
# (si la opción 1 falla porque la rama ya no existe o está activa en otro worktree, usar la opción 2)
git rev-parse HEAD   # anotar este SHA en el registro (§9)
```

- `git fetch` trae las ramas remotas; `git switch` cambia a la revisión a validar. Usar una copia **sin cambios locales** (`git status` limpio) o un worktree dedicado, para que lo validado sea exactamente lo commiteado.
- `git rev-parse HEAD` imprime el SHA que se valida; sin él, el resultado no es trazable.

### 4.2 Entorno Python aislado

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-user -c constraints.txt -e ".[dev]"
```

- `python -m venv .venv` crea un entorno virtual en `.venv`: un Python propio del repositorio, separado del Python del sistema.
- `pip install -e ".[dev]"` instala el paquete en modo editable con sus dependencias de desarrollo (`pyproject.toml`); `-c constraints.txt` fija las versiones exactas con las que se validó el proyecto.
- **`--no-user` (incidente real).** En la ejecución humana de este manual, la instalación original (`... -m pip install -c constraints.txt -e ".[dev]"`) falló porque pip intentaba una instalación `--user` dentro del virtualenv, cosa que pip no admite. La causa es una configuración global de pip (`install.user = true` en `pip.ini`, visible con `python -m pip config list`, o la variable `PIP_USER`). `--no-user` anula esa configuración para este comando. El autor de esta revisión del manual verificó que pip 26.2.2 dentro del venv acepta el flag; en una máquina sin esa configuración es inocuo, por eso es la instrucción general.

### 4.3 Variables de la sesión

PowerShell **no comparte variables entre ventanas**: cada ventana tiene las suyas, y se pierden al cerrarla. Este bloque define todo lo que usan los casos. Ejecutarlo ahora y **repetirlo en cada ventana nueva** (§5):

```powershell
# Bloque de sesión: ejecutar desde la raíz de la copia validada
$env:PYTHONUTF8 = "1"                                     # salida UTF-8 (acentos) en Windows
$py = (Resolve-Path .\.venv\Scripts\python.exe).Path      # Python del venv, ruta absoluta
$B  = "http://127.0.0.1:8000"                             # base de la API (M-07 a M-13)
# Una conexión por rol: migración = dueño, CLI = loader, API = reader
$env:REFERENCE_MIGRATION_DATABASE_URL = "postgresql://admin:admin-pw@127.0.0.1:55432/reference_acc"
$env:REFERENCE_DATABASE_URL           = "postgresql://reference_loader:loader-pw@127.0.0.1:55432/reference_acc"
$env:REFERENCE_READER_DATABASE_URL    = "postgresql://reference_reader:reader-pw@127.0.0.1:55432/reference_acc"
```

- `$py` y `$B` son variables de PowerShell (sólo existen en esa ventana). `$env:...` son variables de entorno que heredan los procesos lanzados desde esa ventana (Alembic, CLIs, Uvicorn).
- `$py` se guarda como ruta absoluta para que siga funcionando aunque se cambie de directorio. (La versión original del manual usaba `$py = ".\.venv\Scripts\python"`, equivalente desde la raíz.)
- Las tres URLs apuntan **sólo** a `127.0.0.1:55432`, el contenedor descartable. Las contraseñas existen sólo en ese contenedor.
- PowerShell no distingue mayúsculas en nombres de variables: `$b` y `$B` son la misma. No reutilizar `$b` para otra cosa (ya ocurrió en un ensayo de M-09).

### 4.4 PostgreSQL 16 descartable

```powershell
docker run -d --name gi-ref-acc -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=admin-pw `
  -e POSTGRES_DB=reference_acc -p 55432:5432 postgres:16-alpine
docker exec gi-ref-acc pg_isready -U admin -d reference_acc   # repetir hasta "accepting connections"
```

- `docker run` crea el contenedor `gi-ref-acc` con una base vacía `reference_acc` y un superusuario `admin`, publicado en el puerto local **55432** (para no chocar con un PostgreSQL local en 5432).
- `pg_isready` informa cuándo la base acepta conexiones; los primeros segundos puede responder `no response`.

**Por qué nunca una base productiva ni Supabase:** los casos crean roles, cargan datos sintéticos, retiran Puerto Rico (M-13) y, en la restauración, borran todo el schema (`downgrade base`). En una base real eso contaminaría o destruiría datos y permisos compartidos. Supabase `gi-dev` está explícitamente fuera de alcance (§10).

### 4.5 Roles (antes de migrar)

```powershell
docker exec gi-ref-acc psql -U admin -d reference_acc -v ON_ERROR_STOP=1 -c "CREATE ROLE reference_reader LOGIN PASSWORD 'reader-pw'; CREATE ROLE reference_loader LOGIN PASSWORD 'loader-pw'; CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN;"
```

| Rol | Uso | Qué le otorgan las migraciones |
|---|---|---|
| `admin` | dueño del schema; ejecuta migraciones (M-01) | todo (superusuario del contenedor) |
| `reference_loader` | CLIs de incorporación (M-03 a M-05, M-13) | lectura y las escrituras mínimas para incorporar snapshots |
| `reference_reader` | la API (M-06) | sólo `SELECT` |
| `anon`, `authenticated` | roles convencionales de Supabase para clientes anónimos/autenticados; se crean aquí para emular Supabase | nada (las migraciones les revocan todo) |

Se crean **antes** de migrar porque las migraciones les otorgan o revocan permisos. Si un rol no existe, la migración omite sus permisos **sin error**: M-03 o M-06 fallarían más tarde y M-02 daría un `0` engañoso. **PASS 4.5:** cuatro líneas `CREATE ROLE`.

### 4.6 Dataset sintético (determinista)

```powershell
& $py tools/acceptance/write_acceptance_dataset.py .\acc-data
```

- Escribe en `.\acc-data` los nueve snapshots JSON que usan los casos. Son **los mismos** que usa la suite autónoma (mismos builders), sintéticos y no productivos.
- `&` es el operador de llamada de PowerShell: ejecuta el programa cuya ruta está en `$py`.
- Por cada archivo imprime su **SHA-256**: una huella de 64 caracteres hexadecimales del contenido exacto. Si un solo byte cambia, la huella cambia. Coincidir con la tabla prueba que el dataset es exactamente el validado (no es una firma de seguridad, es una comprobación de identidad del contenido).
- `acc-data` es temporal: no se commitea y se borra en §8.

**PASS 4.6:** se imprimen exactamente estas sumas (si alguna difiere, el dataset no es el validado: FAIL y no continuar):

```text
67b2008d461bfcdf9af0d19941cf53e48b5f71a28a3e26b6f0e6bf6a90dfa075  01-locales-v1.json
42b22bd3af48671932f5c8a6e1a03ccf3eb65ab1183c5e5506dfded5e4596295  02-regions-v1.json
66f665019013a91ceef5466b8d7c8b65d4a8d58a944743fabf465ebdb56d11a3  03-countries-v1.json
7791622419d31c3a532cff27e31906cfd6d64f448c5c2ce8d4bd62c112ca3147  04-currencies-v1.json
4851499adf0229fec093eccbc0fb33260eae127936305888726dd4106e3068e2  05-units-v1.json
99e0aa874c1b53169cf778b806df918654e037a249e2012df685f4b78089dfc0  N1-countries-v2-ghost-region.json
96e5902280c6c9e23da8d58bd90e7f11b4b286891dc72ff4a5bf73057e068feb  N2-currencies-v2-future-countries.json
b2ed9cefb195c5d81bf9ba8a126c904cb3862b0dbe91bc030136154be5230482  D1-countries-v2-retire-pr.json
5a661acb4fb505193051d3e8c76e2299df6f8cc5624c6bf136648ba9c9065813  D2-currencies-v2-close-pr.json
```

---

## 5. Las dos terminales

La API (M-06) ocupa su ventana mientras está en marcha, así que se necesitan dos. En la ejecución humana de este manual, M-13 falló al principio porque se ejecutó en una segunda ventana donde `$py` no estaba definido. Para evitarlo:

| Ventana | Para qué | Cuándo se abre | Qué configurar |
|---|---|---|---|
| **Terminal B (operador)** | §4, M-01 a M-05, M-07 a M-13 y §8 | al comenzar | §4.2 y el bloque de sesión §4.3 (una vez) |
| **Terminal A (API)** | sólo Uvicorn (M-06) | al llegar a M-06 | `Set-Location` a la raíz de la copia y el bloque de sesión §4.3 (estrictamente necesita sólo `$py`, `PYTHONUTF8` y `REFERENCE_READER_DATABASE_URL`; usar el bloque completo evita omisiones) |

Así, la Terminal B conserva sus variables durante toda la aceptación y sólo la Terminal A, recién abierta, necesita el bloque de sesión. Si cualquier ventana se cierra o se abre otra, **volver a ejecutar el bloque de sesión §4.3** en ella antes de seguir.

Qué necesita cada tipo de comando:

| Comandos | Ventana | `$py` | `$B` | Variable de entorno | Directorio |
|---|---|---|---|---|---|
| `alembic` (M-01, §8) | B | sí | — | `REFERENCE_MIGRATION_DATABASE_URL` | raíz (lee `alembic.ini`) |
| CLIs `incorporate`/`diff`/`check-integrity` (M-03–M-05, M-13) | B | sí | — | `REFERENCE_DATABASE_URL` | raíz (lee `.\acc-data`) |
| Uvicorn (M-06) | A | sí | — | `REFERENCE_READER_DATABASE_URL`, `PYTHONUTF8` | raíz |
| `curl.exe` / `Invoke-RestMethod` (M-07–M-11, último paso de M-13) | B | — | sí | — | cualquiera |
| `docker exec ... psql` (M-02, M-12, §8) | B | — | — | — | cualquiera |

Comprobación rápida en una ventana: `"$py | $B | $env:REFERENCE_DATABASE_URL"` debe mostrar los tres valores, no espacios vacíos.

---

## 6. Datos de prueba (referencia informativa)

> **Las siguientes tablas son referencias informativas. No requieren ejecutar comandos ni cargar datos manualmente.** Los archivos ya se generaron en §4.6 y los UUID ya están incluidos en los comandos de los casos.

### Archivos del dataset

| Archivo | Contenido | Se usa en |
|---|---|---|
| `01-locales-v1` | Locales `en`, `es`, `fr` (fr sin traducciones en los demás catálogos) | M-03, M-04 |
| `02-regions-v1` | Regiones M49 002 África, 019 Américas, 142 Asia; subregiones 202, 419, 021, 035 | M-03 |
| `03-countries-v1` | AR, NA, AQ, TW, US, CA, PR, BV (con excepciones de bandera: el paquete aún no trae SVG, ver §10) | M-03, M-04 |
| `04-currencies-v1` | ARS, USD, EUR, JPY, XAU; asociaciones AR–ARS, US–USD, PR–USD (desde 1899-01-01) | M-03 |
| `05-units-v1` | 14 magnitudes, 50 unidades, 54 asociaciones (incluye masa, longitud, temperatura) | M-03, M-04 |
| `N1`, `N2` | Snapshots inválidos que referencian algo inexistente en otro catálogo | M-05 |
| `D1`, `D2` | Deriva: Countries v2 retira PR; Currency v2 cierra la vigencia PR–USD | M-13 |

- **Archivos positivos (`01`–`05`, versión 1):** un estado inicial coherente de los cinco catálogos. Incluyen casos interesantes a propósito: `fr` existe pero no tiene traducciones (M-08); PR comparte USD con US (M-07, M-13); masa y temperatura permiten conversiones lineales y afines (M-09).
- **N1 (Countries v2):** igual a la v1 salvo que BV apunta a una región con UUID `00000000-0000-4000-8000-000000000000`, que no existe. Debe rechazarse por RF-6 de 003.
- **N2 (Currency v2):** declara haberse validado contra Countries **versión 2**, que en ese momento no está incorporada. Debe rechazarse por RF-41 de 004.
- **D1 (Countries v2):** igual a la v1 salvo que PR pasa a `inactive`. Es válido para Countries, pero deja abierta la asociación PR–USD de Currency (deriva).
- **D2 (Currency v2):** validado contra Countries v2; cierra la vigencia PR–USD el 2026-01-01. Repara la deriva.

Como N1 y N2 se rechazan sin escribir, sus números de versión (2) quedan libres y D1 y D2 pueden usarlos más adelante.

### Identificadores usados en las consultas

Los UUID son las identidades estables de cada entidad: los consumidores guardan estos valores, no códigos ni nombres. Esta tabla permite saber a qué corresponde cada UUID que aparece en los comandos (por ejemplo, en M-07 Argentina se consulta por `fe4be564-…`).

| Qué | Id |
|---|---|
| Locale `en` / `es` / `fr` | `1d806402-a823-4580-9f4d-958c6e5a5354` / `7d74e7f4-4dd7-4a85-a540-09d2393b9a91` / `b8756f67-cbc0-4499-b3b6-453605c505b2` |
| Región 019 / Subregión 419 | `29786b02-6ca2-5d40-9c90-17e6bdf27303` / `1cc20843-3e0c-5637-b7a4-d220f48c2291` |
| País AR / US / PR | `fe4be564-5597-5c73-b0c0-18ad9209f207` / `71705c97-1868-546f-a495-8ba94dce51a7` / `c756eac0-5950-5d6d-b9eb-86c92a68a5ad` |
| Moneda USD | `12c3be84-c22e-5d01-adbf-f28c3aeb0807` |
| Asociación PR–USD | `b79074ab-8dbd-5e70-b59c-c4cfbcf2f384` |
| Unidad kg / lb / m | `2f2fc747-50fd-5709-a665-4fa037eea3b2` / `577ce238-f253-50cf-b881-a9c879f4bfc9` / `3561fd3d-586a-58ed-adc5-1c8cd3b83951` |
| Unidad °C / °F | `d79e8834-8511-5935-9ad5-f828280842f7` / `59286a77-e65f-5055-97d6-dcf775bf9ab7` |
| Magnitud mass / temperature | `b5215a84-a8e2-5953-9de0-ac0c4a8aac78` / `ca64bb7b-9824-5ca9-8888-b7d538630b30` |

---

## 7. Casos

Registrar cada caso como PASS o FAIL en el checklist (§9). Un FAIL no se «corrige» repitiendo: anotar la salida y continuar. Cada caso indica su **tipo**: positivo (el sistema debe aceptar o responder), negativo (debe rechazar) o de deriva (cambio entre catálogos).

### M-01 Migraciones (todos los módulos)

- **Objetivo:** crear la estructura completa del schema `reference` y confirmar que la cadena de migraciones llega al final.
- **Tipo:** técnico, positivo. **Terminal B.**

```powershell
& $py -m alembic upgrade head   # aplica en orden 0001 (Locale) … 0005 (Units) con el rol dueño
& $py -m alembic current        # muestra la revisión aplicada
```

- **Qué demuestra:** las cinco migraciones se aplican en una base vacía, en orden y sin error. `head` es la última revisión de la cadena. Las migraciones crean **estructura** (tablas, claves foráneas, constraints, triggers y permisos de roles); los **datos** de los catálogos llegan después, por snapshots (M-03).
- **En GI real:** es lo que se ejecuta al desplegar una versión nueva del módulo en la base compartida.
- **Esperado:** la última línea de `current` es `0005 (head)`.
- **PASS** si coincide; **FAIL** si hay error o otra revisión.
- **Limitación:** no prueba la reversibilidad (se comprueba opcionalmente en §8 y en la suite, CA-9).

### M-02 Catálogos globales y privilegios mínimos

- **Objetivo:** confirmar que los catálogos son globales y que los roles públicos no tienen acceso a sus tablas.
- **Tipo:** técnico, positivo. **Terminal B.**

```powershell
# Cuenta columnas cuyo nombre contenga "tenant" en el schema reference
docker exec gi-ref-acc psql -U admin -d reference_acc -tAc "SELECT count(*) FROM information_schema.columns WHERE table_schema='reference' AND column_name ILIKE '%tenant%';"
# Cuenta privilegios de tabla concedidos a anon, authenticated o PUBLIC en el schema reference
docker exec gi-ref-acc psql -U admin -d reference_acc -tAc "SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema='reference' AND grantee IN ('anon','authenticated','PUBLIC');"
```

- **Qué demuestra:** (1) ninguna tabla tiene columna de tenant: los datos son los mismos para todos los clientes (regla de `AGENTS.md`); (2) ni los roles de Supabase `anon`/`authenticated` ni `PUBLIC` tienen privilegios de tabla.
- **`anon`/`authenticated` vs `PUBLIC`:** los primeros son roles **convencionales de Supabase** (se crearon en §4.5 para emularlo). `PUBLIC` es nativo de PostgreSQL: no es un rol real sino «todos los roles»; un privilegio concedido a `PUBLIC` lo tiene cualquiera que pueda conectarse. Por eso el acceso se concede sólo a `reference_reader`/`reference_loader`.
- **En GI real:** un cliente de Supabase con la clave anónima no puede leer ni escribir el schema `reference` directamente; los consumidores pasan por la API.
- **Esperado:** `0` y `0`.
- **PASS** si ambos son `0`.
- **Limitación:** es una comprobación acotada, no una auditoría completa de permisos: sólo mira privilegios de **tabla** en `information_schema` (no privilegios de schema, columnas, funciones o secuencias, ni privilegios por defecto). La verificación más amplia (dueño único por tabla, reader sólo `SELECT`) está en la suite, CA-1.

### M-03 Incorporación en orden de dependencias (Locale → Regions → Countries → Currency → Units)

- **Objetivo:** cargar la versión 1 de los cinco catálogos con sus propias CLIs, respetando las dependencias.
- **Tipo:** funcional, positivo. **Terminal B.**

```powershell
& $py -m gi_common_reference.locales.interfaces.cli    incorporate .\acc-data\01-locales-v1.json     # Locale: no depende de nadie
& $py -m gi_common_reference.regions.interfaces.cli    incorporate .\acc-data\02-regions-v1.json     # Regions: usa Locale (nombres)
& $py -m gi_common_reference.countries.interfaces.cli  incorporate .\acc-data\03-countries-v1.json   # Countries: usa Locale y Regions
& $py -m gi_common_reference.currencies.interfaces.cli incorporate .\acc-data\04-currencies-v1.json  # Currency: usa Locale y Countries
& $py -m gi_common_reference.units.interfaces.cli      incorporate .\acc-data\05-units-v1.json       # Units: usa Locale
```

- **Qué demuestra:** cada catálogo valida su snapshot contra las versiones ya incorporadas de los catálogos de los que depende y lo aplica de forma atómica. El orden importa: Countries no puede cargarse antes que Regions porque sus países referencian regiones (la suite comprueba el orden inverso, CA-9).
- **Cómo leer la salida:** `snapshot_version=1` es la versión incorporada; `locale_snapshot_version=1`, `region_snapshot_version=1`, `country_snapshot_version=1` y `ucum_table_version=2.2` son las versiones de las dependencias contra las que se validó; los contadores dicen qué se creó (p. ej. `8 países nuevos`) y `0 actualizaciones` porque es la primera carga.
- **Sintético vs oficial:** estos snapshots son un subconjunto sintético para pruebas. El catálogo oficial (ISO 3166/4217, CLDR, M49, UCUM/UNECE completos) se generará y aprobará en PREP (§10); el mecanismo de incorporación es el mismo.
- **En GI real:** es el procedimiento controlado por el que se publica una nueva versión de un catálogo; nadie edita filas a mano.
- **Esperado** (una línea por comando, `$LASTEXITCODE` = 0 en cada uno):

```text
INCORPORADO snapshot_version=1 (3 nuevos, 0 actualizados)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; 3 regiones nuevas, 4 subregiones nuevas, 0 actualizaciones, 0 reclasificaciones, 0 recodificaciones)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; region_snapshot_version=1; 8 países nuevos, 0 actualizaciones, 0 recodificaciones)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; country_snapshot_version=1; 5 monedas nuevas, 0 actualizadas, 10 localizaciones, 3 asociaciones nuevas, 0 asociaciones actualizadas)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; ucum_table_version=2.2; 50 unidades nuevas, 0 actualizadas, 14 magnitudes nuevas, 0 actualizadas, 54 asociaciones nuevas, 0 actualizadas, 128 localizaciones)
```

- **PASS** si las cinco líneas coinciden y cada exit es 0 (`$LASTEXITCODE` tras cada comando); **FAIL** si alguna difiere o falla.
- **Limitación:** prueba el camino feliz con datos chicos; los casos límite de cada catálogo están en sus suites propias.

### M-04 Idempotencia y `diff` sin escritura

- **Objetivo:** comprobar que reenviar lo ya incorporado no cambia nada, y que `diff` sólo informa.
- **Tipo:** funcional, positivo. **Terminal B.**

```powershell
& $py -m gi_common_reference.locales.interfaces.cli   incorporate .\acc-data\01-locales-v1.json   # misma versión y contenido
& $py -m gi_common_reference.units.interfaces.cli     incorporate .\acc-data\05-units-v1.json     # ídem
& $py -m gi_common_reference.countries.interfaces.cli diff        .\acc-data\03-countries-v1.json # compara sin escribir
```

- **Qué demuestra:** **idempotencia**: misma `snapshot_version` y mismo digest = **NO-OP**, el catálogo queda idéntico. `diff` compara el snapshot con la versión aplicada y no escribe nunca.
- **Por qué importa:** un proceso de carga que se corta o se reintenta (red, timeout, reejecución de un pipeline) puede reenviarse sin riesgo de duplicar ni alterar datos. Y antes de incorporar una versión nueva, un humano puede revisar su `diff`.
- **Esperado:** `NO-OP snapshot_version=1 ya incorporado` (×2) y `NO-OP snapshot_version=1 ya incorporado: sin cambios`; exit 0.
- **PASS** si coincide.
- **Limitación:** la salida no demuestra por sí sola que no se escribió nada; la suite lo verifica con un volcado lógico idéntico antes y después (CA-4). Locale y Regions no tienen `diff`.

### M-05 Integridad referencial entre catálogos (rechazo al incorporar)

- **Objetivo:** provocar **a propósito** dos rechazos y confirmar que el motivo es el correcto.
- **Tipo:** funcional, **negativo**. **Terminal B.**

```powershell
# N1: Countries v2 con BV apuntando a una región inexistente; $LASTEXITCODE imprime el código de salida
& $py -m gi_common_reference.countries.interfaces.cli  incorporate .\acc-data\N1-countries-v2-ghost-region.json; $LASTEXITCODE
# N2: Currency v2 que declara Countries v2, aún no incorporada
& $py -m gi_common_reference.currencies.interfaces.cli incorporate .\acc-data\N2-currencies-v2-future-countries.json; $LASTEXITCODE
```

- **Qué demuestra:** ningún catálogo acepta referencias rotas hacia otro: N1 viola **RF-6 de 003** (la región debe existir en Region/Subregion) y N2 viola **RF-41 de 004** (las versiones de dependencia declaradas deben estar incorporadas). El rechazo es completo: no se escribe nada.
- **En GI real:** un error en la preparación de un snapshot no puede dejar países sin región o monedas validadas contra un estado de Countries que no existe.
- **Esperado:**

```text
RECHAZADO snapshot_version=2
  - RF-6: país 35be21fd-7ddb-5ffb-b954-c8c9f87519d9 (BV): la region_id 00000000-0000-4000-8000-000000000000 no existe en Region/Subregion
1
RECHAZADO snapshot_version=2
  - RF-41: la country_snapshot_version 2 declarada no está incorporada
1
```

- **Cómo interpretar el `1`:** el código de salida `1` es el **rechazo esperado**, no un error del manual. Pero no es PASS automático: un `1` con otro motivo (otro RF, un error de conexión) es FAIL.
- **PASS** si ambos se rechazan con exit 1 y ese motivo; **FAIL** si alguno se incorpora o se rechaza por otro motivo.
- **Limitación:** cubre dos de las referencias entre módulos; la suite cubre seis rechazos de CLI (CA-7) y todas las claves foráneas con SQL directo (CA-8).

### M-06 Arrancar la API (Terminal A, dejarla abierta)

- **Objetivo:** levantar la API real, conectada con el rol de sólo lectura.
- **Tipo:** técnico, preparación de M-07 a M-13. **Terminal A** (ventana nueva).

```powershell
# En la Terminal A, primero: Set-Location a la raíz de la copia validada y el bloque de sesión §4.3
& $py -m uvicorn --factory gi_common_reference.app:app_from_environment --host 127.0.0.1 --port 8000
```

- **Qué hace:** Uvicorn construye la aplicación con `app_from_environment`, que lee `REFERENCE_READER_DATABASE_URL` (rol `reference_reader`), y escucha en `127.0.0.1:8000` (sólo accesible desde esta máquina).
- **Por qué la ventana queda ocupada:** Uvicorn es un servidor; se queda atendiendo peticiones hasta que se lo detiene con `Ctrl+C` (§8). Por eso las consultas se hacen desde la Terminal B.
- **Esperado:** una línea `Uvicorn running on http://127.0.0.1:8000` y ningún error.
- **PASS** si la API arranca y responde en M-07; **FAIL** si termina con error (p. ej. variable de conexión ausente o puerto ocupado).

Volver a la **Terminal B** (que ya tiene `$B`) para M-07 a M-13.

### M-07 Navegación entre catálogos por identidades estables

- **Objetivo:** recorrer los catálogos como lo haría un consumidor, saltando de uno a otro por UUID.
- **Tipo:** funcional, positivo. **Terminal B.** (`curl.exe -s` hace un `GET` silencioso y muestra el JSON.)

```powershell
curl.exe -s "$B/v1/locales/by-code/es"                                                       # 1. obtener el UUID del locale es
curl.exe -s "$B/v1/countries/by-alpha2/AR?locale_id=7d74e7f4-4dd7-4a85-a540-09d2393b9a91"     # 2. Argentina, nombres en es
curl.exe -s "$B/v1/regions/29786b02-6ca2-5d40-9c90-17e6bdf27303"                              # 3. su región, por UUID
curl.exe -s "$B/v1/subregions/1cc20843-3e0c-5637-b7a4-d220f48c2291"                           # 4. su subregión, por UUID
curl.exe -s "$B/v1/currencies/by-country/fe4be564-5597-5c73-b0c0-18ad9209f207"                # 5. monedas de Argentina
curl.exe -s "$B/v1/currencies/12c3be84-c22e-5d01-adbf-f28c3aeb0807/countries"                 # 6. países que usan USD
```

- **Qué demuestra:** las identidades publicadas por un catálogo son resolubles en los demás: el país apunta a su región y subregión, y la subregión pertenece a la misma región (coherencia). Currency resuelve en ambos sentidos la relación país–moneda.
- **En GI real:** Persons guarda `country_id` de una persona; con él obtiene su nombre localizado, su región o su moneda vigente sin duplicar datos.
- **Esperado:**
  1. `locale_id` = `7d74e7f4-…9a91`, `code` `es`.
  2. AR: `"name":"Argentina"`, `"official_name":"República Argentina"`, `region_id` = `29786b02-…7303`, `subregion_id` = `1cc20843-…2291`.
  3. Región: `"code":"019"`.
  4. Subregión: `"code":"419"` y `region_id` = `29786b02-…7303` (mismo padre que el país).
  5. Una sola moneda: `"alphabetic_code":"ARS"`.
  6. Dos `country_id`: `71705c97-…` (US) y `c756eac0-…` (PR).
- **PASS** si se cumplen los 6 puntos.
- **Limitación:** la comparación es visual sobre el JSON; la suite compara los campos de forma exacta (CA-5).

### M-08 Localización uniforme (sin fallback)

- **Objetivo:** comprobar que todos los catálogos traducen con el mismo `locale_id` y que no inventan traducciones.
- **Tipo:** funcional, positivo y un negativo. **Terminal B.**

```powershell
curl.exe -s "$B/v1/units/2f2fc747-50fd-5709-a665-4fa037eea3b2?locale_id=7d74e7f4-4dd7-4a85-a540-09d2393b9a91"   # kg en es
curl.exe -s "$B/v1/units/2f2fc747-50fd-5709-a665-4fa037eea3b2?locale_id=b8756f67-cbc0-4499-b3b6-453605c505b2"   # kg en fr (sin traducción)
curl.exe -s "$B/v1/regions/29786b02-6ca2-5d40-9c90-17e6bdf27303?locale_id=1d806402-a823-4580-9f4d-958c6e5a5354" # región 019 en en
curl.exe -s "$B/v1/currencies/12c3be84-c22e-5d01-adbf-f28c3aeb0807?locale_id=7d74e7f4-4dd7-4a85-a540-09d2393b9a91" # USD en es
curl.exe -s -w " [HTTP %{http_code}]" "$B/v1/countries/by-alpha2/AR?locale_id=not-a-uuid"                        # locale_id mal formado
```

- **Qué demuestra:** el idioma se pide con `locale_id`. Si existe la traducción se devuelve; si no, el campo vale **`null`** (no hay *fallback*: no se cae a inglés u otro idioma). `null` significa «no hay texto en ese idioma», que es distinto de un texto vacío. Un `locale_id` mal formado es un error del cliente: **HTTP 422**. `-w` hace que `curl.exe` imprima además el código HTTP.
- **Por qué sin fallback:** el consumidor decide qué mostrar cuando falta una traducción; un fallback silencioso mostraría un idioma equivocado sin que nadie lo note.
- **Esperado:** `"name":"kilogramo","plural":"kilogramos"`; con `fr`: `"name":null,"plural":null` (sin caer a otro idioma); región `"name":"Americas"`; moneda `"name":"dólar estadounidense"`; el último: `invalid_locale_id` y `[HTTP 422]`.
- **PASS** si los cinco coinciden.
- **Limitación:** localiza 3 de los 6 recursos localizables (unidad, región, moneda) y prueba un `locale_id` mal formado; la suite cubre los seis y el `locale_id` inexistente (CA-6).

### M-09 Conversiones de Units (precisión exacta, decimal como texto)

- **Objetivo:** convertir entre unidades de la misma magnitud y rechazar magnitudes incompatibles.
- **Tipo:** funcional, dos positivos y un negativo. **Terminal B.**

```powershell
# Cuerpos JSON: valor como texto, unidad origen, unidad destino y magnitud
$lbkg = '{"value":"1","from_unit_id":"577ce238-f253-50cf-b881-a9c879f4bfc9","to_unit_id":"2f2fc747-50fd-5709-a665-4fa037eea3b2","quantity_kind_id":"b5215a84-a8e2-5953-9de0-ac0c4a8aac78"}'  # 1 lb → kg (masa)
$cf   = '{"value":"100","from_unit_id":"d79e8834-8511-5935-9ad5-f828280842f7","to_unit_id":"59286a77-e65f-5055-97d6-dcf775bf9ab7","quantity_kind_id":"ca64bb7b-9824-5ca9-8888-b7d538630b30"}' # 100 °C → °F
$bad  = '{"value":"1","from_unit_id":"2f2fc747-50fd-5709-a665-4fa037eea3b2","to_unit_id":"3561fd3d-586a-58ed-adc5-1c8cd3b83951","quantity_kind_id":"b5215a84-a8e2-5953-9de0-ac0c4a8aac78"}'   # kg → m: incompatible
# POST de cada cuerpo; muestra result/exact, o el código HTTP y el error
foreach ($body in $lbkg, $cf, $bad) {
  try { (Invoke-RestMethod -Method Post -Uri "$B/v1/conversions" -ContentType "application/json" -Body $body).data | Select-Object result, exact }
  catch { "HTTP $($_.Exception.Response.StatusCode.value__) $($_.ErrorDetails.Message)" }
}
```

- **Qué demuestra:** lb→kg es una conversión lineal (factor) y °C→°F una afín (factor más desplazamiento); ambas con los factores de la tabla UCUM empaquetada. Pasar de masa a longitud se rechaza con `incompatible_units`.
- **Qué significa `exact`:** según el contrato (RF-27 y D-9 de 005), el cálculo se hace con aritmética racional exacta, sin `float` binario. `exact = True` indica que el resultado se entrega **sin redondeo**; si el valor exacto necesitara más de 34 dígitos significativos, se redondearía una sola vez (half-even) y `exact` sería `False`. El valor viaja como **texto decimal** para no perder precisión en JSON. `exact` se refiere a la aritmética sobre los factores definidos, no certifica la exactitud de la fuente de esos factores.
- **En GI real:** ERP o una vertical convierte cantidades de producto entre unidades sin errores de redondeo acumulados y sin permitir conversiones sin sentido.
- **Esperado:** `result 0.45359237 / exact True`; `result 212 / exact True`; `HTTP 422 {… "code":"incompatible_units" …}`.
- **PASS** si coinciden los tres.
- **Limitación:** tres conversiones; la suite agrega K→°C y km→m (CA-12) y las suites de 005 los límites de precisión. El bucle usa `$body`: no usar `$b`, que pisaría `$B` (§4.3).

### M-10 La API es de solo lectura

- **Objetivo:** confirmar que la API no ofrece operaciones de escritura.
- **Tipo:** técnico, negativo. **Terminal B.**

```powershell
# -X elige el método HTTP; -o NUL descarta el cuerpo; -w imprime sólo el código HTTP
curl.exe -s -o NUL -w "%{http_code}`n" -X DELETE "$B/v1/countries"
curl.exe -s -o NUL -w "%{http_code}`n" -X POST   "$B/v1/currencies"
curl.exe -s -o NUL -w "%{http_code}`n" -X PUT    "$B/v1/units"
```

- **Qué demuestra:** **405** (*Method Not Allowed*) significa que la ruta existe pero no acepta ese método: no hay endpoint para borrar, crear ni reemplazar. Los datos sólo cambian por incorporación de snapshots con la CLI y el rol `reference_loader`, un proceso autorizado y auditable (M-03, M-13). La única ruta `POST` es `/v1/conversions`, que calcula y no escribe.
- **Esperado:** `405` las tres veces.
- **PASS** si las tres respuestas son `405`.
- **Limitación:** prueba tres combinaciones de método y ruta; la suite prueba POST/PUT/PATCH/DELETE en todas las rutas (CA-10). Un 405 demuestra ausencia de la operación en la API, no permisos de base (eso es M-12).

### M-11 Contratos publicados

- **Objetivo:** confirmar que la API publica sus contratos OpenAPI.
- **Tipo:** técnico, positivo. **Terminal B.**

```powershell
# Pide cada documento OpenAPI y muestra su código HTTP
foreach ($p in "openapi.json","openapi/regions.json","openapi/countries.json","openapi/currencies.json","openapi/units.json") { curl.exe -s -o NUL -w "$p %{http_code}`n" "$B/v1/$p" }
```

- **Qué demuestra:** los cinco contratos están disponibles (`openapi.json` es el de Locale). Un consumidor puede descubrir la API y generar clientes desde ellos.
- **Esperado:** `200` en los cinco. (La igualdad exacta con `contracts/*.openapi.json` la verifica la suite automática, CA-11.)
- **PASS** si los cinco son `200`.
- **Limitación:** `200` prueba **disponibilidad**, no contenido. Que lo servido sea idéntico al contrato versionado sólo lo garantiza la suite.

### M-12 Protección de la base (aun con SQL directo)

- **Objetivo:** comprobar que la base se protege sola, aunque alguien saltee la API.
- **Tipo:** técnico, negativo. **Terminal B.**

```powershell
# Como admin (dueño del schema): intenta borrar un locale publicado
docker exec gi-ref-acc psql -U admin -d reference_acc -c "DELETE FROM reference.locale WHERE code='es';"
# Como reference_reader (conexión dentro del contenedor, puerto 5432): intenta borrar monedas
docker exec gi-ref-acc psql "postgresql://reference_reader:reader-pw@127.0.0.1:5432/reference_acc" -c "DELETE FROM reference.currency;"
```

- **Qué demuestra:** dos capas distintas. (1) Un **trigger** impide borrar físicamente un locale publicado incluso al dueño: los retiros son lógicos (`status = inactive`) por snapshot. (2) Los **permisos** de rol impiden que `reference_reader` escriba. Dentro del contenedor PostgreSQL escucha en 5432; el 55432 es sólo el puerto publicado hacia Windows.
- **API vs base:** M-10 prueba que la API no expone escrituras; M-12 que, aunque alguien conecte por SQL, la base mantiene sus invariantes (regla de `AGENTS.md`: proteger con constraints de base).
- **Esperado:** `ERROR:  published locales are never deleted` y `ERROR:  permission denied for table currency`.
- **PASS** si ambos fallan con esos mensajes.
- **Limitación:** un superusuario puede desactivar triggers; esto protege contra errores y accesos indebidos de roles de aplicación, no contra un administrador malicioso. La suite cubre todas las claves foráneas entre módulos y las inmutabilidades (CA-8).

### M-13 Deriva Countries → Currency (detección y reparación)

- **Objetivo:** reproducir un cambio controlado en un catálogo que deja inconsistente a otro, detectarlo y repararlo con una versión nueva.
- **Tipo:** funcional, de **deriva** (D1/D2). **Terminal B**: necesita `$py` y `REFERENCE_DATABASE_URL` para las CLIs y `$B` para el `curl.exe` final. Si se ejecuta en otra ventana, aplicar antes el bloque de sesión §4.3.

```powershell
& $py -m gi_common_reference.currencies.interfaces.cli check-integrity; $LASTEXITCODE                      # 1. estado inicial
& $py -m gi_common_reference.countries.interfaces.cli  incorporate .\acc-data\D1-countries-v2-retire-pr.json # 2. Countries v2: PR inactive
& $py -m gi_common_reference.currencies.interfaces.cli check-integrity; $LASTEXITCODE                      # 3. detectar la deriva
& $py -m gi_common_reference.currencies.interfaces.cli incorporate .\acc-data\D2-currencies-v2-close-pr.json # 4. Currency v2: cierra PR–USD
& $py -m gi_common_reference.currencies.interfaces.cli check-integrity; $LASTEXITCODE                      # 5. integridad restaurada
curl.exe -s "$B/v1/currencies/12c3be84-c22e-5d01-adbf-f28c3aeb0807/countries"                              # 6. países que usan USD hoy
```

- **Qué demuestra:** Countries y Currency se versionan por separado. La desactivación sintética de Puerto Rico es válida para Countries, pero deja abierta la asociación PR–USD, lo que viola **RF-19 de 004** (ninguna asociación activa con vigencia abierta sobre un país `inactive`). `check-integrity` lo detecta (exit 1, con el UUID de la asociación). La reparación no es editar la base: es una **nueva versión de Currency** (D2), validada contra Countries v2, que cierra la vigencia PR–USD y la conserva como historia.
- **Por qué importa:** muestra la gestión controlada de cambios entre catálogos: detectar, decidir y corregir con una versión auditable, sin borrar historia.
- **En GI real:** cuando ISO retira o reasigna un país, el equipo que mantiene Currency ve la violación y publica la versión que la corrige; los consumidores dejan de ver USD como moneda vigente de PR.
- **Esperado, en orden:**
  1. `INTEGRO: …` y `0`.
  2. `INCORPORADO snapshot_version=2 (…; 0 países nuevos, 1 actualizaciones, 0 recodificaciones)`.
  3. `INTEGRIDAD VIOLADA: 1 asociación(es) (RF-19)` con `b79074ab-8dbd-5e70-b59c-c4cfbcf2f384 … Country inactive` y `1`.
  4. `INCORPORADO snapshot_version=2 (…; country_snapshot_version=2; … 1 asociaciones actualizadas)`.
  5. `INTEGRO: …` y `0`.
  6. Un solo `country_id`: `71705c97-…` (US).
- **Cómo interpretar el `1` del paso 3:** es la **detección esperada** de la deriva, no un fallo del caso.
- **PASS** si se cumplen los seis.
- **Limitación:** la suite comprueba además que Currency v2 sobre Countries v1 se rechaza por RF-19 y que la API conserva PR en el historial (CA-15).

---

## 8. Restaurar el entorno

1. **Detener la API:** `Ctrl+C` en la Terminal A. Se puede cerrar esa ventana.
2. **(Opcional, verifica la reversibilidad de las migraciones; Terminal B)** `& $py -m alembic downgrade base` → sin error. `downgrade base` deshace todas las migraciones en orden inverso (0005 … 0001) y elimina tablas, triggers y permisos del schema. Después: `docker exec gi-ref-acc psql -U admin -d reference_acc -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='reference';"` → `1`. Que quede **una** tabla es lo correcto: sólo `alembic_version`, donde Alembic registra la revisión aplicada (ahora ninguna).
3. **Eliminar el contenedor y los datos:** `docker rm -f -v gi-ref-acc` (detiene y borra el contenedor; `-v` borra también el volumen anónimo donde la imagen `postgres` guarda la base, que con el `docker rm -f gi-ref-acc` original quedaba huérfano) y `Remove-Item -Recurse -Force .\acc-data` (borra el dataset sintético).
4. **Limpiar variables:** `Remove-Item Env:REFERENCE_MIGRATION_DATABASE_URL, Env:REFERENCE_DATABASE_URL, Env:REFERENCE_READER_DATABASE_URL`. Opcionalmente `Remove-Item Env:PYTHONUTF8`. `$py` y `$B` desaparecen al cerrar la ventana (o con `Remove-Variable py, B`).

Para repetir la validación desde cero, volver a §4.4 (y aplicar el bloque de sesión §4.3 si la ventana es nueva).

---

## 9. Checklist final y registro

El checklist **no es una batería nueva de pruebas**: consolida por módulo los resultados ya obtenidos en M-01 a M-13 y §8. Una fila es PASS sólo si todos los casos que cita fueron PASS.

| Módulo | Casos | PASS/FAIL |
|---|---|---|
| Transversal (migraciones, global, privilegios) | M-01, M-02, M-12 | |
| 001 Locale | M-03 (línea 1), M-04, M-07 (1), M-08 | |
| 002 Region/Subregion | M-03 (línea 2), M-07 (3, 4), M-08 (región) | |
| 003 Countries | M-03 (línea 3), M-04 (`diff`), M-05 (N1), M-07 (2), M-13 (2) | |
| 004 Currency | M-03 (línea 4), M-05 (N2), M-07 (5, 6), M-08 (moneda), M-13 | |
| 005 Units of Measure | M-03 (línea 5), M-04, M-08 (unidad), M-09 | |
| API y contratos | M-06, M-10, M-11 | |
| Restauración | §8 | |

**Aceptado** solo si todas las filas son PASS.

### Cómo registrar una ejecución

| Campo | Qué anotar |
|---|---|
| Fecha | día de la ejecución |
| Responsable | quién ejecutó y quién acepta |
| Revisión Git | salida de `git rev-parse HEAD` en la copia validada (§4.1); nunca inferirla después |
| Entorno | versión de Python, Docker y PowerShell |
| Resultados | PASS/FAIL de M-01 a M-13 y §8; para cada FAIL, la salida observada |
| Incidentes | problemas del entorno o del manual y cómo se resolvieron |
| Evidencias | dónde están las capturas o transcripciones, si se guardaron |

### Registro: ejecución humana de 001–005 (2026-11)

Resultados **comunicados por el responsable humano**; no son evidencia automatizada:

- M-01 a M-13: **13/13 PASS**. Restauración (§8): **PASS**.
- Incidentes, ya incorporados a este manual: (1) la instalación con pip falló por una instalación `--user` forzada dentro del virtualenv; se resolvió con `--no-user` (§4.2); (2) M-13 falló al ejecutarse en una segunda ventana sin `$py` definido; se resolvió definiendo las variables de sesión (§4.3, §5).
- Ejecutado desde el worktree `D:\Proyectos\worktrees\gi-common-references\006-cross-module-acceptance`. **Fecha exacta y SHA de la revisión ejecutada: no registrados.** El worktree estaba en `5dff6bf` el 2026-11-20, lo que por sí solo no prueba que esa fuera la revisión ejecutada.
- Los ajustes posteriores de comandos de esta versión del manual (`--no-user`, `$py` absoluto, bloque de sesión y flujo de dos terminales, `git rev-parse HEAD`, `docker rm -f -v`) **no fueron ensayados de punta a punta** como conjunto; la próxima ejecución debe registrarse con este formato.

La **evidencia automatizada** es independiente de este registro: la suite de la spec 006 (`28 passed` sobre `22111e7`, en [`acceptance/cross-module/evidence/`](../acceptance/cross-module/evidence/)) y su revisión independiente están documentadas en [`specs/006-cross-module-acceptance/status.md`](../specs/006-cross-module-acceptance/status.md).

---

## 10. Fuera del alcance de este manual (declarado)

- **Banderas de Countries** (`GET /v1/countries/{id}/flag`): el paquete no trae SVG hasta el dataset real de PREP (spec 003, S-7); se valida en las suites de 003 con un almacén de pruebas.
- **Datasets reales** (ISO 3166/4217, CLDR, M49, UCUM/UNECE completos) y **Supabase `gi-dev`**: pendientes declarados de 003–005 (`DEFERRED_TO_PREP_DATASET`).
- Los casos límite de cada catálogo (recodificaciones, reemplazos, vigencias temporales, redondeo half-even, etc.) están en las aceptaciones y suites de cada módulo: `acceptance/currencies/`, `acceptance/units/` y `tests/`.

---

## 11. Relación con AI-NATIVE y auditoría posterior

El repositorio sigue el workflow de AI-NATIVE (`ai-native.lock.json`, v4.0.1): spec aprobada → plan → tasks → implementación → Quality Gates → Independent Review → HITL (merge humano).

**Objetivo del circuito SDD/Acceptance.** La intención arquitectónica es que cada feature produzca, según corresponda: pruebas funcionales, de integración, negativas y de límites, y transversales entre módulos; generadores de datos sintéticos; ejecución autónoma y un manual reproducible de aceptación humana; resultados y evidencias con trazabilidad a los requisitos; y su paso por Quality Gates, Independent Review y HITL.

**Lo que hoy está demostrado** para 001–005 es lo que registran sus specs y `status.md`: en particular, la spec 006 construyó la aceptación transversal, el generador de datos, la evidencia y este manual **como trabajo de la feature**, porque AI-NATIVE v4.0.1 no ofrece comandos de Native Acceptance ni de Dependency Graph (`specs/006-cross-module-acceptance/status.md`, «Gates»). No debe asumirse que AI-NATIVE v4.0.1 genera o garantiza esas capacidades de forma nativa.

**Auditoría posterior (pendiente, no ejecutada).** Verificar sobre AI-NATIVE:

1. Activación automática de Acceptance por cada feature SDD.
2. Generación automática de pruebas y datasets sintéticos.
3. Ejecución autónoma y manual de la aceptación.
4. Quality Gates, evidencias e Independent Review asociados a la aceptación.
5. Calidad y claridad de la documentación de aceptación generada.

Con su resultado se determinará si corresponde una versión AI-NATIVE v4.0.2. Esta auditoría es un pendiente solicitado por el responsable humano al revisar este manual; todavía no está registrada en specs ni en AI-NATIVE. Este manual no modifica AI-NATIVE.
