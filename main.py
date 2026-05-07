import streamlit as st
import pandas as pd
import discogs_client
import time
import requests
import re

# ============== DICCIONARIOS DE NORMALIZACIÓN ==============
COUNTRY_MAP = {
    "JP": "Japan", "FR": "France", "DE": "Germany", "ES": "Spain", 
    "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "CL": "Chile",
    "IT": "Italy", "CA": "Canada", "AU": "Australia", "RU": "Russia"
}

# ============== LOGICA DE NEGOCIO ==============

def clean_extra_info(text):
    if not text: return ""
    return re.sub(r"\s\(\d+\)$", "", str(text)).strip()

def normalize_country(country_raw):
    """Regla 2: Solo US/UK quedan como sigla. El resto a nombre completo."""
    if not country_raw: return "Unknown"
    c = country_raw.strip()
    if c in ["US", "UK"]: return c
    return COUNTRY_MAP.get(c, c)

def pick_best_country(countries_list):
    """Regla 3: Orden de prioridad: Chile > Argentina > Europe > US > Resto."""
    if not countries_list: return "Unknown"
    if isinstance(countries_list, str): 
        return normalize_country(countries_list)
    
    priorities = ["Chile", "Argentina", "Europe", "US"]
    for p in priorities:
        if p in countries_list: return p
    return normalize_country(countries_list[0])

def get_formato_simplificado(fmt_obj):
    """Regla 1: Solo los dos primeros valores (Soporte, Tipo)."""
    if not fmt_obj: return "CD, Album"
    name = fmt_obj.get("name", "CD")
    descriptions = fmt_obj.get("descriptions", [])
    type_val = descriptions[0] if descriptions else "Album"
    return f"{name}, {type_val}"

def build_comentario(estado, seller, categoria):
    if seller in ["PMS", "GLD", "FDC"]:
        return "[code_snippet id=42] Producto nuevo, sellado. DISPONIBLE EN 5 DÍAS HÁBILES."
    if estado == "Nuevo":
        return f"{categoria} nuevo, sellado. COPIAS LIMITADAS."
    return "[code_snippet id=28] Disco en excelente estado. COPIA ÚNICA."

# ============== MOTORES DE BÚSQUEDA ==============

def fetch_discogs(dclient, item):
    try:
        time.sleep(1.2) 
        res = dclient.search(barcode=item, type='release') if item.isdigit() else dclient.search(catno=item, type='release')
        
        if res.count > 0:
            rel = res[0]
            fmt_obj = rel.formats[0] if rel.formats else {}
            # Manejo de múltiples países
            country_val = pick_best_country(getattr(rel, "country", "Unknown"))
            
            return {
                "Barcode": item if item.isdigit() else "",
                "Cat No": clean_extra_info(getattr(rel.labels[0], "catno", item)) if rel.labels else item,
                "Artista": clean_extra_info(rel.artists[0].name) if rel.artists else "Unknown",
                "Título": rel.title,
                "Categoría": "CD", # (Lógica interna se mantiene)
                "Formato": get_formato_simplificado(fmt_obj),
                "Discográfica": clean_extra_info(rel.labels[0].name) if rel.labels else "",
                "País": country_val,
                "Año": getattr(rel, "year", ""),
                "Tags": ", ".join(rel.styles or rel.genres or []),
                "Tracklist": f"<table>{''.join([f'<tr><td>{t.position}</td><td>{t.title}</td></tr>' for t in rel.tracklist])}</table>" if rel.tracklist else "",
                "Link fotos": rel.thumb,
                "Fuente": "Discogs",
                "Needs_Enrichment": False
            }
    except Exception as e:
        if "429" in str(e): return "RATE_LIMIT"
    return None

def fetch_musicbrainz(item):
    """Fallback: Trae lo básico, pero marca para reintento de Discogs."""
    try:
        time.sleep(1.1)
        url = f"https://musicbrainz.org/ws/2/release/?query=barcode:{item}&fmt=json"
        r = requests.get(url, timeout=10).json()
        if r.get('releases'):
            rel = r['releases'][0]
            return {
                "Barcode": item, "Cat No": item,
                "Artista": clean_extra_info(rel.get('artist-credit', [{}])[0].get('name')),
                "Título": rel.get('title'),
                "Discográfica": "MusicBrainz (Pending Discogs)",
                "País": normalize_country(rel.get('country', 'Unknown')),
                "Año": rel.get('date', "")[:4],
                "Fuente": "MusicBrainz",
                "Needs_Enrichment": True # <--- MARCA PARA SEGUNDA PASADA
            }
    except: pass
    return None

# ============== UI STREAMLIT ==============

st.set_page_config(page_title="Music Jungle Pro v4.7", layout="wide")
st.title("📀 Music Jungle - High Precision Matrix")

with st.sidebar:
    st.header("⚙️ Configuración")
    token = st.text_input("Discogs Token", type="password")
    vendedor = st.selectbox("Vendedor", ["MusicJungleCL", "Vintage Jungle", "PondisonOsben", "FDC", "PMS", "GLD"])
    estado_global = st.radio("Estado", ["Nuevo", "Usado"])
    condicion = st.selectbox("Condición", ["Mint (M)", "Near Mint (NM)", "Very Good Plus (VG+)", "Very Good (VG)"])

if "results_list" not in st.session_state:
    st.session_state.results_list = []

raw_input = st.text_area("Lista de Barcodes o Cat Nos:", height=150)
input_list = [x.strip() for x in re.split(r'[\n,]', raw_input) if x.strip()]

if input_list:
    if st.button("🚀 Iniciar Carga"):
        dclient = discogs_client.Client("MusicJungleApp/4.7", user_token=token) if token else None
        pbar = st.progress(0)
        
        for idx, item in enumerate(input_list):
            if any(res.get('ID_Search') == item for res in st.session_state.results_list):
                continue
                
            data = fetch_discogs(dclient, item)
            
            if data == "RATE_LIMIT" or not data:
                data = fetch_musicbrainz(item)
            
            if data and isinstance(data, dict):
                data["ID_Search"] = item
                data["Vendedor"] = vendedor
                data["Estado"] = estado_global
                data["Condición Disco"] = condicion
                data["Condición Caratula"] = condicion
                data["Comentario"] = build_comentario(estado_global, vendedor, data.get("Categoría", "CD"))
                st.session_state.results_list.append(data)
            
            pbar.progress((idx + 1) / len(input_list))

# ============== PUNTO 4: SISTEMA DE ENRIQUECIMIENTO ==============
items_to_enrich = [i for i in st.session_state.results_list if i.get("Needs_Enrichment")]

if items_to_enrich:
    st.warning(f"⚠️ Hay {len(items_to_enrich)} ítems con data incompleta (vía MusicBrainz).")
    if st.button("🔄 Intentar completar data con Discogs (Pasada Final)"):
        dclient = discogs_client.Client("MusicJungleApp/4.7", user_token=token)
        enrich_pbar = st.progress(0)
        for idx, item_data in enumerate(items_to_enrich):
            enriched = fetch_discogs(dclient, item_data["ID_Search"])
            if enriched and isinstance(enriched, dict):
                # Actualizamos los campos faltantes
                item_data.update(enriched)
                item_data["Needs_Enrichment"] = False
            enrich_pbar.progress((idx + 1) / len(items_to_enrich))
        st.success("Enriquecimiento finalizado.")
        st.rerun()

# ============== RENDERIZADO FINAL ==============
if st.session_state.results_list:
    df = pd.DataFrame(st.session_state.results_list)
    # Orden de columnas MJ final
    final_cols = ["Barcode", "Cat No", "Artista", "Título", "Categoría", "Formato", 
                  "Estado", "Condición Disco", "Condición Caratula", "Discográfica", 
                  "País", "Año", "Stock", "Vendedor", "Tags", "Tracklist", "Link fotos", "Comentario"]
    
    # Rellenar faltantes
    df["Stock"] = 1
    df["Costo"] = ""
    df["Precio"] = ""
    
    st.dataframe(df.reindex(columns=final_cols), use_container_width=True)
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Descargar Matriz CSV", data=csv, file_name="Matriz_MusicJungle.csv")
