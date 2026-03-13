import streamlit as st
import pandas as pd
import re
from typing import Dict, Optional, List, Tuple

st.set_page_config(page_title="Tactical Briefing Engine", layout="wide")


# ----------------------------------------------------
# UTIL
# ----------------------------------------------------

def safe_float(x, default=0.0):
    try:
        return float(str(x).replace(",", ".").replace("%", "").strip())
    except Exception:
        return default


def normalize_text(x) -> str:
    return str(x).strip().lower()


def is_empty(x) -> bool:
    s = normalize_text(x)
    return s in {"", "nan", "none"}


def parse_percent_like(x) -> Optional[float]:
    s = str(x).strip()
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*%", s)
    if m:
        return safe_float(m.group(1))
    return None


def parse_number_like(x) -> Optional[float]:
    s = str(x).strip()
    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", s):
        return safe_float(s)
    return None


def parse_ratio_like(x) -> Optional[Tuple[float, float]]:
    s = str(x).strip()
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*/\s*(-?\d+(?:[.,]\d+)?)", s)
    if m:
        return safe_float(m.group(1)), safe_float(m.group(2))
    return None


def coerce_cell_value(x):
    pct = parse_percent_like(x)
    if pct is not None:
        return pct

    num = parse_number_like(x)
    if num is not None:
        return num

    ratio = parse_ratio_like(x)
    if ratio is not None:
        return ratio[0]

    return x


# ----------------------------------------------------
# ALIASES
# Ezeket később tovább lehet finomítani a konkrét exporthoz
# ----------------------------------------------------

METRIC_ALIASES = {
    "ppda": [
        "ppda"
    ],
    "pressing_success_pct": [
        "pressing successful",
        "successful pressing",
        "pressing success",
        "pressing %"
    ],
    "passes_accurate_pct": [
        "passes accurate",
        "accurate passes %",
        "pass accuracy",
        "passes / accurate"
    ],
    "entries_box": [
        "entrances to the opponent's box",
        "entrances to opponents box",
        "entries into box",
        "box entries",
        "penalty box entries"
    ],
    "key_passes": [
        "key passes",
        "key pass"
    ],
    "corners": [
        "corners",
        "corner kicks"
    ],
    "possession_pct": [
        "ball possession",
        "possession %",
        "ball possession %"
    ],
    "shots": [
        "shots",
        "total shots"
    ],
    "xg": [
        "xg",
        "expected goals"
    ]
}


# ----------------------------------------------------
# COLUMN-ORIENTED PARSER
# ----------------------------------------------------

def find_total_row_index(df: pd.DataFrame) -> Optional[int]:
    for r in range(df.shape[0]):
        first_val = normalize_text(df.iat[r, 0])
        if first_val == "total":
            return r
    return None


def build_header_map(df: pd.DataFrame) -> Dict[int, str]:
    headers = {}
    if df.shape[0] == 0:
        return headers

    for c in range(df.shape[1]):
        headers[c] = normalize_text(df.iat[0, c])
    return headers


def find_column_by_aliases(header_map: Dict[int, str], aliases: List[str]) -> Optional[int]:
    for c, h in header_map.items():
        if is_empty(h):
            continue
        for alias in aliases:
            a = normalize_text(alias)
            if a == h or a in h:
                return c
    return None


def parse_main_statistics_sheet(df: pd.DataFrame) -> Dict[str, float]:
    metrics: Dict[str, float] = {}

    total_row = find_total_row_index(df)
    if total_row is None:
        return metrics

    header_map = build_header_map(df)

    for metric_key, aliases in METRIC_ALIASES.items():
        col = find_column_by_aliases(header_map, aliases)
        if col is None:
            continue

        raw_val = df.iat[total_row, col]
        val = coerce_cell_value(raw_val)

        if isinstance(val, (int, float)):
            metrics[metric_key] = float(val)

    return metrics


@st.cache_data(show_spinner=False)
def parse_excel_metrics(file_bytes: bytes) -> Dict[str, float]:
    metrics: Dict[str, float] = {}

    xls = pd.ExcelFile(file_bytes)

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)
        except Exception:
            continue

        sheet_name = normalize_text(sheet)

        if "main statistics" in sheet_name:
            sheet_metrics = parse_main_statistics_sheet(df)
            metrics.update(sheet_metrics)

    return metrics


# ----------------------------------------------------
# SIMPLE SCORING
# ----------------------------------------------------

def clamp(x, lo=1.0, hi=10.0):
    return max(lo, min(hi, x))


def normalize_score(v, a, b):
    if v == 0:
        return 5.0
    if b <= a:
        return 5.0
    return clamp(1 + 9 * ((v - a) / (b - a)))


def score_dimensions(metrics: Dict[str, float]) -> Dict[str, float]:
    return {
        "Letámadás": round(normalize_score(metrics.get("pressing_success_pct", 0), 25, 70), 1),
        "Labdakihozatal": round(normalize_score(metrics.get("passes_accurate_pct", 0), 60, 90), 1),
        "Átmenetek": round(normalize_score(metrics.get("entries_box", 0), 5, 30), 1),
        "Támadó játék": round(normalize_score(metrics.get("key_passes", 0), 1, 15), 1),
        "Pontrúgások": round(normalize_score(metrics.get("corners", 0), 1, 10), 1),
        "Labdabirtoklás": round(normalize_score(metrics.get("possession_pct", 0), 35, 65), 1),
        "Lövésprofil": round(normalize_score(metrics.get("shots", 0), 4, 20), 1),
    }


# ----------------------------------------------------
# ENGINE
# ----------------------------------------------------

def run_engine(team_file, opp_file):
    team_metrics = parse_excel_metrics(team_file.getvalue())
    opp_metrics = parse_excel_metrics(opp_file.getvalue())

    team_scores = score_dimensions(team_metrics)
    opp_scores = score_dimensions(opp_metrics)

    dims = {}
    for k in team_scores:
        dims[k] = {
            "KTE": team_scores[k],
            "ELL": opp_scores[k],
            "Edge": round(team_scores[k] - opp_scores[k], 1)
        }

    return dims, team_metrics, opp_metrics


# ----------------------------------------------------
# DEBUG HELPERS
# ----------------------------------------------------

def debug_sheet_info(file_obj):
    xls = pd.ExcelFile(file_obj)
    out = []

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_obj, sheet_name=sheet, header=None)
        except Exception:
            continue

        info = {
            "sheet_name": sheet,
            "preview": df.head(8),
            "header_row": df.iloc[0].astype(str).tolist() if df.shape[0] > 0 else [],
            "total_row_index": find_total_row_index(df),
            "total_row_values": None
        }

        total_idx = info["total_row_index"]
        if total_idx is not None:
            info["total_row_values"] = df.iloc[total_idx].astype(str).tolist()

        out.append(info)

    return out


# ----------------------------------------------------
# UI
# ----------------------------------------------------

st.title("Tactical Briefing Engine")

step = st.sidebar.radio("Lépés", ["Input", "Debug"], index=0)

if step == "Input":
    st.header("Excel feltöltés")

    kte = st.file_uploader("KTE Excel", type=["xlsx"], key="kte_input")
    opp = st.file_uploader("Opponent Excel", type=["xlsx"], key="opp_input")

    if kte and opp:
        dims, team_metrics, opp_metrics = run_engine(kte, opp)

        st.subheader("Kinyert metrikák – KTE")
        st.json(team_metrics)

        st.subheader("Kinyert metrikák – Ellenfél")
        st.json(opp_metrics)

        st.subheader("Dimenziók")
        st.dataframe(pd.DataFrame(dims).T, use_container_width=True)

elif step == "Debug":
    st.header("Debug")

    kte = st.file_uploader("KTE Excel", type=["xlsx"], key="kte_debug")
    opp = st.file_uploader("Opponent Excel", type=["xlsx"], key="opp_debug")

    if kte:
        st.subheader("KTE parser")
        st.json(parse_excel_metrics(kte.getvalue()))

        st.subheader("KTE sheet debug")
        kte_info = debug_sheet_info(kte)
        for item in kte_info:
            st.markdown(f"### KTE sheet: {item['sheet_name']}")
            st.dataframe(item["preview"], use_container_width=True)
            st.markdown("**Fejlécsor (0. sor):**")
            st.write(item["header_row"])
            st.markdown("**Total sor index:**")
            st.write(item["total_row_index"])
            st.markdown("**Total sor értékei:**")
            st.write(item["total_row_values"])

    if opp:
        st.subheader("Opponent parser")
        st.json(parse_excel_metrics(opp.getvalue()))

        st.subheader("Opponent sheet debug")
        opp_info = debug_sheet_info(opp)
        for item in opp_info:
            st.markdown(f"### Opponent sheet: {item['sheet_name']}")
            st.dataframe(item["preview"], use_container_width=True)
            st.markdown("**Fejlécsor (0. sor):**")
            st.write(item["header_row"])
            st.markdown("**Total sor index:**")
            st.write(item["total_row_index"])
            st.markdown("**Total sor értékei:**")
            st.write(item["total_row_values"])

    if kte and opp:
        st.subheader("Gyors összehasonlítás")
        kte_metrics = parse_excel_metrics(kte.getvalue())
        opp_metrics = parse_excel_metrics(opp.getvalue())

        rows = []
        all_keys = sorted(set(list(kte_metrics.keys()) + list(opp_metrics.keys())))
        for k in all_keys:
            rows.append({
                "metric": k,
                "kte": kte_metrics.get(k, 0),
                "opp": opp_metrics.get(k, 0),
                "same": kte_metrics.get(k, 0) == opp_metrics.get(k, 0)
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True)
