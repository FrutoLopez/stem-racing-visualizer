"""STEM Racing Results Visualizer - Streamlit Application.
Interactive tournament dashboard for live timing, head-to-head match-ups, and championship podium.
Fully adheres to official STEM Racing / F1 in Schools regulations:
- C9.5: Reaction race scoring (Fastest total race time, Base Time 120%, DNF deduction if 5 pts)
- C9.6: Time Trial race scoring (2nd & 3rd best car race time avg, DNF replacement rule, Base Time 115%, DNF deduction if 20 pts)
- C9.7: DNF race results (damage, part separation, off track)
- C9.8: False starts (trigger pressed before lights extinguish, 2.5-point penalty and race forfeit)
"""

import os
from datetime import datetime
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

import data_processor as dp
import styles

# Page Configuration
st.set_page_config(
    page_title="Visualizador STEM Racing",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded"
)


def render_html(html_str: str):
    """Safely render raw HTML without markdown treating indented lines as code blocks."""
    clean_lines = [line.strip() for line in html_str.splitlines() if line.strip()]
    clean_html = "\n".join(clean_lines)
    if hasattr(st, "html"):
        st.html(clean_html)
    else:
        st.markdown(clean_html, unsafe_allow_html=True)


def format_pts(val: float) -> str:
    """Format points cleanly displaying decimals only when needed (e.g. 107.5 vs 110)."""
    if pd.isna(val):
        return "0"
    v = float(val)
    return f"{v:.1f}".rstrip('0').rstrip('.') if (v % 1 != 0) else f"{int(v)}"


# Inject Custom CSS
if hasattr(st, "html"):
    st.html(styles.inject_custom_css())
else:
    st.markdown(styles.inject_custom_css(), unsafe_allow_html=True)

# Assets & Paths
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
TEAMS_CSV_PATH = os.path.join(os.path.dirname(__file__), "Equipos.csv")
LIVE_CSV_PATH = os.path.join(os.path.dirname(__file__), "live_race_data.csv")

logo_b64 = styles.get_base64_encoded_image(LOGO_PATH)

# Load official teams and matchups
official_teams = dp.load_teams_from_csv(TEAMS_CSV_PATH)
matchups_list = dp.get_matchups(official_teams)

RUNS_SCHEMA = ['team', 'race_number', 'reaction_time', 'race_time', 'total_time', 'is_dnf', 'is_false_start']


def normalize_runs_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive active runs for the visualizer from the append-only CSV history.
    Deduplicates by (team, race_number) keeping the latest entry ('last'),
    so edited records overwrite previous values in the visualizer while
    preserving all historical rows in the CSV.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=RUNS_SCHEMA)
    cleaned = df.copy()
    for col in RUNS_SCHEMA:
        if col not in cleaned.columns:
            cleaned[col] = False if col in ('is_dnf', 'is_false_start') else (0.0 if 'time' in col else '')
    cleaned['team'] = cleaned['team'].astype(str).str.strip()
    cleaned = cleaned[cleaned['team'] != '']
    cleaned['race_number'] = pd.to_numeric(cleaned['race_number'], errors='coerce').fillna(1).astype(int)
    cleaned['reaction_time'] = pd.to_numeric(cleaned['reaction_time'], errors='coerce').fillna(0.0).astype(float)
    cleaned['is_dnf'] = cleaned['is_dnf'].astype(bool)
    cleaned['is_false_start'] = cleaned['is_false_start'].astype(bool)

    inv_mask = cleaned['is_dnf'] | cleaned['is_false_start']
    cleaned.loc[inv_mask, 'race_time'] = np.nan
    cleaned.loc[inv_mask, 'total_time'] = np.nan

    not_inv = ~inv_mask
    cleaned.loc[not_inv, 'race_time'] = pd.to_numeric(cleaned.loc[not_inv, 'race_time'], errors='coerce').fillna(0.0).astype(float)
    cleaned.loc[not_inv, 'total_time'] = (cleaned.loc[not_inv, 'reaction_time'] + cleaned.loc[not_inv, 'race_time']).round(4)

    # Deduplicate keeping the latest entry so overwrites always replace old records in the visualizer
    cleaned = cleaned.drop_duplicates(subset=['team', 'race_number'], keep='last')

    # Filter out cleared records (where not DNF, not FS, and race_time <= 0 and reaction_time <= 0)
    active_mask = cleaned['is_dnf'] | cleaned['is_false_start'] | (cleaned['race_time'] > 0) | (cleaned['reaction_time'] > 0)
    cleaned = cleaned[active_mask]

    return cleaned[RUNS_SCHEMA].reset_index(drop=True)


@st.cache_resource
def get_shared_race_store():
    """Global in-memory store shared across all browser tabs/windows for real-time visualizer updates."""
    if os.path.exists(LIVE_CSV_PATH) and os.path.getsize(LIVE_CSV_PATH) > 0:
        try:
            hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
            # Ensure existing CSV on disk has id and timestamp columns persisted
            dp.save_runs_to_csv(hist_df, LIVE_CSV_PATH)
            initial_df = normalize_runs_df(hist_df)
        except Exception:
            hist_df = pd.DataFrame(columns=dp.CSV_SCHEMA)
            initial_df = pd.DataFrame(columns=RUNS_SCHEMA)
    else:
        hist_df = pd.DataFrame(columns=dp.CSV_SCHEMA)
        initial_df = pd.DataFrame(columns=RUNS_SCHEMA)
    mtime = os.path.getmtime(LIVE_CSV_PATH) if os.path.exists(LIVE_CSV_PATH) else 0.0
    return {
        "version": 1,
        "history_df": hist_df,
        "runs_df": initial_df,
        "custom_scores": None,
        "csv_mtime": mtime,
    }


shared_store = get_shared_race_store()
if "history_df" not in shared_store or shared_store["history_df"] is None:
    shared_store["history_df"] = dp.load_runs_from_csv(LIVE_CSV_PATH)

# Check if CSV file was updated externally on disk
if os.path.exists(LIVE_CSV_PATH):
    try:
        disk_mtime = os.path.getmtime(LIVE_CSV_PATH)
        if disk_mtime > shared_store["csv_mtime"] + 0.05:
            hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
            shared_store["history_df"] = hist_df
            shared_store["runs_df"] = normalize_runs_df(hist_df)
            shared_store["csv_mtime"] = disk_mtime
            shared_store["version"] += 1
    except Exception:
        pass


def append_race_records(new_rows: list) -> pd.DataFrame:
    """
    Append new or edited race records to the CSV file with a sequential `id` and `timestamp`,
    and update the active deduplicated `runs_df` for all connected visualizers.
    """
    hist_df = dp.append_runs_to_csv(new_rows, LIVE_CSV_PATH)
    active_df = normalize_runs_df(hist_df)
    shared_store["history_df"] = hist_df.copy()
    shared_store["runs_df"] = active_df.copy()
    if os.path.exists(LIVE_CSV_PATH):
        shared_store["csv_mtime"] = os.path.getmtime(LIVE_CSV_PATH)
    shared_store["version"] += 1
    st.session_state.history_df = hist_df.copy()
    st.session_state.runs_df = active_df.copy()
    st.session_state.local_store_version = shared_store["version"]
    return active_df


def clear_all_records() -> None:
    """Clear all records from CSV and active state to start fresh from 0."""
    empty_hist = dp.clear_runs_csv(LIVE_CSV_PATH)
    empty_active = pd.DataFrame(columns=RUNS_SCHEMA)
    shared_store["history_df"] = empty_hist.copy()
    shared_store["runs_df"] = empty_active.copy()
    if os.path.exists(LIVE_CSV_PATH):
        shared_store["csv_mtime"] = os.path.getmtime(LIVE_CSV_PATH)
    shared_store["version"] += 1
    st.session_state.history_df = empty_hist.copy()
    st.session_state.runs_df = empty_active.copy()
    st.session_state.local_store_version = shared_store["version"]
    st.session_state["_last_active_form_ctx"] = None


def commit_runs_df(new_df: pd.DataFrame) -> pd.DataFrame:
    """Save full grid edits to CSV (with id and timestamp) and broadcast to all connected visualizers."""
    dp.save_runs_to_csv(new_df, LIVE_CSV_PATH)
    hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
    cleaned = normalize_runs_df(hist_df)
    shared_store["history_df"] = hist_df.copy()
    shared_store["runs_df"] = cleaned.copy()
    if os.path.exists(LIVE_CSV_PATH):
        shared_store["csv_mtime"] = os.path.getmtime(LIVE_CSV_PATH)
    shared_store["version"] += 1
    st.session_state.history_df = hist_df.copy()
    st.session_state.runs_df = cleaned.copy()
    st.session_state.local_store_version = shared_store["version"]
    st.session_state["_last_active_form_ctx"] = None
    return cleaned


@st.fragment(run_every=1.0)
def live_visualizer_sync_watcher():
    """Background watcher that automatically refreshes visualizer tabs when records are saved."""
    store = get_shared_race_store()
    if "history_df" not in store or store["history_df"] is None:
        store["history_df"] = dp.load_runs_from_csv(LIVE_CSV_PATH)
    if os.path.exists(LIVE_CSV_PATH):
        try:
            curr_mtime = os.path.getmtime(LIVE_CSV_PATH)
            if curr_mtime > store["csv_mtime"] + 0.05:
                hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
                store["history_df"] = hist_df
                store["runs_df"] = normalize_runs_df(hist_df)
                store["csv_mtime"] = curr_mtime
                store["version"] += 1
        except Exception:
            pass
    if st.session_state.get("local_store_version", -1) != store["version"]:
        st.session_state.history_df = store["history_df"].copy()
        st.session_state.runs_df = store["runs_df"].copy()
        if store["custom_scores"] is not None:
            st.session_state.custom_scores = store["custom_scores"].copy()
        st.session_state.local_store_version = store["version"]
        st.rerun()


# Sync current session with shared store on every script run
st.session_state.history_df = shared_store["history_df"].copy()
st.session_state.runs_df = shared_store["runs_df"].copy()
st.session_state.local_store_version = shared_store["version"]

if "custom_scores" not in st.session_state:
    st.session_state.custom_scores = shared_store["custom_scores"].copy() if shared_store["custom_scores"] is not None else None
elif shared_store["custom_scores"] is not None:
    st.session_state.custom_scores = shared_store["custom_scores"].copy()

if "podium_slide_step" not in st.session_state:
    st.session_state.podium_slide_step = 0

if "podium_anim_nonce" not in st.session_state:
    st.session_state.podium_anim_nonce = 0

# Handle pending view switch before sidebar radio widget is instantiated
if "_pending_view_mode" in st.session_state and st.session_state._pending_view_mode:
    st.session_state.app_view_mode = st.session_state._pending_view_mode
    st.session_state._pending_view_mode = None

# Current runs dataframe
df_runs = st.session_state.runs_df.copy() if st.session_state.runs_df is not None else pd.DataFrame(columns=RUNS_SCHEMA)

# Check race progress (all teams have 4 races)
is_auto_culminated, done_cnt, exp_cnt = dp.check_races_culminated(df_runs, official_teams)

# ==============================================================================
# SIDEBAR CONTROLS
# ==============================================================================
with st.sidebar:
    if logo_b64:
        render_html(f'<div style="text-align: center; margin-bottom: 20px;"><img src="data:image/png;base64,{logo_b64}" style="max-width: 85%; height: auto;"/></div>')

    st.markdown("## 🧭 Pantalla Activa")
    screen_options = [
        "⏱️ Tiempos y Resultados en Pista",
        "🏆 Ceremonia de Podio Oficial",
        "📝 Pantalla de Edición y Registro"
    ]
    cur_mode = st.session_state.get("app_view_mode", "⏱️ Tiempos y Resultados en Pista")
    if cur_mode not in screen_options:
        cur_mode = "⏱️ Tiempos y Resultados en Pista"
        st.session_state.app_view_mode = cur_mode

    selected_view = st.radio(
        "Seleccionar Pantalla:",
        options=screen_options,
        index=screen_options.index(cur_mode),
        key="app_view_mode",
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.markdown("### 📂 Archivo CSV de Carreras")
    export_df_sidebar = st.session_state.history_df if (st.session_state.history_df is not None and not st.session_state.history_df.empty) else pd.DataFrame(columns=dp.CSV_SCHEMA)
    csv_bytes_sidebar = export_df_sidebar.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Exportar CSV de Carreras",
        data=csv_bytes_sidebar,
        file_name=f"carreras_stem_racing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True,
        key="sidebar_export_csv_btn",
        help="Descarga una copia del archivo CSV con todos los registros e historial de timestamps."
    )

    uploaded_race_csv = st.file_uploader(
        "📤 Subir CSV para Visualizar:",
        type=["csv"],
        key="race_csv_uploader",
        help="Sube un archivo CSV de carreras para cargar sus datos y probar las visualizaciones."
    )
    if uploaded_race_csv is not None:
        file_sig = f"{uploaded_race_csv.name}_{uploaded_race_csv.size}"
        auto_loaded = st.session_state.get("_last_uploaded_race_csv_sig") != file_sig
        reload_clicked = st.button("🔄 Recargar CSV Subido", use_container_width=True, key="reload_uploaded_csv_btn")
        if auto_loaded or reload_clicked:
            uploaded_race_csv.seek(0)
            loaded_csv_df = dp.load_runs_from_csv(uploaded_race_csv)
            commit_runs_df(loaded_csv_df)
            st.session_state["_last_uploaded_race_csv_sig"] = file_sig
            st.toast(f"✅ CSV '{uploaded_race_csv.name}' cargado ({len(loaded_csv_df)} registros).")
            st.rerun()
        else:
            st.caption(f"✅ Activo: `{uploaded_race_csv.name}` ({len(st.session_state.history_df)} filas)")
    else:
        st.session_state["_last_uploaded_race_csv_sig"] = None

    st.markdown("---")
    st.markdown("### 📝 Rúbrica de Jueces")
    uploaded_rubric = st.file_uploader(
        "Subir Archivo de Rúbrica:",
        type=["csv", "xlsx"],
        key="rubric_file_uploader",
        help="Sube un archivo CSV o Excel con los puntajes de las categorías de jueces (modo dummy de referencia)."
    )
    if uploaded_rubric is not None:
        st.success(f"📁 Archivo recibido: {uploaded_rubric.name}")

    with st.expander("✏️ Editar Puntajes de Jueces Manualmente"):
        st.caption("Ajusta los puntajes evaluados por los jueces para el Podio General:")
        if st.session_state.custom_scores is not None:
            edited_rubric = st.data_editor(
                st.session_state.custom_scores[['team', 'Identidad de Marca', 'Presentación Verbal', 'Especificaciones y Escrutinio', 'Diseño e Ingeniería', 'Gestión de Proyecto']],
                hide_index=True,
                use_container_width=True,
                key="rubric_editor"
            )
            if st.button("Guardar Puntajes de Jueces", use_container_width=True):
                for col in ['Identidad de Marca', 'Presentación Verbal', 'Especificaciones y Escrutinio', 'Diseño e Ingeniería', 'Gestión de Proyecto']:
                    st.session_state.custom_scores[col] = edited_rubric[col]
                st.session_state.custom_scores['Total'] = st.session_state.custom_scores[dp.DEFAULT_CATEGORIES].sum(axis=1)
                st.session_state.custom_scores = st.session_state.custom_scores.sort_values(by='Total', ascending=False).reset_index(drop=True)
                st.session_state.custom_scores['rank'] = st.session_state.custom_scores.index + 1
                shared_store["custom_scores"] = st.session_state.custom_scores.copy()
                shared_store["version"] += 1
                st.session_state.local_store_version = shared_store["version"]
                st.toast("✅ Puntajes de jueces guardados.")
                st.rerun()

# ==============================================================================
# AUTOMATIC REAL-TIME CALCULATIONS (220 PTS RACING SUM FOR PODIUM)
# ==============================================================================
calc_results = dp.calculate_racing_results(df_runs, all_teams=official_teams, award_points=True)
df_teams_summary = calc_results['teams_summary']
df_race_lb = calc_results['race_leaderboard']
df_total_lb = calc_results['total_leaderboard']
base_race_time = calc_results['base_race_time']
base_total_time = calc_results['base_total_time']

# Racing score for General Championship is ALWAYS the sum of Tiempo de Carro (110 pts) + Tiempo Más Rápido (110 pts) = 220 pts max
pts_race_map = dict(zip(df_race_lb['team'], df_race_lb['points']))
pts_tot_map = dict(zip(df_total_lb['team'], df_total_lb['points']))
racing_pts_map = {t: float(pts_race_map.get(t, 0.0) + pts_tot_map.get(t, 0.0)) for t in official_teams}

# Manage Judge category scores for Championship Podio
if st.session_state.custom_scores is None or set(st.session_state.custom_scores['team']) != set(official_teams):
    st.session_state.custom_scores = dp.get_default_category_scores(official_teams, racing_pts_map)
    shared_store["custom_scores"] = st.session_state.custom_scores.copy()
else:
    st.session_state.custom_scores['Carrera'] = st.session_state.custom_scores['team'].map(racing_pts_map).fillna(0.0)
    cat_cols = [c for c in dp.DEFAULT_CATEGORIES if c in st.session_state.custom_scores.columns]
    st.session_state.custom_scores['Total'] = st.session_state.custom_scores[cat_cols].sum(axis=1)
    st.session_state.custom_scores = st.session_state.custom_scores.sort_values(by='Total', ascending=False).reset_index(drop=True)
    st.session_state.custom_scores['rank'] = st.session_state.custom_scores.index + 1
    shared_store["custom_scores"] = st.session_state.custom_scores.copy()

df_championship = st.session_state.custom_scores


# ==============================================================================
# HELPER: ANIMATED REVEAL SCORECARD FOR PODIUM CEREMONY (3ro, 2do, 1ro)
# ==============================================================================
def render_place_reveal_slide(rank_target: int, medal_emoji: str, title: str, accent_color: str):
    team_data = df_championship[df_championship['rank'] == rank_target]
    if team_data.empty:
        st.info("No hay datos disponibles para esta posición.")
        return

    row = team_data.iloc[0]
    team_name = row['team']
    total_pts = row['Total']
    pts_car = pts_race_map.get(team_name, 0.0)
    pts_fast = pts_tot_map.get(team_name, 0.0)

    # 1. Left Table: Identidad, Verbal, Carrera
    left_table_html = f"""<table class="sr-pptx-table" style="font-size: 15px;">
        <thead>
            <tr>
                <th style="width: 65%;">Categoría de Evaluación</th>
                <th style="width: 35%; text-align: right;">Puntos Obtenidos</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td style="font-weight: 700;">🎨 Identidad de Marca</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{int(row['Identidad de Marca'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 100</span></td>
            </tr>
            <tr>
                <td style="font-weight: 700;">🎤 Presentación Verbal</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{int(row['Presentación Verbal'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 160</span></td>
            </tr>
            <tr style="background: rgba(230, 0, 122, 0.14);">
                <td style="font-weight: 800; color: #FF2A85;">
                    🏎️ Carrera en Pista
                    <div style="font-size: 11px; color: #A09EB8; font-weight: 600; margin-top: 2px;">
                        Carro: {format_pts(pts_car)} + Rápido: {format_pts(pts_fast)}
                    </div>
                </td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: #FF2A85;">{format_pts(row['Carrera'])} <span style="font-size: 12px; color: #FF8A00; font-weight: 600;">/ 220</span></td>
            </tr>
        </tbody>
    </table>"""

    # 2. Right Table: Escrutinio, Diseño, Gestión
    right_table_html = f"""<table class="sr-pptx-table" style="font-size: 15px;">
        <thead>
            <tr>
                <th style="width: 65%;">Categoría de Evaluación</th>
                <th style="width: 35%; text-align: right;">Puntos Obtenidos</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td style="font-weight: 700;">📐 Especificaciones y Escrutinio</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{int(row['Especificaciones y Escrutinio'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 170</span></td>
            </tr>
            <tr>
                <td style="font-weight: 700;">💻 Diseño e Ingeniería</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{int(row['Diseño e Ingeniería'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 180</span></td>
            </tr>
            <tr>
                <td style="font-weight: 700;">📊 Empresa y Gestión de Proyecto</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{int(row['Gestión de Proyecto'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 160</span></td>
            </tr>
        </tbody>
    </table>"""

    render_html(f"""
    <div key="slide-reveal-{rank_target}-{st.session_state.podium_anim_nonce}" style="max-width: 960px; margin: 0 auto;">
        <!-- Título de la Posición Oficial -->
        <div class="sr-anim-title" style="text-align: center; margin-bottom: 20px;">
            <h2 style="font-size: 44px; font-weight: 900; color: {accent_color}; text-transform: uppercase; margin: 0; letter-spacing: 2px; text-shadow: 0 4px 20px rgba(0,0,0,0.6);">
                {medal_emoji} {title}
            </h2>
        </div>

        <!-- Equipo Ganador y Puntaje Total (ARRIBA en puesto protagónico, aparece de ÚLTIMO con suspenso dramático) -->
        <div class="sr-anim-winner" style="display: flex; justify-content: center; align-items: center; gap: 40px; background: rgba(25, 17, 50, 0.92); border: 2px solid {accent_color}; border-radius: 20px; padding: 22px 50px; margin-bottom: 24px; box-shadow: 0 12px 40px rgba(0,0,0,0.65), 0 0 25px {accent_color}55;">
            <div style="text-align: center;">
                <div style="font-size: 12px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1.5px;">Equipo Galardonado</div>
                <div style="font-size: 40px; font-weight: 900; color: #FFFFFF; margin-top: 4px; letter-spacing: 0.5px;">{team_name}</div>
            </div>
            <div style="height: 56px; width: 2px; background: rgba(255,255,255,0.2);"></div>
            <div style="text-align: center;">
                <div style="font-size: 12px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1.5px;">Puntaje Total Acumulado</div>
                <div style="font-size: 44px; font-weight: 900; color: {accent_color}; margin-top: 4px;">{format_pts(total_pts)} <span style="font-size: 16px; color: #E6E4F0;">/ 990 PTS</span></div>
            </div>
        </div>

        <!-- Puntos en las Categorías (Aparecen PRIMERO debajo) -->
        <div class="sr-anim-categories" style="margin-bottom: 15px;">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div>{left_table_html}</div>
                <div>{right_table_html}</div>
            </div>
        </div>
    </div>
    """)


def render_podium_intro_slide():
    """Introductory slide for the Championship Podium ceremony."""
    render_html(f"""
    <div key="podium-intro-{st.session_state.podium_anim_nonce}">
        <div class="sr-anim-title" style="text-align: center; max-width: 900px; margin: 15px auto 0 auto;">
            <div style="font-size: 64px; line-height: 1; margin-bottom: 8px;">🏆</div>
            <div style="font-size: 13px; font-weight: 800; color: #ED6D05; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 6px;">
                Campeonato STEM Racing
            </div>
            <h1 style="font-size: 42px; font-weight: 900; color: #FFFFFF; text-transform: uppercase; margin: 0; letter-spacing: 2px; text-shadow: 0 4px 25px rgba(237, 109, 5, 0.4);">
                Premiación y Podio
            </h1>
        </div>

        <div class="sr-anim-categories" style="display: flex; justify-content: center; align-items: center; gap: 24px; margin: 26px auto 20px auto; max-width: 820px;">
            <div style="background: rgba(25, 17, 50, 0.85); border: 2px solid #ED6D05; border-radius: 16px; padding: 16px 36px; text-align: center; flex: 1; box-shadow: 0 8px 30px rgba(237, 109, 5, 0.2);">
                <div style="font-size: 12px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Puntaje Máximo del Torneo</div>
                <div style="font-size: 40px; font-weight: 900; color: #ED6D05; margin-top: 2px;">990 <span style="font-size: 16px; color: #FFFFFF;">PTS</span></div>
            </div>
            <div style="background: rgba(25, 17, 50, 0.85); border: 2px solid #009FE3; border-radius: 16px; padding: 16px 36px; text-align: center; flex: 1; box-shadow: 0 8px 30px rgba(0, 159, 227, 0.2);">
                <div style="font-size: 12px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Categorías Oficiales</div>
                <div style="font-size: 40px; font-weight: 900; color: #009FE3; margin-top: 2px;">6 <span style="font-size: 16px; color: #FFFFFF;">ÁREAS</span></div>
            </div>
        </div>

        <div class="sr-anim-categories" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; max-width: 860px; margin: 0 auto 28px auto;">
            <div style="background: rgba(18, 12, 36, 0.75); border: 1px solid rgba(0, 159, 227, 0.35); border-radius: 12px; padding: 14px 18px;">
                <div style="font-size: 13px; font-weight: 800; color: #009FE3;">📐 Escrutinio y Especificaciones</div>
                <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">170 <span style="font-size: 12px; color: #A09EB8;">pts</span></div>
            </div>
            <div style="background: rgba(18, 12, 36, 0.75); border: 1px solid rgba(237, 109, 5, 0.35); border-radius: 12px; padding: 14px 18px;">
                <div style="font-size: 13px; font-weight: 800; color: #ED6D05;">💻 Diseño e Ingeniería</div>
                <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">180 <span style="font-size: 12px; color: #A09EB8;">pts</span></div>
            </div>
            <div style="background: rgba(18, 12, 36, 0.75); border: 1px solid rgba(150, 27, 129, 0.45); border-radius: 12px; padding: 14px 18px;">
                <div style="font-size: 13px; font-weight: 800; color: #961B81;">📊 Empresa y Gestión</div>
                <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">160 <span style="font-size: 12px; color: #A09EB8;">pts</span></div>
            </div>
            <div style="background: rgba(18, 12, 36, 0.75); border: 1px solid rgba(252, 188, 0, 0.35); border-radius: 12px; padding: 14px 18px;">
                <div style="font-size: 13px; font-weight: 800; color: #FCBC00;">🎨 Identidad de Marca</div>
                <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">100 <span style="font-size: 12px; color: #A09EB8;">pts</span></div>
            </div>
            <div style="background: rgba(18, 12, 36, 0.75); border: 1px solid rgba(149, 193, 31, 0.35); border-radius: 12px; padding: 14px 18px;">
                <div style="font-size: 13px; font-weight: 800; color: #95C11F;">🎤 Presentación Verbal</div>
                <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">160 <span style="font-size: 12px; color: #A09EB8;">pts</span></div>
            </div>
            <div style="background: rgba(230, 0, 122, 0.15); border: 1px solid #E6007E; border-radius: 12px; padding: 14px 18px;">
                <div style="font-size: 13px; font-weight: 800; color: #E6007E;">🏎️ Carrera en Pista</div>
                <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">220 <span style="font-size: 12px; color: #A09EB8;">pts (110+110)</span></div>
            </div>
        </div>
    </div>
    """)


def render_podium_full_slide():
    """Full podium presentation with 3D pedestals and positions 4-9 split side-by-side."""
    if df_championship.empty:
        st.info("ℹ️ No hay datos de podio disponibles aún.")
        return

    t1 = df_championship[df_championship['rank'] == 1].iloc[0] if len(df_championship) >= 1 else None
    t2 = df_championship[df_championship['rank'] == 2].iloc[0] if len(df_championship) >= 2 else None
    t3 = df_championship[df_championship['rank'] == 3].iloc[0] if len(df_championship) >= 3 else None

    t1_name = t1['team'] if t1 is not None else 'Equipo 1'
    t1_pts = format_pts(t1['Total']) if t1 is not None else "0"
    t2_name = t2['team'] if t2 is not None else 'Equipo 2'
    t2_pts = format_pts(t2['Total']) if t2 is not None else "0"
    t3_name = t3['team'] if t3 is not None else 'Equipo 3'
    t3_pts = format_pts(t3['Total']) if t3 is not None else "0"

    # Positions 4-6 (Left) and 7-9 (Right), excluding position 10
    t4_6 = df_championship[df_championship['rank'].isin([4, 5, 6])].sort_values(by='rank')
    t7_9 = df_championship[df_championship['rank'].isin([7, 8, 9])].sort_values(by='rank')

    def build_mini_table(df_subset):
        rows = []
        for _, r in df_subset.iterrows():
            r_rank = int(r['rank'])
            r_team = r['team']
            r_pts = format_pts(r['Total'])
            rows.append(f"""<tr>
                <td style="padding: 10px 14px; font-weight: 800; font-size: 14px; color: #A09EB8; border-bottom: 1px solid rgba(255, 255, 255, 0.06); text-align: center;">#{r_rank}</td>
                <td style="padding: 10px 14px; font-weight: 800; font-size: 15px; color: #FFFFFF; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">🏎️ {r_team}</td>
                <td style="padding: 10px 14px; text-align: right; font-weight: 900; font-size: 16px; color: #00F0FF; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">{r_pts} <span style="font-size: 11px; color: #A09EB8;">PTS</span></td>
            </tr>""")
        if not rows:
            rows.append('<tr><td colspan="3" style="text-align: center; color: #A09EB8; padding: 10px;">Pendiente</td></tr>')
        return f"""<table class="sr-pptx-table" style="width: 100%; border-collapse: separate; border-spacing: 0; border-radius: 12px; overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.15); background: rgba(18, 12, 36, 0.9); box-shadow: 0 6px 20px rgba(0,0,0,0.35);">
            <thead>
                <tr>
                    <th style="padding: 10px 14px; background: linear-gradient(90deg, #2D1B54 0%, #1D123A 100%); color: #FFFFFF; font-weight: 800; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; border-bottom: 2px solid rgba(255, 107, 0, 0.5); width: 22%; text-align: center;">Pos</th>
                    <th style="padding: 10px 14px; background: linear-gradient(90deg, #2D1B54 0%, #1D123A 100%); color: #FFFFFF; font-weight: 800; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; border-bottom: 2px solid rgba(255, 107, 0, 0.5); width: 48%;">Equipo</th>
                    <th style="padding: 10px 14px; background: linear-gradient(90deg, #2D1B54 0%, #1D123A 100%); color: #FFFFFF; font-weight: 800; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; border-bottom: 2px solid rgba(255, 107, 0, 0.5); width: 30%; text-align: right;">Puntos</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>"""

    table_4_6 = build_mini_table(t4_6)
    table_7_9 = build_mini_table(t7_9)

    podium_ceremony_html = f"""
    <div key="podium-full-{st.session_state.podium_anim_nonce}">
        <div class="sr-podium-container" style="display: flex; justify-content: center; align-items: flex-end; gap: 20px; margin: 15px auto 20px auto; padding: 10px 0; max-width: 850px; width: 100%;">
            <div class="sr-podium-col sr-podium-anim-2" style="display: flex; flex-direction: column; align-items: center; justify-content: flex-end; flex: 1; max-width: 260px; min-width: 180px;">
                <div style="text-align: center; margin-bottom: 14px;">
                    <div style="font-size: 38px;">🥈</div>
                    <div style="font-size: 19px; font-weight: 900; color: #FFFFFF; text-shadow: 0 2px 8px rgba(0,0,0,0.8); margin-top: 4px;">{t2_name}</div>
                    <div style="font-size: 15px; font-weight: 800; color: #E6E8EB; margin-top: 2px;">{t2_pts} PTS</div>
                </div>
                <div class="sr-pedestal sr-pedestal-2" style="width: 100%; height: 180px; border-radius: 16px 16px 0 0; background: linear-gradient(180deg, #E6E8EB 0%, #767B85 100%); color: #0E1217; display: flex; flex-direction: column; align-items: center; justify-content: center; font-weight: 900; box-shadow: 0 10px 30px rgba(0,0,0,0.5), 0 0 25px rgba(220, 225, 235, 0.4); border-top: 3px solid #FFFFFF; box-sizing: border-box;">
                    <span style="font-size: 42px; line-height: 1;">2</span>
                    <span style="font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-top: 6px;">2do Lugar</span>
                </div>
            </div>

            <div class="sr-podium-col sr-podium-anim-1" style="display: flex; flex-direction: column; align-items: center; justify-content: flex-end; flex: 1; max-width: 260px; min-width: 180px;">
                <div style="text-align: center; margin-bottom: 14px;">
                    <div style="font-size: 48px;">👑</div>
                    <div style="font-size: 23px; font-weight: 900; color: #FCBC00; text-shadow: 0 2px 10px rgba(252, 188, 0, 0.5); margin-top: 4px;">{t1_name}</div>
                    <div style="font-size: 17px; font-weight: 900; color: #FCBC00; margin-top: 2px;">{t1_pts} PTS</div>
                </div>
                <div class="sr-pedestal sr-pedestal-1" style="width: 100%; height: 240px; border-radius: 16px 16px 0 0; background: linear-gradient(180deg, #FCBC00 0%, #B87C00 100%); color: #150C00; display: flex; flex-direction: column; align-items: center; justify-content: center; font-weight: 900; box-shadow: 0 14px 40px rgba(0,0,0,0.6), 0 0 35px rgba(252, 188, 0, 0.55); border-top: 3px solid #FFF275; box-sizing: border-box;">
                    <span style="font-size: 54px; line-height: 1;">1</span>
                    <span style="font-size: 16px; text-transform: uppercase; letter-spacing: 1.5px; margin-top: 6px;">CAMPEÓN</span>
                </div>
            </div>

            <div class="sr-podium-col sr-podium-anim-3" style="display: flex; flex-direction: column; align-items: center; justify-content: flex-end; flex: 1; max-width: 260px; min-width: 180px;">
                <div style="text-align: center; margin-bottom: 14px;">
                    <div style="font-size: 38px;">🥉</div>
                    <div style="font-size: 19px; font-weight: 900; color: #FFFFFF; text-shadow: 0 2px 8px rgba(0,0,0,0.8); margin-top: 4px;">{t3_name}</div>
                    <div style="font-size: 15px; font-weight: 800; color: #ED6D05; margin-top: 2px;">{t3_pts} PTS</div>
                </div>
                <div class="sr-pedestal sr-pedestal-3" style="width: 100%; height: 140px; border-radius: 16px 16px 0 0; background: linear-gradient(180deg, #ED6D05 0%, #994400 100%); color: #190B00; display: flex; flex-direction: column; align-items: center; justify-content: center; font-weight: 900; box-shadow: 0 10px 30px rgba(0,0,0,0.5), 0 0 25px rgba(237, 109, 5, 0.45); border-top: 3px solid #FFBE85; box-sizing: border-box;">
                    <span style="font-size: 38px; line-height: 1;">3</span>
                    <span style="font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-top: 6px;">3er Lugar</span>
                </div>
            </div>
        </div>

        <div class="sr-podium-anim-table" style="max-width: 860px; margin: 16px auto 20px auto;">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
                <div>
                    {table_4_6}
                </div>
                <div>
                    {table_7_9}
                </div>
            </div>
        </div>
    </div>
    """
    render_html(podium_ceremony_html)



# ==============================================================================
# ROUTING: EDICIÓN EN VIVO vs VISUALIZADOR DE DIAPOSITIVAS
# ==============================================================================
if selected_view == "📝 Pantalla de Edición y Registro":
    # -------------------------------------------------------------------------
    # PANTALLA DE EDICIÓN Y REGISTRO EN VIVO
    # -------------------------------------------------------------------------
    col_hdr_title, col_hdr_btn1, col_hdr_btn_exp, col_hdr_btn2 = st.columns([2.2, 0.9, 0.9, 1.0])
    with col_hdr_title:
        render_html("""
        <div style="margin-bottom: 20px;">
            <h2 style="font-size: 28px; font-weight: 900; color: #FFFFFF; text-transform: uppercase; margin: 0; letter-spacing: 1px;">
                📝 Registro y Edición de Carreras en Vivo
            </h2>
            <div style="color: #A09EB8; font-size: 14px; margin-top: 5px;">
                Selecciona el enfrentamiento y la carrera. Registra tiempos, marca DNF o False Start. Los resultados se reflejan automáticamente en el visualizador.
            </div>
        </div>
        """)
    with col_hdr_btn1:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        if st.button("📺 Ir al Visualizador", use_container_width=True):
            st.session_state._pending_view_mode = "⏱️ Tiempos y Resultados en Pista"
            st.rerun()
    with col_hdr_btn_exp:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        export_df_hdr = st.session_state.history_df if (st.session_state.history_df is not None and not st.session_state.history_df.empty) else pd.DataFrame(columns=dp.CSV_SCHEMA)
        st.download_button(
            label="📥 Exportar CSV",
            data=export_df_hdr.to_csv(index=False).encode("utf-8"),
            file_name=f"carreras_stem_racing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
            key="hdr_export_csv_btn"
        )
    @st.dialog("⚠️ Confirmar Borrado de Registros")
    def confirm_clear_all_dialog():
        st.warning("¿Estás seguro de que deseas borrar **todos los registros** de carreras? Esta acción vaciará los tiempos actuales y el archivo CSV activo para empezar desde 0.")
        col_conf_yes, col_conf_no = st.columns(2)
        with col_conf_yes:
            if st.button("✅ Sí, borrar todo", type="primary", use_container_width=True):
                clear_all_records()
                st.toast("🗑️ Todos los registros han sido borrados. Listo para empezar de 0.")
                st.rerun()
        with col_conf_no:
            if st.button("❌ Cancelar", use_container_width=True):
                st.rerun()

    with col_hdr_btn2:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        if st.button("🗑️ Borrar Todos los Registros", use_container_width=True):
            confirm_clear_all_dialog()

    # Matchup Selector (Top, Non-typeable Pills)
    matchup_labels = [m['label'] for m in matchups_list]
    st.markdown("<div style='font-size: 14px; font-weight: 700; color: #E6E4F0; margin-bottom: 6px;'>⚔️ Seleccionar Enfrentamiento Oficial:</div>", unsafe_allow_html=True)
    selected_matchup_label = st.pills(
        "Seleccionar Enfrentamiento Oficial:",
        options=matchup_labels,
        default=matchup_labels[0],
        key="input_matchup_selector",
        label_visibility="collapsed"
    )
    if not selected_matchup_label:
        selected_matchup_label = matchup_labels[0]

    selected_matchup = next(m for m in matchups_list if m['label'] == selected_matchup_label)
    team_a = selected_matchup['team_a']
    team_b = selected_matchup['team_b']

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # Race Selector (Placed BELOW matchup selector, Non-typeable Pills)
    st.markdown("<div style='font-size: 14px; font-weight: 700; color: #E6E4F0; margin-bottom: 6px;'>🏁 Seleccionar Carrera:</div>", unsafe_allow_html=True)
    selected_race_num = st.pills(
        "Seleccionar Carrera:",
        options=[1, 2, 3, 4],
        format_func=lambda x: f"Carrera {x}",
        default=1,
        key="input_race_num_selector",
        label_visibility="collapsed"
    )
    if not selected_race_num:
        selected_race_num = 1

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Fetch existing recorded run for team_a and team_b if any
    curr_runs = st.session_state.runs_df
    if not curr_runs.empty:
        mask_exist_a = (curr_runs['team'].astype(str).str.strip() == team_a) & (pd.to_numeric(curr_runs['race_number'], errors='coerce') == int(selected_race_num))
        mask_exist_b = (curr_runs['team'].astype(str).str.strip() == team_b) & (pd.to_numeric(curr_runs['race_number'], errors='coerce') == int(selected_race_num))
        run_a = curr_runs[mask_exist_a]
        run_b = curr_runs[mask_exist_b]
    else:
        run_a = pd.DataFrame()
        run_b = pd.DataFrame()

    already_exists_a = not run_a.empty
    already_exists_b = not run_b.empty

    def get_run_init_vals(run_df: pd.DataFrame):
        if not run_df.empty:
            r = run_df.iloc[-1]
            is_dnf = bool(r.get('is_dnf', False))
            is_fs = bool(r.get('is_false_start', False))
            rxn = float(r.get('reaction_time', 0.000)) if pd.notna(r.get('reaction_time')) else 0.000
            race = float(r.get('race_time', 0.000)) if (pd.notna(r.get('race_time')) and float(r.get('race_time', 0.0)) > 0) else 0.000
            return is_dnf, is_fs, rxn, race
        return False, False, 0.000, 0.000

    init_a_dnf, init_a_fs, init_a_rxn, init_a_race = get_run_init_vals(run_a)
    init_b_dnf, init_b_fs, init_b_rxn, init_b_race = get_run_init_vals(run_b)

    # Widget keys for current matchup & race
    chk_dnf_a_key = f"chk_dnf_a_{team_a}_{selected_race_num}"
    chk_fs_a_key = f"chk_fs_a_{team_a}_{selected_race_num}"
    num_rxn_a_key = f"num_rxn_a_{team_a}_{selected_race_num}"
    num_race_a_key = f"num_race_a_{team_a}_{selected_race_num}"

    chk_dnf_b_key = f"chk_dnf_b_{team_b}_{selected_race_num}"
    chk_fs_b_key = f"chk_fs_b_{team_b}_{selected_race_num}"
    num_rxn_b_key = f"num_rxn_b_{team_b}_{selected_race_num}"
    num_race_b_key = f"num_race_b_{team_b}_{selected_race_num}"

    # Sync widget state whenever matchup, race, or saved store version changes
    active_form_ctx = (team_a, team_b, int(selected_race_num), shared_store["version"])
    if st.session_state.get("_last_active_form_ctx") != active_form_ctx:
        st.session_state[chk_dnf_a_key] = init_a_dnf
        st.session_state[chk_fs_a_key] = init_a_fs
        st.session_state[num_rxn_a_key] = init_a_rxn
        st.session_state[num_race_a_key] = init_a_race

        st.session_state[chk_dnf_b_key] = init_b_dnf
        st.session_state[chk_fs_b_key] = init_b_fs
        st.session_state[num_rxn_b_key] = init_b_rxn
        st.session_state[num_race_b_key] = init_b_race
        st.session_state["_last_active_form_ctx"] = active_form_ctx

    for _k, _def_v in [
        (chk_dnf_a_key, init_a_dnf),
        (chk_fs_a_key, init_a_fs),
        (num_rxn_a_key, init_a_rxn),
        (num_race_a_key, init_a_race),
        (chk_dnf_b_key, init_b_dnf),
        (chk_fs_b_key, init_b_fs),
        (num_rxn_b_key, init_b_rxn),
        (num_race_b_key, init_b_race),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _def_v

    def _on_toggle_dnf_a():
        if st.session_state.get(chk_dnf_a_key, False):
            st.session_state[chk_fs_a_key] = False

    def _on_toggle_fs_a():
        if st.session_state.get(chk_fs_a_key, False):
            st.session_state[chk_dnf_a_key] = False

    def _on_toggle_dnf_b():
        if st.session_state.get(chk_dnf_b_key, False):
            st.session_state[chk_fs_b_key] = False

    def _on_toggle_fs_b():
        if st.session_state.get(chk_fs_b_key, False):
            st.session_state[chk_dnf_b_key] = False

    col_form_area, col_history_area = st.columns([1.2, 1.1])

    with col_form_area:
        render_html(f"""
        <div style="background: rgba(18, 12, 36, 0.85); border: 1px solid rgba(255, 42, 133, 0.4); border-radius: 14px; padding: 18px 20px 10px 20px; margin-bottom: 12px;">
            <div style="font-size: 18px; font-weight: 900; color: #FFFFFF; display: flex; align-items: center; justify-content: space-between;">
                <span>🏁 Ingreso de Tiempos - Carrera {selected_race_num}</span>
                <span style="font-size: 13px; color: #FF8A00; font-weight: 800;">{selected_matchup_label.split(':')[0]}</span>
            </div>
            <div style="font-size: 13px; color: #A09EB8; margin-top: 4px;">
                Ingresa o edita tiempos y presiona Guardar. En el visualizador se sobreescribe el valor activo, mientras que en el CSV se agrega como nuevo registro con ID y timestamp.
            </div>
        </div>
        """)

        if st.button(
            f"🎲 Test Mode: Generar Datos Aleatorios (Carrera {selected_race_num})",
            use_container_width=True,
            key=f"btn_test_mode_{team_a}_{team_b}_{selected_race_num}",
            help="Genera valores aleatorios basados en el Excel de referencia (incluyendo probabilidad de DNF o False Start) y puntuaciones aleatorias de categorías para esta carrera."
        ):
            rnd_a_dnf, rnd_a_fs, rnd_a_rxn, rnd_a_race = dp.generate_random_test_run()
            rnd_b_dnf, rnd_b_fs, rnd_b_rxn, rnd_b_race = dp.generate_random_test_run()

            st.session_state[chk_dnf_a_key] = rnd_a_dnf
            st.session_state[chk_fs_a_key] = rnd_a_fs
            st.session_state[num_rxn_a_key] = rnd_a_rxn
            st.session_state[num_race_a_key] = rnd_a_race

            st.session_state[chk_dnf_b_key] = rnd_b_dnf
            st.session_state[chk_fs_b_key] = rnd_b_fs
            st.session_state[num_rxn_b_key] = rnd_b_rxn
            st.session_state[num_race_b_key] = rnd_b_race

            # Randomize non-racing category scores for the teams in the selected race
            if st.session_state.custom_scores is not None:
                for t_name in [team_a, team_b]:
                    rnd_scores = dp.generate_random_judge_scores_for_team()
                    t_mask = st.session_state.custom_scores['team'] == t_name
                    for cat_col, val in rnd_scores.items():
                        st.session_state.custom_scores.loc[t_mask, cat_col] = val
                cat_cols_all = [c for c in dp.DEFAULT_CATEGORIES if c in st.session_state.custom_scores.columns]
                st.session_state.custom_scores['Total'] = st.session_state.custom_scores[cat_cols_all].sum(axis=1).round(2)
                st.session_state.custom_scores = st.session_state.custom_scores.sort_values(by='Total', ascending=False).reset_index(drop=True)
                st.session_state.custom_scores['rank'] = st.session_state.custom_scores.index + 1
                shared_store["custom_scores"] = st.session_state.custom_scores.copy()

            lbl_a = "DNF" if rnd_a_dnf else ("False Start" if rnd_a_fs else f"{rnd_a_rxn + rnd_a_race:.3f}s")
            lbl_b = "DNF" if rnd_b_dnf else ("False Start" if rnd_b_fs else f"{rnd_b_rxn + rnd_b_race:.3f}s")
            st.toast(f"🎲 Test Mode (Carrera {selected_race_num}): {team_a} [{lbl_a}] | {team_b} [{lbl_b}]. Presiona Guardar para registrar.")

        # Checkboxes outside form so clicking DNF or False Start immediately disables inputs in gray
        col_fa_top, col_fb_top = st.columns(2)
        with col_fa_top:
            status_a_html = '<span style="font-size: 11px; color: #00F0FF; background: rgba(0, 240, 255, 0.12); padding: 2px 8px; border-radius: 6px; font-weight: 700;">✏️ Guardado (sobreescribible)</span>' if already_exists_a else '<span style="font-size: 11px; color: #A09EB8;">⏳ Sin registro</span>'
            st.markdown(f"<div style='display:flex; align-items:center; justify-content:space-between; margin-bottom: 8px;'><span style='font-size: 18px; font-weight: 900; color: #00F0FF;'>🏎️ {team_a}</span>{status_a_html}</div>", unsafe_allow_html=True)
            col_chk_a1, col_chk_a2 = st.columns(2)
            with col_chk_a1:
                a_dnf = st.checkbox("❌ DNF", key=chk_dnf_a_key, on_change=_on_toggle_dnf_a)
            with col_chk_a2:
                a_fs = st.checkbox("🚦 False Start", key=chk_fs_a_key, on_change=_on_toggle_fs_a, help="Salida en falso y forfeit de carrera.")

        with col_fb_top:
            status_b_html = '<span style="font-size: 11px; color: #FF8A00; background: rgba(255, 138, 0, 0.12); padding: 2px 8px; border-radius: 6px; font-weight: 700;">✏️ Guardado (sobreescribible)</span>' if already_exists_b else '<span style="font-size: 11px; color: #A09EB8;">⏳ Sin registro</span>'
            st.markdown(f"<div style='display:flex; align-items:center; justify-content:space-between; margin-bottom: 8px;'><span style='font-size: 18px; font-weight: 900; color: #FF8A00;'>🏎️ {team_b}</span>{status_b_html}</div>", unsafe_allow_html=True)
            col_chk_b1, col_chk_b2 = st.columns(2)
            with col_chk_b1:
                b_dnf = st.checkbox("❌ DNF", key=chk_dnf_b_key, on_change=_on_toggle_dnf_b)
            with col_chk_b2:
                b_fs = st.checkbox("🚦 False Start", key=chk_fs_b_key, on_change=_on_toggle_fs_b, help="Salida en falso y forfeit de carrera.")

        # Time inputs + Submit inside form so typing a correction and clicking Guardar commits on 1st click
        with st.form(key=f"race_entry_form_{team_a}_{team_b}_{selected_race_num}", clear_on_submit=False, border=False):
            col_fa, col_fb = st.columns(2)

            # -----------------------------
            # TEAM A INPUTS
            # -----------------------------
            with col_fa:
                if a_fs:
                    st.text_input("T. Reacción (s):", value="False Start", disabled=True, key=f"txt_rxn_a_{team_a}_{selected_race_num}_fs")
                    st.text_input("T. Carrera (s):", value="False Start", disabled=True, key=f"txt_race_a_{team_a}_{selected_race_num}_fs")
                    a_rxn = 0.0
                    a_race = 0.0
                    render_html('<div style="text-align: center; padding: 6px; background: rgba(255, 138, 0, 0.15); border: 1px solid #FF8A00; border-radius: 8px; margin: 8px 0;"><span class="sr-fs-badge">🚦 FALSE START</span><div style="font-size:11px; color:#A09EB8; margin-top:2px;">Carrera perdida por forfeit</div></div>')
                elif a_dnf:
                    st.text_input("T. Reacción (s):", value="DNF", disabled=True, key=f"txt_rxn_a_{team_a}_{selected_race_num}_dnf")
                    st.text_input("T. Carrera (s):", value="DNF", disabled=True, key=f"txt_race_a_{team_a}_{selected_race_num}_dnf")
                    a_rxn = 0.0
                    a_race = 0.0
                    render_html('<div style="text-align: center; padding: 6px; background: rgba(255, 42, 133, 0.15); border: 1px solid #FF2A85; border-radius: 8px; margin: 8px 0;"><span class="sr-dnf-badge">❌ RESULTADO: DNF</span></div>')
                else:
                    a_rxn = st.number_input("T. Reacción (s):", min_value=0.000, max_value=10.000, step=0.001, format="%.3f", key=num_rxn_a_key)
                    a_race = st.number_input("T. Carrera (s):", min_value=0.000, max_value=30.000, step=0.001, format="%.3f", key=num_race_a_key)
                    tot_a_prev = a_rxn + a_race
                    render_html(f"""<div style="text-align: center; padding: 6px; background: rgba(0, 240, 255, 0.08); border: 1px solid rgba(0, 240, 255, 0.4); border-radius: 8px; margin: 8px 0;">
                        <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo Total Registrado</div>
                        <div style="font-size: 18px; font-weight: 900; color: #00F0FF;">{tot_a_prev:.3f} s</div>
                    </div>""")

            # -----------------------------
            # TEAM B INPUTS
            # -----------------------------
            with col_fb:
                if b_fs:
                    st.text_input("T. Reacción (s):", value="False Start", disabled=True, key=f"txt_rxn_b_{team_b}_{selected_race_num}_fs")
                    st.text_input("T. Carrera (s):", value="False Start", disabled=True, key=f"txt_race_b_{team_b}_{selected_race_num}_fs")
                    b_rxn = 0.0
                    b_race = 0.0
                    render_html('<div style="text-align: center; padding: 6px; background: rgba(255, 138, 0, 0.15); border: 1px solid #FF8A00; border-radius: 8px; margin: 8px 0;"><span class="sr-fs-badge">🚦 FALSE START</span><div style="font-size:11px; color:#A09EB8; margin-top:2px;">Carrera perdida por forfeit</div></div>')
                elif b_dnf:
                    st.text_input("T. Reacción (s):", value="DNF", disabled=True, key=f"txt_rxn_b_{team_b}_{selected_race_num}_dnf")
                    st.text_input("T. Carrera (s):", value="DNF", disabled=True, key=f"txt_race_b_{team_b}_{selected_race_num}_dnf")
                    b_rxn = 0.0
                    b_race = 0.0
                    render_html('<div style="text-align: center; padding: 6px; background: rgba(255, 42, 133, 0.15); border: 1px solid #FF2A85; border-radius: 8px; margin: 8px 0;"><span class="sr-dnf-badge">❌ RESULTADO: DNF</span></div>')
                else:
                    b_rxn = st.number_input("T. Reacción (s):", min_value=0.000, max_value=10.000, step=0.001, format="%.3f", key=num_rxn_b_key)
                    b_race = st.number_input("T. Carrera (s):", min_value=0.000, max_value=30.000, step=0.001, format="%.3f", key=num_race_b_key)
                    tot_b_prev = b_rxn + b_race
                    render_html(f"""<div style="text-align: center; padding: 6px; background: rgba(255, 138, 0, 0.08); border: 1px solid rgba(255, 138, 0, 0.4); border-radius: 8px; margin: 8px 0;">
                        <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo Total Registrado</div>
                        <div style="font-size: 18px; font-weight: 900; color: #FF8A00;">{tot_b_prev:.3f} s</div>
                    </div>""")

            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            submit_matchup_race = st.form_submit_button(
                f"🏁 Guardar Resultados de Carrera {selected_race_num}",
                use_container_width=True,
                type="primary"
            )

        if submit_matchup_race:
            has_data_a = bool(a_dnf or a_fs or (a_race > 0) or (a_rxn > 0))
            has_data_b = bool(b_dnf or b_fs or (b_race > 0) or (b_rxn > 0))

            if not has_data_a and not has_data_b and not already_exists_a and not already_exists_b:
                st.warning("⚠️ No se ingresaron tiempos ni estados (DNF/FS) para guardar.")
            else:
                is_inv_a = bool(a_dnf or a_fs)
                row_dict_a = {
                    'team': team_a,
                    'race_number': int(selected_race_num),
                    'reaction_time': round(float(a_rxn), 4) if not is_inv_a else 0.0,
                    'race_time': np.nan if is_inv_a else round(float(a_race), 4),
                    'total_time': np.nan if is_inv_a else round(float(a_rxn + a_race), 4),
                    'is_dnf': bool(a_dnf and not a_fs),
                    'is_false_start': bool(a_fs)
                }

                is_inv_b = bool(b_dnf or b_fs)
                row_dict_b = {
                    'team': team_b,
                    'race_number': int(selected_race_num),
                    'reaction_time': round(float(b_rxn), 4) if not is_inv_b else 0.0,
                    'race_time': np.nan if is_inv_b else round(float(b_race), 4),
                    'total_time': np.nan if is_inv_b else round(float(b_rxn + b_race), 4),
                    'is_dnf': bool(b_dnf and not b_fs),
                    'is_false_start': bool(b_fs)
                }

                # Determine which team(s) were added or modified to append to the CSV audit log
                changed_a = (
                    (not already_exists_a and has_data_a) or
                    (already_exists_a and (
                        (row_dict_a['is_dnf'] != init_a_dnf) or
                        (row_dict_a['is_false_start'] != init_a_fs) or
                        (not is_inv_a and (abs(float(a_rxn) - init_a_rxn) > 1e-6 or abs(float(a_race) - init_a_race) > 1e-6))
                    ))
                )
                changed_b = (
                    (not already_exists_b and has_data_b) or
                    (already_exists_b and (
                        (row_dict_b['is_dnf'] != init_b_dnf) or
                        (row_dict_b['is_false_start'] != init_b_fs) or
                        (not is_inv_b and (abs(float(b_rxn) - init_b_rxn) > 1e-6 or abs(float(b_race) - init_b_race) > 1e-6))
                    ))
                )

                rows_to_append = []
                if changed_a:
                    rows_to_append.append(row_dict_a)
                if changed_b:
                    rows_to_append.append(row_dict_b)

                # If user clicked Guardar again on existing data without changing values, still append a timestamped record
                if not rows_to_append:
                    if has_data_a or already_exists_a:
                        rows_to_append.append(row_dict_a)
                    if has_data_b or already_exists_b:
                        rows_to_append.append(row_dict_b)

                was_overwrite = (already_exists_a and changed_a) or (already_exists_b and changed_b) or (already_exists_a or already_exists_b)
                append_race_records(rows_to_append)

                if was_overwrite:
                    st.toast(f"✅ Carrera {selected_race_num} actualizada y registrada con timestamp en el CSV!")
                else:
                    st.toast(f"✅ Carrera {selected_race_num} guardada con éxito!")
                st.rerun()

    with col_history_area:
        render_html(f"""
        <div style="background: rgba(18, 12, 36, 0.85); border: 1px solid rgba(0, 240, 255, 0.3); border-radius: 14px; padding: 18px 20px 10px 20px; margin-bottom: 16px;">
            <div style="font-size: 18px; font-weight: 900; color: #FFFFFF; display: flex; align-items: center; justify-content: space-between;">
                <span>⚔️ Historial del Enfrentamiento</span>
                <span style="font-size: 14px; color: #00F0FF; font-weight: 800;">{team_a} vs {team_b}</span>
            </div>
            <div style="font-size: 13px; color: #A09EB8; margin-top: 4px;">
                Resumen de las 4 carreras oficiales de este duelo directo.
            </div>
        </div>
        """)

        # Table of 4 races for this matchup
        history_rows = []
        for r_num in range(1, 5):
            ra = curr_runs[(curr_runs['team'] == team_a) & (curr_runs['race_number'] == r_num)]
            rb = curr_runs[(curr_runs['team'] == team_b) & (curr_runs['race_number'] == r_num)]

            if not ra.empty:
                r_row_a = ra.iloc[-1]
                if r_row_a.get('is_false_start', False):
                    cell_a = '<span class="sr-fs-badge">FALSE START</span>'
                elif r_row_a.get('is_dnf', False):
                    cell_a = '<span class="sr-dnf-badge">DNF</span>'
                else:
                    tot_a_val = r_row_a.get('total_time', 0.0)
                    cell_a = f'<strong style="color: #00F0FF;">{tot_a_val:.3f}s</strong> <span style="font-size:11px; color:#A09EB8;">({r_row_a.get("race_time", 0.0):.3f}s carro)</span>'
            else:
                cell_a = '<span class="sr-pending-badge">⏳ Pendiente</span>'

            if not rb.empty:
                r_row_b = rb.iloc[-1]
                if r_row_b.get('is_false_start', False):
                    cell_b = '<span class="sr-fs-badge">FALSE START</span>'
                elif r_row_b.get('is_dnf', False):
                    cell_b = '<span class="sr-dnf-badge">DNF</span>'
                else:
                    tot_b_val = r_row_b.get('total_time', 0.0)
                    cell_b = f'<strong style="color: #FF8A00;">{tot_b_val:.3f}s</strong> <span style="font-size:11px; color:#A09EB8;">({r_row_b.get("race_time", 0.0):.3f}s carro)</span>'
            else:
                cell_b = '<span class="sr-pending-badge">⏳ Pendiente</span>'

            history_rows.append(f"""<tr>
                <td style="font-weight: 800; color: #FFFFFF;">Carrera {r_num}</td>
                <td style="text-align: center;">{cell_a}</td>
                <td style="text-align: center;">{cell_b}</td>
            </tr>""")

        # Extract best times for both teams in this matchup
        sum_a = df_teams_summary[df_teams_summary['team'] == team_a].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_a].empty) else None
        sum_b = df_teams_summary[df_teams_summary['team'] == team_b].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_b].empty) else None

        best_tot_a_val = sum_a['min_total_time'] if sum_a is not None else None
        car_time_a_val = sum_a['avg_race_time'] if sum_a is not None else None
        best_tot_b_val = sum_b['min_total_time'] if sum_b is not None else None
        car_time_b_val = sum_b['avg_race_time'] if sum_b is not None else None

        best_tot_a_txt = f"{best_tot_a_val:.3f} s" if (pd.notna(best_tot_a_val) and best_tot_a_val > 0) else "Pendiente"
        car_time_a_txt = f"{car_time_a_val:.3f} s" if (pd.notna(car_time_a_val) and car_time_a_val > 0) else "Pendiente"
        best_tot_b_txt = f"{best_tot_b_val:.3f} s" if (pd.notna(best_tot_b_val) and best_tot_b_val > 0) else "Pendiente"
        car_time_b_txt = f"{car_time_b_val:.3f} s" if (pd.notna(car_time_b_val) and car_time_b_val > 0) else "Pendiente"

        hist_table_html = f"""<table class="sr-pptx-table" style="font-size: 13px;">
            <thead>
                <tr>
                    <th style="width: 28%;">Carrera</th>
                    <th style="width: 36%; text-align: center; color: #00F0FF;">{team_a}</th>
                    <th style="width: 36%; text-align: center; color: #FF8A00;">{team_b}</th>
                </tr>
            </thead>
            <tbody>
                {"".join(history_rows)}
            </tbody>
            <tfoot>
                <tr style="background: rgba(255, 255, 255, 0.05); border-top: 2px solid rgba(255, 42, 133, 0.4);">
                    <td style="font-weight: 800; color: #FFFFFF; font-size: 12px;">🏎️ Tiempo de Carro</td>
                    <td style="text-align: center; font-weight: 800; color: #00F0FF;">{car_time_a_txt}</td>
                    <td style="text-align: center; font-weight: 800; color: #FF8A00;">{car_time_b_txt}</td>
                </tr>
                <tr style="background: rgba(255, 42, 133, 0.12);">
                    <td style="font-weight: 800; color: #FFFFFF; font-size: 12px;">🚀 Mejor T. Total</td>
                    <td style="text-align: center; font-weight: 900; color: #00F0FF;">{best_tot_a_txt}</td>
                    <td style="text-align: center; font-weight: 900; color: #FF8A00;">{best_tot_b_txt}</td>
                </tr>
            </tfoot>
        </table>"""
        render_html(hist_table_html)

    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)

    # --- TOURNAMENT PROGRESS MONITOR (10 TEAMS x 4 RACES) ---
    render_html("""
    <div style="background: rgba(18, 12, 36, 0.7); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 14px; padding: 18px 20px 10px 20px; margin-bottom: 16px;">
        <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; display: flex; align-items: center; gap: 8px;">
            <span>📋</span> Monitor General del Torneo (10 Equipos Oficiales)
        </div>
        <div style="font-size: 13px; color: #A09EB8; margin-top: 4px;">
            Seguimiento en tiempo real de las 4 carreras de cada equipo, estado de DNF, False Starts, tiempo de carro y mejor tiempo total.
        </div>
    </div>
    """)

    monitor_rows = []
    for team in official_teams:
        t_summary = df_teams_summary[df_teams_summary['team'] == team].iloc[0]
        t_runs = df_runs[df_runs['team'] == team].sort_values(by='race_number')

        cells_race = []
        for r_i in range(1, 5):
            match_r = t_runs[t_runs['race_number'] == r_i]
            if not match_r.empty:
                r_item = match_r.iloc[-1]
                if r_item.get('is_false_start', False):
                    cells_race.append('<td style="text-align: center;"><span class="sr-fs-badge">FS</span></td>')
                elif r_item.get('is_dnf', False):
                    cells_race.append('<td style="text-align: center;"><span class="sr-dnf-badge">DNF</span></td>')
                else:
                    tot_val = r_item.get('total_time', 0.0)
                    cells_race.append(f'<td style="text-align: center; color: #00F0FF; font-weight: 800; font-size: 13px;">{tot_val:.3f}s</td>')
            else:
                cells_race.append('<td style="text-align: center;"><span class="sr-pending-badge">⏳ Pendiente</span></td>')

        runs_done = len(t_runs)
        badge_color = "#00F0FF" if runs_done >= 4 else ("#FF8A00" if runs_done > 0 else "#6C6885")

        car_time_str = f"{t_summary['avg_race_time']:.3f}s" if pd.notna(t_summary['avg_race_time']) else "---"
        best_tot_str = f"{t_summary['min_total_time']:.3f}s" if pd.notna(t_summary['min_total_time']) else "---"

        dnf_cnt_val = t_summary['dnf_count']
        fs_cnt_val = t_summary['fs_count']
        dnf_badge = f'<span style="color:#FF2A85; font-weight:800;">{dnf_cnt_val}</span>' if dnf_cnt_val > 0 else '<span style="color:#6C6885;">0</span>'
        fs_badge = f'<span style="color:#FF8A00; font-weight:800;">{fs_cnt_val}</span>' if fs_cnt_val > 0 else '<span style="color:#6C6885;">0</span>'

        monitor_rows.append(f"""<tr>
            <td style="font-weight: 700; color: #FFFFFF;">🏎️ {team}</td>
            {"".join(cells_race)}
            <td style="text-align: center; font-weight: 800; color: {badge_color};">{runs_done}/4</td>
            <td style="text-align: center;">{dnf_badge}</td>
            <td style="text-align: center;">{fs_badge}</td>
            <td style="text-align: right; font-weight: 800; color: #FF8A00;">{car_time_str}</td>
            <td style="text-align: right; font-weight: 800; color: #00F0FF;">{best_tot_str}</td>
        </tr>""")

    full_monitor_html = f"""<div style="overflow-x: auto;">
    <table class="sr-pptx-table" style="font-size: 13px;">
        <thead>
            <tr>
                <th style="width: 20%;">Equipo</th>
                <th style="width: 11%; text-align: center;">Carrera 1</th>
                <th style="width: 11%; text-align: center;">Carrera 2</th>
                <th style="width: 11%; text-align: center;">Carrera 3</th>
                <th style="width: 11%; text-align: center;">Carrera 4</th>
                <th style="width: 7%; text-align: center;">Carreras</th>
                <th style="width: 6%; text-align: center; color: #FF2A85;">DNF</th>
                <th style="width: 6%; text-align: center; color: #FF8A00;">FS</th>
                <th style="width: 9%; text-align: right; color: #FF8A00;">T. Carro</th>
                <th style="width: 8%; text-align: right; color: #00F0FF;">Mejor Total</th>
            </tr>
        </thead>
        <tbody>
            {"".join(monitor_rows)}
        </tbody>
    </table>
    </div>"""
    render_html(full_monitor_html)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    # --- FULL CSV AUDIT LOG & DATA GRID EDITOR ---
    with st.expander("🕒 Historial de Registros CSV (con ID y Timestamp) y Editor de Grilla"):
        st.write("Cada vez que se guarda o corrige un resultado, se agrega al CSV con un `id` incremental y su `timestamp`:")
        edit_source = st.session_state.history_df.copy()
        if edit_source.empty:
            edit_source = pd.DataFrame(columns=dp.CSV_SCHEMA)

        edited_data = st.data_editor(
            edit_source,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "id": st.column_config.NumberColumn("ID #", step=1, disabled=True),
                "timestamp": st.column_config.TextColumn("Timestamp", disabled=True),
                "team": st.column_config.SelectboxColumn("Equipo", options=official_teams, required=True),
                "race_number": st.column_config.NumberColumn("Carrera #", min_value=1, max_value=4, step=1, required=True),
                "reaction_time": st.column_config.NumberColumn("T. Reacción (s)", format="%.3f", min_value=0.0, max_value=10.0, step=0.001),
                "race_time": st.column_config.NumberColumn("T. Carrera (s)", format="%.3f", min_value=0.0, max_value=30.0, step=0.001),
                "total_time": st.column_config.NumberColumn("T. Total (s)", format="%.3f", min_value=0.0, max_value=40.0, step=0.001),
                "is_dnf": st.column_config.CheckboxColumn("DNF", default=False),
                "is_false_start": st.column_config.CheckboxColumn("False Start", default=False),
            },
            key="grid_editor_runs"
        )

        col_ge_s1, col_ge_s2 = st.columns(2)
        with col_ge_s1:
            if st.button("💾 Aplicar Cambios de la Grilla y Guardar", use_container_width=True):
                commit_runs_df(edited_data)
                st.toast("✅ Cambios de grilla aplicados con éxito.")
                st.rerun()

        with col_ge_s2:
            if st.button("⚡ Recalcular Tiempos Totales (Reacción + Carrera)", use_container_width=True):
                commit_runs_df(edited_data)
                st.toast("✅ Tiempos totales recalculados.")
                st.rerun()

elif selected_view == "🏆 Ceremonia de Podio Oficial":
    # -------------------------------------------------------------------------
    # PANTALLA EXCLUSIVA DE CEREMONIA DE PODIO OFICIAL
    # Sin encabezado superior, sin pestañas, sin indicador de pasos.
    # Máximo espacio y protagonismo para la ceremonia.
    # -------------------------------------------------------------------------
    live_visualizer_sync_watcher()
    curr_step = int(st.session_state.podium_slide_step)

    # Botones de navegación de la ceremonia (mínimo espacio vertical)
    if curr_step == 0:
        _, col_start, _ = st.columns([1, 1.6, 1])
        with col_start:
            if st.button("🚀 Comenzar Ceremonia de Premiación ➡️", use_container_width=True, type="primary"):
                st.session_state.podium_slide_step = 1
                st.session_state.podium_anim_nonce += 1
                st.rerun()
    else:
        col_nav1, col_nav2, col_nav3 = st.columns([1.2, 1, 1.4])
        with col_nav1:
            if st.button("⬅️ Diapositiva Anterior", use_container_width=True):
                st.session_state.podium_slide_step = max(0, curr_step - 1)
                st.session_state.podium_anim_nonce += 1
                st.rerun()
        with col_nav2:
            if st.button("🔄 Reiniciar Intro", use_container_width=True):
                st.session_state.podium_slide_step = 0
                st.session_state.podium_anim_nonce += 1
                st.rerun()
        with col_nav3:
            next_labels = {
                1: "Siguiente: Revelar 2do Lugar ➡️",
                2: "Siguiente: Revelar 1er Lugar ➡️",
                3: "Siguiente: Ver Podio Completo ➡️",
                4: "🏆 Podio Completo en Pantalla"
            }
            if st.button(next_labels.get(curr_step, "Siguiente ➡️"), use_container_width=True, type="primary", disabled=(curr_step >= 4)):
                st.session_state.podium_slide_step = min(4, curr_step + 1)
                st.session_state.podium_anim_nonce += 1
                st.rerun()

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # Render Current Ceremony Slide (0: Intro -> 1: 3ro -> 2: 2do -> 3: 1ro -> 4: Podio)
    if curr_step == 0:
        render_podium_intro_slide()
    elif curr_step == 1:
        render_place_reveal_slide(rank_target=3, medal_emoji="🥉", title="3er Lugar", accent_color="#CD7F32")
    elif curr_step == 2:
        render_place_reveal_slide(rank_target=2, medal_emoji="🥈", title="2do Lugar", accent_color="#C0C0C0")
    elif curr_step == 3:
        render_place_reveal_slide(rank_target=1, medal_emoji="🥇", title="1er Lugar - Campeón", accent_color="#FFD700")
    else:
        render_podium_full_slide()

else:
    # -------------------------------------------------------------------------
    # PANTALLA DE TIEMPOS Y RESULTADOS EN PISTA (4 TABS)
    # -------------------------------------------------------------------------
    live_visualizer_sync_watcher()
    render_html(styles.render_app_header(logo_b64))

    tab1, tab2, tab3, tab4 = st.tabs([
        "⏱️ Tiempos por Equipos",
        "⚔️ Duelos Cara a Cara",
        "🏎️ Tiempo de Carro",
        "🚀 Tiempo Más Rápido"
    ])

    # ==============================================================================
    # TAB 1: TIEMPOS POR EQUIPOS (Orden Oficial de Equipos, sin subsecciones, sin puntos)
    # ==============================================================================
    with tab1:
        render_html("""
        <div style="text-align: center; margin-bottom: 24px;">
            <h2 style="font-size: 32px; font-weight: 900; color: #FFFFFF; text-transform: uppercase; margin: 0; letter-spacing: 1px;">
                Tiempos por Equipos
            </h2>
            <div style="color: #A09EB8; font-size: 15px; margin-top: 6px;">
                Mejor Tiempo Total (Reacción + Carrera) y Tiempo de Carro (Promedio 2do y 3er mejor tiempo) en orden oficial de equipos
            </div>
        </div>
        """)

        # Preserve strict official team order from Equipos.csv
        order_dict = {tm: idx + 1 for idx, tm in enumerate(official_teams)}
        t1_df = df_teams_summary.copy()
        t1_df['team_order'] = t1_df['team'].map(order_dict).fillna(999).astype(int)
        t1_df = t1_df.sort_values(by='team_order').reset_index(drop=True)

        # Split into 2 columns (Equipos 1-5 Left, Equipos 6-10 Right)
        half = int(np.ceil(len(t1_df) / 2))
        left_teams = t1_df.iloc[:half].reset_index(drop=True)
        right_teams = t1_df.iloc[half:].reset_index(drop=True)

        def build_teams_times_table(df_slice):
            rows = []
            for _, r in df_slice.iterrows():
                ord_num = r['team_order']
                tot_val = r['min_total_time']
                car_val = r['avg_race_time']

                tot_str = f"{tot_val:.3f} s" if (pd.notna(tot_val) and tot_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
                car_str = f"{car_val:.3f} s" if (pd.notna(car_val) and car_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'

                rows.append(f"""<tr>
                    <td style="text-align: center; font-weight: 800; color: #A09EB8;">#{ord_num}</td>
                    <td style="font-weight: 800; color: #FFFFFF; font-size: 16px;">🏎️ {r['team']}</td>
                    <td style="text-align: right; color: #009FE3; font-weight: 900; font-size: 16px;">{tot_str}</td>
                    <td style="text-align: right; color: #ED6D05; font-weight: 900; font-size: 16px;">{car_str}</td>
                </tr>""")
            return f"""<table class="sr-pptx-table">
                <thead>
                    <tr>
                        <th style="width: 12%; text-align: center;">#</th>
                        <th style="width: 38%;">Equipo</th>
                        <th style="width: 25%; text-align: right; color: #009FE3;">Mejor T. Total</th>
                        <th style="width: 25%; text-align: right; color: #ED6D05;">Tiempo de Carro</th>
                    </tr>
                </thead>
                <tbody>{"".join(rows)}</tbody>
            </table>"""

        col_l, col_r = st.columns(2)
        with col_l:
            render_html(build_teams_times_table(left_teams))
        with col_r:
            render_html(build_teams_times_table(right_teams))

        # Tab 1 content complete - no comparison charts as requested

    # ==============================================================================
    # TAB 2: DUELOS CARA A CARA (Sin puntos)
    # ==============================================================================
    with tab2:
        render_html("""
        <div style="text-align: center; margin-bottom: 20px;">
            <h2 style="font-size: 32px; font-weight: 900; color: #FFFFFF; text-transform: uppercase; margin: 0;">
                Duelos Cara a Cara
            </h2>
        </div>
        """)

        # Select from the 5 official matchups using Non-typeable Pills
        st.markdown("<div style='font-size: 14px; font-weight: 700; color: #E6E4F0; margin-bottom: 6px;'>⚔️ Seleccionar Enfrentamiento Oficial:</div>", unsafe_allow_html=True)
        selected_h2h_label = st.pills(
            "Seleccionar Enfrentamiento Oficial:",
            options=[m['label'] for m in matchups_list],
            default=matchups_list[0]['label'],
            key="slide3_matchup_selector",
            label_visibility="collapsed"
        )
        if not selected_h2h_label:
            selected_h2h_label = matchups_list[0]['label']

        current_matchup = next(m for m in matchups_list if m['label'] == selected_h2h_label)
        team_a = current_matchup['team_a']
        team_b = current_matchup['team_b']

        render_html(f"""
        <div style="text-align: center; margin: 12px 0 24px 0;">
            <span style="font-size: 28px; font-weight: 900; color: #00F0FF;">{team_a}</span>
            <span style="font-size: 22px; font-weight: 900; color: #FF2A85; margin: 0 20px;">VS</span>
            <span style="font-size: 28px; font-weight: 900; color: #FF8A00;">{team_b}</span>
        </div>
        """)

        # Build the 4-race rows for both teams
        runs_a = df_runs[df_runs['team'] == team_a].sort_values(by='race_number')
        runs_b = df_runs[df_runs['team'] == team_b].sort_values(by='race_number')

        h2h_table_rows = []
        for r_num in range(1, 5):
            match_a = runs_a[runs_a['race_number'] == r_num]
            match_b = runs_b[runs_b['race_number'] == r_num]

            # Team A cells
            if not match_a.empty:
                ra = match_a.iloc[0]
                if ra.get('is_false_start', False):
                    rxn_a_str = '<span class="sr-fs-badge">FALSE START</span>'
                    race_a_str = '<span class="sr-fs-badge">FALSE START</span>'
                    tot_a_str = '<span class="sr-fs-badge">FALSE START</span>'
                    tot_a_num = None
                elif ra.get('is_dnf', False):
                    rxn_a_str = '<span class="sr-dnf-badge">DNF</span>'
                    race_a_str = '<span class="sr-dnf-badge">DNF</span>'
                    tot_a_str = '<span class="sr-dnf-badge">DNF</span>'
                    tot_a_num = None
                else:
                    rxn_a_str = f"{ra.get('reaction_time', 0.0):.3f} s"
                    race_a_str = f"{ra.get('race_time', 0.0):.3f} s"
                    tot_a_str = f"{ra.get('total_time', 0.0):.3f} s"
                    tot_a_num = ra.get('total_time', 0.0)
            else:
                rxn_a_str = '<span class="sr-pending-badge">---</span>'
                race_a_str = '<span class="sr-pending-badge">---</span>'
                tot_a_str = '<span class="sr-pending-badge">⏳ Pendiente</span>'
                tot_a_num = None

            # Team B cells
            if not match_b.empty:
                rb = match_b.iloc[0]
                if rb.get('is_false_start', False):
                    rxn_b_str = '<span class="sr-fs-badge">FALSE START</span>'
                    race_b_str = '<span class="sr-fs-badge">FALSE START</span>'
                    tot_b_str = '<span class="sr-fs-badge">FALSE START</span>'
                    tot_b_num = None
                elif rb.get('is_dnf', False):
                    rxn_b_str = '<span class="sr-dnf-badge">DNF</span>'
                    race_b_str = '<span class="sr-dnf-badge">DNF</span>'
                    tot_b_str = '<span class="sr-dnf-badge">DNF</span>'
                    tot_b_num = None
                else:
                    rxn_b_str = f"{rb.get('reaction_time', 0.0):.3f} s"
                    race_b_str = f"{rb.get('race_time', 0.0):.3f} s"
                    tot_b_str = f"{rb.get('total_time', 0.0):.3f} s"
                    tot_b_num = rb.get('total_time', 0.0)
            else:
                rxn_b_str = '<span class="sr-pending-badge">---</span>'
                race_b_str = '<span class="sr-pending-badge">---</span>'
                tot_b_str = '<span class="sr-pending-badge">⏳ Pendiente</span>'
                tot_b_num = None

            h2h_table_rows.append({
                'race': f"Carrera {r_num}",
                'rxn_a_str': rxn_a_str, 'race_a_str': race_a_str, 'tot_a_str': tot_a_str, 'tot_a_num': tot_a_num,
                'rxn_b_str': rxn_b_str, 'race_b_str': race_b_str, 'tot_b_str': tot_b_str, 'tot_b_num': tot_b_num
            })

        # Extract best times for both teams in this head-to-head matchup
        sum_h2h_a = df_teams_summary[df_teams_summary['team'] == team_a].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_a].empty) else None
        sum_h2h_b = df_teams_summary[df_teams_summary['team'] == team_b].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_b].empty) else None

        tot_a_val = sum_h2h_a['min_total_time'] if sum_h2h_a is not None else None
        car_a_val = sum_h2h_a['avg_race_time'] if sum_h2h_a is not None else None
        rxn_a_val = sum_h2h_a['min_rxn_time'] if sum_h2h_a is not None else None
        race_a_val = sum_h2h_a['min_race_time'] if sum_h2h_a is not None else None

        tot_b_val = sum_h2h_b['min_total_time'] if sum_h2h_b is not None else None
        car_b_val = sum_h2h_b['avg_race_time'] if sum_h2h_b is not None else None
        rxn_b_val = sum_h2h_b['min_rxn_time'] if sum_h2h_b is not None else None
        race_b_val = sum_h2h_b['min_race_time'] if sum_h2h_b is not None else None

        tot_a_txt = f"{tot_a_val:.3f} s" if (pd.notna(tot_a_val) and tot_a_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        car_a_txt = f"{car_a_val:.3f} s" if (pd.notna(car_a_val) and car_a_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        rxn_a_txt = f"{rxn_a_val:.3f} s" if (pd.notna(rxn_a_val) and rxn_a_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        race_a_txt = f"{race_a_val:.3f} s" if (pd.notna(race_a_val) and race_a_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'

        tot_b_txt = f"{tot_b_val:.3f} s" if (pd.notna(tot_b_val) and tot_b_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        car_b_txt = f"{car_b_val:.3f} s" if (pd.notna(car_b_val) and car_b_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        rxn_b_txt = f"{rxn_b_val:.3f} s" if (pd.notna(rxn_b_val) and rxn_b_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        race_b_txt = f"{race_b_val:.3f} s" if (pd.notna(race_b_val) and race_b_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'

        # Render Slide 3 Table
        h2h_rows_html = []
        for r in h2h_table_rows:
            h2h_rows_html.append(f"""<tr>
                <td style="font-weight: 700; color: #FFFFFF; padding: 12px 16px;">{r['race']}</td>
                <td style="text-align: center; color: #E6E4F0; padding: 12px;">{r['rxn_a_str']}</td>
                <td style="text-align: center; color: #E6E4F0; padding: 12px;">{r['race_a_str']}</td>
                <td style="text-align: center; border-right: 2px solid rgba(255, 42, 133, 0.5); font-weight: 800; color: #00F0FF; padding: 12px;">{r['tot_a_str']}</td>
                <td style="text-align: center; color: #E6E4F0; padding: 12px;">{r['rxn_b_str']}</td>
                <td style="text-align: center; color: #E6E4F0; padding: 12px;">{r['race_b_str']}</td>
                <td style="text-align: center; font-weight: 800; color: #FF8A00; padding: 12px;">{r['tot_b_str']}</td>
            </tr>""")

        h2h_table_html = f"""<table class="sr-pptx-table" style="width: 100%; border-collapse: separate; border-spacing: 0; border-radius: 12px; overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.15); background: rgba(18, 12, 36, 0.85); margin: 20px 0 16px 0;">
            <thead>
                <tr>
                    <th rowspan="2" style="vertical-align: middle; width: 14%; padding: 14px 16px;">Carrera</th>
                    <th colspan="3" style="text-align: center; border-right: 2px solid rgba(255, 42, 133, 0.5); background: rgba(0, 240, 255, 0.15); color: #00F0FF; padding: 12px; font-size: 16px;">
                        🏎️ {team_a}
                    </th>
                    <th colspan="3" style="text-align: center; background: rgba(255, 138, 0, 0.15); color: #FF8A00; padding: 12px; font-size: 16px;">
                        🏎️ {team_b}
                    </th>
                </tr>
                <tr>
                    <th style="font-size: 13px; text-align: center; padding: 10px;">T. Reacción</th>
                    <th style="font-size: 13px; text-align: center; padding: 10px;">T. Carrera</th>
                    <th style="font-size: 13px; text-align: center; border-right: 2px solid rgba(255, 42, 133, 0.5); padding: 10px; color: #00F0FF;">T. Total</th>
                    <th style="font-size: 13px; text-align: center; padding: 10px;">T. Reacción</th>
                    <th style="font-size: 13px; text-align: center; padding: 10px;">T. Carrera</th>
                    <th style="font-size: 13px; text-align: center; padding: 10px; color: #FF8A00;">T. Total</th>
                </tr>
            </thead>
            <tbody>
                {"".join(h2h_rows_html)}
            </tbody>
            <tfoot>
                <tr style="background: rgba(255, 255, 255, 0.04); border-top: 2px solid rgba(255, 42, 133, 0.4);">
                    <td style="font-weight: 800; color: #FFFFFF; padding: 12px 16px; font-size: 13px;">⭐ Mejor T. Reacción</td>
                    <td style="text-align: center; font-weight: 800; color: #00F0FF; padding: 12px;">{rxn_a_txt}</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; border-right: 2px solid rgba(255, 42, 133, 0.5); color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; font-weight: 800; color: #FF8A00; padding: 12px;">{rxn_b_txt}</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                </tr>
                <tr style="background: rgba(255, 255, 255, 0.04);">
                    <td style="font-weight: 800; color: #FFFFFF; padding: 12px 16px; font-size: 13px;">🏎️ Tiempo de Carro</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; font-weight: 800; color: #00F0FF; padding: 12px;">{car_a_txt}</td>
                    <td style="text-align: center; border-right: 2px solid rgba(255, 42, 133, 0.5); color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; font-weight: 800; color: #FF8A00; padding: 12px;">{car_b_txt}</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                </tr>
                <tr style="background: rgba(255, 42, 133, 0.12); border-top: 1px solid rgba(255, 42, 133, 0.4);">
                    <td style="font-weight: 900; color: #FFFFFF; padding: 12px 16px; font-size: 13px;">🚀 Mejor T. Total</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; border-right: 2px solid rgba(255, 42, 133, 0.5); font-weight: 900; color: #00F0FF; font-size: 15px; padding: 12px;">{tot_a_txt}</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    <td style="text-align: center; font-weight: 900; color: #FF8A00; font-size: 15px; padding: 12px;">{tot_b_txt}</td>
                </tr>
            </tfoot>
        </table>"""
        render_html(h2h_table_html)

        # Highlight summary cards for each team right below the matchup table
        h2h_cards_html = f"""
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px;">
            <div style="background: rgba(18, 12, 36, 0.85); border: 1px solid rgba(0, 240, 255, 0.4); border-radius: 12px; padding: 16px 20px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <span style="font-size: 18px; font-weight: 900; color: #009FE3;">🏎️ {team_a}</span>
                    <span style="font-size: 11px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Mejores Tiempos</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; text-align: center;">
                    <div style="background: rgba(0, 159, 227, 0.06); border: 1px solid rgba(0, 159, 227, 0.2); border-radius: 8px; padding: 10px 6px;">
                        <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Mejor Reacción</div>
                        <div style="font-size: 15px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">{rxn_a_txt}</div>
                    </div>
                    <div style="background: rgba(0, 159, 227, 0.06); border: 1px solid rgba(0, 159, 227, 0.2); border-radius: 8px; padding: 10px 6px;">
                        <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo de Carro</div>
                        <div style="font-size: 15px; font-weight: 900; color: #009FE3; margin-top: 4px;">{car_a_txt}</div>
                    </div>
                    <div style="background: rgba(0, 159, 227, 0.14); border: 1px solid #009FE3; border-radius: 8px; padding: 10px 6px;">
                        <div style="font-size: 11px; color: #009FE3; font-weight: 800; text-transform: uppercase;">Mejor T. Total</div>
                        <div style="font-size: 16px; font-weight: 900; color: #009FE3; margin-top: 4px;">{tot_a_txt}</div>
                    </div>
                </div>
            </div>
            <div style="background: rgba(18, 12, 36, 0.85); border: 1px solid rgba(237, 109, 5, 0.4); border-radius: 12px; padding: 16px 20px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <span style="font-size: 18px; font-weight: 900; color: #ED6D05;">🏎️ {team_b}</span>
                    <span style="font-size: 11px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Mejores Tiempos</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; text-align: center;">
                    <div style="background: rgba(237, 109, 5, 0.06); border: 1px solid rgba(237, 109, 5, 0.2); border-radius: 8px; padding: 10px 6px;">
                        <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Mejor Reacción</div>
                        <div style="font-size: 15px; font-weight: 900; color: #FFFFFF; margin-top: 4px;">{rxn_b_txt}</div>
                    </div>
                    <div style="background: rgba(237, 109, 5, 0.06); border: 1px solid rgba(237, 109, 5, 0.2); border-radius: 8px; padding: 10px 6px;">
                        <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo de Carro</div>
                        <div style="font-size: 15px; font-weight: 900; color: #ED6D05; margin-top: 4px;">{car_b_txt}</div>
                    </div>
                    <div style="background: rgba(237, 109, 5, 0.14); border: 1px solid #ED6D05; border-radius: 8px; padding: 10px 6px;">
                        <div style="font-size: 11px; color: #ED6D05; font-weight: 800; text-transform: uppercase;">Mejor T. Total</div>
                        <div style="font-size: 16px; font-weight: 900; color: #ED6D05; margin-top: 4px;">{tot_b_txt}</div>
                    </div>
                </div>
            </div>
        </div>
        """
        render_html(h2h_cards_html)

        # Tab 2 content complete - no comparison charts as requested

    # ==============================================================================
    # TAB 3: TIEMPO DE CARRO (Mejor tiempo, clasificación y diferencia contra el líder, sin Top 3, sin puntos)
    # ==============================================================================
    with tab3:
        render_html("""
        <div style="text-align: center; margin-bottom: 24px;">
            <h2 style="font-size: 32px; font-weight: 900; color: #FFFFFF; text-transform: uppercase; margin: 0;">
                Tiempo de Carro
            </h2>
            <div style="color: #A09EB8; font-size: 15px; margin-top: 6px;">
                Promedio del 2do y 3er mejor tiempo de carrera de cada equipo y diferencia respecto al líder de la categoría
            </div>
        </div>
        """)

        valid_car_lb = df_race_lb[df_race_lb['has_time']].reset_index(drop=True)

        if valid_car_lb.empty:
            st.info("ℹ️ No hay carreras válidas registradas aún. Selecciona '📝 Pantalla de Edición y Registro' en el panel lateral para ingresar tiempos.")
        else:
            leader_car_row = valid_car_lb.iloc[0]
            leader_car_team = leader_car_row['team']
            leader_car_time = float(leader_car_row['avg_race_time'])

            # Highlight Banner for Category Leader (Best Car Time of All)
            render_html(f"""
            <div class="sr-leader-banner">
                <div style="display: flex; align-items: center; gap: 18px;">
                    <div style="font-size: 42px;">🏎️</div>
                    <div>
                        <div style="font-size: 12px; font-weight: 800; font-style: italic; color: #009FE3; text-transform: uppercase; letter-spacing: 1.5px;">
                            Mejor Tiempo de Carro de Todos (Líder de la Categoría)
                        </div>
                        <div style="font-size: 30px; font-weight: 900; font-style: italic; color: #FFFFFF; margin-top: 2px;">
                            {leader_car_team}
                        </div>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 12px; font-weight: 700; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">
                        Tiempo Récord de Carro
                    </div>
                    <div style="font-size: 34px; font-weight: 900; color: #009FE3;">
                        {leader_car_time:.3f} s
                    </div>
                </div>
            </div>
            """)

            # Broadcast Representation of all teams with their Car Time and Delta vs Leader (NO points)
            car_broadcast_rows = []
            for idx, row in df_race_lb.iterrows():
                rank = int(row['rank'])
                team = row['team']
                val = row['avg_race_time']
                best_ind = row['best_race_time']

                if pd.notna(val) and val > 0:
                    time_display = f"{val:.3f} s"
                    ind_display = f"<span style='font-size: 12px; color: #A09EB8;'>(Mejor pista: {best_ind:.3f} s)</span>" if pd.notna(best_ind) else ""
                    delta = float(val) - leader_car_time
                    if delta <= 0.0001:
                        delta_display = '<span style="background: rgba(0, 159, 227, 0.2); color: #009FE3; border: 1px solid #009FE3; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 900;">🏆 LÍDER (MEJOR TIEMPO)</span>'
                    else:
                        delta_display = f'<span style="color: #ED6D05; font-weight: 800; font-size: 16px;">+{delta:.3f} s</span>'
                else:
                    time_display = '<span class="sr-pending-badge">⏳ PENDIENTE</span>'
                    ind_display = ""
                    delta_display = '<span style="color: #6C6885;">---</span>'

                rank_class = "sr-rank-1" if rank == 1 else ("sr-rank-2" if rank == 2 else ("sr-rank-3" if rank == 3 else "sr-rank-badge"))

                car_broadcast_rows.append(f"""<div class="sr-broadcast-row">
                    <div style="display: flex; align-items: center; gap: 16px;">
                        <div class="{rank_class}">{rank}</div>
                        <div style="font-size: 20px;">🏎️</div>
                        <div>
                            <div class="sr-team-name">{team}</div>
                            {ind_display}
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 28px;">
                        <div style="text-align: right;">
                            <div style="font-size: 11px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Tiempo de Carro</div>
                            <div class="sr-time-val">{time_display}</div>
                        </div>
                        <div style="min-width: 190px; text-align: right;">
                            <div style="font-size: 11px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Diferencia vs Líder</div>
                            <div>{delta_display}</div>
                        </div>
                    </div>
                </div>""")

            render_html("\n".join(car_broadcast_rows))

        # Tab 3 content complete - no comparison charts as requested

    # ==============================================================================
    # TAB 4: TIEMPO MÁS RÁPIDO (Mejor tiempo total, clasificación y diferencia contra el líder, sin Top 3, sin puntos)
    # ==============================================================================
    with tab4:
        render_html("""
        <div style="text-align: center; margin-bottom: 24px;">
            <h2 style="font-size: 32px; font-weight: 900; color: #FFFFFF; text-transform: uppercase; margin: 0;">
                Tiempo Más Rápido
            </h2>
            <div style="color: #A09EB8; font-size: 15px; margin-top: 6px;">
                Mejor tiempo total (reacción + carrera) de cada equipo y diferencia respecto al líder de la categoría
            </div>
        </div>
        """)

        valid_tot_lb = df_total_lb[df_total_lb['has_time']].reset_index(drop=True)

        if valid_tot_lb.empty:
            st.info("ℹ️ No hay carreras válidas registradas aún. Selecciona '📝 Pantalla de Edición y Registro' en el panel lateral para ingresar tiempos.")
        else:
            leader_tot_row = valid_tot_lb.iloc[0]
            leader_tot_team = leader_tot_row['team']
            leader_tot_time = float(leader_tot_row['min_total_time'])

            # Highlight Banner for Category Leader (Fastest Total Time of All)
            render_html(f"""
            <div class="sr-leader-banner" style="border-color: #ED6D05; box-shadow: 0 8px 30px rgba(237, 109, 5, 0.22);">
                <div style="display: flex; align-items: center; gap: 18px;">
                    <div style="font-size: 42px;">🚀</div>
                    <div>
                        <div style="font-size: 12px; font-weight: 800; font-style: italic; color: #ED6D05; text-transform: uppercase; letter-spacing: 1.5px;">
                            Mejor Tiempo Más Rápido de Todos (Líder de la Categoría)
                        </div>
                        <div style="font-size: 30px; font-weight: 900; font-style: italic; color: #FFFFFF; margin-top: 2px;">
                            {leader_tot_team}
                        </div>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 12px; font-weight: 700; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">
                        Tiempo Total Récord
                    </div>
                    <div style="font-size: 34px; font-weight: 900; color: #ED6D05;">
                        {leader_tot_time:.3f} s
                    </div>
                </div>
            </div>
            """)

            # Broadcast Representation of all teams with their Fastest Total Time and Delta vs Leader (NO points)
            tot_broadcast_rows = []
            for idx, row in df_total_lb.iterrows():
                rank = int(row['rank'])
                team = row['team']
                val = row['min_total_time']
                rxn_b = row['best_rxn_time']
                race_b = row['best_race_time']

                if pd.notna(val) and val > 0:
                    time_display = f"{val:.3f} s"
                    sub_details = []
                    if pd.notna(rxn_b):
                        sub_details.append(f"Mejor Reacción: {rxn_b:.3f} s")
                    if pd.notna(race_b):
                        sub_details.append(f"Mejor Carrera: {race_b:.3f} s")
                    detail_html = f"<span style='font-size: 12px; color: #A09EB8;'>({' | '.join(sub_details)})</span>" if sub_details else ""

                    delta = float(val) - leader_tot_time
                    if delta <= 0.0001:
                        delta_display = '<span style="background: rgba(237, 109, 5, 0.2); color: #ED6D05; border: 1px solid #ED6D05; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 900;">🚀 LÍDER (MEJOR TIEMPO)</span>'
                    else:
                        delta_display = f'<span style="color: #009FE3; font-weight: 800; font-size: 16px;">+{delta:.3f} s</span>'
                else:
                    time_display = '<span class="sr-pending-badge">⏳ PENDIENTE</span>'
                    detail_html = ""
                    delta_display = '<span style="color: #6C6885;">---</span>'

                rank_class = "sr-rank-1" if rank == 1 else ("sr-rank-2" if rank == 2 else ("sr-rank-3" if rank == 3 else "sr-rank-badge"))

                tot_broadcast_rows.append(f"""<div class="sr-broadcast-row">
                    <div style="display: flex; align-items: center; gap: 16px;">
                        <div class="{rank_class}">{rank}</div>
                        <div style="font-size: 20px;">🏎️</div>
                        <div>
                            <div class="sr-team-name">{team}</div>
                            {detail_html}
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 28px;">
                        <div style="text-align: right;">
                            <div style="font-size: 11px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Mejor Tiempo Total</div>
                            <div class="sr-time-val">{time_display}</div>
                        </div>
                        <div style="min-width: 190px; text-align: right;">
                            <div style="font-size: 11px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Diferencia vs Líder</div>
                            <div>{delta_display}</div>
                        </div>
                    </div>
                </div>""")

            render_html("\n".join(tot_broadcast_rows))

        # Tab 4 content complete - no comparison charts as requested

