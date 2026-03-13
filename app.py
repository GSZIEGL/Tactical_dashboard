import math
import re
from typing import Dict, Optional, List, Tuple

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import altair as alt

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


def clamp(x, lo=1.0, hi=10.0):
    return max(lo, min(hi, x))


def normalize_score(v, a, b):
    if v == 0:
        return 5.0
    if b <= a:
        return 5.0
    return clamp(1 + 9 * ((v - a) / (b - a)))


# ----------------------------------------------------
# ALIASES
# Ezeket a debug tábla alapján lehet finomítani
# ----------------------------------------------------

METRIC_ALIASES = {
    "ppda": [
        "ppda"
    ],
    "pressing_success_pct": [
        "pressing successful",
        "successful pressing",
        "pressing success",
        "pressing %",
        "high pressing successful"
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
# COLUMN-ORIENTED PARSER WITH DEBUG
# ----------------------------------------------------

def find_total_row_index(df: pd.DataFrame) -> Optional[int]:
    for r in range(df.shape[0]):
        if normalize_text(df.iat[r, 0]) == "total":
            return r
    return None


def build_header_map(df: pd.DataFrame) -> Dict[int, str]:
    headers = {}
    if df.shape[0] == 0:
        return headers

    for c in range(df.shape[1]):
        headers[c] = normalize_text(df.iat[0, c])
    return headers


def find_column_by_aliases(header_map: Dict[int, str], aliases: List[str]) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    for c, h in header_map.items():
        if not h or h in {"nan", "none"}:
            continue
        for alias in aliases:
            a = normalize_text(alias)
            if a == h or a in h:
                return c, h, a
    return None, None, None


def parse_main_statistics_sheet(df: pd.DataFrame) -> Tuple[Dict[str, float], List[dict]]:
    metrics: Dict[str, float] = {}
    debug_rows: List[dict] = []

    total_row = find_total_row_index(df)
    if total_row is None:
        return metrics, debug_rows

    header_map = build_header_map(df)

    for metric_key, aliases in METRIC_ALIASES.items():
        col, header_hit, alias_hit = find_column_by_aliases(header_map, aliases)

        if col is None:
            debug_rows.append({
                "metric": metric_key,
                "matched_column_index": None,
                "matched_header": None,
                "matched_alias": None,
                "raw_total_value": None,
                "parsed_value": 0.0,
            })
            continue

        raw_val = df.iat[total_row, col]
        val = coerce_cell_value(raw_val)

        parsed_value = float(val) if isinstance(val, (int, float)) else 0.0
        metrics[metric_key] = parsed_value

        debug_rows.append({
            "metric": metric_key,
            "matched_column_index": col,
            "matched_header": header_hit,
            "matched_alias": alias_hit,
            "raw_total_value": raw_val,
            "parsed_value": parsed_value,
        })

    return metrics, debug_rows


@st.cache_data(show_spinner=False)
def parse_excel_metrics_with_debug(file_bytes: bytes) -> Tuple[Dict[str, float], List[dict], List[dict]]:
    metrics: Dict[str, float] = {}
    all_debug_rows: List[dict] = []
    sheet_debug: List[dict] = []

    xls = pd.ExcelFile(file_bytes)

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)
        except Exception:
            continue

        sheet_name = normalize_text(sheet)
        total_row_idx = find_total_row_index(df)
        header_map = build_header_map(df)

        sheet_debug.append({
            "sheet_name": sheet,
            "preview": df.head(8),
            "header_row": df.iloc[0].astype(str).tolist() if df.shape[0] > 0 else [],
            "total_row_index": total_row_idx,
            "total_row_values": df.iloc[total_row_idx].astype(str).tolist() if total_row_idx is not None else None
        })

        if "main statistics" in sheet_name:
            sheet_metrics, debug_rows = parse_main_statistics_sheet(df)
            metrics.update(sheet_metrics)

            for row in debug_rows:
                row["sheet"] = sheet
                all_debug_rows.append(row)

    return metrics, all_debug_rows, sheet_debug


def parse_excel_metrics(file_bytes: bytes) -> Dict[str, float]:
    metrics, _, _ = parse_excel_metrics_with_debug(file_bytes)
    return metrics


# ----------------------------------------------------
# SCORING
# ----------------------------------------------------

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
    team_metrics, team_debug_rows, team_sheet_debug = parse_excel_metrics_with_debug(team_file.getvalue())
    opp_metrics, opp_debug_rows, opp_sheet_debug = parse_excel_metrics_with_debug(opp_file.getvalue())

    team_scores = score_dimensions(team_metrics)
    opp_scores = score_dimensions(opp_metrics)

    dims = {}
    for k in team_scores:
        dims[k] = {
            "KTE": team_scores[k],
            "ELL": opp_scores[k],
            "Edge": round(team_scores[k] - opp_scores[k], 1)
        }

    return dims, team_metrics, opp_metrics, team_debug_rows, opp_debug_rows, team_sheet_debug, opp_sheet_debug


# ----------------------------------------------------
# CHARTS
# ----------------------------------------------------

def render_bar_chart(dims: Dict[str, Dict[str, float]]):
    rows = []
    for dim, vals in dims.items():
        rows.append({"Dimenzió": dim, "Csapat": "KTE", "Érték": vals["KTE"]})
        rows.append({"Dimenzió": dim, "Csapat": "ELL", "Érték": vals["ELL"]})

    df = pd.DataFrame(rows)

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("Dimenzió:N", sort=list(dims.keys())),
        y=alt.Y("Érték:Q", scale=alt.Scale(domain=[0, 10])),
        color="Csapat:N",
        xOffset="Csapat:N",
        tooltip=["Dimenzió", "Csapat", "Érték"]
    ).properties(height=360)

    st.altair_chart(chart, use_container_width=True)


def render_radar_svg(dims: Dict[str, Dict[str, float]]):
    labels = list(dims.keys())
    kte_vals = [dims[x]["KTE"] for x in labels]
    ell_vals = [dims[x]["ELL"] for x in labels]

    size = 620
    cx, cy = 280, 280
    max_r = 180
    n = len(labels)

    def polygon_points(values: List[float]):
        pts = []
        for i, val in enumerate(values):
            ang = -math.pi / 2 + (2 * math.pi * i / n)
            rr = (val / 10.0) * max_r
            x = cx + math.cos(ang) * rr
            y = cy + math.sin(ang) * rr
            pts.append((x, y))
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts), pts

    grid_polys = []
    axes = []
    label_svg = []

    for lvl in [2, 4, 6, 8, 10]:
        pts = []
        for i in range(n):
            ang = -math.pi / 2 + (2 * math.pi * i / n)
            rr = (lvl / 10.0) * max_r
            x = cx + math.cos(ang) * rr
            y = cy + math.sin(ang) * rr
            pts.append((x, y))
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        grid_polys.append(f'<polygon points="{pts_str}" fill="none" stroke="#D8D2E3" stroke-width="1" />')

    for i, label in enumerate(labels):
        ang = -math.pi / 2 + (2 * math.pi * i / n)
        x2 = cx + math.cos(ang) * max_r
        y2 = cy + math.sin(ang) * max_r
        axes.append(f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#D8D2E3" stroke-width="1" />')

        lx = cx + math.cos(ang) * (max_r + 40)
        ly = cy + math.sin(ang) * (max_r + 40)

        anchor = "middle"
        if lx < cx - 20:
            anchor = "end"
        elif lx > cx + 20:
            anchor = "start"

        label_svg.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="15" text-anchor="{anchor}" fill="#2F1D4A" font-weight="600">{label}</text>'
        )

    kte_poly, kte_pts = polygon_points(kte_vals)
    ell_poly, ell_pts = polygon_points(ell_vals)

    kte_circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#5B2C83" stroke="white" stroke-width="1.2" />'
        for x, y in kte_pts
    )
    ell_circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#B7A3C9" stroke="#5B2C83" stroke-width="1.0" />'
        for x, y in ell_pts
    )

    svg = f"""
    <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" fill="white" />
      {''.join(grid_polys)}
      {''.join(axes)}
      <polygon points="{ell_poly}" fill="rgba(183,163,201,0.28)" stroke="#9D8ABA" stroke-width="3" stroke-dasharray="6 4" />
      <polygon points="{kte_poly}" fill="rgba(91,44,131,0.18)" stroke="#5B2C83" stroke-width="3.2" />
      {ell_circles}
      {kte_circles}
      {''.join(label_svg)}
      <circle cx="455" cy="560" r="7" fill="#5B2C83" />
      <text x="470" y="565" font-size="15" fill="#2F1D4A">KTE</text>
      <circle cx="520" cy="560" r="7" fill="#B7A3C9" stroke="#5B2C83" stroke-width="1" />
      <text x="535" y="565" font-size="15" fill="#2F1D4A">ELL</text>
    </svg>
    """
    components.html(svg, height=650)


# ----------------------------------------------------
# DATA QUALITY
# ----------------------------------------------------

def distinct_metric_count(team_metrics: Dict[str, float], opp_metrics: Dict[str, float]) -> int:
    keys = sorted(set(team_metrics.keys()) | set(opp_metrics.keys()))
    count = 0
    for k in keys:
        if team_metrics.get(k, 0) != opp_metrics.get(k, 0):
            count += 1
    return count


# ----------------------------------------------------
# UI
# ----------------------------------------------------

st.title("Tactical Briefing Engine")

step = st.sidebar.radio("Lépés", ["Input", "Review", "Debug"], index=0)

if "dims" not in st.session_state:
    st.session_state["dims"] = None
if "team_metrics" not in st.session_state:
    st.session_state["team_metrics"] = None
if "opp_metrics" not in st.session_state:
    st.session_state["opp_metrics"] = None
if "team_debug_rows" not in st.session_state:
    st.session_state["team_debug_rows"] = None
if "opp_debug_rows" not in st.session_state:
    st.session_state["opp_debug_rows"] = None
if "team_sheet_debug" not in st.session_state:
    st.session_state["team_sheet_debug"] = None
if "opp_sheet_debug" not in st.session_state:
    st.session_state["opp_sheet_debug"] = None


# ----------------------------------------------------
# INPUT
# ----------------------------------------------------

if step == "Input":
    st.header("Excel feltöltés")

    kte = st.file_uploader("KTE Excel", type=["xlsx"], key="kte_input")
    opp = st.file_uploader("Opponent Excel", type=["xlsx"], key="opp_input")

    if kte and opp:
        dims, team_metrics, opp_metrics, team_debug_rows, opp_debug_rows, team_sheet_debug, opp_sheet_debug = run_engine(kte, opp)

        st.session_state["dims"] = dims
        st.session_state["team_metrics"] = team_metrics
        st.session_state["opp_metrics"] = opp_metrics
        st.session_state["team_debug_rows"] = team_debug_rows
        st.session_state["opp_debug_rows"] = opp_debug_rows
        st.session_state["team_sheet_debug"] = team_sheet_debug
        st.session_state["opp_sheet_debug"] = opp_sheet_debug

        st.success("Adatok feldolgozva.")

        st.subheader("Kinyert metrikák – KTE")
        st.json(team_metrics)

        st.subheader("Kinyert metrikák – Ellenfél")
        st.json(opp_metrics)

        diff_count = distinct_metric_count(team_metrics, opp_metrics)
        if diff_count < 2:
            st.warning(f"Nagyon kevés eltérő nyers metrika van a két csapat között ({diff_count}). Ilyenkor a dimenziók torzak lehetnek.")


# ----------------------------------------------------
# REVIEW
# ----------------------------------------------------

if step == "Review":
    dims = st.session_state.get("dims")
    team_metrics = st.session_state.get("team_metrics")
    opp_metrics = st.session_state.get("opp_metrics")

    if not dims:
        st.warning("Előbb tölts fel adatot az Input fülön.")
    else:
        diff_count = distinct_metric_count(team_metrics, opp_metrics)
        if diff_count < 2:
            st.error("A KTE és az ellenfél között túl kevés eltérő nyers metrika van. Előbb nézd meg a Debug fület.")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Pókháló")
            render_radar_svg(dims)

        with col2:
            st.subheader("Dimenziók")
            render_bar_chart(dims)

        st.subheader("Dimenzió tábla")
        st.dataframe(pd.DataFrame(dims).T, use_container_width=True)

        st.subheader("Stratégiai opciók")
        STRATEGY_PALETTE = {
            "KON": "Kontra mély blokkból",
            "GAT": "Gyors átmenet",
            "BAT": "Középső blokk + átmenet",
            "KIE": "Kiegyensúlyozott",
            "PRS": "Presszing + átmenet",
            "MLT": "Magas letámadás",
            "DOM": "Dominancia",
            "POZ": "Pozíciós támadás",
            "LAB": "Labdatartás"
        }

        p1, p2, p3 = st.columns(3)
        with p1:
            plan_a = st.selectbox("Plan A", list(STRATEGY_PALETTE.keys()))
        with p2:
            plan_b = st.selectbox("Plan B", list(STRATEGY_PALETTE.keys()), index=1)
        with p3:
            split = st.slider("Plan A arány", 50, 70, 60)

        st.write("Plan A:", STRATEGY_PALETTE[plan_a])
        st.write("Plan B:", STRATEGY_PALETTE[plan_b])
        st.info(f"Arány: {split}/{100-split}")


# ----------------------------------------------------
# DEBUG
# ----------------------------------------------------

if step == "Debug":
    st.header("Debug")

    kte = st.file_uploader("KTE Excel", type=["xlsx"], key="kte_debug")
    opp = st.file_uploader("Opponent Excel", type=["xlsx"], key="opp_debug")

    if kte:
        team_metrics, team_debug_rows, team_sheet_debug = parse_excel_metrics_with_debug(kte.getvalue())

        st.subheader("KTE parser találatok")
        st.json(team_metrics)

        st.subheader("KTE metrika → oszlop illesztés")
        st.dataframe(pd.DataFrame(team_debug_rows), use_container_width=True)

        st.subheader("KTE sheet debug")
        for item in team_sheet_debug:
            st.markdown(f"### KTE sheet: {item['sheet_name']}")
            st.dataframe(item["preview"], use_container_width=True)
            st.markdown("**Fejlécsor (0. sor):**")
            st.write(item["header_row"])
            st.markdown("**Total sor index:**")
            st.write(item["total_row_index"])
            st.markdown("**Total sor értékei:**")
            st.write(item["total_row_values"])

    if opp:
        opp_metrics, opp_debug_rows, opp_sheet_debug = parse_excel_metrics_with_debug(opp.getvalue())

        st.subheader("Opponent parser találatok")
        st.json(opp_metrics)

        st.subheader("Opponent metrika → oszlop illesztés")
        st.dataframe(pd.DataFrame(opp_debug_rows), use_container_width=True)

        st.subheader("Opponent sheet debug")
        for item in opp_sheet_debug:
            st.markdown(f"### Opponent sheet: {item['sheet_name']}")
            st.dataframe(item["preview"], use_container_width=True)
            st.markdown("**Fejlécsor (0. sor):**")
            st.write(item["header_row"])
            st.markdown("**Total sor index:**")
            st.write(item["total_row_index"])
            st.markdown("**Total sor értékei:**")
            st.write(item["total_row_values"])

    if kte and opp:
        st.subheader("KTE vs Opponent – nyers metrika összehasonlítás")

        team_metrics, team_debug_rows, _ = parse_excel_metrics_with_debug(kte.getvalue())
        opp_metrics, opp_debug_rows, _ = parse_excel_metrics_with_debug(opp.getvalue())

        compare_rows = []
        all_keys = sorted(set(list(team_metrics.keys()) + list(opp_metrics.keys())))
        debug_team_map = {x["metric"]: x for x in team_debug_rows}
        debug_opp_map = {x["metric"]: x for x in opp_debug_rows}

        for k in all_keys:
            compare_rows.append({
                "metric": k,
                "kte_value": team_metrics.get(k, 0),
                "opp_value": opp_metrics.get(k, 0),
                "same_value": team_metrics.get(k, 0) == opp_metrics.get(k, 0),
                "kte_header": debug_team_map.get(k, {}).get("matched_header"),
                "opp_header": debug_opp_map.get(k, {}).get("matched_header"),
                "kte_raw": debug_team_map.get(k, {}).get("raw_total_value"),
                "opp_raw": debug_opp_map.get(k, {}).get("raw_total_value"),
            })

        st.dataframe(pd.DataFrame(compare_rows), use_container_width=True)

        diff_count = distinct_metric_count(team_metrics, opp_metrics)
        st.write("Eltérő metrikák száma:", diff_count)
