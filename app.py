import math
import re
from typing import Dict, Optional, List, Tuple

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Tactical Briefing Engine", layout="wide")


# =========================================================
# UTIL
# =========================================================

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


# =========================================================
# STRATEGY PALETTE
# =========================================================

STRATEGY_PALETTE = {
    "KON": {
        "name": "Kontra mély blokkból",
        "block": "low",
        "style": "direct",
    },
    "GAT": {
        "name": "Gyors átmenet",
        "block": "mid",
        "style": "direct",
    },
    "BAT": {
        "name": "Középső blokk + átmenet",
        "block": "mid",
        "style": "balanced",
    },
    "KIE": {
        "name": "Kiegyensúlyozott",
        "block": "mid",
        "style": "balanced_control",
    },
    "PRS": {
        "name": "Presszing + átmenet",
        "block": "mid_high",
        "style": "transition_press",
    },
    "MLT": {
        "name": "Magas letámadás",
        "block": "high",
        "style": "aggressive",
    },
    "DOM": {
        "name": "Dominancia",
        "block": "high",
        "style": "control",
    },
    "POZ": {
        "name": "Pozíciós támadás",
        "block": "mid_high",
        "style": "control",
    },
    "LAB": {
        "name": "Labdatartás mélyebben",
        "block": "low_mid",
        "style": "control",
    },
}


def strategy_palette_rows() -> List[dict]:
    label_block = {
        "low": "mély",
        "low_mid": "alacsony-közép",
        "mid": "közép",
        "mid_high": "közép-magas",
        "high": "magas",
    }
    label_style = {
        "direct": "direkt",
        "transition_press": "presszing+átmenet",
        "balanced": "vegyes",
        "balanced_control": "kiegyensúlyozott",
        "control": "kontroll",
        "aggressive": "agresszív",
    }
    return [
        {
            "Kód": k,
            "Stratégia": v["name"],
            "Blokkmagasság": label_block[v["block"]],
            "Játékstílus": label_style[v["style"]],
        }
        for k, v in STRATEGY_PALETTE.items()
    ]


def strategy_scatter_data(selected_a: Optional[str] = None, selected_b: Optional[str] = None) -> List[dict]:
    block_map = {"low": 1, "low_mid": 2, "mid": 3, "mid_high": 4, "high": 5}
    style_map = {
        "direct": 1,
        "transition_press": 2,
        "balanced": 3,
        "balanced_control": 4,
        "control": 5,
        "aggressive": 6,
    }
    style_label = {
        1: "Direkt",
        2: "D/P",
        3: "Vegyes",
        4: "Kiegy.",
        5: "Kontroll",
        6: "Agresszív",
    }
    block_label = {
        1: "Mély",
        2: "Low-mid",
        3: "Közép",
        4: "Mid-high",
        5: "Magas",
    }

    rows = []
    for code, data in STRATEGY_PALETTE.items():
        rows.append(
            {
                "x": style_map.get(data["style"], 3),
                "y": block_map.get(data["block"], 3),
                "code": code,
                "strategy": data["name"],
                "style_label": style_label[style_map.get(data["style"], 3)],
                "block_label": block_label[block_map.get(data["block"], 3)],
                "marker_type": "Plan A" if code == selected_a else "Plan B" if code == selected_b else "Paletta",
            }
        )
    return rows


def render_strategy_map(selected_a: Optional[str] = None, selected_b: Optional[str] = None):
    rows = strategy_scatter_data(selected_a, selected_b)
    spec = {
        "width": "container",
        "height": 430,
        "data": {"values": rows},
        "layer": [
            {
                "mark": {"type": "text", "fontSize": 20, "fontWeight": "bold"},
                "encoding": {
                    "x": {
                        "field": "x",
                        "type": "quantitative",
                        "scale": {"domain": [0.5, 6.5]},
                        "axis": {
                            "title": "Játékstílus: Direkt → Kontroll",
                            "values": [1, 2, 3, 4, 5, 6],
                            "labelExpr": "datum.value == 1 ? 'Direkt' : datum.value == 2 ? 'D/P' : datum.value == 3 ? 'Vegyes' : datum.value == 4 ? 'Kiegy.' : datum.value == 5 ? 'Kontroll' : 'Agresszív'",
                            "grid": True,
                        },
                    },
                    "y": {
                        "field": "y",
                        "type": "quantitative",
                        "scale": {"domain": [0.5, 5.5]},
                        "axis": {
                            "title": "Blokkmagasság: Mély → Magas",
                            "values": [1, 2, 3, 4, 5],
                            "labelExpr": "datum.value == 1 ? 'Mély' : datum.value == 2 ? 'Low-mid' : datum.value == 3 ? 'Közép' : datum.value == 4 ? 'Mid-high' : 'Magas'",
                            "grid": True,
                        },
                    },
                    "text": {"field": "code"},
                    "color": {
                        "field": "marker_type",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Paletta", "Plan A", "Plan B"],
                            "range": ["#5B2C83", "#E0A500", "#2AA7A1"],
                        },
                        "legend": {"title": "Jelölés"},
                    },
                    "tooltip": [
                        {"field": "code", "title": "Kód"},
                        {"field": "strategy", "title": "Stratégia"},
                        {"field": "block_label", "title": "Blokk"},
                        {"field": "style_label", "title": "Stílus"},
                    ],
                },
            }
        ],
        "config": {"view": {"stroke": "#D9D9D9"}},
    }
    st.vega_lite_chart(rows, spec, use_container_width=True)


# =========================================================
# METRIC ALIASES
# =========================================================

METRIC_ALIASES = {
    "ppda": [
        "ppda"
    ],
    "pressing_success_pct": [
        "team pressing successful, %",
        "pressing successful",
        "successful pressing",
        "pressing success",
        "pressing %",
    ],
    "passes_accurate_pct": [
        "passes accurate, %",
        "passes accurate",
        "accurate passes %",
        "pass accuracy",
        "passes / accurate",
    ],
    "entries_box": [
        "entrances to the opponent's box",
        "entrances to opponents box",
        "entries into box",
        "box entries",
        "penalty box entries",
    ],
    "key_passes": [
        "key passes",
        "key pass",
    ],
    "corners": [
        "corners",
        "corner kicks",
    ],
    "possession_pct": [
        "ball possession, %",
        "ball possession",
        "possession %",
        "ball possession %",
    ],
    "shots": [
        "shots",
        "total shots",
    ],
    "xg": [
        "xg",
        "expected goals",
    ],
}


# =========================================================
# PARSER
# =========================================================

def find_total_row_index(df: pd.DataFrame) -> Optional[int]:
    for r in range(df.shape[0]):
        if normalize_text(df.iat[r, 0]) == "total":
            return r
    return None


def find_match_count_from_date_column(df: pd.DataFrame) -> int:
    count = 0
    for r in range(1, df.shape[0]):
        first_val = str(df.iat[r, 0]).strip()
        first_norm = normalize_text(first_val)
        if first_norm in {"", "nan", "none", "total"}:
            continue
        count += 1
    return count


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


def parse_main_statistics_sheet(df: pd.DataFrame) -> Tuple[Dict[str, float], List[dict], int]:
    metrics: Dict[str, float] = {}
    debug_rows: List[dict] = []

    total_row = find_total_row_index(df)
    match_count = find_match_count_from_date_column(df)

    if total_row is None:
        return metrics, debug_rows, match_count

    header_map = build_header_map(df)

    for metric_key, aliases in METRIC_ALIASES.items():
        col, header_hit, alias_hit = find_column_by_aliases(header_map, aliases)

        if col is None:
            debug_rows.append(
                {
                    "metric": metric_key,
                    "matched_column_index": None,
                    "matched_header": None,
                    "matched_alias": None,
                    "raw_total_value": None,
                    "parsed_value": 0.0,
                }
            )
            continue

        raw_val = df.iat[total_row, col]
        val = coerce_cell_value(raw_val)
        parsed_value = float(val) if isinstance(val, (int, float)) else 0.0
        metrics[metric_key] = parsed_value

        debug_rows.append(
            {
                "metric": metric_key,
                "matched_column_index": col,
                "matched_header": header_hit,
                "matched_alias": alias_hit,
                "raw_total_value": raw_val,
                "parsed_value": parsed_value,
            }
        )

    return metrics, debug_rows, match_count


@st.cache_data(show_spinner=False)
def parse_excel_metrics_with_debug(file_bytes: bytes) -> Tuple[Dict[str, float], List[dict], List[dict], int]:
    metrics: Dict[str, float] = {}
    all_debug_rows: List[dict] = []
    sheet_debug: List[dict] = []
    match_count = 0

    xls = pd.ExcelFile(file_bytes)

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)
        except Exception:
            continue

        sheet_name = normalize_text(sheet)
        total_row_idx = find_total_row_index(df)
        local_match_count = find_match_count_from_date_column(df)

        sheet_debug.append(
            {
                "sheet_name": sheet,
                "preview": df.head(8),
                "header_row": df.iloc[0].astype(str).tolist() if df.shape[0] > 0 else [],
                "total_row_index": total_row_idx,
                "match_count": local_match_count,
                "total_row_values": df.iloc[total_row_idx].astype(str).tolist() if total_row_idx is not None else None,
            }
        )

        if "main statistics" in sheet_name:
            sheet_metrics, debug_rows, match_count = parse_main_statistics_sheet(df)
            metrics.update(sheet_metrics)

            for row in debug_rows:
                row["sheet"] = sheet
                all_debug_rows.append(row)

    return metrics, all_debug_rows, sheet_debug, match_count


def parse_excel_metrics(file_bytes: bytes) -> Dict[str, float]:
    metrics, _, _, _ = parse_excel_metrics_with_debug(file_bytes)
    return metrics


# =========================================================
# SCORING
# =========================================================

def score_dimensions(metrics: Dict[str, float], matches: int) -> Dict[str, float]:
    if matches <= 0:
        matches = 1

    entries_pm = metrics.get("entries_box", 0) / matches
    shots_pm = metrics.get("shots", 0) / matches
    key_pass_pm = metrics.get("key_passes", 0) / matches
    corners_pm = metrics.get("corners", 0) / matches

    pressing_pct = metrics.get("pressing_success_pct", 0)
    pass_acc_pct = metrics.get("passes_accurate_pct", 0)
    possession_pct = metrics.get("possession_pct", 0)

    if pressing_pct <= 1:
        pressing_pct *= 100
    if pass_acc_pct <= 1:
        pass_acc_pct *= 100
    if possession_pct <= 1:
        possession_pct *= 100

    return {
        "Letámadás": round(normalize_score(pressing_pct, 25, 70), 1),
        "Labdakihozatal": round(normalize_score(pass_acc_pct, 60, 90), 1),
        "Átmenetek": round(normalize_score(entries_pm, 5, 25), 1),
        "Támadó játék": round(normalize_score(key_pass_pm, 1, 6), 1),
        "Pontrúgások": round(normalize_score(corners_pm, 1, 7), 1),
        "Labdabirtoklás": round(normalize_score(possession_pct, 40, 65), 1),
        "Lövésprofil": round(normalize_score(shots_pm, 5, 20), 1),
    }


def distinct_metric_count(team_metrics: Dict[str, float], opp_metrics: Dict[str, float]) -> int:
    keys = sorted(set(team_metrics.keys()) | set(opp_metrics.keys()))
    count = 0
    for k in keys:
        if team_metrics.get(k, 0) != opp_metrics.get(k, 0):
            count += 1
    return count


def dimension_rows(dims: Dict[str, Dict[str, float]]) -> List[dict]:
    return [
        {
            "Dimenzió": dim,
            "KTE": float(vals["KTE"]),
            "ELL": float(vals["ELL"]),
            "Edge": float(vals["Edge"]),
        }
        for dim, vals in dims.items()
    ]


# =========================================================
# ENGINE
# =========================================================

def run_engine(team_file, opp_file):
    team_metrics, team_debug_rows, team_sheet_debug, team_matches = parse_excel_metrics_with_debug(team_file.getvalue())
    opp_metrics, opp_debug_rows, opp_sheet_debug, opp_matches = parse_excel_metrics_with_debug(opp_file.getvalue())

    team_scores = score_dimensions(team_metrics, team_matches)
    opp_scores = score_dimensions(opp_metrics, opp_matches)

    dims = {}
    for k in team_scores:
        dims[k] = {
            "KTE": team_scores[k],
            "ELL": opp_scores[k],
            "Edge": round(team_scores[k] - opp_scores[k], 1),
        }

    edge_transition = team_scores["Átmenetek"] - opp_scores["Lövésprofil"]
    edge_control = team_scores["Labdakihozatal"] + team_scores["Labdabirtoklás"] - opp_scores["Letámadás"]
    edge_attack = team_scores["Támadó játék"] + team_scores["Pontrúgások"] - opp_scores["Labdabirtoklás"]

    if edge_transition >= max(edge_control, edge_attack):
        suggested_a, suggested_b, suggested_split = "GAT", "BAT", 60
    elif edge_control >= max(edge_transition, edge_attack):
        suggested_a, suggested_b, suggested_split = "KIE", "POZ", 55
    else:
        suggested_a, suggested_b, suggested_split = "PRS", "MLT", 55

    return (
        dims,
        team_metrics,
        opp_metrics,
        team_debug_rows,
        opp_debug_rows,
        team_sheet_debug,
        opp_sheet_debug,
        team_matches,
        opp_matches,
        suggested_a,
        suggested_b,
        suggested_split,
    )


# =========================================================
# CHARTS
# =========================================================

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
        tooltip=["Dimenzió", "Csapat", "Érték"],
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


# =========================================================
# APP STATE
# =========================================================

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
if "team_matches" not in st.session_state:
    st.session_state["team_matches"] = None
if "opp_matches" not in st.session_state:
    st.session_state["opp_matches"] = None
if "selected_plan_a" not in st.session_state:
    st.session_state["selected_plan_a"] = "GAT"
if "selected_plan_b" not in st.session_state:
    st.session_state["selected_plan_b"] = "BAT"
if "selected_split" not in st.session_state:
    st.session_state["selected_split"] = 60


# =========================================================
# UI
# =========================================================

st.title("Tactical Briefing Engine")
st.sidebar.caption("D/P = Direkt / Presszing")

step = st.sidebar.radio(
    "Lépés",
    ["1. Input", "2. Review", "3. Debug"],
    index=0,
)


# =========================================================
# INPUT
# =========================================================

if step == "1. Input":
    st.header("Excel feltöltés")

    kte = st.file_uploader("KTE Excel", type=["xlsx"], key="kte_input")
    opp = st.file_uploader("Opponent Excel", type=["xlsx"], key="opp_input")

    if kte and opp:
        (
            dims,
            team_metrics,
            opp_metrics,
            team_debug_rows,
            opp_debug_rows,
            team_sheet_debug,
            opp_sheet_debug,
            team_matches,
            opp_matches,
            suggested_a,
            suggested_b,
            suggested_split,
        ) = run_engine(kte, opp)

        st.session_state["dims"] = dims
        st.session_state["team_metrics"] = team_metrics
        st.session_state["opp_metrics"] = opp_metrics
        st.session_state["team_debug_rows"] = team_debug_rows
        st.session_state["opp_debug_rows"] = opp_debug_rows
        st.session_state["team_sheet_debug"] = team_sheet_debug
        st.session_state["opp_sheet_debug"] = opp_sheet_debug
        st.session_state["team_matches"] = team_matches
        st.session_state["opp_matches"] = opp_matches
        st.session_state["selected_plan_a"] = suggested_a
        st.session_state["selected_plan_b"] = suggested_b
        st.session_state["selected_split"] = suggested_split

        st.success("Adatok feldolgozva.")

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("KTE – nyers metrikák")
            st.json(team_metrics)
            st.write("Meccsszám:", team_matches)
        with c2:
            st.subheader("ELL – nyers metrikák")
            st.json(opp_metrics)
            st.write("Meccsszám:", opp_matches)

        diff_count = distinct_metric_count(team_metrics, opp_metrics)
        st.write("Eltérő nyers metrikák száma:", diff_count)

        if diff_count < 2:
            st.warning(f"Nagyon kevés eltérő nyers metrika van a két csapat között ({diff_count}).")


# =========================================================
# REVIEW
# =========================================================

if step == "2. Review":
    dims = st.session_state.get("dims")
    team_metrics = st.session_state.get("team_metrics")
    opp_metrics = st.session_state.get("opp_metrics")
    team_matches = st.session_state.get("team_matches")
    opp_matches = st.session_state.get("opp_matches")

    if not dims:
        st.warning("Előbb tölts fel adatot az Input fülön.")
    else:
        diff_count = distinct_metric_count(team_metrics, opp_metrics)

        if diff_count < 2:
            st.error("A KTE és az ellenfél között túl kevés eltérő nyers metrika van. Nézd meg a Debug fület.")

        top1, top2, top3 = st.columns(3)
        top1.metric("Ajánlott Plan A", st.session_state["selected_plan_a"])
        top2.metric("Ajánlott Plan B", st.session_state["selected_plan_b"])
        top3.metric("Arány", f"{st.session_state['selected_split']}/{100 - st.session_state['selected_split']}")

        st.subheader("9 taktikai opció – stratégiai térkép")
        render_strategy_map(st.session_state["selected_plan_a"], st.session_state["selected_plan_b"])

        p1, p2, p3 = st.columns(3)
        with p1:
            st.session_state["selected_plan_a"] = st.selectbox(
                "Plan A",
                options=list(STRATEGY_PALETTE.keys()),
                index=list(STRATEGY_PALETTE.keys()).index(st.session_state["selected_plan_a"]),
                format_func=lambda x: f"{x} – {STRATEGY_PALETTE[x]['name']}",
            )
        with p2:
            available_b = [x for x in STRATEGY_PALETTE.keys() if x != st.session_state["selected_plan_a"]]
            current_b = st.session_state["selected_plan_b"]
            if current_b not in available_b:
                current_b = available_b[0]
            st.session_state["selected_plan_b"] = st.selectbox(
                "Plan B",
                options=available_b,
                index=available_b.index(current_b),
                format_func=lambda x: f"{x} – {STRATEGY_PALETTE[x]['name']}",
            )
        with p3:
            st.session_state["selected_split"] = st.slider(
                "Plan A arány (%)",
                min_value=50,
                max_value=70,
                value=st.session_state["selected_split"],
            )

        st.info("Az arány nem szavazás. A Plan A az alap játékmodell, a Plan B az alkalmazkodó kiegészítés várható megoszlása.")

        with st.expander("A 9 taktikai opció táblázata", expanded=False):
            st.table(strategy_palette_rows())

        st.subheader("Dimenzió tábla")
        st.dataframe(pd.DataFrame(dims).T, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Pókháló")
            render_radar_svg(dims)
        with c2:
            st.subheader("Dimenziók")
            render_bar_chart(dims)

        st.subheader("Skálázási háttér")
        scaling_rows = [
            {
                "mutató": "entries_box / meccs",
                "KTE": round(team_metrics.get("entries_box", 0) / max(team_matches or 1, 1), 2),
                "ELL": round(opp_metrics.get("entries_box", 0) / max(opp_matches or 1, 1), 2),
            },
            {
                "mutató": "shots / meccs",
                "KTE": round(team_metrics.get("shots", 0) / max(team_matches or 1, 1), 2),
                "ELL": round(opp_metrics.get("shots", 0) / max(opp_matches or 1, 1), 2),
            },
            {
                "mutató": "key_passes / meccs",
                "KTE": round(team_metrics.get("key_passes", 0) / max(team_matches or 1, 1), 2),
                "ELL": round(opp_metrics.get("key_passes", 0) / max(opp_matches or 1, 1), 2),
            },
            {
                "mutató": "corners / meccs",
                "KTE": round(team_metrics.get("corners", 0) / max(team_matches or 1, 1), 2),
                "ELL": round(opp_metrics.get("corners", 0) / max(opp_matches or 1, 1), 2),
            },
            {
                "mutató": "passes_accurate_pct",
                "KTE": round((team_metrics.get("passes_accurate_pct", 0) * 100) if team_metrics.get("passes_accurate_pct", 0) <= 1 else team_metrics.get("passes_accurate_pct", 0), 2),
                "ELL": round((opp_metrics.get("passes_accurate_pct", 0) * 100) if opp_metrics.get("passes_accurate_pct", 0) <= 1 else opp_metrics.get("passes_accurate_pct", 0), 2),
            },
            {
                "mutató": "pressing_success_pct",
                "KTE": round((team_metrics.get("pressing_success_pct", 0) * 100) if team_metrics.get("pressing_success_pct", 0) <= 1 else team_metrics.get("pressing_success_pct", 0), 2),
                "ELL": round((opp_metrics.get("pressing_success_pct", 0) * 100) if opp_metrics.get("pressing_success_pct", 0) <= 1 else opp_metrics.get("pressing_success_pct", 0), 2),
            },
            {
                "mutató": "possession_pct",
                "KTE": round((team_metrics.get("possession_pct", 0) * 100) if team_metrics.get("possession_pct", 0) <= 1 else team_metrics.get("possession_pct", 0), 2),
                "ELL": round((opp_metrics.get("possession_pct", 0) * 100) if opp_metrics.get("possession_pct", 0) <= 1 else opp_metrics.get("possession_pct", 0), 2),
            },
        ]
        st.dataframe(pd.DataFrame(scaling_rows), use_container_width=True)

        st.subheader("Gyors briefing draft")
        briefing_left, briefing_right = st.columns(2)

        with briefing_left:
            st.text_area(
                "Ellenfél profil",
                value=(
                    f"Labdabirtoklás: {round((opp_metrics.get('possession_pct', 0) * 100) if opp_metrics.get('possession_pct', 0) <= 1 else opp_metrics.get('possession_pct', 0), 1)}% | "
                    f"Lövések / meccs: {round(opp_metrics.get('shots', 0) / max(opp_matches or 1, 1), 2)} | "
                    f"Box entries / meccs: {round(opp_metrics.get('entries_box', 0) / max(opp_matches or 1, 1), 2)}"
                ),
                height=100,
            )
            st.text_area(
                "Saját állapot",
                value=(
                    f"KTE passzpontosság: {round((team_metrics.get('passes_accurate_pct', 0) * 100) if team_metrics.get('passes_accurate_pct', 0) <= 1 else team_metrics.get('passes_accurate_pct', 0), 1)}% | "
                    f"KTE lövések / meccs: {round(team_metrics.get('shots', 0) / max(team_matches or 1, 1), 2)} | "
                    f"KTE key passes / meccs: {round(team_metrics.get('key_passes', 0) / max(team_matches or 1, 1), 2)}"
                ),
                height=100,
            )

        with briefing_right:
            st.text_area(
                "3 kulcs",
                value="\n".join([
                    "1. Átmenetek sebességének kihasználása",
                    "2. Labdakihozatal stabilizálása nyomás alatt",
                    "3. Pontrúgások és második labdák kontrollja",
                ]),
                height=100,
            )
            st.text_area(
                "Konklúzió",
                value=(
                    f"Ajánlott fő stratégia: {st.session_state['selected_plan_a']} – {STRATEGY_PALETTE[st.session_state['selected_plan_a']]['name']}\n"
                    f"Alternatíva: {st.session_state['selected_plan_b']} – {STRATEGY_PALETTE[st.session_state['selected_plan_b']]['name']}\n"
                    f"Javasolt megoszlás: {st.session_state['selected_split']}/{100 - st.session_state['selected_split']}"
                ),
                height=100,
            )


# =========================================================
# DEBUG
# =========================================================

if step == "3. Debug":
    st.header("Debug")

    kte = st.file_uploader("KTE Excel", type=["xlsx"], key="kte_debug")
    opp = st.file_uploader("Opponent Excel", type=["xlsx"], key="opp_debug")

    if kte:
        team_metrics, team_debug_rows, team_sheet_debug, team_matches = parse_excel_metrics_with_debug(kte.getvalue())

        st.subheader("KTE parser találatok")
        st.json(team_metrics)
        st.write("KTE meccsszám:", team_matches)

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
            st.markdown("**Meccsszám:**")
            st.write(item["match_count"])
            st.markdown("**Total sor értékei:**")
            st.write(item["total_row_values"])

    if opp:
        opp_metrics, opp_debug_rows, opp_sheet_debug, opp_matches = parse_excel_metrics_with_debug(opp.getvalue())

        st.subheader("Opponent parser találatok")
        st.json(opp_metrics)
        st.write("ELL meccsszám:", opp_matches)

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
            st.markdown("**Meccsszám:**")
            st.write(item["match_count"])
            st.markdown("**Total sor értékei:**")
            st.write(item["total_row_values"])

    if kte and opp:
        st.subheader("KTE vs Opponent – nyers metrika összehasonlítás")

        team_metrics, team_debug_rows, _, team_matches = parse_excel_metrics_with_debug(kte.getvalue())
        opp_metrics, opp_debug_rows, _, opp_matches = parse_excel_metrics_with_debug(opp.getvalue())

        compare_rows = []
        all_keys = sorted(set(list(team_metrics.keys()) + list(opp_metrics.keys())))
        debug_team_map = {x["metric"]: x for x in team_debug_rows}
        debug_opp_map = {x["metric"]: x for x in opp_debug_rows}

        for k in all_keys:
            compare_rows.append(
                {
                    "metric": k,
                    "kte_value": team_metrics.get(k, 0),
                    "opp_value": opp_metrics.get(k, 0),
                    "same_value": team_metrics.get(k, 0) == opp_metrics.get(k, 0),
                    "kte_header": debug_team_map.get(k, {}).get("matched_header"),
                    "opp_header": debug_opp_map.get(k, {}).get("matched_header"),
                    "kte_raw": debug_team_map.get(k, {}).get("raw_total_value"),
                    "opp_raw": debug_opp_map.get(k, {}).get("raw_total_value"),
                }
            )

        st.dataframe(pd.DataFrame(compare_rows), use_container_width=True)

        st.subheader("Per meccs skálázott mutatók")
        per_match_rows = [
            {
                "metric": "entries_box_per_match",
                "kte": round(team_metrics.get("entries_box", 0) / max(team_matches, 1), 2),
                "opp": round(opp_metrics.get("entries_box", 0) / max(opp_matches, 1), 2),
            },
            {
                "metric": "shots_per_match",
                "kte": round(team_metrics.get("shots", 0) / max(team_matches, 1), 2),
                "opp": round(opp_metrics.get("shots", 0) / max(opp_matches, 1), 2),
            },
            {
                "metric": "key_passes_per_match",
                "kte": round(team_metrics.get("key_passes", 0) / max(team_matches, 1), 2),
                "opp": round(opp_metrics.get("key_passes", 0) / max(opp_matches, 1), 2),
            },
            {
                "metric": "corners_per_match",
                "kte": round(team_metrics.get("corners", 0) / max(team_matches, 1), 2),
                "opp": round(opp_metrics.get("corners", 0) / max(opp_matches, 1), 2),
            },
        ]
        st.dataframe(pd.DataFrame(per_match_rows), use_container_width=True)

        diff_count = distinct_metric_count(team_metrics, opp_metrics)
        st.write("Eltérő metrikák száma:", diff_count)
