# Aceptación de 001-locales en Supabase gi-dev

Despliegue y prueba real del catálogo de locales (spec 001) en el proyecto Supabase `gi-dev` (`gletzbwuvmwjkmoufmyj`, PostgreSQL 17.6, `sa-east-1`), sin UI, el 2026-10-21.

Circuito: registro IANA versionado → snapshot → CLI de incorporación → Postgres de gi-dev → API HTTP.

## Snapshot publicado en gi-dev

`locale-snapshot.v1.2.json` es el snapshot incorporado en gi-dev. **No se regenera, no se borra y no se reemplaza sin autorización:** sus `locale_id` son la identidad publicada de gi-dev y los locales publicados no se pueden borrar (RNF-8). PREP (`gi-common-reference-prep`) debe reutilizar exactamente estos `locale_id` en los próximos snapshots para gi-dev.

| Dato | Valor |
|---|---|
| `snapshot_version` | 2 (aprobado: la spec admite saltos; permite probar el rechazo de un snapshot anterior nunca visto) |
| IANA `File-Date` | 2026-09-17 |
| `iana.digest` | `sha256:755fad43283be7b41ebe3c89ad054b6eaf928f404f9c0edb74799e0eab74beb1` |
| `content_digest` | `sha256:39fe0b00249a94214a95a182e9c4df24583f267a562b8676b00f9f189a94e3f7` |
| SHA-256 del archivo | `evidence/00-snapshot-sha256.txt` |
| Locales | 8159 (8039 `active`, 120 `inactive`, 120 con deprecación IANA, 0 con `replacement`) |
| Alias (*Preferred-Value*) | 112 (p. ej. `iw`→`he`, `in`→`id`, `ji`→`yi`, `mo`→`ro`) |

Lo generó `tools/acceptance/build_locale_snapshot.py` a partir del blob versionado `tests/fixtures/iana-language-subtag-registry.txt` (con LF, tal como lo publica IANA; el checkout de Windows con `core.autocrlf` lo convierte a CRLF). Es tooling de aceptación, no runtime de Reference ni sustituto de PREP. `.gitattributes` conserva los bytes exactos del JSON.

## Roles y dueño del schema

Roles creados según `docs/operacion.md` (paso 1), con contraseñas guardadas fuera del repositorio:

- `reference_reader`, `reference_loader`: los del runbook.
- `reference_owner`: dueño del schema `reference` y rol de `alembic` (`REFERENCE_MIGRATION_DATABASE_URL`). Solo tiene `LOGIN` y `CREATE` sobre la base: no es superusuario, no crea roles ni bases y no tiene `BYPASSRLS` (decisión aprobada).

**Diferencia con los demás schemas GI:** `core`, `persons`, `crm` y `tenants` son de `postgres`; `reference` es de `reference_owner`.

Conexión: el host directo `db.<ref>.supabase.co` solo publica IPv6, así que todo se ejecutó por el pooler Supavisor en modo sesión (`aws-0-sa-east-1.pooler.supabase.com:5432`, usuario `<rol>.gletzbwuvmwjkmoufmyj`).

## Reproducir las verificaciones

```text
python tools/acceptance/validate_locale_snapshot.py acceptance/locales/gi-dev/locale-snapshot.v1.2.json
python tools/acceptance/gi_dev.py --credentials <json fuera del repo> \
    --pooler-host aws-0-sa-east-1.pooler.supabase.com <comando>
```

Comandos: `probe`, `migrate`, `inspect`, `incorporate <archivo>`, `stats`, `negatives <archivo>`, `security`, `api --total N --active N --inactive N`. Solo `migrate` e `incorporate` escriben, y únicamente por las vías oficiales (`alembic upgrade head` y la CLI). `negatives` y `security` comprueban que la base queda idéntica.

## Evidencia (`evidence/`)

| Archivo | Contenido |
|---|---|
| `00-snapshot-validation.txt` | JSON Schema publicado, lector de la CLI, admisión y plan del dominio |
| `01-migrate.txt` | login de los tres roles y `alembic upgrade head` → `0001 (head)` |
| `02-inspect.txt` | schema, tablas, constraints, FK, triggers, privilegios y `runbook:verify` |
| `03-incorporate.txt` | `INCORPORADO snapshot_version=2 (8159 nuevos, 0 actualizados)` |
| `04-stats.txt`, `09-stats-final.txt` | conteos, metadata del snapshot y ejemplos |
| `05-idempotency.txt` | reincorporación: `NO-OP`, base idéntica |
| `06-negatives.txt` | 12 rechazos (exit 1, regla esperada, base idéntica) |
| `07-security.txt` | matriz de permisos y triggers por rol; anon/authenticated/PUBLIC sin acceso |
| `08-api.txt` | 35 pruebas HTTP contra uvicorn conectado a gi-dev con `reference_reader` |
| `10-postgrest-exposed-schemas.txt` | `reference` no está entre los schemas expuestos por PostgREST |
