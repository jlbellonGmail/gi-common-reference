# Aceptación transversal 006 — evidencia

Caja negra de los cinco catálogos juntos: Postgres 16 descartable (testcontainers), `alembic upgrade head` como subproceso, cada catálogo incorporado con **su CLI** en el orden `locales → regions → countries → currencies → units`, y la API real (uvicorn, rol `reference_reader`) por HTTP. Todos los procesos corren con el guard de red de 004. Datos sintéticos, deterministas y no productivos (`tests/fixtures/*`).

Reproducir (Docker en ejecución):

```text
python tools/acceptance/cross_module_acceptance.py
```

| Archivo | Contenido |
|---|---|
| `evidence/01-environment.txt` | Python, `git HEAD`, base del diff (CA-14), versión de AI-NATIVE, paquetes, código de salida |
| `evidence/02-inputs-sha256.json` | sha256 de cada snapshot enviado a las CLIs |
| `evidence/03-commands.json` | cada comando (`alembic`, CLIs, SQL directo de CA-8, diff de git) con exit code y salidas normalizadas (sin puertos, base ni contraseñas) |
| `evidence/04-http-transcripts.json` | cada petición HTTP con su estado y cuerpo |
| `evidence/05-acceptance-results.txt` | salida de pytest (`-v`) |
| `evidence/06-manifest-sha256.txt` | sha256 de 01–05 |

## Estado por criterio (spec 006)

Resultado de la ejecución registrada en `evidence/` (revisión en `01-environment.txt`): **28 passed, 0 failed, 0 skipped**.

| Criterio | Qué demuestra | Estado |
|---|---|---|
| CA-1 | head `0005`; dueño único por tabla; sin `tenant_id`; sin privilegios públicos; reader solo `SELECT` | PASS |
| CA-2 | grafo = FKs reales = specs = migraciones = `architecture.json`; sin imports entre módulos | PASS (incluye 2 mutaciones automáticas del grafo) |
| CA-3 | cinco CLIs en orden; `diff` no escribe | PASS |
| CA-4 | reincorporación idempotente (dump idéntico) | PASS |
| CA-5 | navegación Locale → País → Región/Subregión → Moneda → Units; 1 lb → kg exacto | PASS |
| CA-6 | localización uniforme en 6 recursos; sin fallback; locale inválido → 4xx | PASS (×6) |
| CA-7 | rechazos por referencia a otro módulo, con motivo verificado y sin escritura | PASS |
| CA-8 | FKs entre módulos (23503) e inmutabilidad (23001) con SQL directo | PASS |
| CA-9 | orden de dependencias forzado en runtime; `downgrade base`/`upgrade head` reversible | PASS |
| CA-10 | API de solo lectura (405); reader sin escritura (42501) | PASS |
| CA-11 | OpenAPI servido = contratos publicados (5) | PASS (×5) |
| CA-12 | conversiones exactas lineales y afines; incompatibles → 4xx | PASS (×5) |
| CA-13 | ningún proceso salió de localhost | PASS |
| CA-14 | 006 no toca código, migraciones, contratos, specs 001–005 ni pruebas existentes | PASS |
| CA-15 | deriva Countries→Currency detectada por `check-integrity` y reparada con Currency v2 | PASS |

## No cubierto aquí (declarado)

- `GET /v1/countries/{id}/flag`: el paquete no trae SVG hasta el dataset de PREP (003, S-7); cubierto por las suites de 003 con almacén inyectado. **NOT_EXECUTED** en caja negra.
- Datasets reales (ISO/CLDR/M49/UCUM/UNECE completos) y Supabase `gi-dev`: **DEFERRED_TO_PREP_DATASET** (pendientes declarados de 003–005).
- CI: el repositorio no tiene CI; esta evidencia es local.
