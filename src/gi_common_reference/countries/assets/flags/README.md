# Assets de bandera (spec 003, RF-19, RF-49, RF-50)

Este directorio viaja dentro del paquete instalado (`gi_common_reference.countries.assets`) y es el
único origen de las banderas: ninguna consulta accede a la red (RF-26).

Contrato de cada asset:

- Archivo SVG directamente en este directorio (sin subdirectorios), con un nombre simple.
- Referenciado desde el snapshot de Countries por `asset_path`, `sha256` (de los bytes exactos del
  archivo) y `media_type` = `image/svg+xml`. La suma se verifica al incorporar y al servir.
- Bien formado, de hasta 512 KiB y sin contenido activo: sin DTD ni entidades, `script`,
  `foreignObject`, `iframe`, `object`, `embed`, animación SMIL (`set`, `animate*`, `discard`), atributos `on*` ni referencias que no sean
  fragmentos locales `#id`.
- La fuente y la licencia se declaran en la procedencia del snapshot (rol `flags`).

Hasta que el dataset de PREP aporte los SVG reales, este directorio solo contiene este archivo. Las
pruebas usan fixtures sintéticos en `tests/fixtures/flags/`.
