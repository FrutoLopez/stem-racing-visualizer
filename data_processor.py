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
from datetime import datetime
from io import BytesIO, StringIO
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np
import openpyxl

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
    """
    cols_schema = CSV_SCHEMA
    try:
        if isinstance(file_source, pd.DataFrame):
            df = file_source.copy()
        elif isinstance(file_source, str):
            if not os.path.exists(file_source) or os.path.getsize(file_source) == 0:
                return pd.DataFrame(columns=cols_schema)
            df = pd.read_csv(file_source)
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
    """Save runs dataframe (with id and timestamp) to CSV file."""
    cols = CSV_SCHEMA
    if df_runs is None or df_runs.empty:
        empty_df = pd.DataFrame(columns=cols)
        empty_df.to_csv(path, index=False)
        return
    out = load_runs_from_csv(df_runs, recalculate_totals=recalculate_totals)
    available_cols = [c for c in cols if c in out.columns]
    out[available_cols].to_csv(path, index=False)


def append_runs_to_csv(new_rows: List[Dict[str, Any]], path: str = "live_race_data.csv") -> pd.DataFrame:
    """
    Append new or edited race records to the CSV file with a general sequential `id`
    and current `timestamp`, keeping all historical entries in the CSV audit log.
    """
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
    """Clear all records from the CSV file to start fresh from 0."""
    empty_df = pd.DataFrame(columns=CSV_SCHEMA)
    empty_df.to_csv(path, index=False)
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
    """
    if not teams:
        cols = ['rank', 'team', 'Total'] + DEFAULT_CATEGORIES
        return pd.DataFrame(columns=cols)

    data = []
    for team in teams:
        carrera_pts = float(race_points_map.get(team, 0.0))
        if zero_init:
            identidad = 0.0
            verbal = 0.0
            escrutinio = 0.0
            diseno = 0.0
            gestion = 0.0
        else:
            seed = sum(ord(c) for c in team)
            rng = np.random.default_rng(seed)
            identidad = float(rng.integers(70, 96))      # max 100
            verbal = float(rng.integers(115, 155))        # max 160
            escrutinio = float(rng.integers(120, 165))    # max 170
            diseno = float(rng.integers(130, 175))        # max 180
            gestion = float(rng.integers(115, 155))       # max 160

        total = round(identidad + verbal + carrera_pts + escrutinio + diseno + gestion, 2)

        data.append({
            'team': team,
            'Identidad de Marca': identidad,
            'Presentación Verbal': verbal,
            'Carrera': carrera_pts,
            'Especificaciones y Escrutinio': escrutinio,
            'Diseño e Ingeniería': diseno,
            'Gestión de Proyecto': gestion,
            'Total': total
        })

    df = pd.DataFrame(data)
    df = df.sort_values(by='Total', ascending=False).reset_index(drop=True)
    df['rank'] = df.index + 1
    return df


def save_judge_scores_to_csv(df_scores: pd.DataFrame, path: str = "judge_scores.csv") -> None:
    """Persist non-racing judge category scores to CSV on disk."""
    if df_scores is None or df_scores.empty:
        return
    cols = ['team'] + NON_RACING_CATEGORIES
    available = [c for c in cols if c in df_scores.columns]
    df_scores[available].to_csv(path, index=False)


def load_judge_scores_from_csv(
    path: str,
    teams: List[str],
    race_points_map: Dict[str, float]
) -> Optional[pd.DataFrame]:
    """Load persisted judge category scores from CSV on disk if available."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    try:
        df = pd.read_csv(path)
        if df.empty or 'team' not in df.columns:
            return None
        df['team'] = df['team'].astype(str).str.strip().replace(LEGACY_TEAM_MAP)
        base_df = get_default_category_scores(teams, race_points_map, zero_init=False)
        for _, row in df.iterrows():
            t_name = str(row['team']).strip()
            mask = base_df['team'] == t_name
            if mask.any():
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
        elif label_low.startswith("design & engineering portfolio ("):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Diseño e Ingeniería"] += val
                bucket["sub_found"]["Diseño e Ingeniería"] = True
        elif any(label_low.startswith(p) for p in ("project management (", "sponsorship & marketing (")):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Gestión de Proyecto"] += val
                bucket["sub_found"]["Gestión de Proyecto"] = True
        elif any(label_low.startswith(p) for p in ("technique (", "composition (", "subject matter (")):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Presentación Verbal"] += val
                bucket["sub_found"]["Presentación Verbal"] = True
        elif any(label_low.startswith(p) for p in ("pit display (", "corporate identity (")):
            val = extract_row_score(awarded_col_idx)
            if val is not None:
                bucket["sub"]["Identidad de Marca"] += val
                bucket["sub_found"]["Identidad de Marca"] = True

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

    return results


def _try_parse_tabular_df(df: pd.DataFrame, official_teams: List[str]) -> Dict[str, Dict[str, float]]:
    """
    Parse a standard tabular CSV/Excel where each row is a team and columns are categories.
    """
    if df is None or df.empty:
        return {}

    col_map: Dict[str, str] = {}
    team_col: Optional[str] = None
    for c in df.columns:
        c_low = str(c).strip().lower()
        if c_low in ("team", "equipo", "team name", "nombre del equipo", "equipos"):
            team_col = c
        elif "escrutinio" in c_low or "scrutineering" in c_low or "specification" in c_low:
            col_map[c] = "Especificaciones y Escrutinio"
        elif "diseño" in c_low or "diseno" in c_low or "design" in c_low or "engineering" in c_low:
            col_map[c] = "Diseño e Ingeniería"
        elif "gestión" in c_low or "gestion" in c_low or "enterprise" in c_low or "empresa" in c_low:
            col_map[c] = "Gestión de Proyecto"
        elif "verbal" in c_low or "presentación" in c_low or "presentacion" in c_low:
            col_map[c] = "Presentación Verbal"
        elif "identidad" in c_low or "marca" in c_low or "brand" in c_low:
            col_map[c] = "Identidad de Marca"

    if not team_col or not col_map:
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
