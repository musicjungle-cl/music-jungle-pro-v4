import streamlit as st
import pandas as pd
import discogs_client
import time
import requests
import re

# ============== LOGICA DE LIMPIEZA (REGEX) ==============

def clean_extra_info(text):
    """Elimina números entre paréntesis al final: 'Artist (2)' -> 'Artist'"""
    if not text: return ""
    return re.sub(r"\s\(\d+\)$", "", str(text)).strip()

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
    """Motor Principal con control de ritmo estricto"""
    try:
        # Respetamos el límite de 60 req/min con margen de seguridad
        time.sleep(1.2) 
        res = dclient.search(barcode=item, type='release') if item.isdigit() else dclient.search(catno=item, type='release')
        
        if res.count > 0:
            rel = res[0]
            fmt = rel.formats[0] if rel.formats else {"name": "CD", "descriptions": []}
            return {
                "Barcode": item if item.isdigit() else "",
                "Cat No": clean_extra_info(getattr(rel.labels[0], "catno", item)) if rel.labels else item,
                "Artista": clean_extra_info(rel.artists[0].name) if rel.artists else "Unknown",
                "Título": rel.title,
                "Categoría": get_categoria(fmt.get("name"), fmt.get("descriptions")),
                "Formato": f"{fmt.get('name')}, {', '.join(fmt.get('descriptions', []))}",
                "Discográfica": clean_extra_info(rel.labels[0].name) if rel.labels else "",
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

def fetch_musicbrainz(item):
    """Fallback de alta calidad para discográfica y tracklist"""
    try:
        time.sleep(1.1) # Límite estricto de MusicBrainz
        url = f"https://musicbrainz.org/ws/2/release/?query=barcode:{item}&fmt=json"
        headers = {'User-Agent': 'MusicJungleBot/4.6 (contacto@musicjungle.cl)'}
        r = requests.get(url, headers=headers, timeout=10).json()
        
        if r.get('releases'):
            rel = r['releases'][0]
            # Extraer discográfica de MB
            label = "Unknown"
            if rel.get('label-info'):
                label = rel['label-info'][0].get('label', {}).get('name', 'Unknown')
            
            return {
                "Barcode": item, "Cat No": item,
                "Artista": clean_extra_info(rel.get('artist-credit', [{}])[0].get('name')),
                "Título": rel.get('title'),
                "Categoría": "CD", # MB es más complejo de mapear, default CD
                "Formato": "Album",
                "Discográfica": clean_extra_info(label),
                "País": rel.get('country', 'Unknown'),
                "Año": rel.get('date', "")[:4],
                "Tags": "Music",
                "Tracklist": "Metadata MB disponible",
                "Link fotos": "",
                "Fuente": "MusicBrainz"
            }
    except: pass
    return None

# ============== UI STREAMLIT ==============

st.set_page_config(page_title="Music Jungle Pro v4.6", layout="wide")
st.title("📀 Generador de Matriz Music Jungle (High Precision)")

with st.sidebar:
    st.header("⚙️ Configuración")
    token = st.text_input("Discogs Token", type="password")
    vendedor = st.selectbox("Vendedor", ["MusicJungleCL", "Vintage Jungle", "PondisonOsben", "FDC", "PMS", "GLD"])
    estado_global = st.radio("Estado de Importación", ["Nuevo", "Usado"])
    condicion = st.selectbox("Condición (Disco/Carátula)", ["Mint (M)", "Near Mint (NM)", "Very Good Plus (VG+)", "Very Good (VG)"])
    
    st.divider()
    st.info("Pausa de seguridad: 1.2s entre discos para evitar baneos de Discogs.")

if "results_list" not in st.session_state:
    st.session_state.results_list = []

raw_input = st.text_area("Lista de Barcodes o Cat Nos:", height=150)
input_list = [x.strip() for x in re.split(r'[\n,]', raw_input) if x.strip()]

if input_list:
    if st.button("🚀 Iniciar Importación Controlada"):
        dclient = discogs_client.Client("MusicJungleApp/4.6", user_token=token) if token else None
        pbar = st.progress(0)
        status = st.empty()
        
        for idx, item in enumerate(input_list):
            # No procesar duplicados en la misma sesión
            if any(res['ID_Search'] == item for res in st.session_state.results_list):
                continue
                
            status.text(f"Buscando {item}...")
            data = fetch_discogs(dclient, item)
            
            # Gestión de Bloqueo / Retoma
            if data == "RATE_LIMIT":
                st.error("🛑 Límite de Discogs alcanzado. Esperando 30 segundos para reintentar con MusicBrainz...")
                time.sleep(30)
                data = fetch_musicbrainz(item)
            
            if not data:
                data = fetch_musicbrainz(item)
            
            if data and isinstance(data, dict):
                data["ID_Search"] = item
                data["Estado"] = estado_global
                data["Condición Disco"] = condicion
                data["Condición Caratula"] = condicion
                data["Costo"] = ""
                data["Precio"] = ""
                data["Stock"] = 1
                data["Vendedor"] = vendedor
                data["Comentario"] = build_comentario(estado_global, vendedor, data.get("Categoría", "CD"))
                
                st.session_state.results_list.append(data)
                st.toast(f"Cargado: {data['Artista']}")
            else:
                st.warning(f"No se encontró metadata para: {item}")
            
            pbar.progress((idx + 1) / len(input_list))
        status.text("✅ Proceso finalizado.")

if st.session_state.results_list:
    df = pd.DataFrame(st.session_state.results_list)
    columns_mj = [
        "Barcode", "Cat No", "Artista", "Título", "Categoría", "Formato", 
        "Estado", "Condición Disco", "Condición Caratula", "Discográfica", 
        "País", "Año", "Costo", "Precio", "Stock", "Vendedor", "Tags", 
        "Tracklist", "Link fotos", "Comentario"
    ]
    
    final_df = df.reindex(columns=columns_mj)
    final_df.insert(0, 'ID', range(1, 1 + len(final_df)))
    
    st.dataframe(final_df, use_container_width=True)
    
    csv = final_df.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Descargar Matriz CSV", data=csv, file_name="Matriz_MusicJungle_Pro.csv", mime="text/csv")
