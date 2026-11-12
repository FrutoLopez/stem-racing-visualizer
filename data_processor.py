"""Data processor and calculation engine for STEM Racing Results.
Computes official timing metrics, head-to-head pairings, and official scoring systems according to:
- C9.5: Reaction race scoring (Fastest total race time, Base Time 120%, DNF deduction if 5 pts)
- C9.6: Time Trial race scoring (2nd & 3rd best car race time avg, DNF replacement rule, Base Time 115%, DNF deduction if 20 pts)
- C9.7: DNF race results
- C9.8: False starts (Jump starts, 2.5-point penalty and race forfeit)
- Official STEM Racing Competition Judging Breakdown (.xlsx / .csv) parser for the 5 non-racing categories.
"""

import csv
import os
import re
import shutil
import threading
from datetime import datetime
from io import BytesIO, StringIO
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np
import openpyxl

CSV_LOCK = threading.RLock()


def _atomic_write_csv(df: pd.DataFrame, path: str, create_backup: bool = True) -> None:
    """
    Write a DataFrame to CSV atomically using a temporary file + flush + os.fsync + os.replace.
    Prevents data loss or 0-byte truncation if the OS crashes or another device reads concurrently.
    Also maintains a `.bak` backup copy when `create_backup=True` and `df` is non-empty.
    """
    tmp_path = f"{path}.tmp"
    bak_path = f"{path}.bak"
    with CSV_LOCK:
        with open(tmp_path, "w", encoding="utf-8", newline="") as f:
            df.to_csv(f, index=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
        if create_backup and not df.empty:
            try:
                shutil.copy2(path, bak_path)
            except OSError:
                pass

DEFAULT_CATEGORIES = [
    "Identidad de Marca",
    "Presentación Verbal",
    "Carrera",
    "Especificaciones y Escrutinio",
    "Diseño e Ingeniería",
    "Gestión de Proyecto"
]

NON_RACING_CATEGORIES = [
    "Identidad de Marca",
    "Presentación Verbal",
    "Especificaciones y Escrutinio",
    "Diseño e Ingeniería",
    "Gestión de Proyecto"
]

DEFAULT_TEAMS = [
    "BoscoTech",
    "JAF Racing Team",
    "Excalibur",
    "Rayo Rabin",
    "Hayai Aerodynamics",
    "Dim3nsion",
    "Raiders",
    "Cybercolts Racing",
    "PNTHR"
]

LEGACY_TEAM_MAP = {
    "ITDB": "BoscoTech",
    "St. George": "JAF Racing Team",
    "Oxford": "Excalibur",
    "Isaac Rabin": "Rayo Rabin",
    "Panamerican": "Hayai Aerodynamics",
    "Sun Yat Sen": "Dim3nsion",
    "Brader": "Raiders",
    "TJS": "Cybercolts Racing",
    "Casco": "PNTHR",
    "ISP": "ISP",
}

SCHOOL_TO_TEAM_MAP = {
    "don bosco": "BoscoTech",
    "itdb": "BoscoTech",
    "st. george": "JAF Racing Team",
    "saint george": "JAF Racing Team",
    "oxford": "Excalibur",
    "isaac rabin": "Rayo Rabin",
    "panamerican": "Hayai Aerodynamics",
    "sun yat sen": "Dim3nsion",
    "chino panameño": "Dim3nsion",
    "brader": "Raiders",
    "thomas jefferson": "Cybercolts Racing",
    "tjs": "Cybercolts Racing",
    "casco": "PNTHR",
    "isp": "ISP",
    "international school of panama": "ISP",
}

TEAM_TO_SCHOOL_MAP = {
    "BoscoTech": "Instituto Técnico Don Bosco (ITDB)",
    "JAF Racing Team": "St. George's International School",
    "Excalibur": "The Oxford School",
    "Rayo Rabin": "Colegio Isaac Rabin",
    "Hayai Aerodynamics": "Panamerican School",
    "Dim3nsion": "Centro Cultural Chino Panameño (Sun Yat Sen)",
    "Raiders": "Colegio Brader",
    "Cybercolts Racing": "Thomas Jefferson School (TJS)",
    "PNTHR": "The Casco School",
    "ISP": "International School of Panama (ISP)",
}


def load_teams_from_csv(path: str = "Equipos.csv") -> List[str]:
    """
    Load official team names from CSV preserving their exact defined order.
    Falling back to DEFAULT_TEAMS if file cannot be read.
    """
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            if not df.empty:
                teams = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
                teams = [t for t in teams if t]
                if teams:
                    return teams
        except Exception:
            pass
    return DEFAULT_TEAMS.copy()


def get_matchups(teams: List[str]) -> List[Dict[str, Any]]:
    """
    Build the official head-to-head pairings based on team order:
    1 vs 2, 3 vs 4, 5 vs 6, 7 vs 8, and if an odd number of teams (9),
    team 9 (PNTHR) races solo in Enfrentamiento 5 for all scoring purposes.
    """
    matchups = []
    n = len(teams)
    pair_count = n // 2
    for i in range(pair_count):
        t_a = teams[2 * i]
        t_b = teams[2 * i + 1]
        matchups.append({
            "id": i + 1,
            "label": f"Enfrentamiento {i + 1}: {t_a} vs {t_b}",
            "team_a": t_a,
            "team_b": t_b,
            "is_solo": False
        })
    if n % 2 == 1:
        t_solo = teams[-1]
        matchups.append({
            "id": pair_count + 1,
            "label": f"Enfrentamiento {pair_count + 1}: {t_solo} (Individual)",
            "team_a": t_solo,
            "team_b": None,
            "is_solo": True
        })
    return matchups


CSV_SCHEMA = ['id', 'timestamp', 'team', 'race_number', 'reaction_time', 'race_time', 'total_time', 'is_dnf', 'is_false_start']


def load_runs_from_csv(file_source: Any, recalculate_totals: bool = False) -> pd.DataFrame:
    """
    Load runs from a CSV file (filepath, BytesIO, DataFrame, or Streamlit UploadedFile).
    Preserves the full append-only CSV log including general `id` and `timestamp`.
    Automatically recovers from `filepath.bak` if the main CSV was truncated/corrupted by an OS crash.
    """
    cols_schema = CSV_SCHEMA
    df = None
    with CSV_LOCK:
        try:
            if isinstance(file_source, pd.DataFrame):
                df = file_source.copy()
            elif isinstance(file_source, str):
                bak_path = f"{file_source}.bak"
                if os.path.exists(file_source) and os.path.getsize(file_source) > 0:
                    try:
                        df = pd.read_csv(file_source)
                    except Exception:
                        df = None
                if (df is None or df.empty) and os.path.exists(bak_path) and os.path.getsize(bak_path) > 0:
                    try:
                        df = pd.read_csv(bak_path)
                        if df is not None and not df.empty:
                            shutil.copy2(bak_path, file_source)
                    except Exception:
                        df = None
                if df is None:
                    return pd.DataFrame(columns=cols_schema)
            elif isinstance(file_source, BytesIO):
                df = pd.read_csv(file_source)
            else:
                content = file_source.getvalue() if hasattr(file_source, 'getvalue') else file_source.read()
                if not content:
                    return pd.DataFrame(columns=cols_schema)
                df = pd.read_csv(BytesIO(content))
        except Exception:
            return pd.DataFrame(columns=cols_schema)

    if df.empty:
        return pd.DataFrame(columns=cols_schema)

    try:
        # Standardize column names
        col_map = {}
        for col in df.columns:
            c_low = str(col).lower().strip()
            if c_low == 'id' or c_low == 'record_id':
                col_map[col] = 'id'
            elif 'time' in c_low and ('stamp' in c_low or 'fecha' in c_low or 'hora' in c_low) or c_low == 'timestamp':
                col_map[col] = 'timestamp'
            elif 'false' in c_low or 'fs' in c_low or 'salida' in c_low or 'jump' in c_low:
                col_map[col] = 'is_false_start'
            elif 'dnf' in c_low:
                col_map[col] = 'is_dnf'
            elif 'manga' in c_low or 'carr' in c_low and ('num' in c_low or '#' in c_low) or 'heat' in c_low or 'race_num' in c_low:
                col_map[col] = 'race_number'
            elif 'team' in c_low or 'equipo' in c_low:
                col_map[col] = 'team'
            elif 'reacc' in c_low or 'rxn' in c_low or 'reaction' in c_low:
                col_map[col] = 'reaction_time'
            elif 'tot' in c_low:
                col_map[col] = 'total_time'
            elif 'pista' in c_low or 'carrera' in c_low or 'race' in c_low:
                col_map[col] = 'race_time'

        df = df.rename(columns=col_map)

        if 'team' not in df.columns:
            df['team'] = [f"Team {i+1}" for i in range(len(df))]
        if 'reaction_time' not in df.columns:
            df['reaction_time'] = 0.0
        if 'race_time' not in df.columns:
            df['race_time'] = 0.0
        if 'total_time' not in df.columns:
            df['total_time'] = 0.0

        # Parse DNF
        if 'is_dnf' not in df.columns:
            df['is_dnf'] = (
                df['race_time'].astype(str).str.upper().str.contains('DNF') |
                df['total_time'].astype(str).str.upper().str.contains('DNF')
            )
        else:
            df['is_dnf'] = df['is_dnf'].astype(str).str.strip().str.lower().isin(['true', '1', 'yes', 'si', 'dnf'])

        # Parse False Start
        if 'is_false_start' not in df.columns:
            df['is_false_start'] = (
                df['race_time'].astype(str).str.upper().str.contains('FS') |
                df['total_time'].astype(str).str.upper().str.contains('FS') |
                df['race_time'].astype(str).str.upper().str.contains('FALSE') |
                df['total_time'].astype(str).str.upper().str.contains('FALSE')
            )
        else:
            df['is_false_start'] = df['is_false_start'].astype(str).str.strip().str.lower().isin(['true', '1', 'yes', 'si', 'fs', 'false start'])

        df['team'] = df['team'].astype(str).str.strip().replace(LEGACY_TEAM_MAP)
        df = df[df['team'] != ''].reset_index(drop=True)

        # Clean numeric fields
        df['reaction_time'] = pd.to_numeric(df['reaction_time'], errors='coerce').fillna(0.0)
        df['race_time'] = pd.to_numeric(df['race_time'], errors='coerce')
        df['total_time'] = pd.to_numeric(df['total_time'], errors='coerce')

        # If marked DNF or False Start, force NaN for race_time & total_time (forfeited)
        invalid_mask = df['is_dnf'] | df['is_false_start']
        df.loc[invalid_mask, 'race_time'] = np.nan
        df.loc[invalid_mask, 'total_time'] = np.nan

        # For valid runs, compute total_time = reaction_time + race_time
        valid_mask = ~invalid_mask
        df.loc[valid_mask & df['race_time'].isna(), 'race_time'] = 0.0
        if recalculate_totals:
            need_total_mask = valid_mask
        else:
            need_total_mask = valid_mask & (
                df['total_time'].isna() |
                (df['total_time'] <= 0) |
                ((df['reaction_time'] + df['race_time']) > 0)
            )
        if need_total_mask.any():
            df.loc[need_total_mask, 'total_time'] = (
                df.loc[need_total_mask, 'reaction_time'] + df.loc[need_total_mask, 'race_time']
            ).round(4)

        if 'race_number' not in df.columns or df['race_number'].isnull().all():
            df['race_number'] = df.groupby('team').cumcount() + 1
        else:
            df['race_number'] = pd.to_numeric(df['race_number'], errors='coerce').fillna(1).astype(int)

        # Ensure general sequential `id` and `timestamp` columns exist
        if 'id' not in df.columns or df['id'].isnull().all():
            df['id'] = range(1, len(df) + 1)
        else:
            df['id'] = pd.to_numeric(df['id'], errors='coerce')
            if df['id'].isna().any():
                df['id'] = range(1, len(df) + 1)
            else:
                df['id'] = df['id'].astype(int)

        if 'timestamp' not in df.columns or df['timestamp'].isnull().all():
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df['timestamp'] = now_str
        else:
            df['timestamp'] = df['timestamp'].fillna(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).astype(str)

        return df[cols_schema].reset_index(drop=True)
    except Exception as e:
        print(f"Error in load_runs_from_csv: {e}")
        return pd.DataFrame(columns=cols_schema)


def save_runs_to_csv(df_runs: pd.DataFrame, path: str = "live_race_data.csv", recalculate_totals: bool = False) -> None:
    """Save runs dataframe (with id and timestamp) to CSV file atomically with backup."""
    cols = CSV_SCHEMA
    with CSV_LOCK:
        if df_runs is None or df_runs.empty:
            empty_df = pd.DataFrame(columns=cols)
            _atomic_write_csv(empty_df, path, create_backup=False)
            return
        out = load_runs_from_csv(df_runs, recalculate_totals=recalculate_totals)
        available_cols = [c for c in cols if c in out.columns]
        _atomic_write_csv(out[available_cols], path, create_backup=True)


def append_runs_to_csv(new_rows: List[Dict[str, Any]], path: str = "live_race_data.csv") -> pd.DataFrame:
    """
    Append new or edited race records to the CSV file with a general sequential `id`
    and current `timestamp`, keeping all historical entries in the CSV audit log.
    Protected by CSV_LOCK and atomic writes so concurrent clients never lose records.
    """
    with CSV_LOCK:
        hist_df = load_runs_from_csv(path)
        next_id = (int(hist_df['id'].max()) + 1) if (not hist_df.empty and 'id' in hist_df.columns and hist_df['id'].notna().any()) else 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        prepared = []
        for row in new_rows:
            item = dict(row)
            item['id'] = next_id
            item['timestamp'] = now_str
            next_id += 1
            prepared.append(item)

        if prepared:
            new_df = pd.DataFrame(prepared)[CSV_SCHEMA]
            hist_df = pd.concat([hist_df, new_df], ignore_index=True) if not hist_df.empty else new_df
            save_runs_to_csv(hist_df, path)
        return hist_df


def clear_runs_csv(path: str = "live_race_data.csv") -> pd.DataFrame:
    """Clear all records from the CSV file and its backup to start fresh from 0."""
    with CSV_LOCK:
        empty_df = pd.DataFrame(columns=CSV_SCHEMA)
        _atomic_write_csv(empty_df, path, create_backup=False)
        bak_path = f"{path}.bak"
        if os.path.exists(bak_path):
            try:
                _atomic_write_csv(empty_df, bak_path, create_backup=False)
            except OSError:
                pass
        return empty_df


def check_races_culminated(df_runs: pd.DataFrame, all_teams: Optional[List[str]] = None) -> Tuple[bool, int, int]:
    """
    Verifica si todas las carreras oficiales de todos los equipos han culminado.
    Cada equipo oficial debe completar sus 4 carreras (válidas, DNF o Salida en Falso).
    Retorna (está_culminado, carreras_completadas, total_esperadas).
    """
    if all_teams is None or len(all_teams) == 0:
        return False, 0, 0
    total_expected = len(all_teams) * 4
    if df_runs is None or df_runs.empty:
        return False, 0, total_expected

    valid_runs = df_runs.dropna(subset=['team', 'race_number']).copy()
    valid_runs['race_number'] = pd.to_numeric(valid_runs['race_number'], errors='coerce')
    valid_runs = valid_runs[valid_runs['race_number'].isin([1, 2, 3, 4])]
    distinct_runs = valid_runs.drop_duplicates(subset=['team', 'race_number'])
    official_runs = distinct_runs[distinct_runs['team'].isin(all_teams)]
    completed_count = len(official_runs)

    teams_with_4 = sum(1 for t in all_teams if len(official_runs[official_runs['team'] == t]) >= 4)
    is_culminated = (teams_with_4 == len(all_teams)) and (len(all_teams) > 0)
    return is_culminated, completed_count, total_expected


def calculate_racing_results(
    df_runs: pd.DataFrame,
    all_teams: Optional[List[str]] = None,
    award_points: bool = True
) -> Dict[str, Any]:
    """
    Performs official STEM Racing scoring calculations according to official rules:

    1. C9.6 Time Trial race scoring (Tiempo de Carro):
       - Four car race times considered. Team's 2nd and 3rd best car race times averaged.
       - Sub-rule: If after discarding a team's fastest time there remains less than 2 times
         from races finished due to DNF/forfeit, the slowest time recorded is again input to the
         average equation until there are a total of 4 times to average.
       - Points:
         * 1st: 110 pts, 2nd: 105 pts, 3rd: 100 pts.
         * Base Time = 115% of 3rd fastest avg.
         * 4th to slowest: 20 + (80 / (BaseTime - 3rd_avg)) * (BaseTime - teams_avg)
         * Any team with avg slower than Base Time scores 20 points.
         * To discriminate between teams scoring 20 pts: deduction of 5 pts for each DNF.

    2. C9.5 Reaction race scoring (Tiempo Más Rápido):
       - Four total race times considered. The fastest time is used.
       - Points:
         * 1st: 110 pts, 2nd: 105 pts, 3rd: 100 pts.
         * Base Time = 120% of 3rd fastest total race time.
         * 4th to slowest: 5 + (95 / (BaseTime - 1st_fastest)) * (BaseTime - teams_fastest)
         * Any team with best total slower than Base Time scores 5 points.
         * To discriminate between teams scoring 5 pts: deduction of 1 pt for each DNF.

    3. C9.8 False starts:
       - False start occurs when trigger pressed before 5 start gate lights extinguish.
       - C9.8.2: All reaction false starts incur a 2.5-point penalty and forfeit that race.
    """
    if all_teams is None:
        if df_runs is not None and not df_runs.empty:
            all_teams = df_runs['team'].dropna().unique().tolist()
        else:
            all_teams = DEFAULT_TEAMS.copy()

    teams_data = []

    for team in all_teams:
        if df_runs is not None and not df_runs.empty:
            team_runs = df_runs[df_runs['team'] == team].sort_values(by='race_number')
        else:
            team_runs = pd.DataFrame()

        runs_count = len(team_runs)
        dnf_count = int(team_runs['is_dnf'].sum()) if runs_count > 0 and 'is_dnf' in team_runs.columns else 0
        fs_count = int(team_runs['is_false_start'].sum()) if runs_count > 0 and 'is_false_start' in team_runs.columns else 0

        # Filter valid finished runs (neither DNF nor False Start, with positive race_time)
        if runs_count > 0:
            is_dnf_series = team_runs['is_dnf'] if 'is_dnf' in team_runs.columns else pd.Series([False] * runs_count)
            is_fs_series = team_runs['is_false_start'] if 'is_false_start' in team_runs.columns else pd.Series([False] * runs_count)
            valid_mask = (~is_dnf_series) & (~is_fs_series) & (team_runs['race_time'].notna()) & (team_runs['race_time'] > 0)
            valid_runs = team_runs[valid_mask]
            valid_count = len(valid_runs)
            valid_races = valid_runs['race_time'].tolist() if valid_count > 0 else []
            valid_totals = valid_runs['total_time'].tolist() if valid_count > 0 else []
            valid_rxns = valid_runs['reaction_time'].tolist() if valid_count > 0 else []
        else:
            valid_count = 0
            valid_races = []
            valid_totals = []
            valid_rxns = []

        sorted_valid_races = sorted(valid_races)
        sorted_valid_totals = sorted(valid_totals)

        # ----------------------------------------------------------------------
        # C9.6 Tiempo de Carro calculation with DNF replacement rule
        # ----------------------------------------------------------------------
        if valid_count >= 3:
            avg_race_time = (sorted_valid_races[1] + sorted_valid_races[2]) / 2.0
        elif valid_count == 2:
            avg_race_time = sorted_valid_races[1]
        elif valid_count == 1:
            avg_race_time = sorted_valid_races[0]
        else:
            avg_race_time = None

        # ----------------------------------------------------------------------
        # C9.5 Tiempo Más Rápido (Fastest total race time among finished valid runs)
        # ----------------------------------------------------------------------
        if valid_count > 0 and sorted_valid_totals:
            min_total_time = sorted_valid_totals[0]
        else:
            min_total_time = None

        min_race_time = min(valid_races) if valid_races else None
        min_rxn_time = min(valid_rxns) if valid_rxns else None

        teams_data.append({
            'team': team,
            'runs_count': runs_count,
            'valid_count': valid_count,
            'dnf_count': dnf_count,
            'fs_count': fs_count,
            'avg_race_time': avg_race_time,
            'min_total_time': min_total_time,
            'min_race_time': min_race_time,
            'min_rxn_time': min_rxn_time,
            'sorted_valid_races': sorted_valid_races,
            'sorted_valid_totals': sorted_valid_totals
        })

    df_teams = pd.DataFrame(teams_data)

    # ==========================================================================
    # LEADERBOARD 1: TIEMPO DE CARRO / TIME TRIAL (C9.6) - Max 110 Pts
    # ==========================================================================
    valid_car_teams = df_teams[df_teams['avg_race_time'].notna()].sort_values(
        by=['avg_race_time', 'min_race_time'], ascending=[True, True]
    ).reset_index(drop=True)
    unranked_car_teams = df_teams[df_teams['avg_race_time'].isna()].reset_index(drop=True)

    n_valid_car = len(valid_car_teams)
    if n_valid_car >= 3:
        j1 = float(valid_car_teams.loc[0, 'avg_race_time'])
        j3 = float(valid_car_teams.loc[2, 'avg_race_time'])
        base_race_time = j3 * 1.15
    elif n_valid_car > 0:
        j1 = float(valid_car_teams.loc[0, 'avg_race_time'])
        j3 = float(valid_car_teams.loc[n_valid_car - 1, 'avg_race_time'])
        base_race_time = j3 * 1.15
    else:
        j1 = 0.0
        j3 = 0.0
        base_race_time = 0.0

    car_leaderboard = []
    for idx, row in valid_car_teams.iterrows():
        rank = idx + 1
        t = float(row['avg_race_time'])
        delta = t - j1 if j1 > 0 else 0.0
        dnf_cnt = row['dnf_count']

        if rank == 1:
            pts = 110.0
        elif rank == 2:
            pts = 105.0
        elif rank == 3:
            pts = 100.0
        else:
            if base_race_time > 0 and t > base_race_time:
                pts = max(0.0, 20.0 - 5.0 * dnf_cnt)
            else:
                denom = base_race_time - j3
                if denom > 0:
                    raw_p = 20.0 + (80.0 / denom) * (base_race_time - t)
                    pts = float(round(raw_p))
                    pts = max(20.0, min(100.0, pts))
                else:
                    pts = 20.0

        car_leaderboard.append({
            'rank': rank,
            'team': row['team'],
            'avg_race_time': t,
            'best_race_time': row['min_race_time'],
            'delta': delta,
            'points': pts if award_points else 0.0,
            'projected_points': pts,
            'points_awarded': award_points,
            'base_time': base_race_time,
            'valid_count': row['valid_count'],
            'dnf_count': dnf_cnt,
            'fs_count': row['fs_count'],
            'has_time': True,
            'runs_count': row['runs_count']
        })

    for idx, row in unranked_car_teams.iterrows():
        if row['runs_count'] > 0:
            unranked_pts = max(0.0, 20.0 - 5.0 * row['dnf_count'])
        else:
            unranked_pts = 0.0

        car_leaderboard.append({
            'rank': n_valid_car + idx + 1,
            'team': row['team'],
            'avg_race_time': None,
            'best_race_time': None,
            'delta': None,
            'points': unranked_pts if award_points else 0.0,
            'projected_points': unranked_pts,
            'points_awarded': award_points,
            'base_time': base_race_time,
            'valid_count': row['valid_count'],
            'dnf_count': row['dnf_count'],
            'fs_count': row['fs_count'],
            'has_time': False,
            'runs_count': row['runs_count']
        })

    df_race_lb = pd.DataFrame(car_leaderboard)
    if not df_race_lb.empty:
        # Sort unranked teams so teams that ran and scored > 0 points appear above teams with 0 runs
        ranked_part = df_race_lb[df_race_lb['has_time']].copy()
        unranked_part = df_race_lb[~df_race_lb['has_time']].copy()
        if not unranked_part.empty:
            unranked_part = unranked_part.sort_values(
                by=['projected_points', 'runs_count'], ascending=[False, False]
            )
        df_race_lb = pd.concat([ranked_part, unranked_part], ignore_index=True)
        df_race_lb['rank'] = df_race_lb.index + 1

    # ==========================================================================
    # LEADERBOARD 2: TIEMPO MÁS RÁPIDO / REACTION RACE (C9.5 & C9.8) - Max 110 Pts
    # ==========================================================================
    valid_tot_teams = df_teams[df_teams['min_total_time'].notna()].sort_values(
        by=['min_total_time', 'min_race_time'], ascending=[True, True]
    ).reset_index(drop=True)
    unranked_tot_teams = df_teams[df_teams['min_total_time'].isna()].reset_index(drop=True)

    n_valid_tot = len(valid_tot_teams)
    if n_valid_tot >= 3:
        q1 = float(valid_tot_teams.loc[0, 'min_total_time'])
        q3 = float(valid_tot_teams.loc[2, 'min_total_time'])
        base_total_time = q3 * 1.20
    elif n_valid_tot > 0:
        q1 = float(valid_tot_teams.loc[0, 'min_total_time'])
        q3 = float(valid_tot_teams.loc[n_valid_tot - 1, 'min_total_time'])
        base_total_time = q3 * 1.20
    else:
        q1 = 0.0
        q3 = 0.0
        base_total_time = 0.0

    tot_leaderboard = []
    for idx, row in valid_tot_teams.iterrows():
        rank = idx + 1
        t = float(row['min_total_time'])
        delta = t - q1 if q1 > 0 else 0.0
        dnf_cnt = row['dnf_count']
        fs_cnt = row['fs_count']

        if rank == 1:
            base_awarded = 110.0
        elif rank == 2:
            base_awarded = 105.0
        elif rank == 3:
            base_awarded = 100.0
        else:
            if base_total_time > 0 and t > base_total_time:
                base_awarded = max(0.0, 5.0 - 1.0 * dnf_cnt)
            else:
                denom = base_total_time - q1
                if denom > 0:
                    raw_p = 5.0 + (95.0 / denom) * (base_total_time - t)
                    base_awarded = float(round(raw_p))
                    base_awarded = max(5.0, min(100.0, base_awarded))
                else:
                    base_awarded = 5.0

        # C9.8.2: All reaction false starts incur a 2.5-point penalty
        fs_penalty = 2.5 * fs_cnt
        final_pts = max(0.0, base_awarded - fs_penalty)

        tot_leaderboard.append({
            'rank': rank,
            'team': row['team'],
            'min_total_time': t,
            'best_rxn_time': row['min_rxn_time'],
            'best_race_time': row['min_race_time'],
            'delta': delta,
            'base_points': base_awarded,
            'fs_penalty': fs_penalty,
            'points': final_pts if award_points else 0.0,
            'projected_points': final_pts,
            'points_awarded': award_points,
            'base_time': base_total_time,
            'valid_count': row['valid_count'],
            'dnf_count': dnf_cnt,
            'fs_count': fs_cnt,
            'has_time': True,
            'runs_count': row['runs_count']
        })

    for idx, row in unranked_tot_teams.iterrows():
        dnf_cnt = row['dnf_count']
        fs_cnt = row['fs_count']
        if row['runs_count'] > 0:
            base_awarded = max(0.0, 5.0 - 1.0 * dnf_cnt)
            fs_penalty = 2.5 * fs_cnt
            final_pts = max(0.0, base_awarded - fs_penalty)
        else:
            base_awarded = 0.0
            fs_penalty = 0.0
            final_pts = 0.0

        tot_leaderboard.append({
            'rank': n_valid_tot + idx + 1,
            'team': row['team'],
            'min_total_time': None,
            'best_rxn_time': None,
            'best_race_time': None,
            'delta': None,
            'base_points': base_awarded,
            'fs_penalty': fs_penalty,
            'points': final_pts if award_points else 0.0,
            'projected_points': final_pts,
            'points_awarded': award_points,
            'base_time': base_total_time,
            'valid_count': row['valid_count'],
            'dnf_count': dnf_cnt,
            'fs_count': fs_cnt,
            'has_time': False,
            'runs_count': row['runs_count']
        })

    df_total_lb = pd.DataFrame(tot_leaderboard)
    if not df_total_lb.empty:
        ranked_tot = df_total_lb[df_total_lb['has_time']].copy()
        unranked_tot = df_total_lb[~df_total_lb['has_time']].copy()
        if not unranked_tot.empty:
            unranked_tot = unranked_tot.sort_values(
                by=['projected_points', 'runs_count'], ascending=[False, False]
            )
        df_total_lb = pd.concat([ranked_tot, unranked_tot], ignore_index=True)
        df_total_lb['rank'] = df_total_lb.index + 1

    return {
        'teams_summary': df_teams,
        'race_leaderboard': df_race_lb,
        'total_leaderboard': df_total_lb,
        'base_race_time': base_race_time,
        'base_total_time': base_total_time,
        'third_place_race_time': j3,
        'third_place_total_time': q3,
        'first_place_total_time': q1,
        'award_points': award_points
    }


CATEGORY_MAX_POINTS = {
    "Especificaciones y Escrutinio": 170,
    "Diseño e Ingeniería": 180,
    "Gestión de Proyecto": 160,
    "Identidad de Marca": 100,
    "Presentación Verbal": 160,
    "Carrera": 220,
    "Total": 990
}

# ==============================================================================
# OFFICIAL STEM RACING JUDGING BREAKDOWN CONFIGURATION (5 Non-Racing Categories)
# ==============================================================================
JUDGING_BREAKDOWN_CONFIG = [
    {
        "category": "Especificaciones y Escrutinio",
        "official_label": "Specification and Scrutineering Judging",
        "max_points": 170,
        "color": "#00ADB5",
        "subcategories": [
            {
                "key": "scrutineering_specifications",
                "label": "Specifications",
                "max_points": 110,
                "step": 1,
            },
            {
                "key": "scrutineering_drawings",
                "label": "Engineering Drawings",
                "max_points": 20,
                "step": 1,
            },
            {
                "key": "scrutineering_renderings",
                "label": "Renderings",
                "max_points": 20,
                "step": 1,
            },
            {
                "key": "scrutineering_assembly",
                "label": "Quality of Finish and Assembly",
                "max_points": 20,
                "step": 1,
            },
        ],
    },
    {
        "category": "Diseño e Ingeniería",
        "official_label": "Design and Engineering Judging",
        "max_points": 180,
        "color": "#FF9F43",
        "subcategories": [
            {
                "key": "design_portfolio",
                "label": "Design & Engineering Portfolio",
                "max_points": 180,
                "step": 1,
            },
        ],
    },
    {
        "category": "Gestión de Proyecto",
        "official_label": "Enterprise Judging",
        "max_points": 160,
        "color": "#10B981",
        "subcategories": [
            {
                "key": "enterprise_management",
                "label": "Project Management",
                "max_points": 80,
                "step": 1,
            },
            {
                "key": "enterprise_marketing",
                "label": "Sponsorship & Marketing",
                "max_points": 80,
                "step": 1,
            },
        ],
    },
    {
        "category": "Presentación Verbal",
        "official_label": "Verbal Presentation Judging",
        "max_points": 160,
        "color": "#A855F7",
        "subcategories": [
            {
                "key": "verbal_technique",
                "label": "Technique",
                "max_points": 60,
                "step": 1,
            },
            {
                "key": "verbal_composition",
                "label": "Composition",
                "max_points": 40,
                "step": 1,
            },
            {
                "key": "verbal_subject",
                "label": "Subject Matter",
                "max_points": 60,
                "step": 1,
            },
        ],
    },
    {
        "category": "Identidad de Marca",
        "official_label": "Brand Identity Judging",
        "max_points": 100,
        "color": "#EC4899",
        "subcategories": [
            {
                "key": "brand_pit_display",
                "label": "Pit Display",
                "max_points": 60,
                "step": 1,
            },
            {
                "key": "brand_corporate_identity",
                "label": "Corporate Identity",
                "max_points": 40,
                "step": 1,
            },
        ],
    },
]

ALL_SUBCATEGORY_KEYS = [
    sub["key"]
    for cat in JUDGING_BREAKDOWN_CONFIG
    for sub in cat["subcategories"]
]

SUBCATEGORY_MAX_POINTS = {
    sub["key"]: sub["max_points"]
    for cat in JUDGING_BREAKDOWN_CONFIG
    for sub in cat["subcategories"]
}

SUBCATEGORY_LABELS = {
    sub["key"]: sub["label"]
    for cat in JUDGING_BREAKDOWN_CONFIG
    for sub in cat["subcategories"]
}

SUBCATEGORY_TO_CATEGORY = {
    sub["key"]: cat["category"]
    for cat in JUDGING_BREAKDOWN_CONFIG
    for sub in cat["subcategories"]
}

CATEGORY_TO_SUBCATEGORIES = {
    cat["category"]: [sub["key"] for sub in cat["subcategories"]]
    for cat in JUDGING_BREAKDOWN_CONFIG
}


def compute_category_totals_from_subcategories(subcats: Dict[str, float]) -> Dict[str, float]:
    """Calculate the 5 main non-racing category totals from their subcategory values."""
    totals: Dict[str, float] = {}
    for cat in JUDGING_BREAKDOWN_CONFIG:
        c_name = cat["category"]
        c_max = float(cat["max_points"])
        sub_sum = sum(float(subcats.get(sub["key"], 0.0)) for sub in cat["subcategories"])
        totals[c_name] = max(0.0, min(c_max, round(sub_sum, 2)))
    return totals


def generate_random_subcategories_for_team() -> Dict[str, int]:
    """
    Generate realistic random test scores for all 12 non-racing subcategories within official limits:
    - Scrutineering: spec 75-108, drawings 13-19, renderings 13-19, assembly 13-19 (max 170)
    - Design: portfolio 130-178 (max 180)
    - Enterprise: management 55-78, marketing 55-78 (max 160)
    - Verbal: technique 42-58, composition 28-39, subject 42-58 (max 160)
    - Brand: pit display 42-58, corporate 28-39 (max 100)
    """
    rng = np.random.default_rng()
    return {
        "scrutineering_specifications": int(rng.integers(75, 109)),
        "scrutineering_drawings": int(rng.integers(13, 20)),
        "scrutineering_renderings": int(rng.integers(13, 20)),
        "scrutineering_assembly": int(rng.integers(13, 20)),
        "design_portfolio": int(rng.integers(130, 179)),
        "enterprise_management": int(rng.integers(55, 79)),
        "enterprise_marketing": int(rng.integers(55, 79)),
        "verbal_technique": int(rng.integers(42, 59)),
        "verbal_composition": int(rng.integers(28, 39)),
        "verbal_subject": int(rng.integers(42, 59)),
        "brand_pit_display": int(rng.integers(42, 59)),
        "brand_corporate_identity": int(rng.integers(28, 39)),
    }


def get_default_category_scores(
    teams: List[str],
    race_points_map: Dict[str, float],
    zero_init: bool = False
) -> pd.DataFrame:
    """
    Generate STEM Racing category scores for all 6 categories (990 total points):
    1. Especificaciones y Escrutinio (170 points max)
    2. Diseño e Ingeniería (180 points max)
    3. Empresa / Gestión de Proyecto (160 points max)
    4. Identidad de Marca (100 points max)
    5. Presentación Verbal (160 points max)
    6. Carrera (220 points max: Time Trials 110 + Reaction 110)
    Total points: 990. Determines the final championship podium.
    Also initializes and tracks all 12 official subcategories.
    """
    if not teams:
        cols = ['rank', 'team', 'Total'] + DEFAULT_CATEGORIES + ALL_SUBCATEGORY_KEYS
        return pd.DataFrame(columns=cols)

    data = []
    for team in teams:
        carrera_pts = float(race_points_map.get(team, 0.0))
        if zero_init:
            subcats = {k: 0.0 for k in ALL_SUBCATEGORY_KEYS}
        else:
            seed = sum(ord(c) for c in team)
            rng = np.random.default_rng(seed)
            subcats = {
                "scrutineering_specifications": float(rng.integers(75, 108)),
                "scrutineering_drawings": float(rng.integers(13, 20)),
                "scrutineering_renderings": float(rng.integers(13, 20)),
                "scrutineering_assembly": float(rng.integers(13, 20)),
                "design_portfolio": float(rng.integers(130, 178)),
                "enterprise_management": float(rng.integers(55, 78)),
                "enterprise_marketing": float(rng.integers(55, 78)),
                "verbal_technique": float(rng.integers(42, 59)),
                "verbal_composition": float(rng.integers(28, 39)),
                "verbal_subject": float(rng.integers(42, 59)),
                "brand_pit_display": float(rng.integers(42, 59)),
                "brand_corporate_identity": float(rng.integers(28, 39)),
            }

        cat_totals = compute_category_totals_from_subcategories(subcats)
        total = round(sum(cat_totals.values()) + carrera_pts, 2)

        row_dict = {
            'team': team,
            'Identidad de Marca': cat_totals['Identidad de Marca'],
            'Presentación Verbal': cat_totals['Presentación Verbal'],
            'Carrera': carrera_pts,
            'Especificaciones y Escrutinio': cat_totals['Especificaciones y Escrutinio'],
            'Diseño e Ingeniería': cat_totals['Diseño e Ingeniería'],
            'Gestión de Proyecto': cat_totals['Gestión de Proyecto'],
            'Total': total
        }
        row_dict.update(subcats)
        data.append(row_dict)

    df = pd.DataFrame(data)
    df = df.sort_values(by='Total', ascending=False).reset_index(drop=True)
    df['rank'] = df.index + 1
    return df


def save_judge_scores_to_csv(df_scores: pd.DataFrame, path: str = "judge_scores.csv") -> None:
    """Persist non-racing judge category and subcategory scores to CSV on disk atomically with backup."""
    if df_scores is None or df_scores.empty:
        return
    cols = ['team'] + NON_RACING_CATEGORIES + [c for c in ALL_SUBCATEGORY_KEYS if c in df_scores.columns]
    available = [c for c in cols if c in df_scores.columns]
    _atomic_write_csv(df_scores[available], path, create_backup=True)


def load_judge_scores_from_csv(
    path: str,
    teams: List[str],
    race_points_map: Dict[str, float]
) -> Optional[pd.DataFrame]:
    """Load persisted judge category and subcategory scores from CSV on disk (or .bak backup) if available."""
    bak_path = f"{path}.bak"
    df = None
    with CSV_LOCK:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                df = pd.read_csv(path)
            except Exception:
                df = None
        if (df is None or df.empty or 'team' not in df.columns) and os.path.exists(bak_path) and os.path.getsize(bak_path) > 0:
            try:
                df = pd.read_csv(bak_path)
                if df is not None and not df.empty and 'team' in df.columns:
                    shutil.copy2(bak_path, path)
            except Exception:
                df = None
    if df is None or df.empty or 'team' not in df.columns:
        return None
    try:
        df['team'] = df['team'].astype(str).str.strip().replace(LEGACY_TEAM_MAP)
        base_df = get_default_category_scores(teams, race_points_map, zero_init=False)
        for _, row in df.iterrows():
            t_name = str(row['team']).strip()
            mask = base_df['team'] == t_name
            if mask.any():
                # Load subcategories if present
                has_any_subcat = False
                for sub_k in ALL_SUBCATEGORY_KEYS:
                    if sub_k in df.columns and pd.notna(row[sub_k]):
                        val = float(pd.to_numeric(row[sub_k], errors='coerce') or 0.0)
                        max_s = float(SUBCATEGORY_MAX_POINTS.get(sub_k, 200))
                        base_df.loc[mask, sub_k] = max(0.0, min(max_s, round(val, 2)))
                        has_any_subcat = True

                if has_any_subcat:
                    sub_vals = {k: float(base_df.loc[mask, k].iloc[0]) for k in ALL_SUBCATEGORY_KEYS}
                    cat_from_sub = compute_category_totals_from_subcategories(sub_vals)
                    for cat_col, cat_val in cat_from_sub.items():
                        base_df.loc[mask, cat_col] = cat_val
                else:
                    for col in NON_RACING_CATEGORIES:
                        if col in df.columns and pd.notna(row[col]):
                            val = float(pd.to_numeric(row[col], errors='coerce') or 0.0)
                            max_pts = float(CATEGORY_MAX_POINTS.get(col, 200))
                            base_df.loc[mask, col] = max(0.0, min(max_pts, round(val, 2)))

        base_df['Carrera'] = base_df['team'].map(race_points_map).fillna(0.0)
        base_df['Total'] = base_df[DEFAULT_CATEGORIES].sum(axis=1).round(2)
        base_df = base_df.sort_values(by='Total', ascending=False).reset_index(drop=True)
        base_df['rank'] = base_df.index + 1
        return base_df
    except Exception:
        return None


def _parse_numeric_score(val: Any) -> Optional[float]:
    """Extract numeric float score from a cell value, ignoring '170 points' labels."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (int, float, np.number)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    s_low = s.lower()
    # Ignore cells that describe Points Available (e.g., "170 points")
    if "point" in s_low or "punto" in s_low or "pág" in s_low or "max" in s_low:
        return None
    s_clean = s.replace(",", ".")
    try:
        return float(s_clean)
    except ValueError:
        return None


def resolve_team_identity(
    raw_name: Optional[str],
    raw_number: Optional[Any],
    raw_school: Optional[str],
    filename: str,
    official_teams: List[str]
) -> Optional[str]:
    """Match a team from Judging Breakdown metadata against the official teams list."""
    if not official_teams:
        official_teams = DEFAULT_TEAMS

    norm_map = {t.lower().strip(): t for t in official_teams}
    for k, v in LEGACY_TEAM_MAP.items():
        if v in official_teams:
            norm_map[k.lower().strip()] = v

    # 1. Direct or substring match on Team Name
    if raw_name:
        rn = str(raw_name).strip()
        rn_low = rn.lower()
        if rn_low in norm_map:
            return norm_map[rn_low]
        for t in official_teams:
            if t.lower() in rn_low or rn_low in t.lower():
                return t
        for k_school, v_team in SCHOOL_TO_TEAM_MAP.items():
            if k_school in rn_low and v_team in official_teams:
                return v_team

    # 2. Match via School Name
    if raw_school:
        rs_low = str(raw_school).strip().lower()
        for k_school, v_team in SCHOOL_TO_TEAM_MAP.items():
            if k_school in rs_low and v_team in official_teams:
                return v_team

    # 3. Match via Team Number (1-based index in official_teams)
    if raw_number is not None:
        num_str = re.sub(r"[^0-9]", "", str(raw_number))
        if num_str:
            idx = int(num_str) - 1
            if 0 <= idx < len(official_teams):
                return official_teams[idx]

    # 4. Match via filename
    if filename:
        fn_low = os.path.splitext(os.path.basename(filename))[0].lower()
        for t in official_teams:
            if t.lower() in fn_low:
                return t
        for k_leg, v_team in LEGACY_TEAM_MAP.items():
            if k_leg.lower() in fn_low and v_team in official_teams:
                return v_team

    return None


def _parse_breakdown_grid_rows(
    rows: List[List[Any]],
    filename: str,
    official_teams: List[str]
) -> Dict[str, Dict[str, float]]:
    """
    Parse a 2D list of rows from a STEM RACING - COMPETITION JUDGING BREAKDOWN sheet/CSV.
    Supports both single-team sheets and stacked multi-team sheets, plus fallback to
    sub-rows and individual scorecard totals when Excel formula cells are uncached.
    """
    team_records: Dict[str, Dict[str, Any]] = {}

    current_raw_name: Optional[str] = None
    current_raw_num: Optional[Any] = None
    current_raw_school: Optional[str] = None
    awarded_col_idx: Optional[int] = None

    def get_current_bucket() -> Dict[str, Any]:
        matched = resolve_team_identity(
            current_raw_name, current_raw_num, current_raw_school, filename, official_teams
        )
        key = matched or "__default__"
        if key not in team_records:
            team_records[key] = {
                "matched_team": matched,
                "main": {},
                "sub": {cat: 0.0 for cat in NON_RACING_CATEGORIES},
                "sub_found": {cat: False for cat in NON_RACING_CATEGORIES},
                "subcategories": {},
                "scorecard": {cat: 0.0 for cat in NON_RACING_CATEGORIES},
                "scorecard_found": {cat: False for cat in NON_RACING_CATEGORIES},
            }
        return team_records[key]

    for row in rows:
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        str_cells = [str(c).strip() if c is not None else "" for c in row]
        low_cells = [s.lower() for s in str_cells]

        # Check for Team Number / Team Name / School metadata row
        for idx, cell_low in enumerate(low_cells):
            if cell_low.startswith("team number") or cell_low.startswith("número de equipo"):
                for look_ahead in range(idx + 1, min(idx + 3, len(str_cells))):
                    if str_cells[look_ahead] and not low_cells[look_ahead].startswith("team name"):
                        current_raw_num = str_cells[look_ahead]
                        break
            elif cell_low.startswith("team name") or cell_low.startswith("nombre del equipo") or cell_low == "equipo:":
                for look_ahead in range(idx + 1, min(idx + 3, len(str_cells))):
                    if str_cells[look_ahead] and not low_cells[look_ahead].startswith("school"):
                        current_raw_name = str_cells[look_ahead]
                        break
            elif cell_low.startswith("school") or cell_low.startswith("colegio"):
                for look_ahead in range(idx + 1, min(idx + 3, len(str_cells))):
                    if str_cells[look_ahead]:
                        current_raw_school = str_cells[look_ahead]
                        break

        # Detect "Awarded Points" header column index
        for idx, cell_low in enumerate(low_cells):
            if "awarded points" in cell_low or "puntos otorgados" in cell_low or "puntos obtenidos" in cell_low:
                awarded_col_idx = idx

        # Find first non-empty label in the row
        first_idx = next((i for i, s in enumerate(str_cells) if s), None)
        if first_idx is None:
            continue
        label_low = low_cells[first_idx]

        def extract_row_score(prefer_col: Optional[int] = None, take_last: bool = False) -> Optional[float]:
            if prefer_col is not None and prefer_col < len(row):
                v = _parse_numeric_score(row[prefer_col])
                if v is not None:
                    return v
            nums = []
            for c_val in row[first_idx + 1:]:
                v = _parse_numeric_score(c_val)
                if v is not None:
                    nums.append(v)
            if not nums:
                return None
            return nums[-1] if take_last else nums[0]

        bucket = get_current_bucket()

        # ------------------------------------------------------------------
        # 1. Main Breakdown Category Rows
        # ------------------------------------------------------------------
        if label_low.startswith("specification and scrutineering judging") or label_low == "especificaciones y escrutinio":
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["main"]["Especificaciones y Escrutinio"] = val
        elif label_low.startswith("design and engineering judging") or label_low == "diseño e ingeniería":
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["main"]["Diseño e Ingeniería"] = val
        elif label_low.startswith("enterprise judging") or label_low in ("gestión de proyecto", "empresa y gestión de proyecto"):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["main"]["Gestión de Proyecto"] = val
        elif label_low.startswith("verbal presentation judging") or label_low == "presentación verbal":
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["main"]["Presentación Verbal"] = val
        elif label_low.startswith("brand identity judging") or label_low == "identidad de marca":
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["main"]["Identidad de Marca"] = val

        # ------------------------------------------------------------------
        # 2. Breakdown Sub-Rows (Fallback if main category formula is uncached)
        # ------------------------------------------------------------------
        elif any(label_low.startswith(p) for p in (
            "specifications (", "engineering drawings (", "renderings (", "quality of finish and assembly ("
        )):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Especificaciones y Escrutinio"] += val
                bucket["sub_found"]["Especificaciones y Escrutinio"] = True
                if label_low.startswith("specifications ("):
                    bucket["subcategories"]["scrutineering_specifications"] = val
                elif label_low.startswith("engineering drawings ("):
                    bucket["subcategories"]["scrutineering_drawings"] = val
                elif label_low.startswith("renderings ("):
                    bucket["subcategories"]["scrutineering_renderings"] = val
                elif label_low.startswith("quality of finish and assembly ("):
                    bucket["subcategories"]["scrutineering_assembly"] = val
        elif label_low.startswith("design & engineering portfolio ("):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Diseño e Ingeniería"] += val
                bucket["sub_found"]["Diseño e Ingeniería"] = True
                bucket["subcategories"]["design_portfolio"] = val
        elif any(label_low.startswith(p) for p in ("project management (", "sponsorship & marketing (")):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Gestión de Proyecto"] += val
                bucket["sub_found"]["Gestión de Proyecto"] = True
                if label_low.startswith("project management ("):
                    bucket["subcategories"]["enterprise_management"] = val
                elif label_low.startswith("sponsorship & marketing ("):
                    bucket["subcategories"]["enterprise_marketing"] = val
        elif any(label_low.startswith(p) for p in ("technique (", "composition (", "subject matter (")):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Presentación Verbal"] += val
                bucket["sub_found"]["Presentación Verbal"] = True
                if label_low.startswith("technique ("):
                    bucket["subcategories"]["verbal_technique"] = val
                elif label_low.startswith("composition ("):
                    bucket["subcategories"]["verbal_composition"] = val
                elif label_low.startswith("subject matter ("):
                    bucket["subcategories"]["verbal_subject"] = val
        elif any(label_low.startswith(p) for p in ("pit display (", "corporate identity (")):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Identidad de Marca"] += val
                bucket["sub_found"]["Identidad de Marca"] = True
                if label_low.startswith("pit display ("):
                    bucket["subcategories"]["brand_pit_display"] = val
                elif label_low.startswith("corporate identity ("):
                    bucket["subcategories"]["brand_corporate_identity"] = val

        # ------------------------------------------------------------------
        # 3. Individual Scorecard Total Rows (Fallback across scorecard sheets)
        # ------------------------------------------------------------------
        elif label_low.startswith("scrutineering total") or label_low.startswith("specifications total"):
            val = extract_row_score(take_last=True)
            if val is not None and val >= 0:
                bucket["scorecard"]["Especificaciones y Escrutinio"] += val
                bucket["scorecard_found"]["Especificaciones y Escrutinio"] = True
        elif "design & engineering portfolio only assessment total" in label_low:
            val = extract_row_score(take_last=True)
            if val is not None and val >= 0:
                bucket["scorecard"]["Diseño e Ingeniería"] = val
                bucket["scorecard_found"]["Diseño e Ingeniería"] = True
        elif "enterprise total" in label_low:
            val = extract_row_score(take_last=True)
            if val is not None and val >= 0:
                bucket["scorecard"]["Gestión de Proyecto"] = val
                bucket["scorecard_found"]["Gestión de Proyecto"] = True
        elif "verbal presentation total" in label_low:
            val = extract_row_score(take_last=True)
            if val is not None and val >= 0:
                bucket["scorecard"]["Presentación Verbal"] = val
                bucket["scorecard_found"]["Presentación Verbal"] = True
        elif "brand identity total" in label_low:
            val = extract_row_score(take_last=True)
            if val is not None and val >= 0:
                bucket["scorecard"]["Identidad de Marca"] = val
                bucket["scorecard_found"]["Identidad de Marca"] = True

    # Consolidate scores per matched team
    results: Dict[str, Dict[str, float]] = {}
    for key, b in team_records.items():
        team_name = b["matched_team"]
        if not team_name:
            continue
        has_any = bool(b["main"]) or any(b["sub_found"].values()) or any(b["scorecard_found"].values())
        if not has_any:
            continue

        cat_scores: Dict[str, float] = {}
        for cat in NON_RACING_CATEGORIES:
            main_v = b["main"].get(cat)
            sub_v = b["sub"][cat] if b["sub_found"][cat] else None
            sc_v = b["scorecard"][cat] if b["scorecard_found"][cat] else None

            # Prefer non-zero value if main formula cell evaluated to 0/None while sub-rows/scorecards had points
            candidates = [v for v in (main_v, sub_v, sc_v) if v is not None]
            if not candidates:
                continue
            positive_candidates = [v for v in candidates if v > 0]
            chosen = positive_candidates[0] if positive_candidates else candidates[0]
            max_pts = float(CATEGORY_MAX_POINTS.get(cat, 200))
            cat_scores[cat] = max(0.0, min(max_pts, round(float(chosen), 2)))

        if cat_scores:
            if team_name not in results:
                results[team_name] = {}
            for cat, val in cat_scores.items():
                if cat not in results[team_name] or val > results[team_name][cat]:
                    results[team_name][cat] = val

            # Also transfer parsed subcategories
            for sub_k, sub_v in b.get("subcategories", {}).items():
                max_s = float(SUBCATEGORY_MAX_POINTS.get(sub_k, 200))
                results[team_name][sub_k] = max(0.0, min(max_s, round(float(sub_v), 2)))

    return results


def _try_parse_tabular_df(df: pd.DataFrame, official_teams: List[str]) -> Dict[str, Dict[str, float]]:
    """
    Parse a standard tabular CSV/Excel where:
    Format A: Each row is a team, and columns are categories or subcategories.
    Format B (Transposed): Each row is a rubric / assessment item, and columns are teams.
    Supports both high-level categories (Especificaciones, Diseño, etc.) and granular subcategories
    (scrutineering_specifications, enterprise_management, verbal_technique, etc.).
    """
    if df is None or df.empty:
        return {}

    # Normalization mappings for subcategories
    subcat_aliases = {
        # Scrutineering
        "scrutineering_specifications": ("scrutineering_specifications", "specifications", "especificaciones"),
        "scrutineering_drawings": ("scrutineering_drawings", "drawings", "planos", "engineering drawings"),
        "scrutineering_renderings": ("scrutineering_renderings", "renderings", "renders"),
        "scrutineering_assembly": ("scrutineering_assembly", "quality of finish", "acabado y ensamble", "assembly"),
        # Design & Engineering
        "design_portfolio": ("design_portfolio", "design & engineering portfolio", "portafolio de diseno", "portafolio de diseño"),
        # Enterprise
        "enterprise_management": ("enterprise_management", "project management", "gestion de proyecto", "gestión de proyecto"),
        "enterprise_marketing": ("enterprise_marketing", "sponsorship & marketing", "sponsorship and marketing", "patrocinio y marketing"),
        # Verbal
        "verbal_technique": ("verbal_technique", "technique", "tecnica", "técnica"),
        "verbal_composition": ("verbal_composition", "composition", "composicion", "composición"),
        "verbal_subject": ("verbal_subject", "subject matter", "tema", "contenido verbal"),
        # Brand
        "brand_pit_display": ("brand_pit_display", "pit display", "stand de pits", "display de pits"),
        "brand_corporate_identity": ("brand_corporate_identity", "corporate identity", "identidad corporativa"),
    }

    category_aliases = {
        "Especificaciones y Escrutinio": ("escrutinio", "scrutineering", "specification", "especificaciones y escrutinio"),
        "Diseño e Ingeniería": ("diseño", "diseno", "design", "engineering", "diseño e ingeniería"),
        "Gestión de Proyecto": ("gestión", "gestion", "enterprise", "empresa", "gestión de proyecto"),
        "Presentación Verbal": ("verbal", "presentación", "presentacion", "presentación verbal"),
        "Identidad de Marca": ("identidad", "marca", "brand", "identidad de marca"),
    }

    def _resolve_rubric_key(text_val: Any) -> Tuple[Optional[str], Optional[str]]:
        """Given a label or key string, returns (subcat_key, cat_name)."""
        t_str = str(text_val).strip().lower()
        if not t_str:
            return None, None
        for skey, aliases in subcat_aliases.items():
            if t_str == skey or any(alias in t_str for alias in aliases):
                return skey, None
        for cname, aliases in category_aliases.items():
            if any(alias in t_str for alias in aliases):
                return None, cname
        return None, None

    # =========================================================================
    # CHECK FORMAT B (Transposed): Rows = Rubros, Columns = Teams
    # Look for team names in df.columns
    # =========================================================================
    matched_team_cols: Dict[str, str] = {}
    rubric_label_col: Optional[str] = None
    rubric_key_col: Optional[str] = None

    for c in df.columns:
        c_str = str(c).strip()
        c_low = c_str.lower()
        if c_low in ("key", "clave", "subcat_key", "codigo"):
            rubric_key_col = c
            continue
        if c_low in ("rubro", "rubros", "categoria", "subcategoria", "item", "criterio", "assessment area", "judging category"):
            rubric_label_col = c
            continue
        # Check if column matches an official team
        matched_t = resolve_team_identity(c_str, None, None, "", official_teams)
        if matched_t:
            matched_team_cols[c] = matched_t

    # If at least 2 teams are columns (or 1 team and a rubric column exists)
    if (len(matched_team_cols) >= 2) or (matched_team_cols and (rubric_label_col or rubric_key_col)):
        if not rubric_label_col and not rubric_key_col:
            # First non-team column can be the rubric label
            for c in df.columns:
                if c not in matched_team_cols:
                    rubric_label_col = c
                    break

        transposed_results: Dict[str, Dict[str, float]] = {t: {} for t in matched_team_cols.values()}

        for _, row in df.iterrows():
            sub_k, cat_n = None, None
            if rubric_key_col and pd.notna(row.get(rubric_key_col)):
                sub_k, cat_n = _resolve_rubric_key(row.get(rubric_key_col))
            if not sub_k and not cat_n and rubric_label_col and pd.notna(row.get(rubric_label_col)):
                sub_k, cat_n = _resolve_rubric_key(row.get(rubric_label_col))

            if not sub_k and not cat_n:
                continue

            for col_c, team_name in matched_team_cols.items():
                v = _parse_numeric_score(row.get(col_c))
                if v is not None:
                    if sub_k:
                        max_pts = float(SUBCATEGORY_MAX_POINTS.get(sub_k, 200))
                        transposed_results[team_name][sub_k] = max(0.0, min(max_pts, round(v, 2)))
                    elif cat_n:
                        max_pts = float(CATEGORY_MAX_POINTS.get(cat_n, 200))
                        transposed_results[team_name][cat_n] = max(0.0, min(max_pts, round(v, 2)))

        # Compute category totals from subcategories
        final_transposed: Dict[str, Dict[str, float]] = {}
        for t_name, scores in transposed_results.items():
            if scores:
                sub_dict = {k: v for k, v in scores.items() if k in ALL_SUBCATEGORY_KEYS}
                if sub_dict:
                    comp = compute_category_totals_from_subcategories(sub_dict)
                    for c_k, c_v in comp.items():
                        if c_k not in scores:
                            scores[c_k] = c_v
                final_transposed[t_name] = scores
        if final_transposed:
            return final_transposed

    # =========================================================================
    # CHECK FORMAT A: Rows = Teams, Columns = Categories/Subcategories
    # =========================================================================
    col_map: Dict[str, str] = {}
    subcat_col_map: Dict[str, str] = {}
    team_col: Optional[str] = None

    for c in df.columns:
        c_low = str(c).strip().lower()
        if c_low in ("team", "equipo", "team name", "nombre del equipo", "equipos", "nombre"):
            team_col = c
            continue

        sub_k, cat_n = _resolve_rubric_key(c)
        if sub_k:
            subcat_col_map[c] = sub_k
        elif cat_n:
            col_map[c] = cat_n

    if not team_col or (not col_map and not subcat_col_map):
        return {}

    results: Dict[str, Dict[str, float]] = {}
    for _, row in df.iterrows():
        raw_t = row.get(team_col)
        if pd.isna(raw_t) or not str(raw_t).strip():
            continue
        matched = resolve_team_identity(str(raw_t), None, None, "", official_teams)
        if not matched:
            continue
        scores: Dict[str, float] = {}

        # 1. Parse subcategories if present
        parsed_subcats: Dict[str, float] = {}
        for src_col, target_sub in subcat_col_map.items():
            v = _parse_numeric_score(row.get(src_col))
            if v is not None:
                max_pts = float(SUBCATEGORY_MAX_POINTS.get(target_sub, 200))
                val_sub = max(0.0, min(max_pts, round(v, 2)))
                scores[target_sub] = val_sub
                parsed_subcats[target_sub] = val_sub

        # If subcategories were provided, calculate category totals from them
        if parsed_subcats:
            computed_cats = compute_category_totals_from_subcategories(parsed_subcats)
            for c_name, c_tot in computed_cats.items():
                scores[c_name] = c_tot

        # 2. Parse main categories if not already provided or if explicitly defined
        for src_col, target_cat in col_map.items():
            v = _parse_numeric_score(row.get(src_col))
            if v is not None:
                max_pts = float(CATEGORY_MAX_POINTS.get(target_cat, 200))
                scores[target_cat] = max(0.0, min(max_pts, round(v, 2)))

        if scores:
            results[matched] = scores
    return results


def parse_judging_rubric_files(
    uploaded_files: Any,
    official_teams: Optional[List[str]] = None
) -> Tuple[Dict[str, Dict[str, float]], List[str]]:
    """
    Parse one or multiple uploaded Judging Rubric files (.xlsx or .csv).
    Supports:
    1. Official 'STEM RACING - COMPETITION JUDGING BREAKDOWN' Excel (.xlsx) or CSV files
       (single-team per file, multi-sheet per team, or multi-team workbooks).
    2. Tabular summary CSV / Excel files with columns for each judging category.
    Returns (team_scores_dict, summary_messages).
    """
    if official_teams is None:
        official_teams = DEFAULT_TEAMS.copy()

    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files] if uploaded_files is not None else []

    combined_scores: Dict[str, Dict[str, float]] = {}
    messages: List[str] = []

    for f_obj in uploaded_files:
        if f_obj is None:
            continue
        fname = getattr(f_obj, "name", str(f_obj))
        try:
            if isinstance(f_obj, str):
                with open(f_obj, "rb") as fp:
                    raw_bytes = fp.read()
            else:
                if hasattr(f_obj, "seek"):
                    f_obj.seek(0)
                raw_bytes = f_obj.getvalue() if hasattr(f_obj, "getvalue") else f_obj.read()
        except Exception as e:
            messages.append(f"⚠️ No se pudo leer '{fname}': {e}")
            continue

        if not raw_bytes:
            continue

        ext = os.path.splitext(fname)[1].lower()
        file_extracted: Dict[str, Dict[str, float]] = {}

        if ext in (".xlsx", ".xlsm", ".xls"):
            try:
                wb = openpyxl.load_workbook(BytesIO(raw_bytes), data_only=True)
                all_rows: List[List[Any]] = []
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    sheet_rows = [[cell.value for cell in r] for r in ws.iter_rows()]
                    all_rows.extend(sheet_rows)
                    # Also try tabular parse on individual sheet if breakdown isn't matched
                file_extracted = _parse_breakdown_grid_rows(all_rows, fname, official_teams)
                if not file_extracted:
                    df_excel = pd.read_excel(BytesIO(raw_bytes))
                    file_extracted = _try_parse_tabular_df(df_excel, official_teams)
            except Exception as e:
                messages.append(f"⚠️ Error procesando Excel '{fname}': {e}")
                continue
        else:
            # CSV file
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
                reader = csv.reader(StringIO(text))
                csv_rows = [r for r in reader]
                file_extracted = _parse_breakdown_grid_rows(csv_rows, fname, official_teams)
                if not file_extracted:
                    df_csv = pd.read_csv(BytesIO(raw_bytes))
                    file_extracted = _try_parse_tabular_df(df_csv, official_teams)
            except Exception as e:
                messages.append(f"⚠️ Error procesando CSV '{fname}': {e}")
                continue

        if file_extracted:
            for t_name, cat_dict in file_extracted.items():
                if t_name not in combined_scores:
                    combined_scores[t_name] = {c: 0.0 for c in NON_RACING_CATEGORIES}
                combined_scores[t_name].update(cat_dict)
                non_race_sum = sum(combined_scores[t_name].get(c, 0.0) for c in NON_RACING_CATEGORIES)
                messages.append(f"✅ **{t_name}** (`{fname}`): {non_race_sum:g} / 770 pts de jueces")
        else:
            messages.append(f"⚠️ No se encontraron puntajes de categorías reconocidos en `{fname}`.")

    return combined_scores, messages


def generate_random_test_run() -> Tuple[bool, bool, float, float]:
    """
    Generate random test values for a single team race based on the reference Excel
    ('Racing Score Calculator.xlsx': reaction_time 0.102–0.299s, race_time 1.208–1.790s),
    with random chance of DNF (~14%) or False Start (~14%).
    Returns (is_dnf, is_false_start, reaction_time, race_time).
    """
    rng = np.random.default_rng()
    roll = float(rng.random())
    if roll < 0.14:
        return True, False, 0.000, 0.000
    elif roll < 0.28:
        return False, True, 0.000, 0.000
    else:
        rxn = round(float(rng.uniform(0.102, 0.299)), 3)
        race = round(float(rng.uniform(1.208, 1.790)), 3)
        return False, False, rxn, race


def generate_random_judge_scores_for_team() -> Dict[str, int]:
    """
    Generate random test scores for the 5 non-racing judge categories within official max limits:
    - Especificaciones y Escrutinio (max 170)
    - Diseño e Ingeniería (max 180)
    - Gestión de Proyecto (max 160)
    - Identidad de Marca (max 100)
    - Presentación Verbal (max 160)
    """
    rng = np.random.default_rng()
    return {
        'Identidad de Marca': int(rng.integers(68, 99)),
        'Presentación Verbal': int(rng.integers(110, 159)),
        'Especificaciones y Escrutinio': int(rng.integers(115, 169)),
        'Diseño e Ingeniería': int(rng.integers(125, 179)),
        'Gestión de Proyecto': int(rng.integers(110, 159)),
    }
