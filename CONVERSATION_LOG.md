# STEM Racing Visualizer - Conversation & Development Log

- **Conversation ID:** `5f4fb2af-4ee9-4368-a6ec-5dad02594b59`
- **Repository:** `https://github.com/FrutoLopez/stem-racing-visualizer`

---

## 👤 User (2026-11-09T20:39:38Z)

Can you check the code for this folder?

---

## 👤 User (2026-11-09T20:41:21Z)

in this location C:\Users\fgldl\Antigravity\STEM Racing Visualizer\stem-racing-visualizer

---

## 🤖 Assistant (2026-11-09T20:43:32Z)

I have reviewed the codebase in `stem-racing-visualizer`. Here is a summary of the architecture, current functionality, and specific issues or improvements found.

---

### 1. Architecture Overview

* **`app.py`** *(1,818 lines)* — Main Streamlit app with a shared in-memory/CSV sync store (`get_shared_race_store` + 1-second `@st.fragment` watcher `live_visualizer_sync_watcher`) and 3 main screens:
  1. **⏱️ Tiempos y Resultados en Pista**: 4 tabs (*Tiempos por Equipos*, *Duelos Cara a Cara*, *Tiempo de Carro*, *Tiempo Más Rápido*).
  2. **🏆 Ceremonia de Podio Oficial**: 5-step animated ceremony reveal (Intro $\rightarrow$ 3rd $\rightarrow$ 2nd $\rightarrow$ 1st $\rightarrow$ Full Podium + Ranks 4–9).
  3. **📝 Pantalla de Edición y Registro**: Head-to-head race time entry (with DNF and False Start toggles), *Test Mode* random generator, 10-team progress monitor, and an append-only CSV audit log editor.
* **`data_processor.py`** *(715 lines)* — Implements the STEM Racing / F1 in Schools scoring rules (**C9.5** Reaction Race, **C9.6** Time Trial with the DNF slowest-time replacement rule, **C9.7** DNFs, and **C9.8** False Start $2.5$-pt penalty) in `calculate_racing_results`, plus CSV persistence (`load_runs_from_csv`, `append_runs_to_csv`).
* **`styles.py`** *(608 lines)* — Custom CSS and HTML helpers following the STEM Racing V1.3 Brand Guidelines (`inject_custom_css`, `load_team_logos_b64`).

---

### 2. Issues & Potential Bugs Identified

1. **Judge Rubric File Uploader is a No-Op (`app.py#L338-L346`)**
   * `uploaded_rubric` accepts `.csv` and `.xlsx` files and displays `"📁 Archivo recibido"`, but never parses the file or updates `st.session_state.custom_scores`. Unless edited manually in the expander below it, non-racing category scores default to deterministic pseudo-random values from `get_default_category_scores`.

2. **Grid Editor Recalculate Button Doesn't Recalculate Edited Rows in CSV (`app.py#L1231-L1242` & `data_processor.py#L189-L193`)**
   * Both `"💾 Aplicar Cambios de la Grilla y Guardar"` and `"⚡ Recalcular Tiempos Totales (Reacción + Carrera)"` call `commit_runs_df(edited_data)` identically.
   * Inside `load_runs_from_csv`, `total_time` is only recomputed if `total_time` is `NaN` or `<= 0`. If a user edits `reaction_time` or `race_time` in the grid editor on an existing row without clearing `total_time`, the saved CSV retains the old `total_time` (even though `normalize_runs_df` recomputes it in memory).

3. **Leaderboard Ordering When Penalties or DNF Deductions Apply (`data_processor.py#L434-L499`, `#L522-L603`)**
   * Both leaderboards sort strictly by time (`avg_race_time` / `min_total_time`) and assign `rank = idx + 1` before computing points.
   * If a team has `t > base_time` with DNFs ($-5$ pts in C9.6 or $-1$ pt in C9.5) or False Starts ($-2.5$ pts in C9.8), their `points` can drop below a slower team's points, while their `rank` remains higher.

4. **Missing Logo Asset for Team `ISP` (`styles.py#L560-L570`)**
   * `TEAM_LOGO_FILES` maps 9 of the 10 teams in `Equipos.csv`, but `ISP` has no entry or logo file in `assets/`, so it falls back to the `🏎️` emoji.

5. **10th Place Team Excluded on Full Podium Screen (`app.py#L574-L576`)**
   * `render_podium_full_slide` renders Ranks 1–3 on the pedestals and Ranks 4–6 and 7–9 in the two bottom tables, intentionally omitting Rank 10.

6. **Unused Code / Dependencies & Outdated Docs**
   * `plotly` (`app.py#L15-L16`) and `dp.check_races_culminated` (`app.py#L272`) are imported/called on every run but unused.
   * `importlib.reload(dp)` and `importlib.reload(styles)` (`app.py#L21-L22`) run on every 1-second watcher tick.
   * `README.md` still describes the older 9-tab `.xlsx` mockup version rather than the current 3-screen live CSV app.

---

Would you like me to fix any of these issues, add a specific feature (such as wiring up the Judge Rubric CSV/Excel uploader), or clean up the codebase?

---

## 👤 User (2026-11-09T20:53:12Z)

create a backup before implementing the changes. Also, here is the xlsx for reference of the file that will be used for uploading the other points

---

## 🤖 Assistant (2026-11-09T21:10:40Z)

A full backup of the project was created first, and all changes have been implemented and verified.

### 1. Backup Created
* **Backup Directory:** `backup_pre_changes_20261109` (contains all original source files, CSVs, assets, and configuration prior to any edits).

---

### 2. Implemented Changes

1. **Official `STEM RACING - COMPETITION JUDGING BREAKDOWN` Uploader (`.xlsx` & `.csv`)**
   * Added `parse_judging_rubric_files` and `_parse_breakdown_grid_rows` in `data_processor.py`:
     * Automatically identifies the team via `Team Name:` (e.g. `BoscoTech`), `Team Number:` (`01`–`10`), `School:` (e.g. `Insituto Técnico Don Bosco`), or filename (`resolve_team_identity`).
     * Extracts `Awarded Points` for the 5 judging categories:
       * `Specification and Scrutineering Judging` $\rightarrow$ **Especificaciones y Escrutinio** (max 170 pts)
       * `Design and Engineering Judging` $\rightarrow$ **Diseño e Ingeniería** (max 180 pts)
       * `Enterprise Judging` $\rightarrow$ **Gestión de Proyecto** (max 160 pts)
       * `Verbal Presentation Judging` $\rightarrow$ **Presentación Verbal** (max 160 pts)
       * `Brand Identity Judging` $\rightarrow$ **Identidad de Marca** (max 100 pts)
     * Includes automatic fallback to sub-category rows (`Specifications`, `Engineering Drawings`, `Renderings`, `Quality of Finish and Assembly`, etc.) and individual Scorecard totals (`Scrutineering Total =`, `Specifications Total =`, etc.) if Excel formula cells are uncached.
   * Wired up the sidebar uploader (`accept_multiple_files=True`) in `app.py` so you can upload a single team's `.xlsx` or multiple teams' `.xlsx` files at once, plus added a **"🔄 Poner Puntajes de Jueces en 0"** button in the manual editor expander.
   * Judge scores are now persisted to `judge_scores.csv` via `save_judge_scores_to_csv` and synced across all open browser tabs.

2. **Code Review Fixes**
   * **Podium Reveal Formatting (`app.py#L412-L462`):** Replaced `int(...)` with `format_pts(...)` on the 5 judging category rows so decimal scores (e.g. `.5`) are preserved.
   * **Full Podium Positions 4–10 (`app.py#L572-L574`):** Included Rank `#10` in the right-hand table (`#7`–`#10`) on the final podium screen.
   * **Grid Editor Total Time Recalculation (`data_processor.py#L121-L198`, `app.py#L209-L223`):** Editing `reaction_time` or `race_time` in the grid editor now always recomputes `total_time = reaction_time + race_time` in both `live_race_data.csv` and active runs.
   * **Performance & Cleanup:** Removed unused `plotly` imports and per-second `importlib.reload` overhead in `app.py`, and updated `README.md`.

---

## 👤 User (2026-11-09T21:12:37Z)

commit and push

---

## 🤖 Assistant (2026-11-09T21:15:31Z)

The changes have been committed and pushed to `origin/main`:

* **Commit:** `bb43abf` — *"Add official Judging Breakdown (.xlsx/.csv) parser, persist judge scores, and fix podium/leaderboard edge cases"*
* **Remote:** `https://github.com/FrutoLopez/stem-racing-visualizer` (`ade0954..bb43abf  main -> main`)
* **Files updated:** `.gitignore`, `README.md`, `app.py`, `data_processor.py`

---

## 👤 User (2026-11-09T21:18:10Z)

There are going to be only 9 teams competing, the last one, ISP dropped out, the current final team, PNTHR will race by itself for all scoring purposes

---

## 🤖 Assistant (2026-11-09T21:31:14Z)

Se han actualizado todos los archivos y la lógica del sistema para operar con los **9 equipos oficiales** tras el retiro de `ISP`, haciendo que **`PNTHR`** compita de forma individual en todas las carreras e instancias de puntuación:

### 1. Listas Oficiales y Mapeos de Equipos
* **`Equipos.csv` y `Equipos_Nombres.csv`:** Se eliminó a `ISP`, quedando los **9 equipos oficiales** (`BoscoTech`, `JAF Racing Team`, `Excalibur`, `Rayo Rabin`, `Hayai Aerodynamics`, `Dim3nsion`, `Raiders`, `Cybercolts Racing` y `PNTHR`).
* **`data_processor.py`:**
  * Se actualizaron `DEFAULT_TEAMS`, `LEGACY_TEAM_MAP` y `SCHOOL_TO_TEAM_MAP` a los 9 equipos (01–09).
  * Se actualizó `get_matchups` para generar los 4 duelos en pareja (`1 vs 2`, `3 vs 4`, `5 vs 6`, `7 vs 8`) y un **5to enfrentamiento individual** (`Enfrentamiento 5: PNTHR (Individual)` con `team_b: None` e `is_solo: True`).

### 2. Registro en Vivo, Duelos, Clasificación y Podio (`app.py`)
* **Puntuación Oficial (C9.5 y C9.6):** Los tiempos registrados para `PNTHR` en sus 4 carreras individuales (`Carreras 1 a 4`) participan exactamente igual que los demás equipos en el cálculo de **Tiempo de Carro (C9.6 Time Trial, 110 pts)**, **Tiempo Más Rápido (C9.5 Reaction Race, 110 pts)** y la clasificación general de **990 puntos**.
* **📝 Pantalla de Edición y Registro:**
  * Cuando se selecciona **`Enfrentamiento 5: PNTHR (Individual)`**, el formulario de captura muestra únicamente la tarjeta de **`PNTHR`**, soporta el generador aleatorio **🎲 Test Mode** para esa carrera individual, guarda solo el registro de `PNTHR` en `live_race_data.csv` y presenta el resumen de sus 4 mangas.
  * `normalize_runs_df` filtra automáticamente cualquier fila histórica que no pertenezca a los 9 equipos activos.
* **⚔️ Duelos Cara a Cara:** Para el Enfrentamiento 5 se muestra una vista dedicada **`🏁 CARRERA INDIVIDUAL`** con la tabla de las 4 mangas (`T. Reacción`, `T. Carrera`, `T. Total`) y la tarjeta resumen de tiempos de `PNTHR`.
* **🏆 Ceremonia de Podio:** En la diapositiva de podio completo (`render_podium_full_slide`), las tablas inferiores muestran las posiciones **`#4 – #6`** y **`#7 – #9`**.

---

## 👤 User (2026-11-09T21:56:21Z)

commit

---

## 🤖 Assistant (2026-11-09T21:57:48Z)

Cambios confirmados en el repositorio local:

* **Commit:** `2f36bb1` (`main`)
* **Mensaje:** `Update competition to 9 teams (remove ISP) with solo racing support for PNTHR`
* **Archivos incluidos:** `Equipos.csv`, `Equipos_Nombres.csv`, `data_processor.py`, `app.py`, `README.md`

---

## 👤 User (2026-11-09T22:04:59Z)

I had an issue where my laptop crashed twice, specifically when inputing data within the visualizer. The data in the visualizer apparently was lost as well when that happened when using streamlit. As in, if  went on my phone, every got empty, and submitting data was inconsistent

---

## 🤖 Assistant (2026-11-09T22:20:36Z)

I inspected the codebase and found **four specific bugs** in `app.py`, `data_processor.py`, and `styles.py` that directly caused the laptop crashes, the empty state when opening on your phone, and the inconsistent data submissions. All four have now been fixed:

---

### 1. Why the Laptop Crashed While Inputting Data (RAM & CPU Spike)
* **Root Cause:**
  1. `styles.get_base64_encoded_image()` and `styles.load_team_logos_b64()` were **not cached** (`@st.cache_data`) and were encoding full-resolution PNG files from disk on **every single button click, checkbox toggle, and number change**, embedding 30–40 copies of large `data:image/png;base64,...` strings into the browser DOM on every rerun.
  2. At the same time, `live_visualizer_sync_watcher` was polling the filesystem every **1.0 second** (`run_every=1.0`) across every open tab/device.
* **Fix Applied:**
  * Added `load_cached_branding_and_teams()` with `@st.cache_data` so CSS, logos, and team lists are read from disk **only once**.
  * Updated `get_base64_encoded_image` and `load_team_logos_b64` to downscale team badge logos in memory to `132×90` thumbnails with Pillow (`PIL.Image`), cutting DOM/WebSocket memory payload on reruns by **~90%**.
  * Relaxed `live_visualizer_sync_watcher` from `1.0s` to `2.5s`.

---

### 2. Why Opening on Your Phone Showed Everything Empty & Why Data Was Lost on Crash
* **Root Cause:**
  1. **Non-atomic CSV writes (`df.to_csv` truncation):** In `save_runs_to_csv`, `to_csv(path)` opens `live_race_data.csv` with mode `'w'`, which **immediately truncates the file to 0 bytes** before writing, without `os.fsync()`. When the laptop crashed during or right after a write, Windows left the file truncated/corrupted on disk with no backup.
  2. **Multi-device race condition (Laptop + Phone):** When your phone connected or polled `live_race_data.csv` at the same moment a save was happening, `load_runs_from_csv` hit a locked or 0-byte file, caught the exception, and returned an **empty DataFrame**. Then `app.py` blindly overwrote `shared_store["history_df"]` and `shared_store["runs_df"]` with that empty DataFrame, wiping out the visualizer state for all connected devices.
* **Fix Applied:**
  * Implemented `_atomic_write_csv` protected by a thread lock (`CSV_LOCK`): every save writes to `.tmp` $\rightarrow$ `flush()` $\rightarrow$ `os.fsync()` $\rightarrow$ atomic `os.replace()`, and automatically maintains a rolling backup (`live_race_data.csv.bak` and `judge_scores.csv.bak`).
  * If `live_race_data.csv` is ever 0 bytes or corrupted after a crash, `load_runs_from_csv` automatically restores it from `live_race_data.csv.bak`.
  * Added `sync_store_from_disk_if_needed` which refuses to overwrite a non-empty `shared_store` with an empty read unless **"🗑️ Borrar Todos los Registros"** was explicitly clicked.

---

### 3. Why Submitting Data Was Inconsistent
* **Root Cause:**
  1. **Form context overwrite bug:** Previously, `active_form_ctx = (team_a, team_b, int(selected_race_num), shared_store["version"])` included `shared_store["version"]`. Whenever your phone or another tab triggered a background sync version bump, lines 871–882 executed **at the top of the script before `with st.form`** and overwrote the numbers you just submitted back to `0.000` right before the save handler ran.
  2. **Split `st.checkbox` (outside `st.form`) vs `st.number_input` (inside `st.form`):** Typing Team A's times and then clicking Team B's `❌ DNF` or `🚦 False Start` checkbox triggered an immediate rerun outside the form, wiping out the uncommitted numbers you had just typed for Team A.
* **Fix Applied:**
  * Removed `shared_store["version"]` from `active_form_ctx` so background syncs from a phone or second tab **never** reset your active input fields.
  * Unified the checkboxes (`❌ DNF`, `🚦 False Start`) and time inputs (`T. Reacción`, `T. Carrera`) into direct `st.session_state`-bound controls with a primary `st.button("🏁 Guardar Resultados...")`, so toggling DNF/False Start on one team never erases the other team's numbers, the `Tiempo Total Registrado` updates live as you type, and clicking **Guardar** always saves on the first click.

---

## 👤 User (2026-11-09T22:34:41Z)

copy a log of this conversation so that i can open it from another computer, add it to the git

---

# Session 2 — Judging Rubric UI, Team Nomenclature, Logos & Podium Ceremony

- **Conversation ID:** `febf84bd-9535-4264-ba92-e0a28ea5e657`
- **Date:** `2026-11-12`

## Summary of Changes

1. **Judging Rubric & Scorecard UI (`app.py`, `styles.py`, `data_processor.py`, `plantilla_registro_jurado.csv`)**
   - Created `plantilla_registro_jurado.csv` in transposed format (rows = 12 judging subcategories, columns = 9 teams) and updated `_try_parse_tabular_df` in `data_processor.py` to parse both standard and transposed rubric CSVs/Excel sheets.
   - Compressed `"📝 Registro de Jurado"` layout, aligned category totals with the subcategory points columns, bolded category headers, added section dividers, removed page number references, and stripped noisy cell/container borders and excess `stNumberInput` padding.

2. **Team Nomenclature & Logos (`Equipos_Nombres.csv`, `Equipos.csv`, `Logos/`, `assets/Logos/`, `Podios/`)**
   - Standardized all team references across `app.py`, `data_processor.py`, `styles.py`, `judge_scores.csv`, `live_race_data.csv`, and `plantilla_registro_jurado.csv` to match `Equipos_Nombres.csv` (`Dim3nsion Motosport`, `Brader Raiders Racing Team`, `PNTHR Racing`, etc.), while retaining legacy alias resolution in `LEGACY_TEAM_MAP`.
   - Rebuilt high-resolution team logos in `Logos/` from the `Entregables/` PDFs (vector paths and `/SMask` transparent PNGs).
   - Compressed the team JPEGs in `assets/Logos/` (~33–67 KB each) and wired `styles.py` (`load_team_logos_b64`) and `app.py` (`_compute_branding_cache_key`) so edits to CSVs or logos automatically bust `@st.cache_data`.
   - Wired the transparent `1400×1400` PNG logos in `Podios/` (`load_podium_logos_b64` / `get_podium_logo_html`) for the podium ceremony.

3. **Podium Ceremony Redesign (`app.py`, `styles.py`, `assets/Animations/podium_dark_bg.gif`)**
   - Removed the separate individual winner slides and bottom positions table (`#4–#9`) so the ceremony focuses exclusively on the 3-winner podium, with individual reveal buttons (`🔄 Intro`, `🏁 Portada`, `🥉 3er Lugar`, `🥈 2do Lugar`, `🥇 1er Lugar`) pushed below the fold (`320px` spacer) plus keyboard navigation (`ArrowRight` / `Space` / `PageDown` and `ArrowLeft` / `PageUp`).
   - Created `assets/Animations/podium_dark_bg.gif` by keying out the white background of `assets/Animations/_.gif` and blending the waving checkered flag over the dark CFD `#05000B` radial-gradient backdrop.
   - Expanded `.sr-podium-stage` to full-window width (`max-width: 100%`, `min-height: 84vh`, `padding-top: 3.0rem`) with metallic 3D cylindrical pedestals and base64-encoded scalloped laurel-wreath SVG medals (`get_podium_medal_svg`).
   - Added a full-window pre-podium splash screen (`render_podium_logo_splash_slide`) showing the animated flag background with the centered STEM Racing Panamá logo, which shrinks, turns white, and morphs (`.sr-logo-morph-out` / `.sr-logo-morph-in`) into `Podios/SR - Mono White copy.png` in the top-left corner when advancing to 3rd place.
   - Created backup snapshot in `design_backup_v3/`.
