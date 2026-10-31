"""Assets SVG de bandera: ruta segura (RF-49). El contenido se valida en T7.

La ruta es relativa al directorio de assets del paquete y se compone de segmentos simples: sin `..`,
sin rutas absolutas, sin separadores de Windows y con extensión `.svg`. Es la misma regla que la
constraint `country_flag_asset_path_format` de la base.
"""

import re

SVG_MEDIA_TYPE = "image/svg+xml"
ASSET_PATH = re.compile(r"([A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.svg")


def is_safe_asset_path(path: str) -> bool:
    """`ar.svg` y `4x3/ar.svg` sí; `../ar.svg`, `/ar.svg`, `a//b.svg`, `ar.png` y `a\\b.svg` no."""
    return ASSET_PATH.fullmatch(path) is not None
