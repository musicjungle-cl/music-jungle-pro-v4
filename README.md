# Music Jungle Pro — Matriz de carga

App Streamlit que arma la **matriz de carga MJ 2026** a partir de barcodes o Cat Nos (Discogs, con MusicBrainz como respaldo).

## Qué hace (v5.0)
- Elige la **mejor edición** de Discogs (Europe > Chile > Argentina > México > otros; opcional: origen preferido).
- **Formato** simplificado (`LP, Album`, `2xLP, Compilation`, `12", EP`, `CD, Album`) y **Categoría** real (Vinilo / CD / Cassette / DVD).
- **Nombre de ficha** con la convención del catálogo: `Artista - Título (Vinilo, Ed. País, Año)`.
- **Estado**: Nuevo ⇒ Mint (M) en disco y carátula; Usado ⇒ condición elegida.
- **Vendedores** con su `post_author` (MusicJungleCL 963, Vintage Jungle 5890, PondisonOsben 969, FDC 1970, PMS 5470, GLD 5457, DAAM 6086), avisos de coherencia vendedor/estado y clase de envío (`por-encargo` por defecto para PMS y DAAM).
- **PDC (costo)** y **Precio** editables; para catálogo por encargo (PMS, DAAM) se sugiere `costo × 1,7 × 1,19` redondeado hacia arriba al próximo valor terminado en 900.
- **Chequeo de duplicados** contra musicjungle.cl (opcional, solo lectura).
- Manejo de rate limit de Discogs (429 ⇒ espera 60 s) y pasada de enriquecimiento para ítems que cayeron a MusicBrainz.

El CSV mantiene las columnas de la matriz (`ID … Comentario`, con `PDC`) y agrega al final `Nombre ficha`, `Vendedor ID`, `Clase de envío` y `Categoría WC`.

## Secretos (Streamlit Cloud → Settings → Secrets)
```toml
DISCOGS_TOKEN = "..."          # opcional: si no, se pide en la barra lateral
WC_BASE_URL = "https://musicjungle.cl"
WC_CONSUMER_KEY = "ck_..."     # solo lectura; habilita el chequeo de duplicados
WC_CONSUMER_SECRET = "cs_..."
```
Nunca subas claves al repositorio (es público).

## Estructura
- `main.py` — interfaz.
- `mj_logic.py` — reglas de catalogación (sin Streamlit, testeable).
- `test_mj_logic.py` — tests de las reglas.
