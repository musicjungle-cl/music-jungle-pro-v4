import streamlit as st
import pandas as pd
import discogs_client
import time
import requests
import re

# ============== CONFIGURACIÓN Y SESIÓN ==============
if "results_list" not in st.session_state:
    st.session_state.results_list = []
if "logs" not in st.session_state:
    st.session_state.logs = []

def add_log(msg):
    st.session_state.logs.insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")

# ============== MOTORES DE BÚSQUEDA ==============

def fetch_itunes(item):
    try:
        url = f"https://itunes.apple.com/lookup?upc={item}&entity=album"
        r = requests.get(url, timeout=5).json()
        if r.get('resultCount', 0) > 0:
            res = r['results'][0]
            return {
                "Artista": res.get("artistName"),
                "Título": res.get("collectionName"),
                "Año": res.get("releaseDate", "")[:4],
                "Discográfica": "iTunes (Digital)",
                "Imagen": res.get("artworkUrl100", "").replace("100x100bb", "600x600bb"),
                "País": "International",
                "Fuente": "iTunes"
            }
    except: pass
    return None

def fetch_musicbrainz(item):
    # MusicBrainz permite 1 req/s. Es más lento pero muy fiable.
    url = f"https://musicbrainz.org/ws/2/release/?query=barcode:{item}&fmt=json"
    try:
        time.sleep(1.0) 
        headers = {'User-Agent': 'MusicJungleBot/4.0 (contacto@musicjungle.cl)'}
        r = requests.get(url, headers=headers, timeout=5).json()
        if r.get('releases'):
            rel = r['releases'][0]
            return {
                "Artista": rel.get('artist-credit', [{}])[0].get('name'),
                "Título": rel.get('title'),
                "Año": rel.get('date', "")[:4],
                "Discográfica": rel.get('label-info', [{}])[0].get('label', {}).get('name', 'Unknown'),
                "Imagen": "", 
                "País": rel.get('country', 'Unknown'),
                "Fuente": "MusicBrainz"
            }
    except: pass
    return None

def fetch_discogs(dclient, item, origin):
    try:
        # Forzamos un pequeño delay preventivo para no quemar el token
        time.sleep(0.8) 
        if item.isdigit() and len(item) >= 7:
            res = dclient.search(barcode=item, type='release')
        else:
            res = dclient.search(catno=item, type='release')
        
        if res.count > 0:
            rel = res[0] # Simplificado: toma el primer match
            return {
                "Artista": rel.artists[0].name if rel.artists else "Unknown",
                "Título": rel.title,
                "Año": getattr(rel, "year", ""),
                "Discográfica": rel.labels[0].name if rel.labels else "",
                "Imagen": rel.thumb,
                "País": getattr(rel, "country", ""),
                "Fuente": "Discogs"
            }
    except Exception as e:
        if "429" in str(e):
            return "RATE_LIMIT"
        add_log(f"Error Discogs: {e}")
    return None

# ============== UI STREAMLIT ==============

st.set_page_config(page_title="Music Jungle Pro - Engine Switcher", layout="wide")
st.title("📀 Music Jungle Pro v4.0")

with st.sidebar:
    st.header("🔌 Conectividad")
    token = st.text_input("Discogs Token", type="password")
    
    st.divider()
    st.header("🤖 Estrategia de Fallback")
    mode = st.radio("Si Discogs falla o se agota:", 
                    ["Detener proceso", "Saltar a MusicBrainz", "Saltar a iTunes"])
    
    if st.button("🗑️ Resetear sesión"):
        st.session_state.results_list = []
        st.session_state.logs = []
        st.rerun()

# Área de entrada
raw_input = st.text_area("Ingresa Barcodes o Números de Catálogo:", height=150, placeholder="724383125726\nCDP 7 46445 2")
input_list = [x.strip() for x in re.split(r'[\n,]', raw_input) if x.strip()]

if input_list:
    processed_ids = [r['ID_Busqueda'] for r in st.session_state.results_list]
    remaining = [i for i in input_list if i not in processed_ids]
    
    st.info(f"Pendientes: {len(remaining)} | Procesados: {len(processed_ids)}")

    if st.button("🚀 Iniciar / Reanudar Carga"):
        dclient = discogs_client.Client("MusicJungleApp/4.0", user_token=token) if token else None
        
        prog_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, item in enumerate(remaining):
            status_text.text(f"Procesando: {item}...")
            data = None
            
            # 1. INTENTO PRINCIPAL: DISCOGS
            if dclient:
                data = fetch_discogs(dclient, item, "Cualquiera")
            
            # 2. MANEJO DE RATE LIMIT O FALLO
            if data == "RATE_LIMIT":
                add_log(f"⚠️ Discogs agotado en {item}. Aplicando Fallback...")
                if mode == "Saltar a MusicBrainz":
                    data = fetch_musicbrainz(item)
                elif mode == "Saltar a iTunes":
                    data = fetch_itunes(item)
                else:
                    st.error("Límite de Discogs alcanzado. Proceso detenido.")
                    break
            
            # 3. SI DISCOGS NO ENCONTRÓ NADA (SIN ERROR 429)
            if not data:
                if mode == "Saltar a MusicBrainz": data = fetch_musicbrainz(item)
                elif mode == "Saltar a iTunes": data = fetch_itunes(item)

            if data and isinstance(data, dict):
                data['ID_Busqueda'] = item
                st.session_state.results_list.append(data)
                add_log(f"✅ {item} cargado desde {data['Fuente']}")
            else:
                add_log(f"❌ {item} no encontrado en ninguna fuente.")
            
            prog_bar.progress((idx + 1) / len(remaining))
        
        st.rerun()

# ============== VISTA DE RESULTADOS ==============
if st.session_state.results_list:
    df = pd.DataFrame(st.session_state.results_list)
    
    # Reordenar para la matriz Music Jungle
    cols = ["ID_Busqueda", "Artista", "Título", "Año", "Discográfica", "País", "Fuente", "Imagen"]
    df = df[cols]
    
    st.subheader("📊 Matriz Generada")
    st.dataframe(df, use_container_width=True)
    
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Descargar Matriz CSV", data=csv, file_name="matriz_mj_pro.csv", mime="text/csv")

# Logs de actividad
if st.session_state.logs:
    with st.expander("📝 Ver log de actividad"):
        for l in st.session_state.logs:
            st.text(l)
