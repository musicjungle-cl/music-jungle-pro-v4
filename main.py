import streamlit as st
import pandas as pd
import discogs_client
import time
import requests
import re

# ============== HELPERS & LOG LOGIC ==============
if "results_list" not in st.session_state:
    st.session_state.results_list = []

def normalize_artist(raw_name):
    if not raw_name: return "Unknown"
    return re.sub(r"\s\(\d+\)$", "", raw_name).strip()

def get_categoria(fmt_name, descriptions):
    joined = (str(fmt_name) + " " + " ".join(descriptions or [])).lower()
    if any(x in joined for x in ["vinyl", "lp", "12\"", "7\"", "10\""]): return "Vinilo"
    if any(x in joined for x in ["cassette", "mc"]): return "Cassette"
    if "dvd" in joined: return "DVD"
    return "CD"

def build_comentario(estado, seller, categoria):
    if seller in ["PMS", "GLD", "FDC"]:
        return "[code_snippet id=42] Producto nuevo, sellado. DISPONIBLE EN 5 DÍAS HÁBILES."
    if estado == "Nuevo":
        return f"{categoria} nuevo, sellado. COPIAS LIMITADAS."
    return "[code_snippet id=28] Disco en excelente estado. COPIA ÚNICA."

# ============== MOTORES DE BÚSQUEDA ==============

def fetch_discogs(dclient, item):
    try:
        time.sleep(0.9) # Safe rate
        res = dclient.search(barcode=item, type='release') if item.isdigit() else dclient.search(catno=item, type='release')
        if res.count > 0:
            rel = res[0]
            fmt = rel.formats[0] if rel.formats else {"name": "CD", "descriptions": []}
            cat = get_categoria(fmt.get("name"), fmt.get("descriptions"))
            return {
                "Barcode": item if item.isdigit() else "",
                "Cat No": getattr(rel.labels[0], "catno", item) if rel.labels else item,
                "Artista": normalize_artist(rel.artists[0].name) if rel.artists else "Unknown",
                "Título": rel.title,
                "Categoría": cat,
                "Formato": f"{fmt.get('name')}, {', '.join(fmt.get('descriptions', []))}",
                "Discográfica": rel.labels[0].name if rel.labels else "",
                "País": getattr(rel, "country", ""),
                "Año": getattr(rel, "year", ""),
                "Tags": ", ".join(rel.styles or rel.genres or []),
                "Tracklist": f"<table>{''.join([f'<tr><td>{t.position}</td><td>{t.title}</td></tr>' for t in rel.tracklist])}</table>" if rel.tracklist else "",
                "Link fotos": rel.thumb,
                "Fuente": "Discogs"
            }
    except Exception as e:
        if "429" in str(e): return "RATE_LIMIT"
    return None

def fetch_itunes(item):
    try:
        url = f"https://itunes.apple.com/lookup?upc={item}&entity=album"
        r = requests.get(url, timeout=5).json()
        if r.get('resultCount', 0) > 0:
            res = r['results'][0]
            return {
                "Barcode": item, "Cat No": item,
                "Artista": res.get("artistName"), "Título": res.get("collectionName"),
                "Categoría": "CD", "Formato": "CD, Album",
                "Discográfica": "iTunes Search", "País": "US", "Año": res.get("releaseDate", "")[:4],
                "Tags": res.get("primaryGenreName", ""), "Tracklist": "Ver en App",
                "Link fotos": res.get("artworkUrl100", "").replace("100x100bb", "600x600bb"),
                "Fuente": "iTunes"
            }
    except: pass
    return None

# ============== INTERFAZ STREAMLIT ==============

st.set_page_config(page_title="MJ DEVELOPER - Music Jungle Pro", layout="wide")
st.title("📀 Generador de Matriz Music Jungle")

with st.sidebar:
    st.header("⚙️ Parámetros Globales")
    token = st.text_input("Discogs Token", type="password")
    vendedor = st.selectbox("Vendedor", ["MusicJungleCL", "Vintage Jungle", "PondisonOsben", "FDC", "PMS", "GLD"])
    estado_global = st.radio("Estado de Importación", ["Nuevo", "Usado"])
    condicion = st.selectbox("Condición (Disco/Carátula)", ["Mint (M)", "Near Mint (NM)", "Very Good Plus (VG+)", "Very Good (VG)"])
    
    st.divider()
    fallback_mode = st.toggle("Auto-Fallback (MB/iTunes)", value=True)

raw_input = st.text_area("Lista de Barcodes o Cat Nos:", height=150)
input_list = [x.strip() for x in re.split(r'[\n,]', raw_input) if x.strip()]

if input_list:
    if st.button("🚀 Generar Matriz"):
        dclient = discogs_client.Client("MusicJungleApp/4.5", user_token=token) if token else None
        pbar = st.progress(0)
        
        for idx, item in enumerate(input_list):
            data = None
            # 1. Intentar Discogs
            if dclient:
                data = fetch_discogs(dclient, item)
            
            # 2. Fallback si falla o no hay datos
            if (not data or data == "RATE_LIMIT") and fallback_mode and item.isdigit():
                st.warning(f"Usando Fallback para {item}...")
                data = fetch_itunes(item)
            
            if data and isinstance(data, dict):
                # Aplicar Reglas de Negocio MJ
                data["Estado"] = estado_global
                data["Condición Disco"] = condicion
                data["Condición Caratula"] = condicion
                data["Costo"] = ""
                data["Precio"] = ""
                data["Stock"] = 1
                data["Vendedor"] = vendedor
                data["Comentario"] = build_comentario(estado_global, vendedor, data["Categoría"])
                
                st.session_state.results_list.append(data)
            
            pbar.progress((idx + 1) / len(input_list))

if st.session_state.results_list:
    df = pd.DataFrame(st.session_state.results_list)
    
    # Asegurar el orden exacto de las columnas solicitado
    columns_mj = [
        "Barcode", "Cat No", "Artista", "Título", "Categoría", "Formato", 
        "Estado", "Condición Disco", "Condición Caratula", "Discográfica", 
        "País", "Año", "Costo", "Precio", "Stock", "Vendedor", "Tags", 
        "Tracklist", "Link fotos", "Comentario"
    ]
    
    # Reindexar y añadir ID
    final_df = df.reindex(columns=columns_mj)
    final_df.insert(0, 'ID', range(1, 1 + len(final_df)))
    
    st.subheader("📋 Vista Previa de Matriz")
    st.dataframe(final_df, use_container_width=True)
    
    csv = final_df.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Descargar CSV Music Jungle", data=csv, file_name="Matriz_MusicJungle.csv", mime="text/csv")
