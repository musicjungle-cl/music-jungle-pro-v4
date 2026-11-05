"""
Lógica de catalogación de Music Jungle (sin dependencias de Streamlit).

Refleja las convenciones vigentes de la skill `publicar-ficha-producto` y de
`discogs_lookup.py` del watcher PMS:
  - elección del mejor release (Europe > Chile > Argentina > México > otros)
  - Formato simplificado: "LP, Album" / "2xLP, Compilation" / "CD, Album" ...
  - Categoría derivada del formato real (Vinilo / CD / Cassette / DVD)
  - País normalizado (Europe / US / UK / Japan / nombre Discogs)
  - Nombre de ficha: "Artista - Título (Vinilo, Ed. País, Año)"
  - Nuevo => Mint (M) en disco y carátula
  - Comentarios según vendedor/estado, precio sugerido para catálogo por encargo
"""
from __future__ import annotations

import math
import re
import time

# ============== CONSTANTES DE NEGOCIO ==============

# vendor -> (post_author en WordPress, grupo)
# Fuente: memoria vendors_musicjungle.
VENDORS = {
    "MusicJungleCL":  {"id": 963,  "grupo": "propio_nuevo"},
    "Vintage Jungle": {"id": 5890, "grupo": "propio_usado"},
    "PondisonOsben":  {"id": 969,  "grupo": "tercero_bodega"},
    "FDC":            {"id": 1970, "grupo": "dropship"},
    "PMS":            {"id": 5470, "grupo": "dropship"},
    "GLD":            {"id": 5457, "grupo": "dropship"},
    "DAAM":           {"id": 6086, "grupo": "encargo"},
}

# Vendedores cuyo stock no está en bodega: "DISPONIBLE EN 5 DÍAS HÁBILES"
VENDORS_5_DIAS = {"PMS", "GLD", "FDC", "DAAM"}

# Catálogo por encargo => etiqueta "Catálogo por encargo" + clase de envío por-encargo
VENDORS_ENCARGO = {"PMS", "DAAM"}

SHIPPING_CLASSES = ["(definir en WC)", "por-encargo", "discos-distribucion", "distribuidor"]

CONDICIONES = ["Mint (M)", "Near Mint (NM)", "Very Good Plus (VG+)", "Very Good (VG)"]

# Categorías WooCommerce (ids verificados en woo_sync del watcher)
WC_CATEGORY_IDS = {"Vinilo": 83, "CD": 184, "Cassette": 185, "DVD": 4865}

# Columnas de la matriz de carga MJ 2026 ("TEMPLATE 2026 - UPDATE"), más extras al final
MATRIX_COLUMNS = [
    "ID", "Barcode", "Cat No", "Artista", "Título", "Categoría", "Formato",
    "Estado", "Condición Disco", "Condición Caratula", "Discográfica", "País",
    "Año", "PDC", "Precio", "Stock", "Vendedor", "Tags", "Tracklist",
    "Link fotos", "Comentario",
]
EXTRA_COLUMNS = ["Nombre ficha", "Vendedor ID", "Clase de envío", "Categoría WC"]

ALLOWED_TYPE = ["Album", "Compilation", "Single", "EP"]

# ============== NORMALIZACIÓN ==============


def clean_extra_info(text) -> str:
    """Quita el sufijo de desambiguación de Discogs: 'Artista (2)' -> 'Artista'."""
    if not text:
        return ""
    return re.sub(r"\s\(\d+\)$", "", str(text)).strip()


def normalize_artist(raw_name: str) -> str:
    name = clean_extra_info(raw_name)
    for suffix, prefix in [(", The", "The "), (", Los", "Los "), (", El", "El ")]:
        if suffix in name:
            name = prefix + name.replace(suffix, "")
    tokens = name.split()
    if len(tokens) >= 2 and tokens[0].lower() in {"the", "los", "el"} and tokens[1].lower() in {"the", "los", "el"}:
        name = " ".join([tokens[0]] + tokens[2:])
    return name.strip()


def normalize_label(raw_label: str) -> str:
    return clean_extra_info(raw_label)


def normalize_country(country: str) -> str:
    """Europe / US / UK / Japan se unifican; el resto queda con el nombre de Discogs."""
    c = (country or "").strip()
    if not c:
        return ""
    c_norm = c.replace("&", ",").replace("/", ",")
    parts = [p.strip() for p in c_norm.split(",") if p.strip()]
    for p in parts:
        if p.lower() == "europe":
            return "Europe"
    lowered = {p.lower(): p for p in parts}
    if any(k in lowered for k in ["us", "usa", "united states"]):
        return "US"
    if any(k in lowered for k in ["uk", "united kingdom"]):
        return "UK"
    if any(k in lowered for k in ["japan", "jp"]):
        return "Japan"
    return parts[0] if parts else c


def build_formato_simplificado(fmt: dict) -> str:
    """'LP, Album' · '2xLP, Compilation' · '12", EP' · 'CD, Album' · 'Cassette, Album'."""
    if not fmt:
        return ""
    name = (fmt.get("name") or "").strip()
    desc_set = set(fmt.get("descriptions") or [])
    try:
        qty = int(fmt.get("qty")) if fmt.get("qty") is not None else None
    except (ValueError, TypeError):
        qty = None

    support = name
    low = name.lower()
    if low == "vinyl":
        if "LP" in desc_set:
            support = "LP"
        elif '12"' in desc_set:
            support = '12"'
        elif '7"' in desc_set:
            support = '7"'
        elif '10"' in desc_set:
            support = '10"'
        else:
            support = "LP"
    elif low in {"cd", "cdr"}:
        support = "CD"
    elif low == "cassette":
        support = "Cassette"
    elif low == "dvd":
        support = "DVD"

    if qty and qty > 1:
        support = f"{qty}x{support}"

    type_token = next((t for t in ALLOWED_TYPE if t in desc_set), "Album")
    return f"{support}, {type_token}"


def categoria_from_format(name: str, descriptions: list) -> str:
    name_l = (name or "").lower()
    joined = " ".join(d.lower() for d in (descriptions or []))
    if "vinyl" in name_l or "lp" in joined or "12" in joined or "7" in joined:
        return "Vinilo"
    if "cassette" in name_l or "cassette" in joined or "mc" in joined:
        return "Cassette"
    if "dvd" in name_l or "dvd" in joined:
        return "DVD"
    return "CD"


def build_tracklist_html(tracklist) -> str:
    rows = [
        f"<tr><td>{getattr(t, 'position', '')}</td><td>{getattr(t, 'title', '')}</td></tr>"
        for t in (tracklist or [])
        if getattr(t, "title", "")
    ]
    return f"<table>{''.join(rows)}</table>" if rows else ""


def build_product_name(artista: str, titulo: str, categoria: str, formato: str, pais: str, year) -> str:
    """
    'Artista - Título (Vinilo, Ed. País, Año)'. Formatos múltiples:
      2xLP  -> 'Vinilo, 2LP, Ed. ...'   2xCD -> '2 CD, Ed. ...'   12" -> 'Vinilo, 12", Ed. ...'
    Si falta país o año se omiten dentro del paréntesis.
    """
    extra = None
    if formato:
        support = formato.split(",")[0].strip()
        m = re.match(r"^(\d+)x(.+)$", support, re.IGNORECASE)
        if m:
            qty, base = m.group(1), m.group(2)
            b = base.upper()
            if b == "LP":
                extra = f"{qty}LP"
            elif b in ("CD", "CDR"):
                extra = f"{qty} CD"
            elif b == "CASSETTE":
                extra = f"{qty} Cassette"
            else:
                extra = f"{qty}x{base}"
        elif '"' in support:
            extra = support

    parts: list[str] = []
    if extra and categoria == "Vinilo":
        parts += [categoria, extra]
    elif extra:
        parts.append(extra)
    elif categoria:
        parts.append(categoria)
    if pais:
        parts.append(f"Ed. {pais}")
    if year:
        parts.append(str(year))
    subtitle = f" ({', '.join(parts)})" if parts else ""

    if artista and titulo:
        return f"{artista} - {titulo}{subtitle}"
    return f"{artista or titulo}{subtitle}"


# ============== REGLAS COMERCIALES ==============


def condiciones_para(estado: str, condicion_usado: str) -> tuple[str, str]:
    """Nuevo/sellado => Mint (M) en disco y carátula; Usado => la condición elegida."""
    if estado == "Nuevo":
        return "Mint (M)", "Mint (M)"
    return condicion_usado, condicion_usado


def build_comentario(estado: str, vendedor: str, categoria: str) -> str:
    if estado == "Usado":
        return "[code_snippet id=28] Disco en excelente estado. COPIA ÚNICA."
    if vendedor in VENDORS_5_DIAS:
        return f"[code_snippet id=42]\n{categoria} nuevo, sellado. DISPONIBLE EN 5 DÍAS HÁBILES"
    return f"{categoria} nuevo, sellado. COPIAS LIMITADAS"


def to_number(v):
    """Valor de celda -> número, o None si está vacío/NaN."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def precio_encargo(costo) -> int | None:
    """
    Catálogo por encargo: costo x 1,7 x 1,19, redondeado HACIA ARRIBA al próximo
    valor terminado en 900.  13.900 -> 28.119,7 -> 28.900.
    """
    c = to_number(costo)
    if c is None or c <= 0:
        return None
    raw = c * 1.7 * 1.19
    return int(math.ceil((raw - 900) / 1000) * 1000 + 900)


def default_shipping_class(vendedor: str) -> str:
    return "por-encargo" if vendedor in VENDORS_ENCARGO else SHIPPING_CLASSES[0]


def vendor_warnings(vendedor: str, estado: str) -> list[str]:
    """Avisos de coherencia vendedor/estado (963 = nuevo, 5890 = usado)."""
    w = []
    if estado == "Usado" and vendedor == "MusicJungleCL":
        w.append("Los usados propios van con 'Vintage Jungle' (5890); un proceso reasigna los Usado de 963 a 5890.")
    if estado == "Nuevo" and vendedor == "Vintage Jungle":
        w.append("'Vintage Jungle' es el catálogo de usados; para stock nuevo propio usa 'MusicJungleCL'.")
    return w


# ============== DISCOGS ==============

_EUROPEAN_COUNTRIES = {
    "europe", "uk", "united kingdom", "germany", "france", "italy", "spain",
    "netherlands", "belgium", "sweden", "norway", "denmark", "finland",
    "austria", "switzerland", "portugal", "greece", "poland", "czech republic",
    "hungary", "romania", "yugoslavia", "east germany", "west germany",
    "russia", "ukraine", "czechoslovakia", "ireland", "scotland", "wales",
}

REGION_COUNTRIES = {
    "Europa": _EUROPEAN_COUNTRIES - {"uk", "united kingdom", "scotland", "wales"},
    "USA/Canadá": {"us", "usa", "united states", "canada"},
    "Japón": {"japan", "jp"},
    "UK": {"uk", "united kingdom", "england", "scotland", "wales", "northern ireland", "great britain"},
    "Australia/NZ": {"australia", "new zealand"},
    "LatAm": {"chile", "argentina", "brazil", "peru", "colombia", "mexico", "méxico",
              "uruguay", "paraguay", "bolivia", "ecuador", "venezuela"},
}

# Cuántos resultados de búsqueda se evalúan por ítem. Cada acceso lazy a un
# release puede costar una llamada; limitarlo evita agotar los 60 req/min.
MAX_CANDIDATES = 6


def _country_priority_score(country_raw: str) -> int:
    """Europe > Chile > Argentina > México > otros (valor crudo de Discogs)."""
    c = (country_raw or "").lower().strip()
    if not c:
        return 0
    if c == "europe" or c in _EUROPEAN_COUNTRIES:
        return 13
    if "chile" in c:
        return 11
    if "argentina" in c:
        return 10
    if "mexico" in c or "méxico" in c:
        return 9
    return 5


def country_in_region(country: str, region: str) -> bool:
    if region in (None, "", "Cualquiera"):
        return True
    parts = re.split(r"[,&/]", (country or "").lower())
    allowed = REGION_COUNTRIES.get(region, set())
    return any(p.strip() in allowed for p in parts)


def _score_release(rel, origin: str = "Cualquiera") -> int:
    s = 0
    try:
        country_raw = getattr(rel, "country", "") or ""
        s += _country_priority_score(country_raw)
        if origin not in (None, "", "Cualquiera") and country_in_region(country_raw, origin):
            s += 20  # el origen pedido explícitamente manda
        year_val = getattr(rel, "year", 0) or 0
        if year_val:
            s += 2 + min(10, max(0, (int(year_val) - 1950) // 5))
        labs = getattr(rel, "labels", [])
        if labs and getattr(labs[0], "catno", ""):
            s += 2
        if getattr(rel, "images", None):
            s += 2
        if getattr(rel, "formats", None):
            s += 2
        data = getattr(rel, "data", {})
        have = data.get("community", {}).get("have", 0) if isinstance(data, dict) else 0
        s += min(5, have // 500)
    except Exception:
        pass
    return s


def pick_best_release(results, origin: str = "Cualquiera"):
    if not results:
        return None
    best, best_score = None, -1
    for i, rel in enumerate(results):
        if i >= MAX_CANDIDATES:
            break
        sc = _score_release(rel, origin)
        if sc > best_score:
            best, best_score = rel, sc
    return best


def is_barcode(token: str) -> bool:
    return token.isdigit() and len(token) >= 7


def parse_inputs(raw: str) -> list[str]:
    """Barcodes / Cat Nos separados por salto de línea, coma o espacio; sin duplicados, en orden."""
    seen, out = set(), []
    for chunk in re.split(r"[\n,;]", raw or ""):
        for tok in chunk.split():
            tok = tok.strip()
            if tok and tok not in seen:
                out.append(tok)
                seen.add(tok)
    return out


def release_to_row(release, item: str) -> dict:
    """Convierte un release de Discogs en los campos de la matriz."""
    artist = normalize_artist(release.artists[0].name if getattr(release, "artists", None) else "Unknown")
    title = release.title or "Unknown"
    year = str(getattr(release, "year", "") or "")

    raw_label, cat_no = "", ""
    if getattr(release, "labels", None):
        lab = release.labels[0]
        raw_label = normalize_label(lab.name)
        # En resultados de búsqueda el catno viene en lab.data, no como atributo
        lab_data = getattr(lab, "data", None)
        cat_no = (getattr(lab, "catno", "")
                  or (lab_data.get("catno", "") if isinstance(lab_data, dict) else "")
                  or "")
    if not cat_no:
        rel_data = getattr(release, "data", None)
        cat_no = rel_data.get("catno", "") if isinstance(rel_data, dict) else ""

    # Portada: imagen primaria completa; thumb solo como último recurso
    image = ""
    images = getattr(release, "images", None) or []
    if images:
        image = images[0].get("uri") or images[0].get("resource_url") or ""
    image = image or getattr(release, "thumb", "") or ""

    fmt_obj = (getattr(release, "formats", None) or [{}])[0]
    categoria = categoria_from_format(fmt_obj.get("name"), fmt_obj.get("descriptions"))
    formato = build_formato_simplificado(fmt_obj)
    pais = normalize_country(getattr(release, "country", ""))
    styles = ", ".join(getattr(release, "styles", None) or getattr(release, "genres", None) or [])

    return {
        "Barcode": item if is_barcode(item) else "",
        "Cat No": cat_no or ("" if is_barcode(item) else item),
        "Artista": artist,
        "Título": title,
        "Categoría": categoria,
        "Formato": formato,
        "Discográfica": raw_label,
        "País": pais,
        "Año": year,
        "Tags": styles,
        "Tracklist": build_tracklist_html(getattr(release, "tracklist", None)),
        "Link fotos": image,
        "Fuente": "Discogs",
        "Needs_Enrichment": False,
        "Discogs ID": getattr(release, "id", ""),
    }


RATE_LIMIT = "RATE_LIMIT"


def fetch_discogs(dclient, item: str, origin: str = "Cualquiera", retries: int = 1, sleep=time.sleep):
    """
    Busca por barcode (>=7 dígitos) o por Cat No. Devuelve dict, None (no encontrado)
    o RATE_LIMIT si Discogs siguió respondiendo 429 tras esperar la ventana de 60 s.
    """
    if dclient is None:
        return None
    rate_limited = 0
    attempt = 0
    while attempt <= retries:
        try:
            sleep(1.1)
            res = dclient.search(barcode=item, type="release") if is_barcode(item) \
                else dclient.search(catno=item, type="release")
            release = pick_best_release(res, origin)
            return release_to_row(release, item) if release else None
        except Exception as e:  # noqa: BLE001
            if "429" in str(e):
                if rate_limited < 2:
                    rate_limited += 1
                    sleep(61)  # la ventana de Discogs es de 60 s
                    continue
                return RATE_LIMIT
            if attempt < retries:
                attempt += 1
                sleep(3)
                continue
            return None
    return None


def fetch_musicbrainz(item: str, http_get=None, sleep=time.sleep):
    """Fallback mínimo; deja la fila marcada para una pasada de enriquecimiento en Discogs."""
    import requests
    http_get = http_get or requests.get
    try:
        sleep(1.1)
        r = http_get(
            "https://musicbrainz.org/ws/2/release/",
            params={"query": f"barcode:{item}", "fmt": "json"},
            headers={"User-Agent": "MusicJungleApp/5.0 (https://musicjungle.cl)"},
            timeout=10,
        ).json()
        if r.get("releases"):
            rel = r["releases"][0]
            ac = (rel.get("artist-credit") or [{}])[0]
            return {
                "Barcode": item if is_barcode(item) else "",
                "Cat No": "" if is_barcode(item) else item,
                "Artista": clean_extra_info(ac.get("name")),
                "Título": rel.get("title") or "",
                "Categoría": "",
                "Formato": "",
                "Discográfica": "",
                "País": normalize_country(rel.get("country", "")),
                "Año": (rel.get("date") or "")[:4],
                "Tags": "",
                "Tracklist": "",
                "Link fotos": "",
                "Fuente": "MusicBrainz",
                "Needs_Enrichment": True,
            }
    except Exception:  # noqa: BLE001
        pass
    return None


# ============== ARMADO DE LA FILA FINAL ==============


def finalize_row(data: dict, *, item: str, vendedor: str, estado: str, condicion_usado: str,
                 shipping_class: str, costo=None, stock: int = 1) -> dict:
    """Completa los campos que dependen de la configuración (vendedor, estado, costos)."""
    cd, cc = condiciones_para(estado, condicion_usado)
    categoria = data.get("Categoría") or "Producto"  # vacío solo en filas de MusicBrainz sin enriquecer
    row = dict(data)
    row.update({
        "ID_Search": item,
        "Vendedor": vendedor,
        "Vendedor ID": VENDORS[vendedor]["id"],
        "Estado": estado,
        "Condición Disco": cd,
        "Condición Caratula": cc,
        "Comentario": build_comentario(estado, vendedor, categoria),
        "Clase de envío": shipping_class,
        "Stock": stock,
        "PDC": costo or None,
        "Precio": (precio_encargo(costo) if vendedor in VENDORS_ENCARGO and costo else None),
    })
    refresh_derived(row)
    return row


def refresh_derived(row: dict) -> dict:
    """Recalcula campos derivados (nombre de ficha, categoría WC) tras un enriquecimiento o edición."""
    row["Nombre ficha"] = build_product_name(
        row.get("Artista", ""), row.get("Título", ""), row.get("Categoría", ""),
        row.get("Formato", ""), row.get("País", ""), row.get("Año", ""),
    )
    row["Categoría WC"] = WC_CATEGORY_IDS.get(row.get("Categoría", ""))
    return row


def apply_enrichment(row: dict, enriched: dict) -> dict:
    """Mezcla datos de Discogs sobre una fila de MusicBrainz sin pisar configuración del usuario."""
    for k, v in enriched.items():
        row[k] = v
    row["Needs_Enrichment"] = False
    categoria = row.get("Categoría") or "CD"
    row["Comentario"] = build_comentario(row.get("Estado", "Nuevo"), row.get("Vendedor", ""), categoria)
    return refresh_derived(row)


# ============== CHEQUEO DE DUPLICADOS (WooCommerce, solo lectura) ==============


def check_duplicate(barcode: str, base_url: str, key: str, secret: str, http_get=None):
    """
    Busca el barcode en el catálogo publicado (Paso 1 de la skill).
    Devuelve (estado, detalle):
      ("existe", "id 123 · publish · Artista - Título")  /  ("libre", "")  /  ("error", "motivo")
    Usa solo GET sobre wc/v3/products (lectura) con `global_unique_id`.
    """
    import requests
    if not barcode:
        return "libre", ""
    http_get = http_get or requests.get
    try:
        r = http_get(
            f"{base_url.rstrip('/')}/wp-json/wc/v3/products",
            params={"search": barcode, "status": "any", "per_page": 20, "nocache": "1"},
            auth=(key, secret),
            headers={"User-Agent": "MusicJungleApp/5.0"},
            timeout=15,
        )
        if r.status_code != 200:
            return "error", f"HTTP {r.status_code}"
        hits = [p for p in r.json() if str(p.get("global_unique_id", "")) == str(barcode)]
        if hits:
            p = hits[0]
            extra = f" (+{len(hits) - 1} más)" if len(hits) > 1 else ""
            return "existe", f"id {p.get('id')} · {p.get('status')} · {p.get('name', '')}{extra}"
        return "libre", ""
    except Exception as e:  # noqa: BLE001
        return "error", type(e).__name__
