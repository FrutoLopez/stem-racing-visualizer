"""STEM Racing Results Visualizer - Streamlit Application.
Interactive tournament dashboard for live timing, head-to-head match-ups, and championship podium.
Fully adheres to official STEM Racing / F1 in Schools regulations:
- C9.5: Reaction race scoring (Fastest total race time, Base Time 120%, DNF deduction if 5 pts)
- C9.6: Time Trial race scoring (2nd & 3rd best car race time avg, DNF replacement rule, Base Time 115%, DNF deduction if 20 pts)
- C9.7: DNF race results (damage, part separation, off track)
- C9.8: False starts (trigger pressed before lights extinguish, 2.5-point penalty and race forfeit)
"""

import os
import base64
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np

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


# Assets & Paths
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
PODIOS_DIR = os.path.join(os.path.dirname(__file__), "Podios")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
MONO_WHITE_LOGO_PATH = os.path.join(PODIOS_DIR, "SR - Mono White copy.png")
TEAMS_CSV_PATH = os.path.join(os.path.dirname(__file__), "Equipos_Nombres.csv")
LIVE_CSV_PATH = os.path.join(os.path.dirname(__file__), "live_race_data.csv")
JUDGE_CSV_PATH = os.path.join(os.path.dirname(__file__), "judge_scores.csv")


def _compute_branding_cache_key() -> tuple:
    """Build a lightweight mtime signature so edits to team CSV, styles, or logos bust @st.cache_data."""
    mtimes = []
    for p in (TEAMS_CSV_PATH, os.path.join(os.path.dirname(__file__), "styles.py")):
        mtimes.append(os.path.getmtime(p) if os.path.exists(p) else 0.0)
    for folder in (os.path.join(ASSETS_DIR, "Logos"), PODIOS_DIR):
        if os.path.isdir(folder):
            for fn in sorted(os.listdir(folder)):
                fp = os.path.join(folder, fn)
                if os.path.isfile(fp):
                    mtimes.append((folder, fn, os.path.getmtime(fp)))
    return tuple(mtimes)


@st.cache_data(show_spinner=False)
def load_cached_branding_and_teams(cache_key: tuple):
    """Cache CSS, downscaled base64 logos, and team list once per file state to avoid disk I/O spikes."""
    css_str = styles.inject_custom_css()
    main_logo = styles.get_base64_encoded_image(LOGO_PATH, max_size=(640, 260))
    mono_white_logo = styles.get_base64_encoded_image(MONO_WHITE_LOGO_PATH, max_size=(520, 240))
    t_logos = styles.load_team_logos_b64(ASSETS_DIR)
    p_logos = styles.load_podium_logos_b64(PODIOS_DIR)
    teams = dp.load_teams_from_csv(TEAMS_CSV_PATH)
    matchups = dp.get_matchups(teams)
    return css_str, main_logo, mono_white_logo, t_logos, p_logos, teams, matchups


custom_css_str, logo_b64, mono_white_logo_b64, team_logos_b64, podium_logos_b64, official_teams, matchups_list = load_cached_branding_and_teams(_compute_branding_cache_key())

# Inject Custom CSS
if hasattr(st, "html"):
    st.html(custom_css_str)
else:
    st.markdown(custom_css_str, unsafe_allow_html=True)


def team_badge(team_name: str, height: int = 28, gap: int = 9) -> str:
    """Render team logo + team name inline."""
    return styles.render_team_with_logo(team_name, team_logos_b64, height=height, gap=gap)


def team_logo_only(team_name: str, height: int = 34, fallback_emoji: str = "🏎️") -> str:
    """Render only the team logo (or fallback emoji if team has no logo)."""
    return styles.get_team_logo_html(team_name, team_logos_b64, height=height, fallback_emoji=fallback_emoji)


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
    cleaned['team'] = cleaned['team'].astype(str).str.strip().replace(dp.LEGACY_TEAM_MAP)
    cleaned = cleaned[cleaned['team'].isin(official_teams)]
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
    with dp.CSV_LOCK:
        hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
        if hist_df is not None and not hist_df.empty:
            dp.save_runs_to_csv(hist_df, LIVE_CSV_PATH)
            initial_df = normalize_runs_df(hist_df)
        else:
            hist_df = pd.DataFrame(columns=dp.CSV_SCHEMA)
            initial_df = pd.DataFrame(columns=RUNS_SCHEMA)
        mtime = os.path.getmtime(LIVE_CSV_PATH) if os.path.exists(LIVE_CSV_PATH) else 0.0
        judge_mtime = os.path.getmtime(JUDGE_CSV_PATH) if os.path.exists(JUDGE_CSV_PATH) else 0.0
        persisted_judges = dp.load_judge_scores_from_csv(JUDGE_CSV_PATH, official_teams, {})
        return {
            "version": 1,
            "history_df": hist_df,
            "runs_df": initial_df,
            "custom_scores": persisted_judges,
            "csv_mtime": mtime,
            "judge_csv_mtime": judge_mtime,
            "explicitly_cleared": False,
        }


def sync_store_from_disk_if_needed(store: dict) -> bool:
    """
    Safely check if CSV files on disk have newer valid data without ever wiping
    non-empty in-memory state if a concurrent read returns empty.
    Returns True if store was updated.
    """
    updated = False
    with dp.CSV_LOCK:
        if "history_df" not in store or store["history_df"] is None:
            hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
            store["history_df"] = hist_df
            store["runs_df"] = normalize_runs_df(hist_df)
            updated = True
        elif store["history_df"].empty and not store.get("explicitly_cleared", False):
            # If memory store appears empty on a new connection, recover from disk/.bak if records exist
            hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
            if not hist_df.empty:
                store["history_df"] = hist_df
                store["runs_df"] = normalize_runs_df(hist_df)
                store["csv_mtime"] = os.path.getmtime(LIVE_CSV_PATH) if os.path.exists(LIVE_CSV_PATH) else 0.0
                store["version"] += 1
                updated = True

        if os.path.exists(LIVE_CSV_PATH):
            try:
                disk_mtime = os.path.getmtime(LIVE_CSV_PATH)
                if disk_mtime > store.get("csv_mtime", 0.0) + 0.05:
                    hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH)
                    # Guard against replacing non-empty store with an empty read unless explicitly cleared
                    if not hist_df.empty or store.get("explicitly_cleared", False) or store["history_df"].empty:
                        store["history_df"] = hist_df
                        store["runs_df"] = normalize_runs_df(hist_df)
                        store["csv_mtime"] = disk_mtime
                        store["version"] += 1
                        updated = True
            except Exception:
                pass

        if os.path.exists(JUDGE_CSV_PATH):
            try:
                j_mtime = os.path.getmtime(JUDGE_CSV_PATH)
                if j_mtime > store.get("judge_csv_mtime", 0.0) + 0.05:
                    loaded_j = dp.load_judge_scores_from_csv(JUDGE_CSV_PATH, official_teams, {})
                    if loaded_j is not None and not loaded_j.empty:
                        store["custom_scores"] = loaded_j
                        store["judge_csv_mtime"] = j_mtime
                        store["version"] += 1
                        updated = True
            except Exception:
                pass

        teams_sig = tuple(official_teams)
        if store.get("teams_sig") != teams_sig:
            store["runs_df"] = normalize_runs_df(store.get("history_df"))
            loaded_j = dp.load_judge_scores_from_csv(JUDGE_CSV_PATH, official_teams, {})
            if loaded_j is not None and not loaded_j.empty:
                store["custom_scores"] = loaded_j
            store["teams_sig"] = teams_sig
            store["version"] += 1
            updated = True
    return updated


shared_store = get_shared_race_store()
sync_store_from_disk_if_needed(shared_store)


def append_race_records(new_rows: list) -> pd.DataFrame:
    """
    Append new or edited race records to the CSV file with a sequential `id` and `timestamp`,
    and update the active deduplicated `runs_df` for all connected visualizers.
    """
    with dp.CSV_LOCK:
        hist_df = dp.append_runs_to_csv(new_rows, LIVE_CSV_PATH)
        active_df = normalize_runs_df(hist_df)
        shared_store["explicitly_cleared"] = False
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
    with dp.CSV_LOCK:
        empty_hist = dp.clear_runs_csv(LIVE_CSV_PATH)
        empty_active = pd.DataFrame(columns=RUNS_SCHEMA)
        shared_store["explicitly_cleared"] = True
        shared_store["history_df"] = empty_hist.copy()
        shared_store["runs_df"] = empty_active.copy()
        if os.path.exists(LIVE_CSV_PATH):
            shared_store["csv_mtime"] = os.path.getmtime(LIVE_CSV_PATH)
        shared_store["version"] += 1
        st.session_state.history_df = empty_hist.copy()
        st.session_state.runs_df = empty_active.copy()
        st.session_state.local_store_version = shared_store["version"]
        st.session_state["_last_active_form_ctx"] = None


def commit_runs_df(new_df: pd.DataFrame, recalculate_totals: bool = True) -> pd.DataFrame:
    """Save full grid edits to CSV (with id and timestamp) and broadcast to all connected visualizers."""
    with dp.CSV_LOCK:
        dp.save_runs_to_csv(new_df, LIVE_CSV_PATH, recalculate_totals=recalculate_totals)
        hist_df = dp.load_runs_from_csv(LIVE_CSV_PATH, recalculate_totals=recalculate_totals)
        cleaned = normalize_runs_df(hist_df)
        shared_store["explicitly_cleared"] = cleaned.empty
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


def save_and_sync_judge_scores(scores_df: pd.DataFrame, racing_pts_map: dict) -> pd.DataFrame:
    """Recalculate championship totals/ranks, persist judge scores to disk, and sync shared store."""
    with dp.CSV_LOCK:
        updated = scores_df.copy()
        updated['Carrera'] = updated['team'].map(racing_pts_map).fillna(0.0)
        cat_cols = [c for c in dp.DEFAULT_CATEGORIES if c in updated.columns]
        updated['Total'] = updated[cat_cols].sum(axis=1).round(2)
        updated = updated.sort_values(by='Total', ascending=False).reset_index(drop=True)
        updated['rank'] = updated.index + 1
        dp.save_judge_scores_to_csv(updated, JUDGE_CSV_PATH)
        if os.path.exists(JUDGE_CSV_PATH):
            shared_store["judge_csv_mtime"] = os.path.getmtime(JUDGE_CSV_PATH)
        shared_store["custom_scores"] = updated.copy()
        shared_store["version"] += 1
        st.session_state.custom_scores = updated.copy()
        st.session_state.local_store_version = shared_store["version"]
        return updated


@st.fragment(run_every=2.5)
def live_visualizer_sync_watcher():
    """Background watcher that refreshes passive visualizer tabs when records are saved."""
    store = get_shared_race_store()
    sync_store_from_disk_if_needed(store)
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
    loaded_from_disk = dp.load_judge_scores_from_csv(JUDGE_CSV_PATH, official_teams, racing_pts_map)
    if loaded_from_disk is not None:
        st.session_state.custom_scores = loaded_from_disk
    else:
        st.session_state.custom_scores = dp.get_default_category_scores(official_teams, racing_pts_map)
    shared_store["custom_scores"] = st.session_state.custom_scores.copy()
else:
    st.session_state.custom_scores['Carrera'] = st.session_state.custom_scores['team'].map(racing_pts_map).fillna(0.0)
    cat_cols = [c for c in dp.DEFAULT_CATEGORIES if c in st.session_state.custom_scores.columns]
    st.session_state.custom_scores['Total'] = st.session_state.custom_scores[cat_cols].sum(axis=1).round(2)
    st.session_state.custom_scores = st.session_state.custom_scores.sort_values(by='Total', ascending=False).reset_index(drop=True)
    st.session_state.custom_scores['rank'] = st.session_state.custom_scores.index + 1
    shared_store["custom_scores"] = st.session_state.custom_scores.copy()

for sub_col in dp.ALL_SUBCATEGORY_KEYS:
    if sub_col not in st.session_state.custom_scores.columns:
        st.session_state.custom_scores[sub_col] = 0.0

# ==============================================================================
# SIDEBAR CONTROLS
# ==============================================================================
with st.sidebar:
    if logo_b64:
        render_html(f'<div style="text-align: center; margin-bottom: 20px;"><img src="data:image/png;base64,{logo_b64}" style="max-width: 85%; height: auto;"/></div>')

    st.markdown("## 🧭 Pantalla Activa")
    screen_options = [
        "⏱️ Tiempos y Resultados en Pista",
        "🏆 Ceremonia de Podio",
        "📝 Pantalla de Edición y Registro",
        "📝 Registro de Jurado"
    ]
    if "_pending_view_mode" in st.session_state and st.session_state._pending_view_mode in screen_options:
        st.session_state.app_view_mode = st.session_state._pending_view_mode
        del st.session_state._pending_view_mode

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
        width="stretch",
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
        reload_clicked = st.button("🔄 Recargar CSV Subido", width="stretch", key="reload_uploaded_csv_btn")
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
    uploaded_rubric_files = st.file_uploader(
        "Subir Archivo(s) de Evaluación (.xlsx / .csv):",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
        key="rubric_file_uploader",
        help="Sube uno o varios archivos Excel/CSV de evaluación ('STEM RACING - COMPETITION JUDGING BREAKDOWN') por equipo o tabla resumen."
    )
    if uploaded_rubric_files:
        rubric_sig = "|".join(f"{f.name}_{f.size}" for f in uploaded_rubric_files)
        auto_load_rubric = st.session_state.get("_last_uploaded_rubric_sig") != rubric_sig
        reload_rubric_btn = st.button("🔄 Recargar Puntajes de Archivo(s)", width="stretch", key="reload_rubric_btn")
        if auto_load_rubric or reload_rubric_btn:
            parsed_scores, parse_msgs = dp.parse_judging_rubric_files(uploaded_rubric_files, official_teams)
            st.session_state["_last_uploaded_rubric_msgs"] = parse_msgs
            st.session_state["_last_uploaded_rubric_sig"] = rubric_sig
            if parsed_scores and st.session_state.custom_scores is not None:
                for t_name, cat_vals in parsed_scores.items():
                    t_mask = st.session_state.custom_scores['team'] == t_name
                    if t_mask.any():
                        for cat_col, val in cat_vals.items():
                            st.session_state.custom_scores.loc[t_mask, cat_col] = val
                save_and_sync_judge_scores(st.session_state.custom_scores, racing_pts_map)
                st.toast(f"✅ Puntajes de jueces cargados para {len(parsed_scores)} equipo(s).")
                st.rerun()
        for msg in st.session_state.get("_last_uploaded_rubric_msgs", []):
            st.caption(msg)
    else:
        st.session_state["_last_uploaded_rubric_sig"] = None
        st.session_state["_last_uploaded_rubric_msgs"] = []

    with st.expander("✏️ Editar Puntajes de Jueces Manualmente"):
        if st.button("📝 Abrir Registro de Jurado", width="stretch", key="sidebar_goto_js_btn"):
            st.session_state._pending_view_mode = "📝 Registro de Jurado"
            st.rerun()
        st.caption("Ajusta los puntajes evaluados por los jueces para el Podio General:")
        if st.session_state.custom_scores is not None:
            edited_rubric = st.data_editor(
                st.session_state.custom_scores[['team', 'Identidad de Marca', 'Presentación Verbal', 'Especificaciones y Escrutinio', 'Diseño e Ingeniería', 'Gestión de Proyecto']],
                hide_index=True,
                width="stretch",
                key="rubric_editor"
            )
            if st.button("💾 Guardar Puntajes de Jueces", width="stretch"):
                for col in dp.NON_RACING_CATEGORIES:
                    st.session_state.custom_scores[col] = pd.to_numeric(edited_rubric[col], errors='coerce').fillna(0.0).clip(
                        lower=0.0, upper=float(dp.CATEGORY_MAX_POINTS.get(col, 200))
                    )
                save_and_sync_judge_scores(st.session_state.custom_scores, racing_pts_map)
                st.toast("✅ Puntajes de jueces guardados.")
                st.rerun()
            if st.button("🔄 Poner Puntajes de Jueces en 0", width="stretch"):
                zero_df = dp.get_default_category_scores(official_teams, racing_pts_map, zero_init=True)
                save_and_sync_judge_scores(zero_df, racing_pts_map)
                st.toast("🗑️ Puntajes de jueces reiniciados en 0.")
                st.rerun()

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
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{format_pts(row['Identidad de Marca'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 100</span></td>
            </tr>
            <tr>
                <td style="font-weight: 700;">🎤 Presentación Verbal</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{format_pts(row['Presentación Verbal'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 160</span></td>
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
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{format_pts(row['Especificaciones y Escrutinio'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 170</span></td>
            </tr>
            <tr>
                <td style="font-weight: 700;">💻 Diseño e Ingeniería</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{format_pts(row['Diseño e Ingeniería'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 180</span></td>
            </tr>
            <tr>
                <td style="font-weight: 700;">📊 Empresa y Gestión de Proyecto</td>
                <td style="text-align: right; font-weight: 900; font-size: 17px; color: {accent_color};">{format_pts(row['Gestión de Proyecto'])} <span style="font-size: 12px; color: #A09EB8; font-weight: 600;">/ 160</span></td>
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
            <div style="display: flex; align-items: center; gap: 18px;">
                {team_logo_only(team_name, height=58)}
                <div style="text-align: left;">
                    <div style="font-size: 12px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1.5px;">Equipo Galardonado</div>
                    <div style="font-size: 40px; font-weight: 900; color: #FFFFFF; margin-top: 4px; letter-spacing: 0.5px;">{team_name}</div>
                </div>
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
                <div style="font-size: 12px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Categorías de Evaluación</div>
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


@st.cache_data(show_spinner=False)
def load_podium_bg_gif_b64(cache_key: float) -> str:
    """Load the podium background GIF from assets/Animations/ as base64 (preferring dark-blended version)."""
    anim_dir = os.path.join(ASSETS_DIR, "Animations")
    if os.path.isdir(anim_dir):
        preferred = os.path.join(anim_dir, "podium_dark_bg.gif")
        if os.path.exists(preferred):
            with open(preferred, "rb") as f:
                return base64.b64encode(f.read()).decode()
        for fn in sorted(os.listdir(anim_dir)):
            if fn.lower().endswith(".gif"):
                fp = os.path.join(anim_dir, fn)
                with open(fp, "rb") as f:
                    return base64.b64encode(f.read()).decode()
    return ""


def _get_podium_bg_gif_b64() -> str:
    anim_dir = os.path.join(ASSETS_DIR, "Animations")
    mtime = 0.0
    if os.path.isdir(anim_dir):
        preferred = os.path.join(anim_dir, "podium_dark_bg.gif")
        if os.path.exists(preferred):
            mtime = os.path.getmtime(preferred)
        else:
            for fn in sorted(os.listdir(anim_dir)):
                if fn.lower().endswith(".gif"):
                    mtime = os.path.getmtime(os.path.join(anim_dir, fn))
                    break
    return load_podium_bg_gif_b64(mtime)


def render_podium_logo_splash_slide():
    """Full-window splash screen before the podium with the animated flag background and centered STEM Racing Panamá logo."""
    gif_b64 = _get_podium_bg_gif_b64()
    bg_gif_html = (
        f'<img src="data:image/gif;base64,{gif_b64}" alt="" '
        f'style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; z-index: 0; pointer-events: none;" />'
        if gif_b64 else ""
    )
    center_logo_html = (
        f'<img src="data:image/png;base64,{logo_b64}" alt="STEM Racing Panamá" '
        f'style="max-width: 560px; width: 68%; height: auto; filter: drop-shadow(0 10px 32px rgba(0,0,0,0.85));" />'
        if logo_b64 else
        '<div style="font-size: 48px; font-weight: 900; color: #FFFFFF;">STEM RACING PANAMÁ</div>'
    )
    render_html(f"""
    <div key="podium-splash-{st.session_state.podium_anim_nonce}">
        <div class="sr-podium-stage" style="position: relative; overflow: hidden; border-radius: 14px; width: 100%; max-width: none; min-height: 84vh; margin: 0; padding: 36px 28px; display: flex; align-items: center; justify-content: center; box-sizing: border-box; background: rgba(12, 8, 24, 0.85);">
            {bg_gif_html}
            <div class="sr-anim-winner" style="position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; width: 100%; animation-delay: 0.1s;">
                {center_logo_html}
            </div>
        </div>
    </div>
    """)


def render_podium_full_slide(reveal_level: int = 3):
    """Podium presentation with stretched GIF background and step-by-step 3rd -> 2nd -> 1st reveal."""
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

    # Positions 4-6 (Left) and 7-9 (Right) for the 9 competing teams
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
                <td style="padding: 10px 14px; font-weight: 800; font-size: 15px; color: #FFFFFF; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">{team_badge(r_team, height=24)}</td>
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

    gif_b64 = _get_podium_bg_gif_b64()
    bg_gif_html = (
        f'<img src="data:image/gif;base64,{gif_b64}" alt="" '
        f'style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; z-index: 0; pointer-events: none;" />'
        if gif_b64 else ""
    )
    if reveal_level == 1 and logo_b64 and mono_white_logo_b64:
        sr_logo_html = (
            f'<img src="data:image/png;base64,{logo_b64}" alt="" class="sr-logo-morph-out" />'
            f'<img src="data:image/png;base64,{mono_white_logo_b64}" alt="STEM Racing" class="sr-logo-morph-in" />'
        )
    else:
        sr_logo_html = (
            f'<img src="data:image/png;base64,{mono_white_logo_b64}" alt="STEM Racing" '
            f'style="position: absolute; top: 24px; left: 28px; height: 82px; width: auto; z-index: 2; pointer-events: none; filter: drop-shadow(0 2px 10px rgba(0,0,0,0.7));" />'
            if mono_white_logo_b64 else ""
        )

    # Reveal states: 1 = pop 3rd, 2 = 3rd visible + pop 2nd, 3 = 3rd & 2nd visible + pop 1st + table
    col3_cls = "sr-podium-col sr-podium-anim-pop" if reveal_level == 1 else "sr-podium-col"
    col3_vis = "visible" if reveal_level >= 1 else "hidden"

    col2_cls = "sr-podium-col sr-podium-anim-pop" if reveal_level == 2 else "sr-podium-col"
    col2_vis = "visible" if reveal_level >= 2 else "hidden"

    col1_cls = "sr-podium-col sr-podium-anim-pop" if reveal_level == 3 else "sr-podium-col"
    col1_vis = "visible" if reveal_level >= 3 else "hidden"

    def build_cylinder_col(col_cls: str, col_vis: str, rank: int, team_name: str, pts_str: str, logo_h: int, ped_h: int, medal_sz: int) -> str:
        medal_svg = styles.get_podium_medal_svg(rank, size=medal_sz)
        logo_html = styles.get_podium_logo_html(team_name, podium_logos_b64, height=logo_h)
        return f"""
        <div class="{col_cls}" style="visibility: {col_vis}; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; flex: 1; max-width: 310px; min-width: 220px;">
            <div style="text-align: center; margin-bottom: -16px; position: relative; z-index: 3;">
                <div style="font-size: 21px; font-weight: 900; color: #FFFFFF; text-shadow: 0 2px 10px rgba(0,0,0,0.95); margin-bottom: 10px; letter-spacing: 0.3px;">{team_name}</div>
                <div>{logo_html}</div>
            </div>
            <div style="position: relative; width: 100%; height: {ped_h}px; margin-top: 18px; background: linear-gradient(90deg, #8A8E94 0%, #C8CCD1 18%, #F4F6F9 45%, #D0D4D9 72%, #7D8086 100%); border-radius: 0 0 50% 50% / 0 0 22px 22px; box-shadow: 0 16px 32px rgba(0,0,0,0.68); display: flex; flex-direction: column; align-items: center; justify-content: center; padding-top: 20px; box-sizing: border-box;">
                <div style="position: absolute; top: -18px; left: 0; right: 0; height: 36px; border-radius: 50%; background: radial-gradient(ellipse at 50% 45%, #7B7E84 0%, #52555B 70%, #3E4045 100%); border: 1.5px solid rgba(255, 255, 255, 0.35); box-shadow: inset 0 2px 6px rgba(0,0,0,0.45); z-index: 2;"></div>
                <div style="position: relative; z-index: 3; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 7px;">
                    {medal_svg}
                    <div style="font-size: 19px; font-weight: 900; color: #111111; letter-spacing: 0.4px;">{pts_str} PTS</div>
                </div>
            </div>
        </div>
        """

    col2_html = build_cylinder_col(col2_cls, col2_vis, 2, t2_name, t2_pts, logo_h=142, ped_h=195, medal_sz=70)
    col1_html = build_cylinder_col(col1_cls, col1_vis, 1, t1_name, t1_pts, logo_h=166, ped_h=265, medal_sz=82)
    col3_html = build_cylinder_col(col3_cls, col3_vis, 3, t3_name, t3_pts, logo_h=132, ped_h=150, medal_sz=64)

    podium_ceremony_html = f"""
    <div key="podium-full-{reveal_level}-{st.session_state.podium_anim_nonce}">
        <div class="sr-podium-stage" style="position: relative; overflow: hidden; border-radius: 14px; width: 100%; max-width: none; min-height: 84vh; margin: 0; padding: 36px 28px 44px 28px; display: flex; align-items: flex-end; justify-content: center; box-sizing: border-box; background: rgba(12, 8, 24, 0.85);">
            {bg_gif_html}
            {sr_logo_html}
            <div class="sr-podium-container" style="position: relative; z-index: 1; display: flex; justify-content: center; align-items: flex-end; gap: 48px; margin: 0 auto; padding: 10px 0 0 0; max-width: 1220px; width: 100%;">
                {col2_html}
                {col1_html}
                {col3_html}
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
    col_hdr_title, col_hdr_btn1, col_hdr_btn_js, col_hdr_btn_exp, col_hdr_btn2 = st.columns([2.0, 0.8, 0.9, 0.8, 0.9])
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
        if st.button("📺 Ir al Visualizador", width="stretch"):
            st.session_state._pending_view_mode = "⏱️ Tiempos y Resultados en Pista"
            st.rerun()
    with col_hdr_btn_js:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        if st.button("📝 Registro de Jurado", width="stretch", key="hdr_goto_js_btn"):
            st.session_state._pending_view_mode = "📝 Registro de Jurado"
            st.rerun()
    with col_hdr_btn_exp:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        export_df_hdr = st.session_state.history_df if (st.session_state.history_df is not None and not st.session_state.history_df.empty) else pd.DataFrame(columns=dp.CSV_SCHEMA)
        st.download_button(
            label="📥 Exportar CSV",
            data=export_df_hdr.to_csv(index=False).encode("utf-8"),
            file_name=f"carreras_stem_racing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            width="stretch",
            key="hdr_export_csv_btn"
        )
    @st.dialog("⚠️ Confirmar Borrado de Registros")
    def confirm_clear_all_dialog():
        st.warning("¿Estás seguro de que deseas borrar **todos los registros** de carreras? Esta acción vaciará los tiempos actuales y el archivo CSV activo para empezar desde 0.")
        col_conf_yes, col_conf_no = st.columns(2)
        with col_conf_yes:
            if st.button("✅ Sí, borrar todo", type="primary", width="stretch"):
                clear_all_records()
                st.toast("🗑️ Todos los registros han sido borrados. Listo para empezar de 0.")
                st.rerun()
        with col_conf_no:
            if st.button("❌ Cancelar", width="stretch"):
                st.rerun()

    with col_hdr_btn2:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        if st.button("🗑️ Borrar Todos los Registros", width="stretch"):
            confirm_clear_all_dialog()

    # Matchup Selector (Top, Non-typeable Pills)
    matchup_labels = [m['label'] for m in matchups_list]
    if st.session_state.get("input_matchup_selector") not in matchup_labels:
        st.session_state["input_matchup_selector"] = matchup_labels[0]
    st.markdown("<div style='font-size: 14px; font-weight: 700; color: #E6E4F0; margin-bottom: 6px;'>⚔️ Seleccionar Enfrentamiento:</div>", unsafe_allow_html=True)
    selected_matchup_label = st.pills(
        "Seleccionar Enfrentamiento:",
        options=matchup_labels,
        default=matchup_labels[0],
        key="input_matchup_selector",
        label_visibility="collapsed"
    )
    if not selected_matchup_label or selected_matchup_label not in matchup_labels:
        selected_matchup_label = matchup_labels[0]

    selected_matchup = next(m for m in matchups_list if m['label'] == selected_matchup_label)
    team_a = selected_matchup['team_a']
    team_b = selected_matchup['team_b']
    is_solo_matchup = (team_b is None) or bool(selected_matchup.get('is_solo', False))

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
        run_a = curr_runs[mask_exist_a]
        if not is_solo_matchup:
            mask_exist_b = (curr_runs['team'].astype(str).str.strip() == team_b) & (pd.to_numeric(curr_runs['race_number'], errors='coerce') == int(selected_race_num))
            run_b = curr_runs[mask_exist_b]
        else:
            run_b = pd.DataFrame()
    else:
        run_a = pd.DataFrame()
        run_b = pd.DataFrame()

    already_exists_a = not run_a.empty
    already_exists_b = (not is_solo_matchup) and (not run_b.empty)

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

    # Sync widget state only when the selected matchup or race number changes (never mid-edit on background version ticks)
    active_form_ctx = (team_a, team_b, int(selected_race_num))
    if st.session_state.get("_last_active_form_ctx") != active_form_ctx:
        st.session_state[chk_dnf_a_key] = init_a_dnf
        st.session_state[chk_fs_a_key] = init_a_fs
        st.session_state[num_rxn_a_key] = init_a_rxn
        st.session_state[num_race_a_key] = init_a_race

        if not is_solo_matchup:
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
            width="stretch",
            key=f"btn_test_mode_{team_a}_{team_b}_{selected_race_num}",
            help="Genera valores aleatorios basados en el Excel de referencia (incluyendo probabilidad de DNF o False Start) y puntuaciones aleatorias de categorías para esta carrera."
        ):
            rnd_a_dnf, rnd_a_fs, rnd_a_rxn, rnd_a_race = dp.generate_random_test_run()
            st.session_state[chk_dnf_a_key] = rnd_a_dnf
            st.session_state[chk_fs_a_key] = rnd_a_fs
            st.session_state[num_rxn_a_key] = rnd_a_rxn
            st.session_state[num_race_a_key] = rnd_a_race
            lbl_a = "DNF" if rnd_a_dnf else ("False Start" if rnd_a_fs else f"{rnd_a_rxn + rnd_a_race:.3f}s")

            teams_to_randomize = [team_a]
            if not is_solo_matchup:
                rnd_b_dnf, rnd_b_fs, rnd_b_rxn, rnd_b_race = dp.generate_random_test_run()
                st.session_state[chk_dnf_b_key] = rnd_b_dnf
                st.session_state[chk_fs_b_key] = rnd_b_fs
                st.session_state[num_rxn_b_key] = rnd_b_rxn
                st.session_state[num_race_b_key] = rnd_b_race
                lbl_b = "DNF" if rnd_b_dnf else ("False Start" if rnd_b_fs else f"{rnd_b_rxn + rnd_b_race:.3f}s")
                teams_to_randomize.append(team_b)

            # Randomize non-racing category scores for the teams in the selected race
            if st.session_state.custom_scores is not None:
                for t_name in teams_to_randomize:
                    rnd_scores = dp.generate_random_judge_scores_for_team()
                    t_mask = st.session_state.custom_scores['team'] == t_name
                    for cat_col, val in rnd_scores.items():
                        st.session_state.custom_scores.loc[t_mask, cat_col] = val
                save_and_sync_judge_scores(st.session_state.custom_scores, racing_pts_map)

            if is_solo_matchup:
                st.toast(f"🎲 Test Mode (Carrera {selected_race_num}): {team_a} [{lbl_a}]. Presiona Guardar para registrar.")
            else:
                st.toast(f"🎲 Test Mode (Carrera {selected_race_num}): {team_a} [{lbl_a}] | {team_b} [{lbl_b}]. Presiona Guardar para registrar.")

        col_fa_top, col_fb_top = st.columns(2)
        with col_fa_top:
            status_a_html = '<span style="font-size: 11px; color: #00F0FF; background: rgba(0, 240, 255, 0.12); padding: 2px 8px; border-radius: 6px; font-weight: 700;">✏️ Guardado (sobreescribible)</span>' if already_exists_a else '<span style="font-size: 11px; color: #A09EB8;">⏳ Sin registro</span>'
            st.markdown(f"<div style='display:flex; align-items:center; justify-content:space-between; margin-bottom: 8px;'><span style='font-size: 18px; font-weight: 900; color: #00F0FF;'>{team_badge(team_a, height=28)}</span>{status_a_html}</div>", unsafe_allow_html=True)
            col_chk_a1, col_chk_a2 = st.columns(2)
            with col_chk_a1:
                a_dnf = st.checkbox("❌ DNF", key=chk_dnf_a_key, on_change=_on_toggle_dnf_a)
            with col_chk_a2:
                a_fs = st.checkbox("🚦 False Start", key=chk_fs_a_key, on_change=_on_toggle_fs_a, help="Salida en falso y forfeit de carrera.")

        with col_fb_top:
            if not is_solo_matchup:
                status_b_html = '<span style="font-size: 11px; color: #FF8A00; background: rgba(255, 138, 0, 0.12); padding: 2px 8px; border-radius: 6px; font-weight: 700;">✏️ Guardado (sobreescribible)</span>' if already_exists_b else '<span style="font-size: 11px; color: #A09EB8;">⏳ Sin registro</span>'
                st.markdown(f"<div style='display:flex; align-items:center; justify-content:space-between; margin-bottom: 8px;'><span style='font-size: 18px; font-weight: 900; color: #FF8A00;'>{team_badge(team_b, height=28)}</span>{status_b_html}</div>", unsafe_allow_html=True)
                col_chk_b1, col_chk_b2 = st.columns(2)
                with col_chk_b1:
                    b_dnf = st.checkbox("❌ DNF", key=chk_dnf_b_key, on_change=_on_toggle_dnf_b)
                with col_chk_b2:
                    b_fs = st.checkbox("🚦 False Start", key=chk_fs_b_key, on_change=_on_toggle_fs_b, help="Salida en falso y forfeit de carrera.")
            else:
                b_dnf = False
                b_fs = False
                st.markdown("<div style='display:flex; align-items:center; justify-content:space-between; margin-bottom: 8px;'><span style='font-size: 15px; font-weight: 800; color: #A09EB8;'>🏎️ Modalidad Individual</span><span style='font-size: 11px; color: #FCBC00; background: rgba(252, 188, 0, 0.14); padding: 2px 8px; border-radius: 6px; font-weight: 700;'>Sin Oponente</span></div>", unsafe_allow_html=True)

        # Direct session-state bound inputs (no nested st.form split) so toggling DNF/FS or clicking Guardar on mobile/desktop never drops typed numbers
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
                tot_a_prev = float(a_rxn) + float(a_race)
                render_html(f"""<div style="text-align: center; padding: 6px; background: rgba(0, 240, 255, 0.08); border: 1px solid rgba(0, 240, 255, 0.4); border-radius: 8px; margin: 8px 0;">
                    <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo Total Registrado</div>
                    <div style="font-size: 18px; font-weight: 900; color: #00F0FF;">{tot_a_prev:.3f} s</div>
                </div>""")

        # -----------------------------
        # TEAM B INPUTS (OR SOLO CARD)
        # -----------------------------
        with col_fb:
            if is_solo_matchup:
                b_rxn = 0.0
                b_race = 0.0
                render_html(f"""<div style="text-align: center; padding: 28px 16px; background: rgba(255, 255, 255, 0.03); border: 1px dashed rgba(255, 255, 255, 0.18); border-radius: 12px; margin: 8px 0;">
                    <div style="font-size: 28px; margin-bottom: 6px;">🏁</div>
                    <div style="font-size: 14px; font-weight: 800; color: #FFFFFF; text-transform: uppercase; letter-spacing: 0.8px;">Carrera Individual</div>
                    <div style="font-size: 12px; color: #A09EB8; margin-top: 6px; line-height: 1.4;">
                        <strong>{team_a}</strong> corre de forma individual en pista para todos los cálculos de puntuación (Tiempo de Carro y Tiempo Más Rápido).
                    </div>
                </div>""")
            elif b_fs:
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
                tot_b_prev = float(b_rxn) + float(b_race)
                render_html(f"""<div style="text-align: center; padding: 6px; background: rgba(255, 138, 0, 0.08); border: 1px solid rgba(255, 138, 0, 0.4); border-radius: 8px; margin: 8px 0;">
                    <div style="font-size: 11px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo Total Registrado</div>
                    <div style="font-size: 18px; font-weight: 900; color: #FF8A00;">{tot_b_prev:.3f} s</div>
                </div>""")

        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
        submit_matchup_race = st.button(
            f"🏁 Guardar Resultados de Carrera {selected_race_num}",
            key=f"btn_save_race_{team_a}_{team_b}_{selected_race_num}",
            width="stretch",
            type="primary"
        )

        if submit_matchup_race:
            has_data_a = bool(a_dnf or a_fs or (a_race > 0) or (a_rxn > 0))
            has_data_b = (not is_solo_matchup) and bool(b_dnf or b_fs or (b_race > 0) or (b_rxn > 0))

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

                changed_a = (
                    (not already_exists_a and has_data_a) or
                    (already_exists_a and (
                        (row_dict_a['is_dnf'] != init_a_dnf) or
                        (row_dict_a['is_false_start'] != init_a_fs) or
                        (not is_inv_a and (abs(float(a_rxn) - init_a_rxn) > 1e-6 or abs(float(a_race) - init_a_race) > 1e-6))
                    ))
                )

                rows_to_append = []
                if changed_a:
                    rows_to_append.append(row_dict_a)

                changed_b = False
                if not is_solo_matchup:
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
                    changed_b = (
                        (not already_exists_b and has_data_b) or
                        (already_exists_b and (
                            (row_dict_b['is_dnf'] != init_b_dnf) or
                            (row_dict_b['is_false_start'] != init_b_fs) or
                            (not is_inv_b and (abs(float(b_rxn) - init_b_rxn) > 1e-6 or abs(float(b_race) - init_b_race) > 1e-6))
                        ))
                    )
                    if changed_b:
                        rows_to_append.append(row_dict_b)

                # If user clicked Guardar again on existing data without changing values, still append a timestamped record
                if not rows_to_append:
                    if has_data_a or already_exists_a:
                        rows_to_append.append(row_dict_a)
                    if not is_solo_matchup and (has_data_b or already_exists_b):
                        rows_to_append.append(row_dict_b)

                was_overwrite = (already_exists_a and changed_a) or (already_exists_b and changed_b) or (already_exists_a or already_exists_b)
                append_race_records(rows_to_append)

                if was_overwrite:
                    st.toast(f"✅ Carrera {selected_race_num} actualizada y registrada con timestamp en el CSV!")
                else:
                    st.toast(f"✅ Carrera {selected_race_num} guardada con éxito!")
                st.rerun()

    with col_history_area:
        hist_title_right = f"{team_a} (Individual)" if is_solo_matchup else f"{team_a} vs {team_b}"
        render_html(f"""
        <div style="background: rgba(18, 12, 36, 0.85); border: 1px solid rgba(0, 240, 255, 0.3); border-radius: 14px; padding: 18px 20px 10px 20px; margin-bottom: 16px;">
            <div style="font-size: 18px; font-weight: 900; color: #FFFFFF; display: flex; align-items: center; justify-content: space-between;">
                <span>⚔️ Historial del Enfrentamiento</span>
                <span style="font-size: 14px; color: #00F0FF; font-weight: 800;">{hist_title_right}</span>
            </div>
            <div style="font-size: 13px; color: #A09EB8; margin-top: 4px;">
                Resumen de las 4 carreras registradas en pista.
            </div>
        </div>
        """)

        sum_a = df_teams_summary[df_teams_summary['team'] == team_a].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_a].empty) else None
        best_tot_a_val = sum_a['min_total_time'] if sum_a is not None else None
        car_time_a_val = sum_a['avg_race_time'] if sum_a is not None else None
        best_tot_a_txt = f"{best_tot_a_val:.3f} s" if (pd.notna(best_tot_a_val) and best_tot_a_val > 0) else "Pendiente"
        car_time_a_txt = f"{car_time_a_val:.3f} s" if (pd.notna(car_time_a_val) and car_time_a_val > 0) else "Pendiente"

        if is_solo_matchup:
            history_rows = []
            for r_num in range(1, 5):
                ra = curr_runs[(curr_runs['team'] == team_a) & (curr_runs['race_number'] == r_num)]
                if not ra.empty:
                    r_row_a = ra.iloc[-1]
                    if r_row_a.get('is_false_start', False):
                        cell_a = '<span class="sr-fs-badge">FALSE START</span>'
                    elif r_row_a.get('is_dnf', False):
                        cell_a = '<span class="sr-dnf-badge">DNF</span>'
                    else:
                        tot_a_val = r_row_a.get('total_time', 0.0)
                        cell_a = f'<strong style="color: #00F0FF;">{tot_a_val:.3f}s</strong> <span style="font-size:11px; color:#A09EB8;">(Reacción: {r_row_a.get("reaction_time", 0.0):.3f}s | Carro: {r_row_a.get("race_time", 0.0):.3f}s)</span>'
                else:
                    cell_a = '<span class="sr-pending-badge">⏳ Pendiente</span>'

                history_rows.append(f"""<tr>
                    <td style="font-weight: 800; color: #FFFFFF;">Carrera {r_num}</td>
                    <td style="text-align: center;">{cell_a}</td>
                </tr>""")

            hist_table_html = f"""<table class="sr-pptx-table" style="font-size: 13px;">
                <thead>
                    <tr>
                        <th style="width: 30%;">Carrera</th>
                        <th style="width: 70%; text-align: center; color: #00F0FF;">{team_badge(team_a, height=22)}</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(history_rows)}
                </tbody>
                <tfoot>
                    <tr style="background: rgba(255, 255, 255, 0.05); border-top: 2px solid rgba(255, 42, 133, 0.4);">
                        <td style="font-weight: 800; color: #FFFFFF; font-size: 12px;">🏎️ Tiempo de Carro</td>
                        <td style="text-align: center; font-weight: 800; color: #00F0FF;">{car_time_a_txt}</td>
                    </tr>
                    <tr style="background: rgba(255, 42, 133, 0.12);">
                        <td style="font-weight: 800; color: #FFFFFF; font-size: 12px;">🚀 Mejor T. Total</td>
                        <td style="text-align: center; font-weight: 900; color: #00F0FF;">{best_tot_a_txt}</td>
                    </tr>
                </tfoot>
            </table>"""
        else:
            # Table of 4 races for this 2-team matchup
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

            sum_b = df_teams_summary[df_teams_summary['team'] == team_b].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_b].empty) else None
            best_tot_b_val = sum_b['min_total_time'] if sum_b is not None else None
            car_time_b_val = sum_b['avg_race_time'] if sum_b is not None else None
            best_tot_b_txt = f"{best_tot_b_val:.3f} s" if (pd.notna(best_tot_b_val) and best_tot_b_val > 0) else "Pendiente"
            car_time_b_txt = f"{car_time_b_val:.3f} s" if (pd.notna(car_time_b_val) and car_time_b_val > 0) else "Pendiente"

            hist_table_html = f"""<table class="sr-pptx-table" style="font-size: 13px;">
                <thead>
                    <tr>
                        <th style="width: 28%;">Carrera</th>
                        <th style="width: 36%; text-align: center; color: #00F0FF;">{team_badge(team_a, height=22)}</th>
                        <th style="width: 36%; text-align: center; color: #FF8A00;">{team_badge(team_b, height=22)}</th>
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

    # --- TOURNAMENT PROGRESS MONITOR (9 TEAMS x 4 RACES) ---
    render_html(f"""
    <div style="background: rgba(18, 12, 36, 0.7); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 14px; padding: 18px 20px 10px 20px; margin-bottom: 16px;">
        <div style="font-size: 20px; font-weight: 900; color: #FFFFFF; display: flex; align-items: center; gap: 8px;">
            <span>📋</span> Monitor General del Torneo ({len(official_teams)} Equipos)
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
            <td style="font-weight: 700; color: #FFFFFF;">{team_badge(team, height=24)}</td>
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
            width="stretch",
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
            if st.button("💾 Aplicar Cambios de la Grilla y Guardar", width="stretch"):
                commit_runs_df(edited_data, recalculate_totals=True)
                st.toast("✅ Cambios de grilla aplicados con éxito.")
                st.rerun()

        with col_ge_s2:
            if st.button("⚡ Recalcular Tiempos Totales (Reacción + Carrera)", width="stretch"):
                commit_runs_df(edited_data, recalculate_totals=True)
                st.toast("✅ Tiempos totales recalculados.")
                st.rerun()

elif selected_view == "🏆 Ceremonia de Podio":
    # -------------------------------------------------------------------------
    # PANTALLA EXCLUSIVA DE CEREMONIA DE PODIO
    # Sin encabezado superior, sin pestañas, sin indicador de pasos.
    # Máximo espacio y protagonismo para la ceremonia.
    # -------------------------------------------------------------------------
    live_visualizer_sync_watcher()
    curr_step = int(st.session_state.podium_slide_step)

    # Render Current Ceremony Slide (0: Intro -> 1: Logo Splash -> 2: Pop 3ro -> 3: Pop 2do -> 4: Pop 1ro)
    if curr_step == 0:
        render_podium_intro_slide()
    elif curr_step == 1:
        render_podium_logo_splash_slide()
    else:
        render_podium_full_slide(reveal_level=min(3, max(1, curr_step - 1)))

    # Empujar los botones bastante más abajo para que no salgan en la pantalla principal
    st.markdown("<div style='height: 320px;'></div>", unsafe_allow_html=True)

    # Botones de navegación de la ceremonia (en la parte inferior)
    if curr_step == 0:
        _, col_start, _ = st.columns([1, 1.6, 1])
        with col_start:
            if st.button("🚀 Comenzar Ceremonia de Premiación ➡️", width="stretch", type="primary"):
                st.session_state.podium_slide_step = 1
                st.session_state.podium_anim_nonce += 1
                st.rerun()
    else:
        col_nav0, col_nav_logo, col_nav3rd, col_nav2nd, col_nav1st = st.columns([0.8, 0.9, 1.0, 1.0, 1.0])
        with col_nav0:
            if st.button("🔄 Intro", width="stretch"):
                st.session_state.podium_slide_step = 0
                st.session_state.podium_anim_nonce += 1
                st.rerun()
        with col_nav_logo:
            if st.button("🏁 Portada", width="stretch", type="secondary"):
                st.session_state.podium_slide_step = 1
                st.session_state.podium_anim_nonce += 1
                st.rerun()
        with col_nav3rd:
            if st.button("🥉 3er Lugar", width="stretch", type="primary" if curr_step == 1 else "secondary"):
                st.session_state.podium_slide_step = 2
                st.session_state.podium_anim_nonce += 1
                st.rerun()
        with col_nav2nd:
            if st.button("🥈 2do Lugar", width="stretch", type="primary" if curr_step == 2 else "secondary"):
                st.session_state.podium_slide_step = 3
                st.session_state.podium_anim_nonce += 1
                st.rerun()
        with col_nav1st:
            if st.button("🥇 1er Lugar", width="stretch", type="primary" if curr_step == 3 else "secondary"):
                st.session_state.podium_slide_step = 4
                st.session_state.podium_anim_nonce += 1
                st.rerun()

    # Keyboard navigation (ArrowRight / Space / PageDown to advance, ArrowLeft / PageUp to go back)
    next_btn_match = {0: "Comenzar Ceremonia", 1: "3er Lugar", 2: "2do Lugar", 3: "1er Lugar"}.get(curr_step, "")
    prev_btn_match = {1: "Intro", 2: "Portada", 3: "3er Lugar", 4: "2do Lugar"}.get(curr_step, "")
    components.html(f"""
    <script>
    (function() {{
        const pDoc = window.parent.document;
        if (window.parent._srPodiumKeyHandler) {{
            pDoc.removeEventListener('keydown', window.parent._srPodiumKeyHandler);
        }}
        function clickMatchingButton(labelSubstr) {{
            if (!labelSubstr) return;
            const btns = pDoc.querySelectorAll('button');
            for (const btn of btns) {{
                if (btn.innerText && btn.innerText.includes(labelSubstr)) {{
                    btn.click();
                    return;
                }}
            }}
        }}
        window.parent._srPodiumKeyHandler = function(e) {{
            const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
            if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {{
                if ({'true' if next_btn_match else 'false'}) {{
                    e.preventDefault();
                    clickMatchingButton({next_btn_match!r});
                }}
            }} else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {{
                if ({'true' if prev_btn_match else 'false'}) {{
                    e.preventDefault();
                    clickMatchingButton({prev_btn_match!r});
                }}
            }}
        }};
        pDoc.addEventListener('keydown', window.parent._srPodiumKeyHandler);
    }})();
    </script>
    """, height=0)

elif selected_view == "📝 Registro de Jurado":
    # -------------------------------------------------------------------------
    # PANTALLA: REGISTRO DE JURADO (HOJA DE EVALUACIÓN POR EQUIPO)
    # -------------------------------------------------------------------------
    live_visualizer_sync_watcher()

    # Team selector state initialization
    if "judging_summary_team_idx" not in st.session_state:
        st.session_state.judging_summary_team_idx = 0
    if "_pending_jurado_team_idx" in st.session_state:
        st.session_state.judging_summary_team_idx = int(st.session_state.pop("_pending_jurado_team_idx")) % len(official_teams)
        st.session_state["reg_jurado_sel_team"] = official_teams[st.session_state.judging_summary_team_idx]
    if st.session_state.judging_summary_team_idx >= len(official_teams):
        st.session_state.judging_summary_team_idx = 0
    if st.session_state.get("reg_jurado_sel_team") not in official_teams:
        st.session_state["reg_jurado_sel_team"] = official_teams[st.session_state.judging_summary_team_idx]

    if "_pending_jurado_subcats" in st.session_state:
        pending_team, pending_vals = st.session_state.pop("_pending_jurado_subcats")
        for s_k, s_v in pending_vals.items():
            st.session_state[f"rj_{pending_team}_{s_k}"] = float(s_v)

    def _on_jurado_team_select():
        sel = st.session_state.get("reg_jurado_sel_team")
        if sel in official_teams:
            st.session_state.judging_summary_team_idx = official_teams.index(sel)

    # Compact header row: Title + Team selector in a single row to avoid scrolling
    _, col_title_bar, col_tnav_prev, col_tsel, col_tnav_next, _ = st.columns([0.4, 1.9, 0.9, 2.7, 0.9, 0.4], gap="small", vertical_alignment="center")
    with col_title_bar:
        render_html("""
        <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size: 19px; font-weight: 900; font-style: italic; color: #FFFFFF; letter-spacing: 0.3px;">📝 Registro de Jurado</span>
        </div>
        """)
    with col_tnav_prev:
        if st.button("⬅️ Ant.", width="stretch", key="reg_jurado_prev_btn"):
            st.session_state._pending_jurado_team_idx = (st.session_state.judging_summary_team_idx - 1) % len(official_teams)
            st.rerun()
    with col_tsel:
        selected_team = st.selectbox(
            "Seleccionar Equipo:",
            options=official_teams,
            key="reg_jurado_sel_team",
            on_change=_on_jurado_team_select,
            format_func=lambda t: f"#{official_teams.index(t)+1} {t} — {dp.TEAM_TO_SCHOOL_MAP.get(t, '')}",
            label_visibility="collapsed"
        )
        st.session_state.judging_summary_team_idx = official_teams.index(selected_team)
    with col_tnav_next:
        if st.button("Sig. ➡️", width="stretch", key="reg_jurado_next_btn"):
            st.session_state._pending_jurado_team_idx = (st.session_state.judging_summary_team_idx + 1) % len(official_teams)
            st.rerun()

    # Get team data
    team_num = official_teams.index(selected_team) + 1
    school_name = dp.TEAM_TO_SCHOOL_MAP.get(selected_team, "")
    t_mask = st.session_state.custom_scores['team'] == selected_team
    team_row = st.session_state.custom_scores[t_mask].iloc[0]

    cur_subcats = {}
    for sub_k in dp.ALL_SUBCATEGORY_KEYS:
        val = team_row.get(sub_k)
        cur_subcats[sub_k] = float(val) if pd.notna(val) else 0.0

    # Racing points from track
    tt_pts = float(pts_race_map.get(selected_team, 0.0))
    rr_pts = float(pts_tot_map.get(selected_team, 0.0))
    racing_subtotal = float(racing_pts_map.get(selected_team, 0.0))

    # Center the scorecard box
    _, col_scorecard, _ = st.columns([0.4, 6.4, 0.4])

    with col_scorecard:
        new_subcat_inputs = {}
        with st.container():
            render_html('<span class="sr-jurado-compact-marker" style="display:none;"></span>')

            # Loop through categories
            for cat_idx, cat_cfg in enumerate(dp.JUDGING_BREAKDOWN_CONFIG):
                cat_name = cat_cfg["category"]
                cat_off_label = cat_cfg["official_label"]
                cat_max = cat_cfg["max_points"]
                cat_color = cat_cfg.get("color", "#E6007E")

                # Visual divider between sections (skip before the very first category)
                if cat_idx > 0:
                    render_html('<div class="sr-jurado-divider"></div>')

                # Calculate live sum for this category
                cat_current_sum = 0.0
                for sub_item in cat_cfg["subcategories"]:
                    s_key = sub_item["key"]
                    input_key = f"rj_{selected_team}_{s_key}"
                    if input_key in st.session_state:
                        cat_current_sum += float(st.session_state[input_key])
                    else:
                        cat_current_sum += float(cur_subcats.get(s_key, 0.0))

                # Category Header Row (Aligned with subcategory columns)
                c_cat1, c_cat2, c_cat3 = st.columns([5.8, 2.0, 2.2], gap="small", vertical_alignment="center")
                with c_cat1:
                    render_html(f"""
                    <div class="sr-jurado-cat-head">
                        <span class="sr-jurado-cat-name" style="color: {cat_color};">{cat_off_label}</span>
                    </div>
                    """)
                with c_cat2:
                    render_html(f'<div class="sr-jurado-cat-pts">{cat_max} pts</div>')
                with c_cat3:
                    render_html(f'<div class="sr-jurado-cat-badge">{min(float(cat_max), cat_current_sum):.0f} pts</div>')

                # Subcategory rows
                for sub_item in cat_cfg["subcategories"]:
                    s_key = sub_item["key"]
                    s_label = sub_item["label"]
                    s_max = sub_item["max_points"]
                    s_step = sub_item.get("step", 1)

                    c_sub1, c_sub2, c_sub3 = st.columns([5.8, 2.0, 2.2], gap="small", vertical_alignment="center")
                    with c_sub1:
                        render_html(f'<div class="sr-jurado-sub-label">{s_label}</div>')
                    with c_sub2:
                        render_html(f'<div class="sr-jurado-sub-pts">{s_max} pts</div>')
                    with c_sub3:
                        val_input = st.number_input(
                            f"{s_label}",
                            min_value=0.0,
                            max_value=float(s_max),
                            value=float(min(float(s_max), max(0.0, cur_subcats.get(s_key, 0.0)))),
                            step=float(s_step),
                            format="%.0f",
                            label_visibility="collapsed",
                            key=f"rj_{selected_team}_{s_key}"
                        )
                        new_subcat_inputs[s_key] = val_input

            # Visual divider before Racing section
            render_html('<div class="sr-jurado-divider"></div>')

            # Racing Row (Aligned with subcategory columns)
            c_rc1, c_rc2, c_rc3 = st.columns([5.8, 2.0, 2.2], gap="small", vertical_alignment="center")
            with c_rc1:
                render_html("""
                <div class="sr-jurado-racing-head">
                    <span class="sr-jurado-cat-name" style="color: #009FE3;">Racing</span>
                </div>
                """)
            with c_rc2:
                render_html('<div class="sr-jurado-cat-pts" style="color: #009FE3;">220 pts</div>')
            with c_rc3:
                render_html(f'<div class="sr-jurado-sub-val" style="color: #009FE3; font-weight: 900; font-size: 12px; height: 24px;">{racing_subtotal:.1f} pts</div>')

            # Racing sub-rows: Time Trials & Reaction Racing
            c_r1, c_r2, c_r3 = st.columns([5.8, 2.0, 2.2], gap="small", vertical_alignment="center")
            with c_r1:
                render_html('<div class="sr-jurado-sub-label">Time Trials</div>')
            with c_r2:
                render_html('<div class="sr-jurado-sub-pts">110 pts</div>')
            with c_r3:
                render_html(f'<div class="sr-jurado-sub-val">{tt_pts:.1f}</div>')

            c_rx1, c_rx2, c_rx3 = st.columns([5.8, 2.0, 2.2], gap="small", vertical_alignment="center")
            with c_rx1:
                render_html('<div class="sr-jurado-sub-label">Reaction Racing</div>')
            with c_rx2:
                render_html('<div class="sr-jurado-sub-pts">110 pts</div>')
            with c_rx3:
                render_html(f'<div class="sr-jurado-sub-val">{rr_pts:.1f}</div>')

            # TOTAL Row (Gold & Pink accent)
            live_non_racing_sum = sum(new_subcat_inputs.values())
            live_grand_total = round(live_non_racing_sum + racing_subtotal, 1)

            render_html(f"""
            <div class="sr-jurado-total-head">
                <div style="display:flex; align-items:baseline; gap:10px;">
                    <span style="font-size: 13.5px; font-weight: 900; font-style: italic; color: #FFFFFF;">TOTAL COMPETENCIA</span>
                    <span style="font-size: 11px; color: #A0A0B5;">(Jueces: {live_non_racing_sum:.0f} pts | Carrera: {racing_subtotal:.1f} pts)</span>
                </div>
                <div style="font-size: 18px; font-weight: 900; color: #FCBC00;">
                    {live_grand_total:.1f} <span style="font-size: 12px; color: #E0E0E0;">/ 990 pts</span>
                </div>
            </div>
            """)

        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

        # Action Buttons right below the cuadro
        def save_team_scores(team_name: str, subcats_dict: dict):
            mask = st.session_state.custom_scores['team'] == team_name
            if mask.any():
                for k, v in subcats_dict.items():
                    st.session_state.custom_scores.loc[mask, k] = v
                cat_computed = dp.compute_category_totals_from_subcategories(subcats_dict)
                for c_col, c_val in cat_computed.items():
                    st.session_state.custom_scores.loc[mask, c_col] = c_val
                save_and_sync_judge_scores(st.session_state.custom_scores, racing_pts_map)

        col_b1, col_b2, col_b3, col_b4 = st.columns([1.5, 1.6, 1.2, 1.1])
        with col_b1:
            if st.button(f"💾 Guardar {selected_team}", type="primary", width="stretch", key="rj_save_team_btn"):
                save_team_scores(selected_team, new_subcat_inputs)
                st.toast(f"✅ Puntajes de {selected_team} guardados ({live_grand_total:.1f} / 990 pts).")
                st.rerun()
        with col_b2:
            if st.button("💾 Guardar y Siguiente ➡️", width="stretch", key="rj_save_next_btn"):
                save_team_scores(selected_team, new_subcat_inputs)
                st.session_state._pending_jurado_team_idx = (st.session_state.judging_summary_team_idx + 1) % len(official_teams)
                st.toast(f"✅ {selected_team} guardado. Pasando al siguiente equipo...")
                st.rerun()
        with col_b3:
            if st.button("🎲 Datos de Prueba", width="stretch", key="rj_rnd_team_btn", help="Genera puntajes de prueba para este equipo."):
                rnd_sub = dp.generate_random_subcategories_for_team()
                save_team_scores(selected_team, rnd_sub)
                st.session_state._pending_jurado_subcats = (selected_team, rnd_sub)
                st.toast(f"🎲 Datos de prueba generados para {selected_team}.")
                st.rerun()
        with col_b4:
            if st.button("🔄 Reiniciar a 0", width="stretch", key="rj_zero_team_btn", help="Pone las subcategorías de este equipo en 0."):
                zero_sub = {k: 0.0 for k in dp.ALL_SUBCATEGORY_KEYS}
                save_team_scores(selected_team, zero_sub)
                st.session_state._pending_jurado_subcats = (selected_team, zero_sub)
                st.toast(f"🗑️ Subcategorías de {selected_team} en 0.")
                st.rerun()

    # Expandable Summary Table at bottom
    with st.expander("📊 Ver Tabla Resumen de Todos los Equipos y Descargar/Subir Plantilla CSV"):
        matrix_rows = []
        for t_idx, row in st.session_state.custom_scores.iterrows():
            t_n = str(row['team'])
            matrix_rows.append({
                "Pos": int(row.get('rank', t_idx + 1)),
                "Equipo": t_n,
                "Colegio": dp.TEAM_TO_SCHOOL_MAP.get(t_n, ""),
                "Escrutinio (170)": round(float(row.get('Especificaciones y Escrutinio', 0.0)), 1),
                "Diseño (180)": round(float(row.get('Diseño e Ingeniería', 0.0)), 1),
                "Gestión (160)": round(float(row.get('Gestión de Proyecto', 0.0)), 1),
                "Verbal (160)": round(float(row.get('Presentación Verbal', 0.0)), 1),
                "Marca (100)": round(float(row.get('Identidad de Marca', 0.0)), 1),
                "Subtotal Jueces (770)": round(float(row.get('Especificaciones y Escrutinio', 0.0) + row.get('Diseño e Ingeniería', 0.0) + row.get('Gestión de Proyecto', 0.0) + row.get('Presentación Verbal', 0.0) + row.get('Identidad de Marca', 0.0)), 1),
                "Carrera (220)": round(float(row.get('Carrera', 0.0)), 1),
                "TOTAL (990)": round(float(row.get('Total', 0.0)), 1),
            })
        st.dataframe(pd.DataFrame(matrix_rows), hide_index=True, width="stretch")

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            # Build transposed export of current scores (Rows = Rubros, Columns = Teams)
            transposed_export_rows = []
            for cat_cfg in dp.JUDGING_BREAKDOWN_CONFIG:
                for sub in cat_cfg["subcategories"]:
                    sub_key = sub["key"]
                    r_dict = {
                        "Rubro": sub["label"],
                        "Key": sub_key,
                        "Puntos Max": sub["max_points"]
                    }
                    for _, row_sc in st.session_state.custom_scores.iterrows():
                        t_name = str(row_sc["team"])
                        r_dict[t_name] = float(row_sc.get(sub_key, 0.0))
                    transposed_export_rows.append(r_dict)
            exp_transposed_csv = pd.DataFrame(transposed_export_rows).to_csv(index=False).encode("utf-8")

            st.download_button(
                "📥 Descargar CSV de Jurado Actual",
                data=exp_transposed_csv,
                file_name=f"registro_jurado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                width="stretch",
                key="rj_dl_csv",
                help="Descarga el estado actual en formato transpuesta (filas: rubros, columnas: equipos)."
            )
        with col_dl2:
            plantilla_path = "plantilla_registro_jurado.csv"
            if os.path.exists(plantilla_path):
                with open(plantilla_path, "rb") as f:
                    plantilla_bytes = f.read()
                st.download_button(
                    "📄 Descargar Plantilla CSV en Blanco",
                    data=plantilla_bytes,
                    file_name="plantilla_registro_jurado.csv",
                    mime="text/csv",
                    width="stretch",
                    key="rj_dl_plantilla_csv",
                    help="Descarga la plantilla con las filas como rubros y las columnas como equipos lista para rellenar."
                )

else:
    # -------------------------------------------------------------------------
    # PANTALLA DE TIEMPOS Y RESULTADOS EN PISTA (4 TABS)
    # -------------------------------------------------------------------------
    live_visualizer_sync_watcher()
    render_html('<div class="sr-results-screen"></div>' + styles.render_app_header(logo_b64))

    tab1, tab2, tab3, tab4 = st.tabs([
        "⏱️ Tiempos por Equipos",
        "🏁 Carreras",
        "🏎️ Tiempo de Carro",
        "🚀 Tiempo Más Rápido"
    ])

    # ==============================================================================
    # TAB 1: TIEMPOS POR EQUIPOS (Orden Oficial de Equipos, sin subsecciones, sin puntos)
    # ==============================================================================
    with tab1:
        render_html("""
        <div class="sr-tab-header">
            <h2>
                Tiempos por Equipos
            </h2>
            <div class="sr-tab-subtitle">
                Mejor Tiempo Total (Reacción + Carrera) y Tiempo de Carro (Promedio 2do y 3er mejor tiempo) en orden de equipos
            </div>
        </div>
        """)

        # Preserve strict team order from Equipos_Nombres.csv
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
                    <td style="font-weight: 800; color: #FFFFFF; font-size: 16px;">{team_badge(r['team'], height=30)}</td>
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
        <div class="sr-tab-header">
            <h2>
                Carreras
            </h2>
        </div>
        """)

        # Select from the 5 official matchups using Non-typeable Pills
        h2h_matchup_labels = [m['label'] for m in matchups_list]
        if st.session_state.get("slide3_matchup_selector") not in h2h_matchup_labels:
            st.session_state["slide3_matchup_selector"] = h2h_matchup_labels[0]
        selected_h2h_label = st.pills(
            "Seleccionar Enfrentamiento:",
            options=h2h_matchup_labels,
            default=h2h_matchup_labels[0],
            key="slide3_matchup_selector",
            label_visibility="collapsed"
        )
        if not selected_h2h_label or selected_h2h_label not in h2h_matchup_labels:
            selected_h2h_label = h2h_matchup_labels[0]

        current_matchup = next(m for m in matchups_list if m['label'] == selected_h2h_label)
        team_a = current_matchup['team_a']
        team_b = current_matchup['team_b']
        is_solo_h2h = (team_b is None) or bool(current_matchup.get('is_solo', False))

        if is_solo_h2h:
            render_html(f"""
            <div class="sr-h2h-vs-banner">
                <span style="font-size: 24px; font-weight: 900; color: #00F0FF;">{team_badge(team_a, height=36, gap=10)}</span>
                <span style="font-size: 13px; font-weight: 800; color: #FCBC00; background: rgba(252, 188, 0, 0.14); border: 1px solid rgba(252, 188, 0, 0.45); padding: 5px 12px; border-radius: 20px; letter-spacing: 1px;">🏁 CARRERA INDIVIDUAL</span>
            </div>
            """)
        else:
            render_html(f"""
            <div class="sr-h2h-vs-banner">
                <span style="font-size: 24px; font-weight: 900; color: #00F0FF;">{team_badge(team_a, height=36, gap=10)}</span>
                <span style="font-size: 20px; font-weight: 900; color: #FF2A85; margin: 0 6px;">VS</span>
                <span style="font-size: 24px; font-weight: 900; color: #FF8A00;">{team_badge(team_b, height=36, gap=10)}</span>
            </div>
            """)

        # Build the 4-race rows for team_a (and team_b if not solo)
        runs_a = df_runs[df_runs['team'] == team_a].sort_values(by='race_number')
        runs_b = df_runs[df_runs['team'] == team_b].sort_values(by='race_number') if not is_solo_h2h else pd.DataFrame()

        h2h_table_rows = []
        for r_num in range(1, 5):
            match_a = runs_a[runs_a['race_number'] == r_num]
            match_b = runs_b[runs_b['race_number'] == r_num] if not is_solo_h2h else pd.DataFrame()

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
            if not is_solo_h2h and not match_b.empty:
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

        # Extract best times for team_a (and team_b if not solo)
        sum_h2h_a = df_teams_summary[df_teams_summary['team'] == team_a].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_a].empty) else None
        tot_a_val = sum_h2h_a['min_total_time'] if sum_h2h_a is not None else None
        car_a_val = sum_h2h_a['avg_race_time'] if sum_h2h_a is not None else None
        rxn_a_val = sum_h2h_a['min_rxn_time'] if sum_h2h_a is not None else None

        tot_a_txt = f"{tot_a_val:.3f} s" if (pd.notna(tot_a_val) and tot_a_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        car_a_txt = f"{car_a_val:.3f} s" if (pd.notna(car_a_val) and car_a_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
        rxn_a_txt = f"{rxn_a_val:.3f} s" if (pd.notna(rxn_a_val) and rxn_a_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'

        if is_solo_h2h:
            solo_rows_html = []
            for r in h2h_table_rows:
                solo_rows_html.append(f"""<tr>
                    <td style="font-weight: 700; color: #FFFFFF; padding: 12px 16px;">{r['race']}</td>
                    <td style="text-align: center; color: #E6E4F0; padding: 12px;">{r['rxn_a_str']}</td>
                    <td style="text-align: center; color: #E6E4F0; padding: 12px;">{r['race_a_str']}</td>
                    <td style="text-align: center; font-weight: 800; color: #00F0FF; padding: 12px;">{r['tot_a_str']}</td>
                </tr>""")

            h2h_table_html = f"""<table class="sr-pptx-table" style="width: 100%; max-width: 780px; margin: 20px auto 16px auto; border-collapse: separate; border-spacing: 0; border-radius: 12px; overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.15); background: rgba(18, 12, 36, 0.85);">
                <thead>
                    <tr>
                        <th rowspan="2" style="vertical-align: middle; width: 22%; padding: 14px 16px;">Carrera</th>
                        <th colspan="3" style="text-align: center; background: rgba(0, 240, 255, 0.15); color: #00F0FF; padding: 12px; font-size: 16px;">
                            {team_badge(team_a, height=28)}
                        </th>
                    </tr>
                    <tr>
                        <th style="font-size: 13px; text-align: center; padding: 10px;">T. Reacción</th>
                        <th style="font-size: 13px; text-align: center; padding: 10px;">T. Carrera</th>
                        <th style="font-size: 13px; text-align: center; padding: 10px; color: #00F0FF;">T. Total</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(solo_rows_html)}
                </tbody>
                <tfoot>
                    <tr style="background: rgba(255, 255, 255, 0.04); border-top: 2px solid rgba(255, 42, 133, 0.4);">
                        <td style="font-weight: 800; color: #FFFFFF; padding: 12px 16px; font-size: 13px;">⭐ Mejor T. Reacción</td>
                        <td style="text-align: center; font-weight: 800; color: #00F0FF; padding: 12px;">{rxn_a_txt}</td>
                        <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                        <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    </tr>
                    <tr style="background: rgba(255, 255, 255, 0.04);">
                        <td style="font-weight: 800; color: #FFFFFF; padding: 12px 16px; font-size: 13px;">🏎️ Tiempo de Carro</td>
                        <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                        <td style="text-align: center; font-weight: 800; color: #00F0FF; padding: 12px;">{car_a_txt}</td>
                        <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                    </tr>
                    <tr style="background: rgba(255, 42, 133, 0.12); border-top: 1px solid rgba(255, 42, 133, 0.4);">
                        <td style="font-weight: 900; color: #FFFFFF; padding: 12px 16px; font-size: 13px;">🚀 Mejor T. Total</td>
                        <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                        <td style="text-align: center; color: #6C6885; padding: 12px;">---</td>
                        <td style="text-align: center; font-weight: 900; color: #00F0FF; font-size: 15px; padding: 12px;">{tot_a_txt}</td>
                    </tr>
                </tfoot>
            </table>"""
            render_html(h2h_table_html)

            h2h_cards_html = f"""
            <div style="max-width: 540px; margin: 0 auto 8px auto;">
                <div class="sr-h2h-card" style="border: 1px solid rgba(0, 240, 255, 0.4);">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 16px; font-weight: 900; color: #009FE3;">{team_badge(team_a, height=26)}</span>
                        <span style="font-size: 11px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Mejores Tiempos (Individual)</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; text-align: center;">
                        <div style="background: rgba(0, 159, 227, 0.06); border: 1px solid rgba(0, 159, 227, 0.2); border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Mejor Reacción</div>
                            <div style="font-size: 14px; font-weight: 900; color: #FFFFFF; margin-top: 2px;">{rxn_a_txt}</div>
                        </div>
                        <div style="background: rgba(0, 159, 227, 0.06); border: 1px solid rgba(0, 159, 227, 0.2); border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo de Carro</div>
                            <div style="font-size: 14px; font-weight: 900; color: #009FE3; margin-top: 2px;">{car_a_txt}</div>
                        </div>
                        <div style="background: rgba(0, 159, 227, 0.14); border: 1px solid #009FE3; border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #009FE3; font-weight: 800; text-transform: uppercase;">Mejor T. Total</div>
                            <div style="font-size: 15px; font-weight: 900; color: #009FE3; margin-top: 2px;">{tot_a_txt}</div>
                        </div>
                    </div>
                </div>
            </div>
            """
            render_html(h2h_cards_html)
        else:
            sum_h2h_b = df_teams_summary[df_teams_summary['team'] == team_b].iloc[0] if (df_teams_summary is not None and not df_teams_summary[df_teams_summary['team'] == team_b].empty) else None
            tot_b_val = sum_h2h_b['min_total_time'] if sum_h2h_b is not None else None
            car_b_val = sum_h2h_b['avg_race_time'] if sum_h2h_b is not None else None
            rxn_b_val = sum_h2h_b['min_rxn_time'] if sum_h2h_b is not None else None

            tot_b_txt = f"{tot_b_val:.3f} s" if (pd.notna(tot_b_val) and tot_b_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
            car_b_txt = f"{car_b_val:.3f} s" if (pd.notna(car_b_val) and car_b_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'
            rxn_b_txt = f"{rxn_b_val:.3f} s" if (pd.notna(rxn_b_val) and rxn_b_val > 0) else '<span class="sr-pending-badge">⏳ Pendiente</span>'

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
                            {team_badge(team_a, height=28)}
                        </th>
                        <th colspan="3" style="text-align: center; background: rgba(255, 138, 0, 0.15); color: #FF8A00; padding: 12px; font-size: 16px;">
                            {team_badge(team_b, height=28)}
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
            <div class="sr-h2h-cards-grid">
                <div class="sr-h2h-card" style="border: 1px solid rgba(0, 240, 255, 0.4);">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 16px; font-weight: 900; color: #009FE3;">{team_badge(team_a, height=26)}</span>
                        <span style="font-size: 11px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Mejores Tiempos</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; text-align: center;">
                        <div style="background: rgba(0, 159, 227, 0.06); border: 1px solid rgba(0, 159, 227, 0.2); border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Mejor Reacción</div>
                            <div style="font-size: 14px; font-weight: 900; color: #FFFFFF; margin-top: 2px;">{rxn_a_txt}</div>
                        </div>
                        <div style="background: rgba(0, 159, 227, 0.06); border: 1px solid rgba(0, 159, 227, 0.2); border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo de Carro</div>
                            <div style="font-size: 14px; font-weight: 900; color: #009FE3; margin-top: 2px;">{car_a_txt}</div>
                        </div>
                        <div style="background: rgba(0, 159, 227, 0.14); border: 1px solid #009FE3; border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #009FE3; font-weight: 800; text-transform: uppercase;">Mejor T. Total</div>
                            <div style="font-size: 15px; font-weight: 900; color: #009FE3; margin-top: 2px;">{tot_a_txt}</div>
                        </div>
                    </div>
                </div>
                <div class="sr-h2h-card" style="border: 1px solid rgba(237, 109, 5, 0.4);">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 16px; font-weight: 900; color: #ED6D05;">{team_badge(team_b, height=26)}</span>
                        <span style="font-size: 11px; font-weight: 800; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">Mejores Tiempos</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; text-align: center;">
                        <div style="background: rgba(237, 109, 5, 0.06); border: 1px solid rgba(237, 109, 5, 0.2); border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Mejor Reacción</div>
                            <div style="font-size: 14px; font-weight: 900; color: #FFFFFF; margin-top: 2px;">{rxn_b_txt}</div>
                        </div>
                        <div style="background: rgba(237, 109, 5, 0.06); border: 1px solid rgba(237, 109, 5, 0.2); border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #A09EB8; font-weight: 700; text-transform: uppercase;">Tiempo de Carro</div>
                            <div style="font-size: 14px; font-weight: 900; color: #ED6D05; margin-top: 2px;">{car_b_txt}</div>
                        </div>
                        <div style="background: rgba(237, 109, 5, 0.14); border: 1px solid #ED6D05; border-radius: 8px; padding: 7px 6px;">
                            <div style="font-size: 10px; color: #ED6D05; font-weight: 800; text-transform: uppercase;">Mejor T. Total</div>
                            <div style="font-size: 15px; font-weight: 900; color: #ED6D05; margin-top: 2px;">{tot_b_txt}</div>
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
        <div class="sr-tab-header">
            <h2>
                Tiempo de Carro
            </h2>
            <div class="sr-tab-subtitle">
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
                <div style="display: flex; align-items: center; gap: 14px;">
                    <div>{team_logo_only(leader_car_team, height=44, fallback_emoji="🏎️")}</div>
                    <div>
                        <div style="font-size: 11px; font-weight: 800; font-style: italic; color: #009FE3; text-transform: uppercase; letter-spacing: 1.5px;">
                            Mejor Tiempo de Carro de Todos (Líder de la Categoría)
                        </div>
                        <div style="font-size: 24px; font-weight: 900; font-style: italic; color: #FFFFFF; margin-top: 1px;">
                            {leader_car_team}
                        </div>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 11px; font-weight: 700; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">
                        Tiempo Récord de Carro
                    </div>
                    <div style="font-size: 28px; font-weight: 900; color: #009FE3;">
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
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <div class="{rank_class}">{rank}</div>
                        <div>{team_logo_only(team, height=28, fallback_emoji="🏎️")}</div>
                        <div>
                            <div class="sr-team-name">{team}</div>
                            {ind_display}
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <div style="text-align: right;">
                            <div style="font-size: 10px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Tiempo de Carro</div>
                            <div class="sr-time-val">{time_display}</div>
                        </div>
                        <div style="min-width: 145px; text-align: right;">
                            <div style="font-size: 10px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Diferencia vs Líder</div>
                            <div>{delta_display}</div>
                        </div>
                    </div>
                </div>""")

            render_html(f'<div class="sr-broadcast-grid">{"".join(car_broadcast_rows)}</div>')

        # Tab 3 content complete - no comparison charts as requested

    # ==============================================================================
    # TAB 4: TIEMPO MÁS RÁPIDO (Mejor tiempo total, clasificación y diferencia contra el líder, sin Top 3, sin puntos)
    # ==============================================================================
    with tab4:
        render_html("""
        <div class="sr-tab-header">
            <h2>
                Tiempo Más Rápido
            </h2>
            <div class="sr-tab-subtitle">
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
                <div style="display: flex; align-items: center; gap: 14px;">
                    <div>{team_logo_only(leader_tot_team, height=44, fallback_emoji="🚀")}</div>
                    <div>
                        <div style="font-size: 11px; font-weight: 800; font-style: italic; color: #ED6D05; text-transform: uppercase; letter-spacing: 1.5px;">
                            Mejor Tiempo Más Rápido de Todos (Líder de la Categoría)
                        </div>
                        <div style="font-size: 24px; font-weight: 900; font-style: italic; color: #FFFFFF; margin-top: 1px;">
                            {leader_tot_team}
                        </div>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 11px; font-weight: 700; color: #A09EB8; text-transform: uppercase; letter-spacing: 1px;">
                        Tiempo Total Récord
                    </div>
                    <div style="font-size: 28px; font-weight: 900; color: #ED6D05;">
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
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <div class="{rank_class}">{rank}</div>
                        <div>{team_logo_only(team, height=28, fallback_emoji="🏎️")}</div>
                        <div>
                            <div class="sr-team-name">{team}</div>
                            {detail_html}
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <div style="text-align: right;">
                            <div style="font-size: 10px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Mejor Tiempo Total</div>
                            <div class="sr-time-val">{time_display}</div>
                        </div>
                        <div style="min-width: 145px; text-align: right;">
                            <div style="font-size: 10px; color: #A09EB8; text-transform: uppercase; font-weight: 700;">Diferencia vs Líder</div>
                            <div>{delta_display}</div>
                        </div>
                    </div>
                </div>""")

            render_html(f'<div class="sr-broadcast-grid">{"".join(tot_broadcast_rows)}</div>')

        # Tab 4 content complete - no comparison charts as requested
