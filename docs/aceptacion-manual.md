# Manual de aceptación funcional — gi-common-reference (001–005)

Guía para que el responsable humano valide **a mano** los cinco catálogos (Locale, Region/Subregion, Countries, Currency, Units of Measure), individualmente y en conjunto, sin conocer la implementación. Cada caso indica comando, resultado esperado y criterio PASS/FAIL. Las salidas esperadas se copiaron de un ensayo real de este mismo manual (2026-11-18, revisión de la rama `feature/006-cross-module-acceptance`).

> **Todo ocurre en un Postgres descartable en Docker (puerto 55432).** No usar nunca una URL de Supabase ni de un entorno compartido. Los datos son **sintéticos y no productivos**.

La versión automatizada de estos mismos casos es `tests/acceptance/test_cross_module_acceptance.py` (runner: `python tools/acceptance/cross_module_acceptance.py`); la evidencia de su última ejecución está en `acceptance/cross-module/evidence/`.

---

## 0. Prerrequisitos

| Requisito | Verificación | Esperado |
|---|---|---|
| Docker Desktop en ejecución | `docker version --format '{{.Server.Version}}'` | un número de versión, sin error |
| Python ≥ 3.12 | `python --version` | `Python 3.12` o superior |
| Git y el repositorio | `git -C D:\Proyectos\gi-common-reference status` | sin error |
| Puertos libres 55432 y 8000 | `netstat -ano \| findstr ":55432 :8000"` | ninguna línea `LISTENING` |
| `curl.exe` (Windows 10+) | `curl.exe --version` | una versión |

Todos los comandos están en **PowerShell**, desde la raíz de una copia del repositorio en la revisión a validar.

## 1. Preparar el entorno (una vez)

```powershell
# 1.1 Revisión a validar (o usar el worktree D:\Proyectos\worktrees\gi-common-references\006-cross-module-acceptance)
git fetch origin
git switch feature/006-cross-module-acceptance

# 1.2 Entorno Python aislado
python -m venv .venv
.\.venv\Scripts\python -m pip install -c constraints.txt -e ".[dev]"
$env:PYTHONUTF8 = "1"
$py = ".\.venv\Scripts\python"

# 1.3 Postgres 16 descartable
docker run -d --name gi-ref-acc -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=admin-pw `
  -e POSTGRES_DB=reference_acc -p 55432:5432 postgres:16-alpine
docker exec gi-ref-acc pg_isready -U admin -d reference_acc   # repetir hasta "accepting connections"

# 1.4 Roles (ANTES de migrar; las contraseñas son solo de este entorno descartable)
docker exec gi-ref-acc psql -U admin -d reference_acc -v ON_ERROR_STOP=1 -c "CREATE ROLE reference_reader LOGIN PASSWORD 'reader-pw'; CREATE ROLE reference_loader LOGIN PASSWORD 'loader-pw'; CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN;"

# 1.5 Variables (una por rol: migración = dueño, CLI = loader, API = reader)
$env:REFERENCE_MIGRATION_DATABASE_URL = "postgresql://admin:admin-pw@127.0.0.1:55432/reference_acc"
$env:REFERENCE_DATABASE_URL           = "postgresql://reference_loader:loader-pw@127.0.0.1:55432/reference_acc"
$env:REFERENCE_READER_DATABASE_URL    = "postgresql://reference_reader:reader-pw@127.0.0.1:55432/reference_acc"

# 1.6 Dataset sintético (determinista)
& $py tools/acceptance/write_acceptance_dataset.py .\acc-data
```

**PASS 1.4:** cuatro líneas `CREATE ROLE`. **PASS 1.6:** se imprimen exactamente estas sumas (si alguna difiere, el dataset no es el validado: FAIL y no continuar):

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

### Datos de prueba

| Archivo | Contenido |
|---|---|
| `01-locales-v1` | Locales `en`, `es`, `fr` (fr sin traducciones en los demás catálogos) |
| `02-regions-v1` | Regiones M49 002 África, 019 Américas, 142 Asia; subregiones 202, 419, 021, 035 |
| `03-countries-v1` | AR, NA, AQ, TW, US, CA, PR, BV (con excepciones de bandera: el paquete aún no trae SVG, ver §5) |
| `04-currencies-v1` | ARS, USD, EUR, JPY, XAU; asociaciones AR–ARS, US–USD, PR–USD (desde 1899-01-01) |
| `05-units-v1` | 14 magnitudes, 50 unidades, 54 asociaciones (incluye masa, longitud, temperatura) |
| `N1`, `N2` | Snapshots inválidos que referencian algo inexistente en otro catálogo |
| `D1`, `D2` | Deriva: Countries v2 retira PR; Currency v2 cierra la vigencia PR–USD |

### Identificadores usados en las consultas

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

## 2. Casos

Registrar cada caso como PASS o FAIL en el checklist (§4). Un FAIL no se «corrige» repitiendo: anotar la salida y continuar.

### M-01 Migraciones (todos los módulos)

```powershell
& $py -m alembic upgrade head
& $py -m alembic current
```

**Esperado:** la última línea de `current` es `0005 (head)`. **PASS** si coincide; **FAIL** si hay error o otra revisión.

### M-02 Catálogos globales y privilegios mínimos

```powershell
docker exec gi-ref-acc psql -U admin -d reference_acc -tAc "SELECT count(*) FROM information_schema.columns WHERE table_schema='reference' AND column_name ILIKE '%tenant%';"
docker exec gi-ref-acc psql -U admin -d reference_acc -tAc "SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema='reference' AND grantee IN ('anon','authenticated','PUBLIC');"
```

**Esperado:** `0` y `0` (ninguna columna de tenant, ningún privilegio público). **PASS** si ambos son `0`.

### M-03 Incorporación en orden de dependencias (Locale → Regions → Countries → Currency → Units)

```powershell
& $py -m gi_common_reference.locales.interfaces.cli    incorporate .\acc-data\01-locales-v1.json
& $py -m gi_common_reference.regions.interfaces.cli    incorporate .\acc-data\02-regions-v1.json
& $py -m gi_common_reference.countries.interfaces.cli  incorporate .\acc-data\03-countries-v1.json
& $py -m gi_common_reference.currencies.interfaces.cli incorporate .\acc-data\04-currencies-v1.json
& $py -m gi_common_reference.units.interfaces.cli      incorporate .\acc-data\05-units-v1.json
```

**Esperado** (una línea por comando, `$LASTEXITCODE` = 0 en cada uno):

```text
INCORPORADO snapshot_version=1 (3 nuevos, 0 actualizados)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; 3 regiones nuevas, 4 subregiones nuevas, 0 actualizaciones, 0 reclasificaciones, 0 recodificaciones)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; region_snapshot_version=1; 8 países nuevos, 0 actualizaciones, 0 recodificaciones)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; country_snapshot_version=1; 5 monedas nuevas, 0 actualizadas, 10 localizaciones, 3 asociaciones nuevas, 0 asociaciones actualizadas)
INCORPORADO snapshot_version=1 (locale_snapshot_version=1; ucum_table_version=2.2; 50 unidades nuevas, 0 actualizadas, 14 magnitudes nuevas, 0 actualizadas, 54 asociaciones nuevas, 0 actualizadas, 128 localizaciones)
```

### M-04 Idempotencia y `diff` sin escritura

```powershell
& $py -m gi_common_reference.locales.interfaces.cli   incorporate .\acc-data\01-locales-v1.json
& $py -m gi_common_reference.units.interfaces.cli     incorporate .\acc-data\05-units-v1.json
& $py -m gi_common_reference.countries.interfaces.cli diff        .\acc-data\03-countries-v1.json
```

**Esperado:** `NO-OP snapshot_version=1 ya incorporado` (×2) y `NO-OP snapshot_version=1 ya incorporado: sin cambios`; exit 0. **PASS** si coincide.

### M-05 Integridad referencial entre catálogos (rechazo al incorporar)

```powershell
& $py -m gi_common_reference.countries.interfaces.cli  incorporate .\acc-data\N1-countries-v2-ghost-region.json; $LASTEXITCODE
& $py -m gi_common_reference.currencies.interfaces.cli incorporate .\acc-data\N2-currencies-v2-future-countries.json; $LASTEXITCODE
```

**Esperado:**

```text
RECHAZADO snapshot_version=2
  - RF-6: país 35be21fd-7ddb-5ffb-b954-c8c9f87519d9 (BV): la region_id 00000000-0000-4000-8000-000000000000 no existe en Region/Subregion
1
RECHAZADO snapshot_version=2
  - RF-41: la country_snapshot_version 2 declarada no está incorporada
1
```

**PASS** si ambos se rechazan con exit 1 y ese motivo; **FAIL** si alguno se incorpora.

### M-06 Arrancar la API (dejar esta ventana abierta)

```powershell
& $py -m uvicorn --factory gi_common_reference.app:app_from_environment --host 127.0.0.1 --port 8000
```

En **otra** ventana PowerShell (con `$B = "http://127.0.0.1:8000"`) ejecutar M-07 a M-11.

### M-07 Navegación entre catálogos por identidades estables

```powershell
curl.exe -s "$B/v1/locales/by-code/es"
curl.exe -s "$B/v1/countries/by-alpha2/AR?locale_id=7d74e7f4-4dd7-4a85-a540-09d2393b9a91"
curl.exe -s "$B/v1/regions/29786b02-6ca2-5d40-9c90-17e6bdf27303"
curl.exe -s "$B/v1/subregions/1cc20843-3e0c-5637-b7a4-d220f48c2291"
curl.exe -s "$B/v1/currencies/by-country/fe4be564-5597-5c73-b0c0-18ad9209f207"
curl.exe -s "$B/v1/currencies/12c3be84-c22e-5d01-adbf-f28c3aeb0807/countries"
```

**Esperado:**
1. `locale_id` = `7d74e7f4-…9a91`, `code` `es`.
2. AR: `"name":"Argentina"`, `"official_name":"República Argentina"`, `region_id` = `29786b02-…7303`, `subregion_id` = `1cc20843-…2291`.
3. Región: `"code":"019"`.
4. Subregión: `"code":"419"` y `region_id` = `29786b02-…7303` (mismo padre que el país).
5. Una sola moneda: `"alphabetic_code":"ARS"`.
6. Dos `country_id`: `71705c97-…` (US) y `c756eac0-…` (PR).

**PASS** si se cumplen los 6 puntos.

### M-08 Localización uniforme (sin fallback)

```powershell
curl.exe -s "$B/v1/units/2f2fc747-50fd-5709-a665-4fa037eea3b2?locale_id=7d74e7f4-4dd7-4a85-a540-09d2393b9a91"
curl.exe -s "$B/v1/units/2f2fc747-50fd-5709-a665-4fa037eea3b2?locale_id=b8756f67-cbc0-4499-b3b6-453605c505b2"
curl.exe -s "$B/v1/regions/29786b02-6ca2-5d40-9c90-17e6bdf27303?locale_id=1d806402-a823-4580-9f4d-958c6e5a5354"
curl.exe -s "$B/v1/currencies/12c3be84-c22e-5d01-adbf-f28c3aeb0807?locale_id=7d74e7f4-4dd7-4a85-a540-09d2393b9a91"
curl.exe -s -w " [HTTP %{http_code}]" "$B/v1/countries/by-alpha2/AR?locale_id=not-a-uuid"
```

**Esperado:** `"name":"kilogramo","plural":"kilogramos"`; con `fr`: `"name":null,"plural":null` (sin caer a otro idioma); región `"name":"Americas"`; moneda `"name":"dólar estadounidense"`; el último: `invalid_locale_id` y `[HTTP 422]`. **PASS** si los cinco coinciden.

### M-09 Conversiones de Units (precisión exacta, decimal como texto)

```powershell
$lbkg = '{"value":"1","from_unit_id":"577ce238-f253-50cf-b881-a9c879f4bfc9","to_unit_id":"2f2fc747-50fd-5709-a665-4fa037eea3b2","quantity_kind_id":"b5215a84-a8e2-5953-9de0-ac0c4a8aac78"}'
$cf   = '{"value":"100","from_unit_id":"d79e8834-8511-5935-9ad5-f828280842f7","to_unit_id":"59286a77-e65f-5055-97d6-dcf775bf9ab7","quantity_kind_id":"ca64bb7b-9824-5ca9-8888-b7d538630b30"}'
$bad  = '{"value":"1","from_unit_id":"2f2fc747-50fd-5709-a665-4fa037eea3b2","to_unit_id":"3561fd3d-586a-58ed-adc5-1c8cd3b83951","quantity_kind_id":"b5215a84-a8e2-5953-9de0-ac0c4a8aac78"}'
foreach ($body in $lbkg, $cf, $bad) {
  try { (Invoke-RestMethod -Method Post -Uri "$B/v1/conversions" -ContentType "application/json" -Body $body).data | Select-Object result, exact }
  catch { "HTTP $($_.Exception.Response.StatusCode.value__) $($_.ErrorDetails.Message)" }
}
```

**Esperado:** `result 0.45359237 / exact True`; `result 212 / exact True`; `HTTP 422 {… "code":"incompatible_units" …}`. **PASS** si coinciden los tres.

### M-10 La API es de solo lectura

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" -X DELETE "$B/v1/countries"
curl.exe -s -o NUL -w "%{http_code}`n" -X POST   "$B/v1/currencies"
curl.exe -s -o NUL -w "%{http_code}`n" -X PUT    "$B/v1/units"
```

**Esperado:** `405` las tres veces.

### M-11 Contratos publicados

```powershell
foreach ($p in "openapi.json","openapi/regions.json","openapi/countries.json","openapi/currencies.json","openapi/units.json") { curl.exe -s -o NUL -w "$p %{http_code}`n" "$B/v1/$p" }
```

**Esperado:** `200` en los cinco. (La igualdad exacta con `contracts/*.openapi.json` la verifica la suite automática, CA-11.)

### M-12 Protección de la base (aun con SQL directo)

```powershell
docker exec gi-ref-acc psql -U admin -d reference_acc -c "DELETE FROM reference.locale WHERE code='es';"
docker exec gi-ref-acc psql "postgresql://reference_reader:reader-pw@127.0.0.1:5432/reference_acc" -c "DELETE FROM reference.currency;"
```

**Esperado:** `ERROR:  published locales are never deleted` y `ERROR:  permission denied for table currency`. **PASS** si ambos fallan.

### M-13 Deriva Countries → Currency (detección y reparación)

```powershell
& $py -m gi_common_reference.currencies.interfaces.cli check-integrity; $LASTEXITCODE
& $py -m gi_common_reference.countries.interfaces.cli  incorporate .\acc-data\D1-countries-v2-retire-pr.json
& $py -m gi_common_reference.currencies.interfaces.cli check-integrity; $LASTEXITCODE
& $py -m gi_common_reference.currencies.interfaces.cli incorporate .\acc-data\D2-currencies-v2-close-pr.json
& $py -m gi_common_reference.currencies.interfaces.cli check-integrity; $LASTEXITCODE
curl.exe -s "$B/v1/currencies/12c3be84-c22e-5d01-adbf-f28c3aeb0807/countries"
```

**Esperado, en orden:**
1. `INTEGRO: …` y `0`.
2. `INCORPORADO snapshot_version=2 (…; 0 países nuevos, 1 actualizaciones, 0 recodificaciones)`.
3. `INTEGRIDAD VIOLADA: 1 asociación(es) (RF-19)` con `b79074ab-8dbd-5e70-b59c-c4cfbcf2f384 … Country inactive` y `1`.
4. `INCORPORADO snapshot_version=2 (…; country_snapshot_version=2; … 1 asociaciones actualizadas)`.
5. `INTEGRO: …` y `0`.
6. Un solo `country_id`: `71705c97-…` (US).

**PASS** si se cumplen los seis.

---

## 3. Restaurar el entorno

1. Detener la API: `Ctrl+C` en la ventana de M-06.
2. (Opcional, verifica la reversibilidad de las migraciones) `& $py -m alembic downgrade base` → sin error; después `docker exec gi-ref-acc psql -U admin -d reference_acc -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='reference';"` → `1` (solo `alembic_version`).
3. Eliminar el contenedor y los datos: `docker rm -f gi-ref-acc` y `Remove-Item -Recurse -Force .\acc-data`.
4. Limpiar variables: `Remove-Item Env:REFERENCE_MIGRATION_DATABASE_URL, Env:REFERENCE_DATABASE_URL, Env:REFERENCE_READER_DATABASE_URL`.

Para repetir la validación desde cero, volver a §1.3.

## 4. Checklist final

| Módulo | Casos | PASS/FAIL |
|---|---|---|
| Transversal (migraciones, global, privilegios) | M-01, M-02, M-12 | |
| 001 Locale | M-03 (línea 1), M-04, M-07 (1), M-08 | |
| 002 Region/Subregion | M-03 (línea 2), M-07 (3, 4), M-08 (región) | |
| 003 Countries | M-03 (línea 3), M-04 (`diff`), M-05 (N1), M-07 (2), M-13 (2) | |
| 004 Currency | M-03 (línea 4), M-05 (N2), M-07 (5, 6), M-08 (moneda), M-13 | |
| 005 Units of Measure | M-03 (línea 5), M-04, M-08 (unidad), M-09 | |
| API y contratos | M-06, M-10, M-11 | |
| Restauración | §3 | |

**Aceptado** solo si todas las filas son PASS. Registrar fecha, revisión (`git rev-parse HEAD`) y responsable.

## 5. Fuera del alcance de este manual (declarado)

- **Banderas de Countries** (`GET /v1/countries/{id}/flag`): el paquete no trae SVG hasta el dataset real de PREP (spec 003, S-7); se valida en las suites de 003 con un almacén de pruebas.
- **Datasets reales** (ISO 3166/4217, CLDR, M49, UCUM/UNECE completos) y **Supabase `gi-dev`**: pendientes declarados de 003–005 (`DEFERRED_TO_PREP_DATASET`).
- Los casos límite de cada catálogo (recodificaciones, reemplazos, vigencias temporales, redondeo half-even, etc.) están en las aceptaciones y suites de cada módulo: `acceptance/currencies/`, `acceptance/units/` y `tests/`.
