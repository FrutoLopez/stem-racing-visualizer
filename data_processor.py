"""Data processor and calculation engine for STEM Racing Results.
Computes official timing metrics, head-to-head pairings, and official scoring systems according to:
- C9.5: Reaction race scoring (Fastest total race time, Base Time 120%, DNF deduction if 5 pts)
- C9.6: Time Trial race scoring (2nd & 3rd best car race time avg, DNF replacement rule, Base Time 115%, DNF deduction if 20 pts)
- C9.7: DNF race results
- C9.8: False starts (Jump starts, 2.5-point penalty and race forfeit)
"""

import os
from io import BytesIO
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np

DEFAULT_CATEGORIES = [
    "Identidad de Marca",
    "Presentación Verbal",
    "Carrera",
    "Especificaciones y Escrutinio",
    "Diseño e Ingeniería",
    "Gestión de Proyecto"
]

DEFAULT_TEAMS = [
    "ITDB",
    "St. George",
    "Oxford",
    "Isaac Rabin",
    "Panamerican",
    "Sun Yat Sen",
    "Brader",
    "TJS",
    "Casco",
    "ISP"
]


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
    Build the 5 fixed head-to-head pairings based on team order:
    1 vs 2, 3 vs 4, 5 vs 6, 7 vs 8, 9 vs 10.
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
            "team_b": t_b
        })
    return matchups


from datetime import datetime

CSV_SCHEMA = ['id', 'timestamp', 'team', 'race_number', 'reaction_time', 'race_time', 'total_time', 'is_dnf', 'is_false_start']


def load_runs_from_csv(file_source: Any) -> pd.DataFrame:
    """
    Load runs from a CSV file (filepath, BytesIO, or Streamlit UploadedFile).
    Preserves the full append-only CSV log including general `id` and `timestamp`.
    """
    cols_schema = CSV_SCHEMA
    try:
        if isinstance(file_source, str):
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

        df['team'] = df['team'].astype(str).str.strip()
        df = df[df['team'] != ''].reset_index(drop=True)

        # Clean numeric fields
        df['reaction_time'] = pd.to_numeric(df['reaction_time'], errors='coerce').fillna(0.0)
        df['race_time'] = pd.to_numeric(df['race_time'], errors='coerce')
        df['total_time'] = pd.to_numeric(df['total_time'], errors='coerce')

        # If marked DNF or False Start, force NaN for race_time & total_time (forfeited)
        invalid_mask = df['is_dnf'] | df['is_false_start']
        df.loc[invalid_mask, 'race_time'] = np.nan
        df.loc[invalid_mask, 'total_time'] = np.nan

        # For valid runs where total_time is missing or 0, calculate rxn + race
        valid_mask = ~invalid_mask
        df.loc[valid_mask & df['race_time'].isna(), 'race_time'] = 0.0
        need_total_mask = valid_mask & (df['total_time'].isna() | (df['total_time'] <= 0))
        if need_total_mask.any():
            df.loc[need_total_mask, 'total_time'] = (
                df.loc[need_total_mask, 'reaction_time'] + df.loc[need_total_mask, 'race_time']
            )

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


def save_runs_to_csv(df_runs: pd.DataFrame, path: str = "live_race_data.csv") -> None:
    """Save runs dataframe (with id and timestamp) to CSV file."""
    cols = CSV_SCHEMA
    if df_runs is None or df_runs.empty:
        empty_df = pd.DataFrame(columns=cols)
        empty_df.to_csv(path, index=False)
        return
    out = df_runs.copy()
    if 'id' not in out.columns:
        out['id'] = range(1, len(out) + 1)
    if 'timestamp' not in out.columns:
        out['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        # C9.6 Tiempo de Carro calculation with DNF replacement rule:
        # "If after discarding a team’s fastest time there remains less than two (2)
        # times from races finished, due to DNF’s, the slowest time recorded is again
        # input to the average equation until there are a total of four (4) times to average"
        # ----------------------------------------------------------------------
        if valid_count >= 3:
            # 3 or 4 valid races: discarding fastest leaves >= 2 times.
            # 2nd and 3rd best are index 1 and 2.
            avg_race_time = (sorted_valid_races[1] + sorted_valid_races[2]) / 2.0
        elif valid_count == 2:
            # 2 valid races: discarding fastest leaves only 1 time (< 2).
            # The slowest time recorded (index 1) is input again until 4 times: [r0, r1, r1, r1].
            # In these 4 times, 2nd and 3rd best are both r1. Average is r1.
            avg_race_time = sorted_valid_races[1]
        elif valid_count == 1:
            # 1 valid race: discarding fastest leaves 0 times (< 2).
            # The slowest (and only) recorded time r0 is input until 4 times: [r0, r0, r0, r0].
            # Average is r0.
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
    valid_car_teams = df_teams[df_teams['avg_race_time'].notna()].sort_values(by='avg_race_time', ascending=True).reset_index(drop=True)
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
                # C9.6: "Any team that has an average slower than the base time will score 20 points.
                # To further discriminate between these teams, a deduction will be made of 5 points for any DNF result"
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
            'has_time': True
        })

    for idx, row in unranked_car_teams.iterrows():
        # If team ran races but all were DNF/forfeit, apply 20 - 5*dnf
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
            'has_time': False
        })

    df_race_lb = pd.DataFrame(car_leaderboard)

    # ==========================================================================
    # LEADERBOARD 2: TIEMPO MÁS RÁPIDO / REACTION RACE (C9.5 & C9.8) - Max 110 Pts
    # ==========================================================================
    valid_tot_teams = df_teams[df_teams['min_total_time'].notna()].sort_values(by='min_total_time', ascending=True).reset_index(drop=True)
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
                # C9.5: "Any team with a best total race time slower than base time will score 5 points.
                # To further discriminate between any teams scoring 5 points, a deduction of 1 point will be made for any DNF"
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
            'has_time': True
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
            'has_time': False
        })

    df_total_lb = pd.DataFrame(tot_leaderboard)

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


def get_default_category_scores(teams: List[str], race_points_map: Dict[str, float]) -> pd.DataFrame:
    """
    Generate standard STEM Racing category scores for all 6 categories (990 total points):
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
        seed = sum(ord(c) for c in team)
        rng = np.random.default_rng(seed)

        carrera_pts = float(race_points_map.get(team, 0.0))
        identidad = int(rng.integers(70, 96))      # max 100
        verbal = int(rng.integers(115, 155))        # max 160
        escrutinio = int(rng.integers(120, 165))    # max 170
        diseno = int(rng.integers(130, 175))        # max 180
        gestion = int(rng.integers(115, 155))       # max 160

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
        # Random DNF
        return True, False, 0.000, 0.000
    elif roll < 0.28:
        # Random False Start
        return False, True, 0.000, 0.000
    else:
        # Valid run based on Racing Score Calculator.xlsx distributions
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


