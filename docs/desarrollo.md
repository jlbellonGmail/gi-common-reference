# Desarrollo y CI

Requisitos del entorno para correr la suite completa de `gi-common-reference`. Ninguno es opcional: si falta alguno, las pruebas que lo necesitan **fallan** con un mensaje que indica cómo provisionarlo. No se saltan.

## Requisitos

| Requisito | Para qué | Cómo provisionarlo |
|---|---|---|
| Python ≥ 3.12 | servicio y pruebas | entorno virtual propio |
| Docker en ejecución | `tests/integration` y `tests/contract` levantan `postgres:16-alpine` con testcontainers | Docker Desktop o un daemon Docker accesible; la imagen se descarga la primera vez |
| `node` en el PATH | el check `architecture` de AI-NATIVE y los comandos `sdd` / `hitl` | instalar Node.js |
| Release de AI-NATIVE en la caché local | `tests/contract/test_architecture_contract.py` y `test_module_contract.py` ejecutan el check `architecture` de la release fijada en `ai-native.lock.json` | ver más abajo |

`setuptools` (extra `dev`) es necesario para `tests/contract/test_installed_package.py`, que construye el wheel del proyecto sin red y ejecuta la CLI desde esa instalación.

`tests/unit` no usa ninguna fixture de base de datos, así que no necesita Docker, `node` ni la caché. `node` y la caché solo los exigen las dos pruebas de arquitectura de `tests/contract`.

### Release de AI-NATIVE (caché)

El check `architecture` se toma de la release que fija `ai-native.lock.json`, desde la caché local de AI-NATIVE: `$AI_NATIVE_CACHE`, o `~/.ai-native/cache` si la variable no existe. Es la misma caché que usa `node .ai-native/ai-native.mjs`. Se provisiona una vez, con el bootstrap de cualquier copia de esa release:

```text
node <release>/runtime/bootstrap/cli.mjs sync --project .
```

En CI, ese paso debe ejecutarse antes de `pytest` (y, si se cachea el directorio, la clave de caché debe incluir el `platform.digest` de `ai-native.lock.json`). Si la release no está, `pytest` falla con el digest que falta y esta instrucción.

## Instalación reproducible

`constraints.txt` fija las versiones validadas de todas las dependencias, directas y transitivas:

```text
python -m venv .venv
pip install -c constraints.txt -e ".[dev]"
```

`pyproject.toml` declara qué se necesita; `constraints.txt` declara con qué versiones se validó. Para actualizar dependencias, instalar sin `-c` en un entorno limpio, correr la verificación completa y regenerar el archivo con el comando de su cabecera. El OpenAPI publicado (`contracts/locales-api.v1.openapi.json`) se compara como JSON (igualdad semántica del documento parseado: el orden de las claves y el formato no importan) con el generado, así que una actualización de `fastapi` o `pydantic` puede exigir regenerarlo.

## Schema del snapshot: dos copias

El schema del snapshot existe en dos lugares, y deben ser equivalentes (`tests/contract/test_packaged_schema.py` lo verifica como JSON):

- `src/gi_common_reference/locales/infrastructure/locale-snapshot.v1.schema.json`: la copia que viaja dentro del paquete instalado; la CLI la carga con `importlib.resources`.
- `contracts/locale-snapshot.v1.schema.json`: la copia publicada para PREP.

Al cambiar el schema, editar una y copiarla sobre la otra.

## Verificación

```text
pytest -q
ruff format --check . && ruff check .
mypy
node .ai-native/ai-native.mjs sdd validate 001-locales
node .ai-native/ai-native.mjs hitl --base develop
```

Para desplegar y operar el servicio (roles, migraciones, API, incorporación), ver [`operacion.md`](operacion.md).

`pytest` ya incluye el guard de red (`--disable-socket`, solo `127.0.0.1`/`localhost`): ningún test sale a internet. Docker se usa por su socket local.
