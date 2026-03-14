import io
import json
import math
import re
from typing import Dict, Optional, List, Tuple

import altair as alt
import pandas as pd
import pdfplumber
import streamlit as st
import streamlit.components.v1 as components
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

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


def unique_keep_order(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for x in items:
        key = x.strip()
        if key and key not in seen:
            out.append(key)
            seen.add(key)
    return out


def df_to_records(df: Optional[pd.DataFrame]) -> List[dict]:
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")


# =========================================================
# STRATEGY PALETTE
# =========================================================

STRATEGY_PALETTE = {
    "KON": {"name": "Kontra mély blokkból", "block": "low", "style": "direct"},
    "GAT": {"name": "Gyors átmenet", "block": "mid", "style": "direct"},
    "BAT": {"name": "Középső blokk + átmenet", "block": "mid", "style": "balanced"},
    "KIE": {"name": "Kiegyensúlyozott", "block": "mid", "style": "balanced_control"},
    "PRS": {"name": "Presszing + átmenet", "block": "mid_high", "style": "transition_press"},
    "MLT": {"name": "Magas letámadás", "block": "high", "style": "aggressive"},
    "DOM": {"name": "Dominancia", "block": "high", "style": "control"},
    "POZ": {"name": "Pozíciós támadás", "block": "mid_high", "style": "control"},
    "LAB": {"name": "Labdatartás mélyebben", "block": "low_mid", "style": "control"},
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
    style_label = {1: "Direkt", 2: "D/P", 3: "Vegyes", 4: "Kiegy.", 5: "Kontroll", 6: "Agresszív"}
    block_label = {1: "Mély", 2: "Low-mid", 3: "Közép", 4: "Mid-high", 5: "Magas"}

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
                        "scale": {"domain": ["Paletta", "Plan A", "Plan B"], "range": ["#5B2C83", "#E0A500", "#2AA7A1"]},
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
# MATCH METRIC ALIASES
# =========================================================

METRIC_ALIASES = {
    "ppda": ["ppda"],
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
    "key_passes": ["key passes", "key pass"],
    "corners": ["corners", "corner kicks"],
    "possession_pct": [
        "ball possession, %",
        "ball possession",
        "possession %",
        "ball possession %",
    ],
    "shots": ["shots", "total shots"],
    "xg": ["xg", "expected goals"],
}


# =========================================================
# PLAYER COLUMN ALIASES
# =========================================================

PLAYER_COL_ALIASES = {
    "player": ["player"],
    "position": ["position"],
    "minutes_played": ["minutes played"],
    "passes": ["passes"],
    "progressive_passes": ["progressive passes"],
    "key_passes": ["key passes"],
    "interceptions": ["interceptions"],
    "defensive_challenges": ["defensive challenges"],
    "def_challenges_won_pct": ["defensive challenges won, %", "defensive challenges won %"],
}


# =========================================================
# MATCH PARSER
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


# =========================================================
# PLAYER PARSER
# =========================================================

def rename_player_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {}
    for target, aliases in PLAYER_COL_ALIASES.items():
        found = None
        for col in df.columns:
            col_norm = normalize_text(col)
            if any(alias in col_norm for alias in aliases):
                found = col
                break
        if found is not None:
            col_map[found] = target
    return df.rename(columns=col_map)


@st.cache_data(show_spinner=False)
def parse_player_excel(file_bytes: bytes) -> Dict[str, pd.DataFrame]:
    df = pd.read_excel(file_bytes)
    df = rename_player_columns(df)

    required = ["player", "minutes_played"]
    for req in required:
        if req not in df.columns:
            return {
                "creators": pd.DataFrame(),
                "progressors": pd.DataFrame(),
                "build_up": pd.DataFrame(),
                "defenders": pd.DataFrame(),
                "duel_players": pd.DataFrame(),
            }

    df["minutes_played"] = pd.to_numeric(df["minutes_played"], errors="coerce").fillna(0)
    df = df[df["minutes_played"] >= 300].copy()

    for col in ["passes", "progressive_passes", "key_passes", "interceptions", "defensive_challenges"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False).replace("-", pd.NA)
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "passes" not in df.columns:
        df["passes"] = 0.0
    if "progressive_passes" not in df.columns:
        df["progressive_passes"] = 0.0
    if "key_passes" not in df.columns:
        df["key_passes"] = 0.0
    if "interceptions" not in df.columns:
        df["interceptions"] = 0.0
    if "defensive_challenges" not in df.columns:
        df["defensive_challenges"] = 0.0
    if "position" not in df.columns:
        df["position"] = ""

    creators = df.sort_values("key_passes", ascending=False)[["player", "position", "key_passes"]].head(3).reset_index(drop=True)
    progressors = df.sort_values("progressive_passes", ascending=False)[["player", "position", "progressive_passes"]].head(3).reset_index(drop=True)
    build_up = df.sort_values("passes", ascending=False)[["player", "position", "passes"]].head(3).reset_index(drop=True)
    defenders = df.sort_values("interceptions", ascending=False)[["player", "position", "interceptions"]].head(3).reset_index(drop=True)
    duel_players = df.sort_values("defensive_challenges", ascending=False)[["player", "position", "defensive_challenges"]].head(3).reset_index(drop=True)

    return {
        "creators": creators,
        "progressors": progressors,
        "build_up": build_up,
        "defenders": defenders,
        "duel_players": duel_players,
    }


# =========================================================
# PDF PARSER - FINOMHANGOLT
# =========================================================

TARGET_PAGES = [1, 2, 3, 4, 6]


@st.cache_data(show_spinner=False)
def extract_pdf_pages(file_bytes: bytes, target_pages: Tuple[int, ...] = tuple(TARGET_PAGES), max_pages: int = 40) -> List[dict]:
    out = []
    try:
        with pdfplumber.open(file_bytes) as pdf:
            total_pages = min(len(pdf.pages), max_pages)
            for p in range(total_pages):
                if p not in target_pages:
                    continue
                txt = pdf.pages[p].extract_text() or ""
                if txt.strip():
                    out.append({"page_index": p, "page_number": p + 1, "text": txt})
    except Exception:
        return []
    return out


def combine_targeted_pdf_texts(files: List[object]) -> Tuple[str, List[dict]]:
    page_blocks = []
    texts = []
    for f in files:
        if f is None:
            continue
        pages = extract_pdf_pages(f.getvalue())
        page_blocks.extend(pages)
        texts.extend([x["text"] for x in pages if x["text"].strip()])
    return "\n\n".join(texts), page_blocks


def extract_lines_with_keywords(text: str, keywords: List[str], limit: int = 6) -> List[str]:
    out = []
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    for line in lines:
        line_norm = normalize_text(line)
        if any(k in line_norm for k in keywords):
            out.append(line)
        if len(out) >= limit:
            break
    return unique_keep_order(out)


def infer_formation(text: str) -> Optional[str]:
    m = re.search(r"\b([3-5]-[1-5]-[1-5](?:-[1-3])?)\b", text)
    if m:
        return m.group(1)
    return None


def extract_player_names_from_pdf(text: str, limit: int = 6) -> List[str]:
    names = re.findall(r"\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű\-]+(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű\-]+)+\b", text)
    return unique_keep_order(names)[:limit]


def build_pdf_insights(text: str) -> Dict[str, object]:
    formation = infer_formation(text)

    dna_lines = extract_lines_with_keywords(
        text,
        ["press", "pressing", "build-up", "build up", "transition", "counter", "direct", "possession", "ppda"],
        limit=8,
    )

    risk_lines = extract_lines_with_keywords(
        text,
        ["weakness", "risk", "vulnerable", "exposed", "set piece", "cross", "transition", "counter", "lost balls"],
        limit=8,
    )

    set_piece_lines = extract_lines_with_keywords(
        text,
        ["corner", "free kick", "set piece", "header", "aerial"],
        limit=6,
    )

    dynamics_lines = extract_lines_with_keywords(
        text,
        ["first half", "second half", "tempo", "start", "late phase", "after losing", "after winning", "momentum"],
        limit=6,
    )

    pressing_lines = extract_lines_with_keywords(
        text,
        ["pressing", "high pressing", "low pressing", "ppda", "challenge intensity"],
        limit=6,
    )

    build_up_lines = extract_lines_with_keywords(
        text,
        ["build-up", "build up", "passes accurate", "progressive", "passes into penalty area", "final third"],
        limit=6,
    )

    player_threat_lines = extract_lines_with_keywords(
        text,
        ["key passes", "progressive passes", "shots", "xg", "penalty area", "entries", "through pass"],
        limit=8,
    )

    detected_names = extract_player_names_from_pdf(text, limit=8)

    return {
        "formation": formation or "n.a.",
        "dna_lines": dna_lines,
        "risk_lines": risk_lines,
        "set_piece_lines": set_piece_lines,
        "dynamics_lines": dynamics_lines,
        "pressing_lines": pressing_lines,
        "build_up_lines": build_up_lines,
        "player_threat_lines": player_threat_lines,
        "detected_names": detected_names,
    }


# =========================================================
# SCORING / ENGINE
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
    return sum(1 for k in keys if team_metrics.get(k, 0) != opp_metrics.get(k, 0))


def build_warning_list(opp_players, opp_pdf_insights) -> List[str]:
    warnings = []

    if opp_players is not None and not opp_players["creators"].empty:
        row = opp_players["creators"].iloc[0]
        warnings.append(f"{row['player']} – fő kreatív játékos, félterület-védekezés prioritás.")
    if opp_players is not None and not opp_players["progressors"].empty:
        row = opp_players["progressors"].iloc[0]
        warnings.append(f"{row['player']} – fő progresszor, pressing trigger jelölt.")
    if opp_players is not None and not opp_players["duel_players"].empty:
        row = opp_players["duel_players"].iloc[0]
        warnings.append(f"{row['player']} – párharcerős profil, második labdákra figyelni.")

    if opp_pdf_insights:
        warnings.extend(opp_pdf_insights["risk_lines"][:2])

    if not warnings:
        warnings = [
            "A fő progressziós csatornákat korán zárni.",
            "A második labdák kontrollja kulcskérdés.",
        ]

    return unique_keep_order(warnings)


def build_three_keys(dims, opp_pdf_insights, warnings) -> List[str]:
    keys = []

    if dims["Átmenetek"]["KTE"] >= dims["Átmenetek"]["ELL"]:
        keys.append("Átmeneti helyzetek sebességi kihasználása.")
    else:
        keys.append("Átmeneti védekezés kontrollja és rest defense stabilizálása.")

    if dims["Labdakihozatal"]["KTE"] >= dims["Letámadás"]["ELL"]:
        keys.append("Labdakihozatal türelemmel, belső progressziós csatornák használatával.")
    else:
        keys.append("Korai nyomás ellen egyszerűsített labdakihozatal és második labdák készítése.")

    if opp_pdf_insights and opp_pdf_insights["set_piece_lines"]:
        keys.append("Pontrúgás-védekezés: első kontakt és lecsorgók kontrollja.")
    else:
        keys.append("Boxon belüli jelenlét és második hullám érkezések javítása.")

    return unique_keep_order(keys)[:3]


def build_match_dynamics(opp_pdf_insights, dims) -> List[str]:
    dynamics = []

    if opp_pdf_insights and opp_pdf_insights["dynamics_lines"]:
        dynamics.extend(opp_pdf_insights["dynamics_lines"][:3])

    if not dynamics:
        dynamics = [
            "Erős kezdő fázis várható, középső zónás párharcokkal.",
            "A középső szakaszban a labdakihozatal minősége döntő lehet.",
            "A végjátékban nőhet az átmeneti helyzetek száma.",
        ]

    if dims["Pontrúgások"]["ELL"] > dims["Pontrúgások"]["KTE"]:
        dynamics.append("A késői szakaszban nőhet az ellenfél pontrúgás-veszélye.")

    return unique_keep_order(dynamics)[:4]


def build_opponent_dna_text(opp_pdf_insights, opp_metrics, opp_matches) -> str:
    possession = (opp_metrics.get("possession_pct", 0) * 100) if opp_metrics.get("possession_pct", 0) <= 1 else opp_metrics.get("possession_pct", 0)
    shots_pm = round(opp_metrics.get("shots", 0) / max(opp_matches or 1, 1), 2)
    entries_pm = round(opp_metrics.get("entries_box", 0) / max(opp_matches or 1, 1), 2)
    formation = opp_pdf_insights["formation"] if opp_pdf_insights else "n.a."

    bullet_lines = opp_pdf_insights["dna_lines"][:3] if opp_pdf_insights else []
    bullet_text = "\n".join([f"- {x}" for x in bullet_lines])

    return (
        f"Formáció: {formation}\n"
        f"Labdabirtoklás: {round(possession, 1)}%\n"
        f"Lövések / meccs: {shots_pm}\n"
        f"Box entries / meccs: {entries_pm}\n\n"
        f"{bullet_text}"
    ).strip()




def parse_bullet_text(text: str) -> List[str]:
    return [x.strip("-• ").strip() for x in str(text).splitlines() if x.strip()]


def player_focus_options(opp_players: Optional[Dict[str, pd.DataFrame]]) -> List[str]:
    opts = []
    if not opp_players:
        return opts
    labels = {
        "creators": "Creator",
        "progressors": "Progressor",
        "build_up": "Build-up",
        "defenders": "Defender",
        "duel_players": "Duel",
    }
    for group, prefix in labels.items():
        df = opp_players.get(group)
        if df is None or df.empty or "Player" not in df.columns:
            continue
        for _, row in df.head(3).iterrows():
            player = str(row.get("Player", "")).strip()
            if player:
                opts.append(f"{player} ({prefix})")
    return unique_keep_order(opts)


def coach_risk_options(base_warnings: Optional[List[str]]) -> List[str]:
    defaults = [
        "pontrúgás-védekezés",
        "half-space védekezés",
        "second ball kontroll",
        "átmeneti védekezés",
        "magas presszing kijátszása",
    ]
    return unique_keep_order((base_warnings or []) + defaults)


def build_coach_summary(controls: Dict[str, object]) -> Dict[str, str]:
    focus_areas = controls.get("focus_areas", [])
    selected_risks = controls.get("selected_risks", [])
    focus_players = controls.get("focus_players", [])

    opponent_profile = (
        f"Elsődleges játékmodell: {controls.get('primary_model', '-')}"
        f" | Alternatíva: {controls.get('secondary_model', '-')}"
        f" | Meccskép fókusz: {', '.join(focus_areas) if focus_areas else 'nincs kijelölve'}"
    )

    own_state = (
        f"Labdakihozatal: {controls.get('build_up_solution', '-')}"
        f" | Védelmi blokk: {controls.get('defensive_block', '-')}"
        f" | Presszing fókuszterület: {controls.get('pressing_zone', '-')}"
        f" | Pontrúgás prioritás: {controls.get('set_piece_priority', '-')}"
    )

    keys = []
    if focus_areas:
        keys.append(f"Elsődleges fókusz: {', '.join(focus_areas[:3])}.")
    keys.append(
        f"Plan A hangsúly: {controls.get('plan_a_emphasis', 60)}%, "
        f"forgatókönyv: {controls.get('match_scenario', '-')}.")
    if focus_players:
        keys.append(f"Kulcsjátékos-fókusz: {', '.join(focus_players[:3])}.")
    if controls.get("second_ball_focus"):
        keys.append("Second ball kontroll kiemelt feladat.")
    if controls.get("halfspace_defense_priority"):
        keys.append("Félterület-védekezés kiemelt prioritás.")
    keys = unique_keep_order(keys)[:3]

    risks = []
    for r in selected_risks[:4]:
        risks.append(r if str(r).endswith(".") else f"{r}.")
    if not risks:
        risks = ["Nincs külön coach által megjelölt extra kockázat."]

    conclusion = (
        f"Plan A: {controls.get('primary_model', '-')}; "
        f"Plan B: {controls.get('secondary_model', '-')}; "
        f"arány: {controls.get('plan_a_emphasis', 60)}/{100 - int(controls.get('plan_a_emphasis', 60))}. "
        f"Fő meccsdinamika: {controls.get('match_scenario', '-')}. "
        f"Labdakihozatal: {controls.get('build_up_solution', '-')}, blokk: {controls.get('defensive_block', '-')}. "
        f"Pontrúgás: {controls.get('set_piece_priority', '-')}"
    )

    dynamics = [
        f"Forgatókönyv: {controls.get('match_scenario', '-')}.",
        f"Presszing fókuszterület: {controls.get('pressing_zone', '-')}.",
        f"Labdakihozatal: {controls.get('build_up_solution', '-')}, védelmi blokk: {controls.get('defensive_block', '-')}.",
    ]
    if controls.get("second_ball_focus"):
        dynamics.append("A meccs későbbi szakaszában nőhet a lecsorgók jelentősége.")
    if controls.get("halfspace_defense_priority"):
        dynamics.append("Half-space terhelésre célzott védekezési reakció szükséges.")

    return {
        "opponent_profile_text": opponent_profile,
        "own_state_text": own_state,
        "three_keys_text": "\n".join([f"- {x}" for x in keys]),
        "risks_text": "\n".join([f"- {x}" for x in risks]),
        "match_dynamics_text": "\n".join([f"- {x}" for x in unique_keep_order(dynamics)[:4]]),
        "conclusion_text": conclusion,
    }


def sync_coach_texts_from_controls():
    controls = {
        "primary_model": st.session_state.get("coach_primary_model", st.session_state.get("selected_plan_a", "GAT")),
        "secondary_model": st.session_state.get("coach_secondary_model", st.session_state.get("selected_plan_b", "BAT")),
        "focus_areas": st.session_state.get("coach_focus_areas", []),
        "selected_risks": st.session_state.get("coach_selected_risks", []),
        "focus_players": st.session_state.get("coach_focus_players", []),
        "pressing_zone": st.session_state.get("coach_pressing_zone", "közép"),
        "build_up_solution": st.session_state.get("coach_build_up_solution", "vegyes"),
        "defensive_block": st.session_state.get("coach_defensive_block", "közepes"),
        "match_scenario": st.session_state.get("coach_match_scenario", "balanced"),
        "plan_a_emphasis": st.session_state.get("coach_plan_a_emphasis", st.session_state.get("selected_split", 60)),
        "set_piece_priority": st.session_state.get("coach_set_piece_priority", "mindkettő"),
        "second_ball_focus": st.session_state.get("coach_second_ball_focus", False),
        "halfspace_defense_priority": st.session_state.get("coach_halfspace_defense_priority", False),
    }
    summary = build_coach_summary(controls)
    for k, v in summary.items():
        st.session_state[k] = v
    st.session_state["selected_plan_a"] = controls["primary_model"]
    st.session_state["selected_plan_b"] = controls["secondary_model"]
    st.session_state["selected_split"] = int(controls["plan_a_emphasis"])


def render_methodology_block():
    with st.expander("Metodika / hogyan dolgozik az app", expanded=False):
        st.markdown(
            """
**Input források**
- Match Excel: Main statistics sheet, oszlopalapú Total sor olvasás
- Player Excel: top játékosprofilok percpadlóval és top 3 rangsorokkal
- PDF: célzott oldalak (2,3,4,5,7), nem teljes dokumentum

**7 dimenzió logika**
- A total értékek ott, ahol kell, per meccs skálázódnak
- A dimenziók 1-10 közé normalizált összehasonlító score-ok
- A különbségek alapján készül a KTE vs ellenfél edge

**Stratégiai javaslat**
- Átmenet / kontroll / támadási edge alapján választ elsődleges Plan A-t
- A Plan B mindig eltérő stratégiai kód
- A coach felületen ez strukturáltan felülírható

**Plan A / Plan B arány**
- A slider a tervezett hangsúlyt mutatja
- 60/40 = alapvetően Plan A, de előkészített Plan B váltás
- 50/50 = közel kiegyensúlyozott, két forgatókönyves meccsterv

**Coach input elv**
- Nincs szabad szöveg
- Csak checkbox / selectbox / multiselect / slider
- Emiatt a briefing export-kompatibilis marad
            """
        )


def build_pdf_export_bytes(package: Dict[str, object]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading = styles["Heading2"]
    body = styles["BodyText"]
    body.spaceAfter = 6
    small = ParagraphStyle("small", parent=body, fontSize=9, leading=12)

    story = []
    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]

    story.append(Paragraph("Tactical Briefing Export", title_style))
    story.append(Spacer(1, 6))

    meta = [
        ["Plan A", str(p1["plan_a"])],
        ["Plan B", str(p1["plan_b"])],
        ["Arány", str(p1["plan_split"])],
        ["Coach fókusz", ", ".join(package.get("coach_controls", {}).get("focus_areas", [])) or "n.a."],
    ]
    tbl = Table(meta, colWidths=[35 * mm, 140 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))

    story.append(Paragraph("7 dimenziós összehasonlítás", heading))
    dim_rows = [["Dimenzió", "KTE", "ELL", "Edge"]]
    for dim, vals in p1["dimensions"].items():
        dim_rows.append([dim, str(vals["KTE"]), str(vals["ELL"]), str(vals["Edge"])])
    dt = Table(dim_rows, colWidths=[55 * mm, 20 * mm, 20 * mm, 20 * mm])
    dt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEE8F5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(dt)
    story.append(Spacer(1, 10))

    for title, value in [
        ("Ellenfél profil", p1["opponent_profile"]),
        ("Saját állapot", p1["own_state"]),
        ("Opponent DNA", p3["opponent_dna"]),
        ("Konklúzió", p1["conclusion"]),
    ]:
        story.append(Paragraph(title, heading))
        story.append(Paragraph(str(value).replace("\n", "<br/>"), body))
        story.append(Spacer(1, 4))

    story.append(Paragraph("3 kulcs", heading))
    for item in p1["three_keys"]:
        story.append(Paragraph(f"• {item}", body))

    story.append(Spacer(1, 4))
    story.append(Paragraph("Kockázatok", heading))
    for item in p1["risks"]:
        story.append(Paragraph(f"• {item}", body))

    story.append(Spacer(1, 4))
    story.append(Paragraph("Várható meccsdinamika", heading))
    for item in p3["match_dynamics"]:
        story.append(Paragraph(f"• {item}", body))

    story.append(Spacer(1, 4))
    story.append(Paragraph("Kulcsjátékos fókusz", heading))
    for item in package.get("coach_controls", {}).get("focus_players", []):
        story.append(Paragraph(f"• {item}", body))
    if not package.get("coach_controls", {}).get("focus_players", []):
        story.append(Paragraph("• nincs külön kiválasztva", body))

    story.append(Spacer(1, 4))
    story.append(Paragraph("Opponent key players", heading))
    for group_name, records in p3["key_player_threats"].items():
        story.append(Paragraph(group_name, small))
        if not records:
            story.append(Paragraph("–", small))
            continue
        for r in records[:3]:
            story.append(Paragraph(str(r), small))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


def build_export_package(
    selected_plan_a: str,
    selected_plan_b: str,
    selected_split: int,
    dims: Dict[str, Dict[str, float]],
    opponent_profile_text: str,
    own_state_text: str,
    three_keys_text: str,
    risks_text: str,
    match_dynamics_text: str,
    conclusion_text: str,
    opponent_dna_text: str,
    opp_players: Optional[Dict[str, pd.DataFrame]],
    coach_controls: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    package = {
        "page_1_onepager": {
            "plan_a": selected_plan_a,
            "plan_b": selected_plan_b,
            "plan_split": f"{selected_split}/{100 - selected_split}",
            "dimensions": dims,
            "opponent_profile": opponent_profile_text,
            "own_state": own_state_text,
            "three_keys": parse_bullet_text(three_keys_text),
            "risks": parse_bullet_text(risks_text),
            "conclusion": conclusion_text,
        },
        "page_3_tactical_overview": {
            "opponent_dna": opponent_dna_text,
            "match_dynamics": parse_bullet_text(match_dynamics_text),
            "key_player_threats": {
                "creators": df_to_records(opp_players["creators"]) if opp_players else [],
                "progressors": df_to_records(opp_players["progressors"]) if opp_players else [],
                "build_up": df_to_records(opp_players["build_up"]) if opp_players else [],
                "defenders": df_to_records(opp_players["defenders"]) if opp_players else [],
                "duel_players": df_to_records(opp_players["duel_players"]) if opp_players else [],
            },
        },
        "coach_controls": coach_controls or {},
    }
    return package


def build_markdown_export(package: Dict[str, object]) -> str:
    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]

    md = []
    md.append("# Tactical Briefing Export")
    md.append("")
    md.append("## 1. oldal – Onepager")
    md.append(f"- Plan A: {p1['plan_a']}")
    md.append(f"- Plan B: {p1['plan_b']}")
    md.append(f"- Arány: {p1['plan_split']}")
    md.append("")
    md.append("### Ellenfél profil")
    md.append(p1["opponent_profile"])
    md.append("")
    md.append("### Saját állapot")
    md.append(p1["own_state"])
    md.append("")
    md.append("### 3 kulcs")
    for x in p1["three_keys"]:
        md.append(f"- {x}")
    md.append("")
    md.append("### Kockázatok")
    for x in p1["risks"]:
        md.append(f"- {x}")
    md.append("")
    md.append("### Konklúzió")
    md.append(p1["conclusion"])
    md.append("")
    md.append("### Coach controlok")
    for k, v in package.get("coach_controls", {}).items():
        md.append(f"- {k}: {v}")
    md.append("")
    md.append("## 3. oldal – Tactical overview")
    md.append("")
    md.append("### Opponent DNA")
    md.append(p3["opponent_dna"])
    md.append("")
    md.append("### Várható meccsdinamika")
    for x in p3["match_dynamics"]:
        md.append(f"- {x}")
    md.append("")
    md.append("### Key player threats")
    for group_name, records in p3["key_player_threats"].items():
        md.append(f"#### {group_name}")
        for r in records:
            md.append(f"- {r}")
        md.append("")
    return "\n".join(md)


def run_engine(
    team_match_file,
    opp_match_file,
    team_player_file=None,
    opp_player_file=None,
    team_pdf_files=None,
    opp_pdf_files=None,
):
    team_metrics, team_debug_rows, team_sheet_debug, team_matches = parse_excel_metrics_with_debug(team_match_file.getvalue())
    opp_metrics, opp_debug_rows, opp_sheet_debug, opp_matches = parse_excel_metrics_with_debug(opp_match_file.getvalue())

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

    team_players = parse_player_excel(team_player_file.getvalue()) if team_player_file else None
    opp_players = parse_player_excel(opp_player_file.getvalue()) if opp_player_file else None

    team_pdf_text, team_pdf_pages = combine_targeted_pdf_texts(team_pdf_files or [])
    opp_pdf_text, opp_pdf_pages = combine_targeted_pdf_texts(opp_pdf_files or [])

    team_pdf_insights = build_pdf_insights(team_pdf_text) if team_pdf_text.strip() else None
    opp_pdf_insights = build_pdf_insights(opp_pdf_text) if opp_pdf_text.strip() else None

    warnings = build_warning_list(opp_players, opp_pdf_insights)
    three_keys = build_three_keys(dims, opp_pdf_insights, warnings)
    match_dynamics = build_match_dynamics(opp_pdf_insights, dims)
    opponent_dna_text = build_opponent_dna_text(opp_pdf_insights, opp_metrics, opp_matches)

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
        team_players,
        opp_players,
        warnings,
        three_keys,
        match_dynamics,
        team_pdf_text,
        opp_pdf_text,
        team_pdf_insights,
        opp_pdf_insights,
        team_pdf_pages,
        opp_pdf_pages,
        opponent_dna_text,
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

    width = 960
    height = 760
    cx, cy = 360, 330
    max_r = 210
    n = len(labels)

    def wrap_label(text: str, width_chars: int = 14) -> List[str]:
        words = text.split()
        lines = []
        current = ""
        for w in words:
            candidate = f"{current} {w}".strip()
            if len(candidate) <= width_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        return lines[:3]

    def polygon_points(values: List[float]):
        pts = []
        for i, val in enumerate(values):
            ang = -math.pi / 2 + (2 * math.pi * i / n)
            rr = (val / 10.0) * max_r
            x = cx + math.cos(ang) * rr
            y = cy + math.sin(ang) * rr
            pts.append((x, y))
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts), pts

    grid_polys, axes, label_svg, level_labels = [], [], [], []

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
        level_labels.append(f'<text x="{cx + 8}" y="{cy - (lvl / 10.0) * max_r + 4:.1f}" font-size="11" fill="#8B7CA3">{lvl}</text>')

    for i, label in enumerate(labels):
        ang = -math.pi / 2 + (2 * math.pi * i / n)
        x2 = cx + math.cos(ang) * max_r
        y2 = cy + math.sin(ang) * max_r
        axes.append(f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#D8D2E3" stroke-width="1" />')

        lx = cx + math.cos(ang) * (max_r + 85)
        ly = cy + math.sin(ang) * (max_r + 85)

        anchor = "middle"
        if lx < cx - 40:
            anchor = "end"
        elif lx > cx + 40:
            anchor = "start"

        wrapped = wrap_label(label)
        tspans = []
        for j, part in enumerate(wrapped):
            dy = 0 if j == 0 else 18
            tspans.append(f'<tspan x="{lx:.1f}" dy="{dy}">{part}</tspan>')
        label_svg.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="16" text-anchor="{anchor}" fill="#2F1D4A" font-weight="600">{"".join(tspans)}</text>'
        )

    kte_poly, kte_pts = polygon_points(kte_vals)
    ell_poly, ell_pts = polygon_points(ell_vals)

    kte_circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.8" fill="#5B2C83" stroke="white" stroke-width="1.2" />'
        for x, y in kte_pts
    )
    ell_circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.8" fill="#B7A3C9" stroke="#5B2C83" stroke-width="1.0" />'
        for x, y in ell_pts
    )

    svg = f"""
    <svg width="100%" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" rx="18" ry="18" fill="white" />
      {''.join(grid_polys)}
      {''.join(level_labels)}
      {''.join(axes)}
      <polygon points="{ell_poly}" fill="rgba(183,163,201,0.24)" stroke="#9D8ABA" stroke-width="2.6" stroke-dasharray="6 4" />
      <polygon points="{kte_poly}" fill="rgba(91,44,131,0.16)" stroke="#5B2C83" stroke-width="3" />
      {ell_circles}
      {kte_circles}
      {''.join(label_svg)}

      <rect x="690" y="70" width="200" height="74" rx="12" fill="#F8F5FC" stroke="#E1D8EE"/>
      <circle cx="715" cy="97" r="7" fill="#5B2C83" />
      <text x="732" y="102" font-size="15" fill="#2F1D4A" font-weight="600">KTE</text>
      <circle cx="715" cy="122" r="7" fill="#B7A3C9" stroke="#5B2C83" stroke-width="1" />
      <text x="732" y="127" font-size="15" fill="#2F1D4A" font-weight="600">ELL</text>
      <text x="715" y="148" font-size="11" fill="#6D5B88">Skála: 1-10</text>
    </svg>
    """
    components.html(svg, height=height + 10)


# =========================================================
# APP STATE
# =========================================================

defaults = {
    "dims": None,
    "team_metrics": None,
    "opp_metrics": None,
    "team_debug_rows": None,
    "opp_debug_rows": None,
    "team_sheet_debug": None,
    "opp_sheet_debug": None,
    "team_matches": None,
    "opp_matches": None,
    "selected_plan_a": "GAT",
    "selected_plan_b": "BAT",
    "selected_split": 60,
    "team_players": None,
    "opp_players": None,
    "warnings": None,
    "three_keys": None,
    "match_dynamics": None,
    "team_pdf_text": "",
    "opp_pdf_text": "",
    "team_pdf_insights": None,
    "opp_pdf_insights": None,
    "team_pdf_pages": None,
    "opp_pdf_pages": None,
    "opponent_dna_text": "",
    "opponent_profile_text": "",
    "own_state_text": "",
    "three_keys_text": "",
    "risks_text": "",
    "match_dynamics_text": "",
    "conclusion_text": "",
    "coach_primary_model": "GAT",
    "coach_secondary_model": "BAT",
    "coach_focus_areas": [],
    "coach_selected_risks": [],
    "coach_focus_players": [],
    "coach_pressing_zone": "közép",
    "coach_build_up_solution": "vegyes",
    "coach_defensive_block": "közepes",
    "coach_match_scenario": "balanced",
    "coach_plan_a_emphasis": 60,
    "coach_set_piece_priority": "mindkettő",
    "coach_second_ball_focus": False,
    "coach_halfspace_defense_priority": False,
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =========================================================
# UI
# =========================================================

st.title("Tactical Briefing Engine")
st.sidebar.caption("D/P = Direkt / Presszing")

step = st.sidebar.radio(
    "Lépés",
    ["1. Input", "2. Review", "3. Debug", "4. Export Prep"],
    index=0,
)


# =========================================================
# INPUT
# =========================================================

if step == "1. Input":
    st.header("Inputok feltöltése")

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("KTE")
        kte_match = st.file_uploader("KTE Match Excel", type=["xlsx"], key="kte_match")
        kte_player = st.file_uploader("KTE Player Excel", type=["xlsx"], key="kte_player")
        kte_pdf_1 = st.file_uploader("KTE PDF 1", type=["pdf"], key="kte_pdf_1")
        kte_pdf_2 = st.file_uploader("KTE PDF 2", type=["pdf"], key="kte_pdf_2")

    with c2:
        st.subheader("Opponent")
        opp_match = st.file_uploader("Opponent Match Excel", type=["xlsx"], key="opp_match")
        opp_player = st.file_uploader("Opponent Player Excel", type=["xlsx"], key="opp_player")
        opp_pdf_1 = st.file_uploader("Opponent PDF 1", type=["pdf"], key="opp_pdf_1")
        opp_pdf_2 = st.file_uploader("Opponent PDF 2", type=["pdf"], key="opp_pdf_2")
        opp_pdf_3 = st.file_uploader("Opponent PDF 3", type=["pdf"], key="opp_pdf_3")

    if kte_match and opp_match:
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
            team_players,
            opp_players,
            warnings,
            three_keys,
            match_dynamics,
            team_pdf_text,
            opp_pdf_text,
            team_pdf_insights,
            opp_pdf_insights,
            team_pdf_pages,
            opp_pdf_pages,
            opponent_dna_text,
        ) = run_engine(
            kte_match,
            opp_match,
            kte_player,
            opp_player,
            [kte_pdf_1, kte_pdf_2],
            [opp_pdf_1, opp_pdf_2, opp_pdf_3],
        )

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
        st.session_state["team_players"] = team_players
        st.session_state["opp_players"] = opp_players
        st.session_state["warnings"] = warnings
        st.session_state["three_keys"] = three_keys
        st.session_state["match_dynamics"] = match_dynamics
        st.session_state["team_pdf_text"] = team_pdf_text
        st.session_state["opp_pdf_text"] = opp_pdf_text
        st.session_state["team_pdf_insights"] = team_pdf_insights
        st.session_state["opp_pdf_insights"] = opp_pdf_insights
        st.session_state["team_pdf_pages"] = team_pdf_pages
        st.session_state["opp_pdf_pages"] = opp_pdf_pages
        st.session_state["opponent_dna_text"] = opponent_dna_text

        # export-ready structured defaults
        possession_opp = (opp_metrics.get("possession_pct", 0) * 100) if opp_metrics.get("possession_pct", 0) <= 1 else opp_metrics.get("possession_pct", 0)
        possession_team = (team_metrics.get("possession_pct", 0) * 100) if team_metrics.get("possession_pct", 0) <= 1 else team_metrics.get("possession_pct", 0)

        st.session_state["coach_primary_model"] = suggested_a
        st.session_state["coach_secondary_model"] = suggested_b
        st.session_state["coach_focus_areas"] = ["pressing", "transition"] if dims["Átmenetek"]["Edge"] >= 0 else ["build-up", "rest defense"]
        st.session_state["coach_selected_risks"] = warnings[:3]
        st.session_state["coach_focus_players"] = player_focus_options(opp_players)[:3]
        st.session_state["coach_pressing_zone"] = "közép"
        st.session_state["coach_build_up_solution"] = "vegyes"
        st.session_state["coach_defensive_block"] = "közepes"
        st.session_state["coach_match_scenario"] = "balanced"
        st.session_state["coach_plan_a_emphasis"] = suggested_split
        st.session_state["coach_set_piece_priority"] = "mindkettő"
        st.session_state["coach_second_ball_focus"] = any("second" in w.lower() or "lecsorg" in w.lower() for w in warnings)
        st.session_state["coach_halfspace_defense_priority"] = any("félter" in w.lower() or "half" in w.lower() for w in warnings)

        st.session_state["opponent_profile_text"] = (
            f"Formáció: {(opp_pdf_insights['formation'] if opp_pdf_insights else 'n.a.')} | "
            f"Labdabirtoklás: {round(possession_opp, 1)}% | "
            f"Lövések / meccs: {round(opp_metrics.get('shots', 0) / max(opp_matches or 1, 1), 2)} | "
            f"Box entries / meccs: {round(opp_metrics.get('entries_box', 0) / max(opp_matches or 1, 1), 2)}"
        )
        st.session_state["own_state_text"] = (
            f"KTE passzpontosság: {round((team_metrics.get('passes_accurate_pct', 0) * 100) if team_metrics.get('passes_accurate_pct', 0) <= 1 else team_metrics.get('passes_accurate_pct', 0), 1)}% | "
            f"KTE labdabirtoklás: {round(possession_team, 1)}% | "
            f"KTE lövések / meccs: {round(team_metrics.get('shots', 0) / max(team_matches or 1, 1), 2)} | "
            f"KTE key passes / meccs: {round(team_metrics.get('key_passes', 0) / max(team_matches or 1, 1), 2)}"
        )

        sync_coach_texts_from_controls()

        st.success("Adatok feldolgozva.")

        a1, a2 = st.columns(2)
        with a1:
            st.subheader("KTE – nyers metrikák")
            st.json(team_metrics)
            st.write("Meccsszám:", team_matches)
        with a2:
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
    opp_players = st.session_state.get("opp_players")
    opp_pdf_insights = st.session_state.get("opp_pdf_insights")
    opponent_dna_text = st.session_state.get("opponent_dna_text")

    if not dims:
        st.warning("Előbb tölts fel adatot az Input fülön.")
    else:
        sync_coach_texts_from_controls()
        render_methodology_block()

        diff_count = distinct_metric_count(team_metrics, opp_metrics)
        if diff_count < 2:
            st.error("A KTE és az ellenfél között túl kevés eltérő nyers metrika van. Nézd meg a Debug fület.")

        top1, top2, top3 = st.columns(3)
        top1.metric("Ajánlott / választott Plan A", st.session_state["selected_plan_a"])
        top2.metric("Ajánlott / választott Plan B", st.session_state["selected_plan_b"])
        top3.metric("Arány", f"{st.session_state['selected_split']}/{100 - st.session_state['selected_split']}")

        st.subheader("9 taktikai opció – stratégiai térkép")
        render_strategy_map(st.session_state["selected_plan_a"], st.session_state["selected_plan_b"])

        coach_left, coach_right = st.columns([1.15, 1])
        with coach_left:
            st.subheader("Coach finomhangolás")
            c1, c2 = st.columns(2)
            with c1:
                st.session_state["coach_primary_model"] = st.selectbox(
                    "Elsődleges játékmodell",
                    options=list(STRATEGY_PALETTE.keys()),
                    index=list(STRATEGY_PALETTE.keys()).index(st.session_state["coach_primary_model"]),
                    format_func=lambda x: f"{x} – {STRATEGY_PALETTE[x]['name']}",
                )
            with c2:
                available_b = [x for x in STRATEGY_PALETTE.keys() if x != st.session_state["coach_primary_model"]]
                current_b = st.session_state["coach_secondary_model"]
                if current_b not in available_b:
                    current_b = available_b[0]
                st.session_state["coach_secondary_model"] = st.selectbox(
                    "Alternatív játékmodell",
                    options=available_b,
                    index=available_b.index(current_b),
                    format_func=lambda x: f"{x} – {STRATEGY_PALETTE[x]['name']}",
                )

            st.session_state["coach_focus_areas"] = st.multiselect(
                "Meccskép prioritás",
                options=["pressing", "build-up", "transition", "set pieces", "rest defense"],
                default=st.session_state["coach_focus_areas"],
            )

            z1, z2, z3 = st.columns(3)
            with z1:
                st.session_state["coach_pressing_zone"] = st.selectbox(
                    "Pressing fókuszterület",
                    ["bal", "közép", "jobb", "half-space"],
                    index=["bal", "közép", "jobb", "half-space"].index(st.session_state["coach_pressing_zone"]),
                )
            with z2:
                st.session_state["coach_build_up_solution"] = st.selectbox(
                    "Labdakihozatal",
                    ["rövid", "vegyes", "direkt"],
                    index=["rövid", "vegyes", "direkt"].index(st.session_state["coach_build_up_solution"]),
                )
            with z3:
                st.session_state["coach_defensive_block"] = st.selectbox(
                    "Védelmi blokk",
                    ["mély", "közepes", "magas"],
                    index=["mély", "közepes", "magas"].index(st.session_state["coach_defensive_block"]),
                )

            s1, s2 = st.columns(2)
            with s1:
                st.session_state["coach_match_scenario"] = st.selectbox(
                    "Meccsdinamika forgatókönyv",
                    ["conservative", "balanced", "aggressive"],
                    index=["conservative", "balanced", "aggressive"].index(st.session_state["coach_match_scenario"]),
                )
            with s2:
                st.session_state["coach_set_piece_priority"] = st.selectbox(
                    "Pontrúgás prioritás",
                    ["támadó", "védekező", "mindkettő"],
                    index=["támadó", "védekező", "mindkettő"].index(st.session_state["coach_set_piece_priority"]),
                )

            st.session_state["coach_plan_a_emphasis"] = st.slider(
                "Plan A hangsúly (%)",
                min_value=50,
                max_value=70,
                value=int(st.session_state["coach_plan_a_emphasis"]),
            )

            f1, f2 = st.columns(2)
            with f1:
                st.session_state["coach_second_ball_focus"] = st.checkbox(
                    "Second ball fókusz", value=st.session_state["coach_second_ball_focus"]
                )
            with f2:
                st.session_state["coach_halfspace_defense_priority"] = st.checkbox(
                    "Félterület-védekezés prioritás", value=st.session_state["coach_halfspace_defense_priority"]
                )

            st.session_state["coach_selected_risks"] = st.multiselect(
                "Fő kockázat prioritások",
                options=coach_risk_options(st.session_state.get("warnings")),
                default=st.session_state["coach_selected_risks"],
            )

            st.session_state["coach_focus_players"] = st.multiselect(
                "Kulcsjátékos-fókusz",
                options=player_focus_options(opp_players),
                default=st.session_state["coach_focus_players"],
            )

            sync_coach_texts_from_controls()

        with coach_right:
            st.subheader("Strukturált briefing preview")
            st.markdown("**Ellenfél profil**")
            st.info(st.session_state["opponent_profile_text"])
            st.markdown("**Saját állapot**")
            st.info(st.session_state["own_state_text"])
            st.markdown("**Konklúzió**")
            st.success(st.session_state["conclusion_text"])

        with st.expander("A 9 taktikai opció táblázata", expanded=False):
            st.table(strategy_palette_rows())

        st.subheader("Dimenzió tábla")
        st.dataframe(pd.DataFrame(dims).T, use_container_width=True)

        c1, c2 = st.columns([1.25, 1])
        with c1:
            st.subheader("Pókháló")
            render_radar_svg(dims)
        with c2:
            st.subheader("Dimenziók")
            render_bar_chart(dims)

        st.subheader("Opponent key players")
        if opp_players is not None:
            k1, k2 = st.columns(2)
            with k1:
                st.write("CREATORS")
                st.dataframe(opp_players["creators"], use_container_width=True)
                st.write("PROGRESSORS")
                st.dataframe(opp_players["progressors"], use_container_width=True)
                st.write("BUILD UP")
                st.dataframe(opp_players["build_up"], use_container_width=True)
            with k2:
                st.write("DEFENDERS")
                st.dataframe(opp_players["defenders"], use_container_width=True)
                st.write("DUEL PLAYERS")
                st.dataframe(opp_players["duel_players"], use_container_width=True)
        else:
            st.info("Nincs opponent player Excel feltöltve.")

        r1, r2 = st.columns(2)
        with r1:
            st.subheader("Opponent DNA")
            st.code(opponent_dna_text)
        with r2:
            st.subheader("Kockázatok")
            for line in parse_bullet_text(st.session_state["risks_text"]):
                st.write(f"- {line}")

        r3, r4 = st.columns(2)
        with r3:
            st.subheader("3 kulcs")
            for line in parse_bullet_text(st.session_state["three_keys_text"]):
                st.write(f"- {line}")
        with r4:
            st.subheader("Várható meccsdinamika")
            for line in parse_bullet_text(st.session_state["match_dynamics_text"]):
                st.write(f"- {line}")

        if opp_pdf_insights:
            st.subheader("PDF-ből kinyert tactical notes")
            note1, note2, note3 = st.columns(3)
            with note1:
                st.write("Pressing")
                for x in opp_pdf_insights["pressing_lines"][:5]:
                    st.write(f"- {x}")
            with note2:
                st.write("Build-up / Final third")
                for x in opp_pdf_insights["build_up_lines"][:5]:
                    st.write(f"- {x}")
            with note3:
                st.write("Set piece / Player threats")
                for x in (opp_pdf_insights["set_piece_lines"][:3] + opp_pdf_insights["player_threat_lines"][:3]):
                    st.write(f"- {x}")


# =========================================================
# DEBUG
# =========================================================
# DEBUG
# =========================================================

if step == "3. Debug":
    st.header("Debug")

    kte_match = st.file_uploader("KTE Match Excel", type=["xlsx"], key="kte_debug_match")
    opp_match = st.file_uploader("Opponent Match Excel", type=["xlsx"], key="opp_debug_match")
    kte_player = st.file_uploader("KTE Player Excel", type=["xlsx"], key="kte_debug_player")
    opp_player = st.file_uploader("Opponent Player Excel", type=["xlsx"], key="opp_debug_player")
    kte_pdf = st.file_uploader("KTE PDF", type=["pdf"], key="kte_debug_pdf")
    opp_pdf = st.file_uploader("Opponent PDF", type=["pdf"], key="opp_debug_pdf")

    if kte_match:
        team_metrics, team_debug_rows, _, team_matches = parse_excel_metrics_with_debug(kte_match.getvalue())
        st.subheader("KTE match parser találatok")
        st.json(team_metrics)
        st.write("KTE meccsszám:", team_matches)
        st.subheader("KTE metrika → oszlop illesztés")
        st.dataframe(pd.DataFrame(team_debug_rows), use_container_width=True)

    if opp_match:
        opp_metrics, opp_debug_rows, _, opp_matches = parse_excel_metrics_with_debug(opp_match.getvalue())
        st.subheader("Opponent match parser találatok")
        st.json(opp_metrics)
        st.write("ELL meccsszám:", opp_matches)
        st.subheader("Opponent metrika → oszlop illesztés")
        st.dataframe(pd.DataFrame(opp_debug_rows), use_container_width=True)

    if kte_match and opp_match:
        st.subheader("KTE vs Opponent – nyers metrika összehasonlítás")

        team_metrics, team_debug_rows, _, _ = parse_excel_metrics_with_debug(kte_match.getvalue())
        opp_metrics, opp_debug_rows, _, _ = parse_excel_metrics_with_debug(opp_match.getvalue())

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

    if kte_player:
        st.subheader("KTE player parser")
        kte_players = parse_player_excel(kte_player.getvalue())
        for key, df in kte_players.items():
            st.write(key.upper())
            st.dataframe(df, use_container_width=True)

    if opp_player:
        st.subheader("Opponent player parser")
        opp_players = parse_player_excel(opp_player.getvalue())
        for key, df in opp_players.items():
            st.write(key.upper())
            st.dataframe(df, use_container_width=True)

    if kte_pdf:
        st.subheader("KTE PDF targeted pages")
        text, pages = combine_targeted_pdf_texts([kte_pdf])
        st.write("Felhasznált oldalak:", [x["page_number"] for x in pages])
        st.text_area("KTE PDF extracted text", value=text[:6000], height=260)
        st.write(build_pdf_insights(text))

    if opp_pdf:
        st.subheader("Opponent PDF targeted pages")
        text, pages = combine_targeted_pdf_texts([opp_pdf])
        st.write("Felhasznált oldalak:", [x["page_number"] for x in pages])
        st.text_area("Opponent PDF extracted text", value=text[:6000], height=260)
        st.write(build_pdf_insights(text))


# =========================================================
# EXPORT PREP
# =========================================================


if step == "4. Export Prep":
    dims = st.session_state.get("dims")
    opp_players = st.session_state.get("opp_players")

    if not dims:
        st.warning("Előbb tölts fel adatot az Input fülön.")
    else:
        sync_coach_texts_from_controls()
        render_methodology_block()
        st.header("Export Prep – template előkészítés")

        coach_controls = {
            "primary_model": st.session_state["coach_primary_model"],
            "secondary_model": st.session_state["coach_secondary_model"],
            "focus_areas": st.session_state["coach_focus_areas"],
            "selected_risks": st.session_state["coach_selected_risks"],
            "focus_players": st.session_state["coach_focus_players"],
            "pressing_zone": st.session_state["coach_pressing_zone"],
            "build_up_solution": st.session_state["coach_build_up_solution"],
            "defensive_block": st.session_state["coach_defensive_block"],
            "match_scenario": st.session_state["coach_match_scenario"],
            "plan_a_emphasis": st.session_state["coach_plan_a_emphasis"],
            "set_piece_priority": st.session_state["coach_set_piece_priority"],
            "second_ball_focus": st.session_state["coach_second_ball_focus"],
            "halfspace_defense_priority": st.session_state["coach_halfspace_defense_priority"],
        }

        package = build_export_package(
            selected_plan_a=st.session_state["selected_plan_a"],
            selected_plan_b=st.session_state["selected_plan_b"],
            selected_split=st.session_state["selected_split"],
            dims=dims,
            opponent_profile_text=st.session_state["opponent_profile_text"],
            own_state_text=st.session_state["own_state_text"],
            three_keys_text=st.session_state["three_keys_text"],
            risks_text=st.session_state["risks_text"],
            match_dynamics_text=st.session_state["match_dynamics_text"],
            conclusion_text=st.session_state["conclusion_text"],
            opponent_dna_text=st.session_state["opponent_dna_text"],
            opp_players=opp_players,
            coach_controls=coach_controls,
        )

        md_export = build_markdown_export(package)
        json_export = json.dumps(package, ensure_ascii=False, indent=2)
        pdf_export = build_pdf_export_bytes(package)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("JSON export package")
            st.code(json_export, language="json")
            st.download_button(
                "JSON letöltése",
                data=json_export.encode("utf-8"),
                file_name="briefing_export_package.json",
                mime="application/json",
            )
            st.download_button(
                "PDF briefing letöltése",
                data=pdf_export,
                file_name="briefing_export_package.pdf",
                mime="application/pdf",
            )

        with col2:
            st.subheader("Markdown export preview")
            st.text_area("Markdown", value=md_export, height=480)
            st.download_button(
                "Markdown letöltése",
                data=md_export.encode("utf-8"),
                file_name="briefing_export_package.md",
                mime="text/markdown",
            )

        st.subheader("Coach control snapshot")
        st.json(coach_controls)

        st.subheader("Mi jön ezután?")
        st.write("- Következő lépés: a JSON/PDF package mezőit rámapeljük a gold standard PPT template konkrét textboxaira.")
        st.write("- Utána: tényleges PPT generálás és visszaadás kész briefing deckként.")
