import re

import discogs_client
import pandas as pd
import streamlit as st

import mj_logic as mj

APP_VERSION = "5.0"
UA = f"MusicJungleApp/{APP_VERSION}"

st.set_page_config(page_title=f"Music Jungle Pro v{APP_VERSION}", layout="wide")
st.title("📀 Music Jungle - Matriz de carga")


def secret(name: str, default: str = "") -> str:
    """Lee un secreto de Streamlit Cloud sin fallar si no existe secrets.toml."""
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


# ============== SIDEBAR ==============
with st.sidebar:
    st.header("⚙️ Configuración")
    token = st.text_input(
        "Discogs Token", type="password",
        help="Si lo dejas vacío se usa DISCOGS_TOKEN de los secretos de la app.",
    ) or secret("DISCOGS_TOKEN")

    vendedor = st.selectbox("Vendedor", list(mj.VENDORS.keys()))
    st.caption(f"post_author WordPress: **{mj.VENDORS[vendedor]['id']}**")

    estado_global = st.radio("Estado", ["Nuevo", "Usado"], horizontal=True)
    if estado_global == "Usado":
        condicion = st.selectbox("Condición (disco y carátula)", mj.CONDICIONES, index=2)
    else:
        condicion = "Mint (M)"
        st.caption("Nuevo ⇒ Mint (M) en disco y carátula.")

    origin = st.selectbox(
        "Origen preferido", ["Cualquiera"] + list(mj.REGION_COUNTRIES.keys()),
        help="Sin preferencia se prioriza Europe > Chile > Argentina > México.",
    )
    shipping_class = st.selectbox(
        "Clase de envío", mj.SHIPPING_CLASSES,
        index=mj.SHIPPING_CLASSES.index(mj.default_shipping_class(vendedor)),
        help="PMS y DAAM (por encargo) usan por-encargo. Para el resto, confirma antes de cargar.",
    )

    wc_url = secret("WC_BASE_URL", "https://musicjungle.cl")
    wc_key, wc_secret = secret("WC_CONSUMER_KEY"), secret("WC_CONSUMER_SECRET")
    check_dups = st.checkbox(
        "Chequear duplicados en musicjungle.cl",
        value=bool(wc_key and wc_secret), disabled=not (wc_key and wc_secret),
        help="Requiere WC_CONSUMER_KEY y WC_CONSUMER_SECRET (solo lectura) en los secretos de la app.",
    )
    if not (wc_key and wc_secret):
        st.caption("Sin credenciales WC en secretos: el chequeo de duplicados está desactivado.")

for w in mj.vendor_warnings(vendedor, estado_global):
    st.warning(w)

if "results_list" not in st.session_state:
    st.session_state.results_list = []

# ============== ENTRADA ==============
raw_input = st.text_area("Lista de Barcodes o Cat Nos (uno por línea, o separados por coma):", height=150)
input_list = mj.parse_inputs(raw_input)
if input_list:
    st.caption(f"{len(input_list)} ítems únicos.")


def run_dup_check(row: dict) -> None:
    if check_dups and row.get("Barcode"):
        estado, detalle = mj.check_duplicate(row["Barcode"], wc_url, wc_key, wc_secret)
        row["Duplicado"] = {"existe": "⚠️ " + detalle, "libre": "✅ libre", "error": "❓ " + detalle}[estado]
    else:
        row["Duplicado"] = ""


if input_list and st.button("🚀 Iniciar Carga"):
    if not token:
        st.error("Falta el token de Discogs (sidebar o secreto DISCOGS_TOKEN).")
        st.stop()
    dclient = discogs_client.Client(UA, user_token=token)
    pbar = st.progress(0)
    status = st.empty()
    pendientes = [i for i in input_list if not any(r.get("ID_Search") == i for r in st.session_state.results_list)]

    for idx, item in enumerate(pendientes):
        status.write(f"Buscando {item} ({idx + 1}/{len(pendientes)})…")
        data = mj.fetch_discogs(dclient, item, origin)
        if data == mj.RATE_LIMIT:
            st.warning(f"Discogs limitó las consultas en {item}; se usa MusicBrainz y queda para enriquecer.")
        if (data == mj.RATE_LIMIT or not data) and mj.is_barcode(item):
            data = mj.fetch_musicbrainz(item)
        if isinstance(data, dict):
            row = mj.finalize_row(
                data, item=item, vendedor=vendedor, estado=estado_global,
                condicion_usado=condicion, shipping_class=shipping_class,
            )
            run_dup_check(row)
            st.session_state.results_list.append(row)
        else:
            st.warning(f"No encontrado: {item}")
        pbar.progress((idx + 1) / max(len(pendientes), 1))
    status.empty()

# ============== ENRIQUECIMIENTO (MusicBrainz -> Discogs) ==============
items_to_enrich = [i for i in st.session_state.results_list if i.get("Needs_Enrichment")]
if items_to_enrich:
    st.warning(f"⚠️ Hay {len(items_to_enrich)} ítems con data incompleta (vía MusicBrainz).")
    if st.button("🔄 Intentar completar data con Discogs (Pasada Final)"):
        if not token:
            st.error("Falta el token de Discogs.")
            st.stop()
        dclient = discogs_client.Client(UA, user_token=token)
        enrich_pbar = st.progress(0)
        for idx, row in enumerate(items_to_enrich):
            enriched = mj.fetch_discogs(dclient, row["ID_Search"], origin)
            if isinstance(enriched, dict):
                mj.apply_enrichment(row, enriched)
            enrich_pbar.progress((idx + 1) / len(items_to_enrich))
        st.success("Enriquecimiento finalizado.")
        st.rerun()

# ============== RESULTADO EDITABLE ==============
if st.session_state.results_list:
    st.subheader("🧾 Resultado")
    st.caption(
        "Edita PDC (costo), Precio y Stock directamente en la tabla. "
        + ("Para DAAM/PMS el precio se sugiere con costo × 1,7 × 1,19 redondeado hacia arriba a *900. "
           if vendedor in mj.VENDORS_ENCARGO else
           "Para este vendedor no hay fórmula fija de precio: complétalo tú. ")
        + "El 'Nombre ficha' se recalcula al descargar."
    )

    df = pd.DataFrame(st.session_state.results_list)
    for c in mj.MATRIX_COLUMNS + mj.EXTRA_COLUMNS + ["Duplicado", "Fuente"]:
        if c not in df.columns:
            df[c] = ""
    df["ID"] = range(1, len(df) + 1)

    view_cols = ["ID", "Duplicado", "Fuente"] + [c for c in mj.MATRIX_COLUMNS if c != "ID"] + mj.EXTRA_COLUMNS
    edited = st.data_editor(
        df[view_cols],
        width="stretch",
        hide_index=True,
        key="final_editor",
        column_config={
            "PDC": st.column_config.NumberColumn("PDC (costo)", min_value=0, step=100),
            "Precio": st.column_config.NumberColumn(min_value=0, step=100),
            "Stock": st.column_config.NumberColumn(min_value=1, step=1),
            "Duplicado": st.column_config.TextColumn(disabled=True),
            "Fuente": st.column_config.TextColumn(disabled=True),
            "Nombre ficha": st.column_config.TextColumn(disabled=True),
            "Vendedor ID": st.column_config.NumberColumn(disabled=True),
            "Categoría WC": st.column_config.NumberColumn(disabled=True),
        },
    )

    # Volcar las ediciones al estado, recalculando derivados
    for i, rec in enumerate(edited.to_dict("records")):
        base = st.session_state.results_list[i]
        costo_prev = mj.to_number(base.get("PDC"))
        base.update({k: rec[k] for k in mj.MATRIX_COLUMNS + ["Clase de envío"] if k != "ID"})
        costo, precio = mj.to_number(rec["PDC"]), mj.to_number(rec["Precio"])
        base["PDC"], base["Precio"] = costo, precio
        # Si cambió el costo y el vendedor es por encargo, re-sugerir el precio
        if base["Vendedor"] in mj.VENDORS_ENCARGO and costo and costo != costo_prev:
            base["Precio"] = mj.precio_encargo(costo)
        mj.refresh_derived(base)

    out = pd.DataFrame(st.session_state.results_list)
    out["ID"] = range(1, len(out) + 1)
    out = out.reindex(columns=mj.MATRIX_COLUMNS + mj.EXTRA_COLUMNS)

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        st.download_button(
            "⬇️ Descargar Matriz CSV", data=out.to_csv(index=False).encode("utf-8"),
            file_name="Matriz_MusicJungle.csv", mime="text/csv",
        )
    with col2:
        if st.button("🗑️ Limpiar resultados"):
            st.session_state.results_list = []
            st.rerun()
