import io
import json
import math
import re
import unicodedata
import base64
from pathlib import Path
from typing import Dict, Optional, List, Tuple

import altair as alt
import pandas as pd
import pdfplumber
import streamlit as st
import streamlit.components.v1 as components

MATPLOTLIB_AVAILABLE = True
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    MATPLOTLIB_AVAILABLE = False

REPORTLAB_AVAILABLE = True
SVGLIB_AVAILABLE = True
CAIROSVG_AVAILABLE = True
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader, simpleSplit
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except Exception:
    REPORTLAB_AVAILABLE = False

try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF
except Exception:
    SVGLIB_AVAILABLE = False

try:
    import cairosvg
except Exception:
    CAIROSVG_AVAILABLE = False

st.set_page_config(page_title="Tactical Briefing Engine", layout="wide")

PDF_FONT_NAME = "Helvetica"
PDF_FONT_BOLD_NAME = "Helvetica-Bold"

def ensure_pdf_font() -> str:
    global PDF_FONT_NAME, PDF_FONT_BOLD_NAME
    if not REPORTLAB_AVAILABLE:
        return PDF_FONT_NAME
    if PDF_FONT_NAME != "Helvetica":
        return PDF_FONT_NAME

    regular_candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/local/share/fonts/DejaVuSans.ttf",
        str(Path.home() / ".fonts" / "NotoSans-Regular.ttf"),
        str(Path.home() / ".fonts" / "DejaVuSans.ttf"),
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/local/share/fonts/DejaVuSans-Bold.ttf",
        str(Path.home() / ".fonts" / "NotoSans-Bold.ttf"),
        str(Path.home() / ".fonts" / "DejaVuSans-Bold.ttf"),
    ]

    try:
        if MATPLOTLIB_AVAILABLE:
            from matplotlib import font_manager
            regular_candidates.insert(0, font_manager.findfont("DejaVu Sans", fallback_to_default=True))
            bold_candidates.insert(0, font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight="bold"), fallback_to_default=True))
    except Exception:
        pass

    regular = next((c for c in regular_candidates if c and Path(c).exists()), None)
    bold = next((c for c in bold_candidates if c and Path(c).exists()), None)
    try:
        if regular:
            pdfmetrics.registerFont(TTFont("DejaVuSans", regular))
            PDF_FONT_NAME = "DejaVuSans"
        if bold:
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold))
            PDF_FONT_BOLD_NAME = "DejaVuSans-Bold"
        elif regular:
            PDF_FONT_BOLD_NAME = PDF_FONT_NAME
    except Exception:
        PDF_FONT_NAME = "Helvetica"
        PDF_FONT_BOLD_NAME = "Helvetica-Bold"
    return PDF_FONT_NAME


def pdf_safe_text(text) -> str:
    """Normalize text for PDF output and preserve Hungarian characters when a Unicode font is available."""
    ensure_pdf_font()
    s = "" if text is None else str(text)
    s = unicodedata.normalize("NFC", s)
    replacements = {
        " ": " ",
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
        "…": "...",
        "​": "",
    }
    for src, dst in replacements.items():
        s = s.replace(src, dst)
    return s


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




def label_strategy(code: str) -> str:
    return f"{code} – {STRATEGY_PALETTE.get(code, {}).get('name', code)}" if code else "-"


def label_scenario(value: str) -> str:
    return {"conservative": "konzervatív", "balanced": "kiegyensúlyozott", "aggressive": "agresszív"}.get(value, value or "-")


def label_focus_area(value: str) -> str:
    return {
        "pressing": "letámadás",
        "build-up": "labdakihozatal",
        "transition": "átmenetek",
        "set pieces": "pontrúgások",
        "rest defense": "rest defense",
    }.get(value, value or "-")


def format_focus_areas(items: List[str]) -> str:
    if not items:
        return "nincs külön fókusz"
    return ", ".join(label_focus_area(x) for x in items)


def baseline_coach_controls(selected_plan_a: str, selected_plan_b: str, selected_split: int) -> Dict[str, object]:
    linked = linked_controls_from_model(selected_plan_a)
    return {
        "primary_model": selected_plan_a,
        "secondary_model": selected_plan_b,
        "focus_areas": linked.get("focus_areas", []),
        "pressing_zone": "közép",
        "build_up_solution": linked.get("build_up_solution", "vegyes"),
        "defensive_block": linked.get("defensive_block", "közepes"),
        "match_scenario": linked.get("match_scenario", "balanced"),
        "plan_a_emphasis": int(selected_split),
        "set_piece_priority": "mindkettő",
        "second_ball_focus": False,
        "halfspace_defense_priority": False,
        "selected_risks": [],
    }


def has_meaningful_coach_intervention(controls: Dict[str, object], baseline: Dict[str, object]) -> bool:
    keys = [
        "primary_model", "secondary_model", "pressing_zone", "build_up_solution",
        "defensive_block", "match_scenario", "plan_a_emphasis", "set_piece_priority",
        "second_ball_focus", "halfspace_defense_priority", "selected_risks", "focus_areas",
    ]
    for key in keys:
        a = controls.get(key)
        b = baseline.get(key)
        if isinstance(a, list) or isinstance(b, list):
            if sorted(list(a or [])) != sorted(list(b or [])):
                return True
        else:
            if a != b:
                return True
    return False

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
    block_label = {1: "Mély", 2: "Alacsony-közép", 3: "Közép", 4: "Közép-magas", 5: "Magas"}

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




def linked_controls_from_model(model_code: str) -> Dict[str, object]:
    data = STRATEGY_PALETTE.get(model_code, STRATEGY_PALETTE["KIE"])
    block_map = {"low": "mély", "low_mid": "mély", "mid": "közepes", "mid_high": "közepes", "high": "magas"}
    style = data.get("style", "balanced")

    if style == "direct":
        build_up = "direkt"
        focus_areas = ["transition"]
        scenario = "balanced"
    elif style in ["control", "balanced_control"]:
        build_up = "rövid"
        focus_areas = ["build-up"]
        scenario = "conservative" if data.get("block") in ["low", "low_mid"] else "balanced"
    elif style == "transition_press":
        build_up = "vegyes"
        focus_areas = ["pressing", "transition"]
        scenario = "aggressive"
    elif style == "aggressive":
        build_up = "direkt"
        focus_areas = ["pressing", "transition"]
        scenario = "aggressive"
    else:
        build_up = "vegyes"
        focus_areas = ["pressing", "build-up"]
        scenario = "balanced"

    return {
        "build_up_solution": build_up,
        "defensive_block": block_map.get(data.get("block", "mid"), "közepes"),
        "match_scenario": scenario,
        "focus_areas": focus_areas,
    }


def apply_linked_coach_controls(model_code: str):
    linked = linked_controls_from_model(model_code)
    st.session_state["coach_build_up_solution"] = linked["build_up_solution"]
    st.session_state["coach_defensive_block"] = linked["defensive_block"]
    st.session_state["coach_match_scenario"] = linked["match_scenario"]
    st.session_state["coach_focus_areas"] = linked["focus_areas"]

def render_strategy_map(selected_a: Optional[str] = None, selected_b: Optional[str] = None, height: int = 430):
    rows = strategy_scatter_data(selected_a, selected_b)
    spec = {
        "width": "container",
        "height": height,
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
                            "labelExpr": "datum.value == 1 ? 'Mély' : datum.value == 2 ? 'Alacsony-közép' : datum.value == 3 ? 'Közép' : datum.value == 4 ? 'Közép-magas' : 'Magas'",
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

    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
    except ImportError:
        st.session_state["excel_import_error"] = (
            "Az Excel-fájlok feldolgozásához hiányzik az openpyxl csomag. "
            "Tedd be a requirements.txt fájlba: openpyxl"
        )
        return metrics, all_debug_rows, sheet_debug, match_count
    except Exception as e:
        st.session_state["excel_import_error"] = f"Az Excel-fájl nem olvasható: {e}"
        return metrics, all_debug_rows, sheet_debug, match_count

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet, header=None)
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
    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
    except ImportError:
        st.session_state["excel_import_error"] = (
            "Az Excel-fájlok feldolgozásához hiányzik az openpyxl csomag. "
            "Tedd be a requirements.txt fájlba: openpyxl"
        )
        return {
            "creators": pd.DataFrame(),
            "progressors": pd.DataFrame(),
            "build_up": pd.DataFrame(),
            "defenders": pd.DataFrame(),
            "duel_players": pd.DataFrame(),
        }
    except Exception:
        return {
            "creators": pd.DataFrame(),
            "progressors": pd.DataFrame(),
            "build_up": pd.DataFrame(),
            "defenders": pd.DataFrame(),
            "duel_players": pd.DataFrame(),
        }
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


def first_existing_column(df: Optional[pd.DataFrame], candidates: List[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    lowered = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    return None


def get_player_col(df: Optional[pd.DataFrame]) -> Optional[str]:
    return first_existing_column(df, ["Player", "player", "Játékos", "jatekos"])


def get_current_coach_controls() -> Dict[str, object]:
    return {
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
        "suggested_plan_a": st.session_state.get("selected_plan_a", "GAT"),
        "suggested_plan_b": st.session_state.get("selected_plan_b", "BAT"),
        "suggested_split": st.session_state.get("selected_split", 60),
    }


def apply_coach_adjustments(base_dims: Dict[str, Dict[str, float]], controls: Dict[str, object]):
    adjusted = {k: dict(v) for k, v in base_dims.items()}
    impacts = []

    def add(dim: str, delta: float, reason: str):
        if dim not in adjusted:
            return
        before = adjusted[dim]["KTE"]
        adjusted[dim]["KTE"] = round(clamp(before + delta), 1)
        adjusted[dim]["Edge"] = round(adjusted[dim]["KTE"] - adjusted[dim]["ELL"], 1)
        impacts.append({"Dimenzió": dim, "Hatás": round(delta, 1), "Ok": reason})

    focus_areas = controls.get("focus_areas", []) or []
    for area in focus_areas:
        if area == "pressing":
            add("Letámadás", 0.8, "Coach fókusz: pressing")
            add("Labdabirtoklás", -0.2, "Coach fókusz: pressing trade-off")
        elif area == "build-up":
            add("Labdakihozatal", 0.8, "Coach fókusz: build-up")
            add("Labdabirtoklás", 0.4, "Coach fókusz: build-up")
            add("Átmenetek", -0.2, "Coach fókusz: build-up trade-off")
        elif area == "transition":
            add("Átmenetek", 0.9, "Coach fókusz: transition")
            add("Támadó játék", 0.4, "Coach fókusz: transition")
            add("Labdabirtoklás", -0.2, "Coach fókusz: transition trade-off")
        elif area == "set pieces":
            add("Pontrúgások", 0.9, "Coach fókusz: set pieces")
        elif area == "rest defense":
            add("Letámadás", 0.5, "Coach fókusz: rest defense")
            add("Lövésprofil", -0.2, "Coach fókusz: rest defense trade-off")

    build_up = controls.get("build_up_solution")
    if build_up == "rövid":
        add("Labdakihozatal", 0.7, "Rövid build-up")
        add("Labdabirtoklás", 0.5, "Rövid build-up")
        add("Átmenetek", -0.3, "Rövid build-up trade-off")
    elif build_up == "direkt":
        add("Átmenetek", 0.7, "Direkt build-up")
        add("Támadó játék", 0.3, "Direkt build-up")
        add("Labdabirtoklás", -0.5, "Direkt build-up trade-off")
        add("Labdakihozatal", -0.2, "Direkt build-up trade-off")

    block = controls.get("defensive_block")
    if block == "mély":
        add("Letámadás", -0.3, "Mély blokk")
        add("Átmenetek", 0.5, "Mély blokk")
        add("Pontrúgások", 0.2, "Mély blokk")
    elif block == "magas":
        add("Letámadás", 0.8, "Magas blokk")
        add("Labdabirtoklás", 0.2, "Magas blokk")
        add("Átmenetek", -0.2, "Magas blokk trade-off")

    pressing_zone = controls.get("pressing_zone")
    if pressing_zone == "half-space":
        add("Letámadás", 0.4, "Half-space pressing fókusz")
        add("Támadó játék", 0.2, "Half-space pressing fókusz")
    elif pressing_zone in ["bal", "jobb"]:
        add("Letámadás", 0.3, f"Oldalsó pressing fókusz: {pressing_zone}")

    scenario = controls.get("match_scenario")
    if scenario == "conservative":
        add("Labdakihozatal", 0.3, "Konzervatív forgatókönyv")
        add("Labdabirtoklás", 0.3, "Konzervatív forgatókönyv")
        add("Átmenetek", -0.3, "Konzervatív forgatókönyv trade-off")
    elif scenario == "aggressive":
        add("Letámadás", 0.5, "Agresszív forgatókönyv")
        add("Támadó játék", 0.5, "Agresszív forgatókönyv")
        add("Lövésprofil", 0.2, "Agresszív forgatókönyv")
        add("Labdakihozatal", -0.2, "Agresszív forgatókönyv trade-off")

    plan_a = int(controls.get("plan_a_emphasis", 60))
    if plan_a >= 65:
        add("Támadó játék", 0.3, "Magas Plan A hangsúly")
    elif plan_a <= 54:
        add("Labdakihozatal", 0.2, "Kiegyenlítettebb terv")
        add("Átmenetek", 0.2, "Kiegyenlítettebb terv")

    set_piece = controls.get("set_piece_priority")
    if set_piece == "támadó":
        add("Pontrúgások", 0.5, "Támadó pontrúgás-prioritás")
    elif set_piece == "védekező":
        add("Letámadás", 0.2, "Védekező pontrúgás-prioritás")
    elif set_piece == "mindkettő":
        add("Pontrúgások", 0.3, "Kétoldali pontrúgás-prioritás")

    if controls.get("second_ball_focus"):
        add("Átmenetek", 0.4, "Second ball fókusz")
        add("Pontrúgások", 0.2, "Second ball fókusz")
    if controls.get("halfspace_defense_priority"):
        add("Letámadás", 0.3, "Félterület-védekezési prioritás")
        add("Labdakihozatal", 0.2, "Félterület-védekezési prioritás")

    impact_df = pd.DataFrame(impacts)
    if not impact_df.empty:
        impact_df = impact_df.groupby(["Dimenzió", "Ok"], as_index=False)["Hatás"].sum()
        impact_df["Hatás"] = impact_df["Hatás"].round(1)

    summary_rows = []
    for dim, vals in base_dims.items():
        summary_rows.append({
            "Dimenzió": dim,
            "Alap KTE": vals["KTE"],
            "Szimulált KTE": adjusted[dim]["KTE"],
            "ELL": vals["ELL"],
            "Alap edge": vals["Edge"],
            "Szimulált edge": adjusted[dim]["Edge"],
            "Δ": round(adjusted[dim]["KTE"] - vals["KTE"], 1),
        })
    return adjusted, impact_df, pd.DataFrame(summary_rows)


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
        player_col = get_player_col(df)
        if df is None or df.empty or not player_col:
            continue
        for _, row in df.head(3).iterrows():
            player = str(row.get(player_col, "")).strip()
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
        f"forgatókönyv: {controls.get('match_scenario', '-')}."
    )
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
    controls = get_current_coach_controls()
    summary = build_coach_summary(controls)
    for k, v in summary.items():
        st.session_state[k] = v
    st.session_state["selected_plan_a"] = controls["primary_model"]
    st.session_state["selected_plan_b"] = controls["secondary_model"]
    st.session_state["selected_split"] = int(controls["plan_a_emphasis"])
    base_dims = st.session_state.get("dims")
    if base_dims:
        adjusted_dims, impact_df, comparison_df = apply_coach_adjustments(base_dims, controls)
        st.session_state["dims_adjusted"] = adjusted_dims
        st.session_state["coach_impact_df"] = impact_df
        st.session_state["coach_dim_comparison"] = comparison_df
        ds = build_decision_support(
            base_dims,
            adjusted_dims,
            controls,
            st.session_state.get("team_metrics"),
            st.session_state.get("opp_metrics"),
            st.session_state.get("team_matches"),
            st.session_state.get("opp_matches"),
            st.session_state.get("opp_pdf_insights"),
        )
        st.session_state["decision_support"] = ds
        runtime = build_runtime_narrative_texts(
            adjusted_dims if st.session_state.get("use_adjusted_dims", True) else base_dims,
            controls,
            st.session_state.get("team_metrics"),
            st.session_state.get("opp_metrics"),
            st.session_state.get("team_matches"),
            st.session_state.get("opp_matches"),
            st.session_state.get("opp_pdf_insights"),
            st.session_state.get("opp_players"),
            ds,
        )
        st.session_state["opponent_profile_text"] = runtime["opponent_profile_text"]
        st.session_state["own_state_text"] = runtime["own_state_text"]
        st.session_state["three_keys_text"] = runtime["three_keys_text"]
        st.session_state["risks_text"] = runtime["risks_text"]
        st.session_state["match_dynamics_text"] = runtime["match_dynamics_text"]
        st.session_state["conclusion_text"] = runtime["conclusion_text"]


def metric_pm(metrics: Optional[Dict[str, float]], key: str, matches: Optional[int]) -> float:
    if not metrics:
        return 0.0
    return round(metrics.get(key, 0) / max(matches or 1, 1), 2)


def build_decision_support(base_dims, adjusted_dims, controls, team_metrics, opp_metrics, team_matches, opp_matches, opp_pdf_insights):
    base_dims = base_dims or {}
    adjusted_dims = adjusted_dims or base_dims or {}
    controls = controls or {}

    def dim_delta(name: str) -> float:
        if name not in adjusted_dims or name not in base_dims:
            return 0.0
        return round(adjusted_dims[name]["KTE"] - base_dims[name]["KTE"], 1)

    changes = []
    for dim in adjusted_dims:
        if dim in base_dims:
            d = dim_delta(dim)
            if abs(d) > 0:
                changes.append({"dim": dim, "delta": d})
    changes = sorted(changes, key=lambda x: abs(x["delta"]), reverse=True)

    opp_shots_pm = metric_pm(opp_metrics, "shots", opp_matches)
    opp_entries_pm = metric_pm(opp_metrics, "entries_box", opp_matches)
    opp_keypasses_pm = metric_pm(opp_metrics, "key_passes", opp_matches)
    team_entries_pm = metric_pm(team_metrics, "entries_box", team_matches)
    team_keypasses_pm = metric_pm(team_metrics, "key_passes", team_matches)
    opp_poss = opp_metrics.get("possession_pct", 0)
    if opp_poss <= 1:
        opp_poss *= 100
    team_press = team_metrics.get("pressing_success_pct", 0)
    if team_press <= 1:
        team_press *= 100
    opp_pass = opp_metrics.get("passes_accurate_pct", 0)
    if opp_pass <= 1:
        opp_pass *= 100

    archetype = _infer_opponent_archetype(adjusted_dims, opp_pdf_insights)
    top_for = sorted([(k, v.get("Edge", 0)) for k, v in adjusted_dims.items() if float(v.get("Edge", 0)) > 0], key=lambda x: x[1], reverse=True)[:3]
    top_against = sorted([(k, v.get("Edge", 0)) for k, v in adjusted_dims.items() if float(v.get("Edge", 0)) < 0], key=lambda x: x[1])[:3]

    matchup_notes = []
    if opp_pass >= 74:
        matchup_notes.append("Az ellenfél stabilan hozza fel a labdát, ezért a pressinget váltási jelekhez kell kötni, és nem érdemes túl korán kinyitni a csapatot.")
    elif opp_pass >= 68:
        matchup_notes.append("Az ellenfél passzjátéka nem kiemelkedő, ezért az irányított pressingcsapdák működhetnek a legjobban.")
    else:
        matchup_notes.append("Az ellenfél passzjátéka sebezhetőbb, ezért a feljebb indított pressingből több labdaszerzés jöhet.")

    if opp_entries_pm >= 16 or opp_shots_pm >= 10:
        matchup_notes.append("Az ellenfél sokszor és sok játékossal érkezik a box környékére, ezért a rest defense szerkezetet végig stabilan kell tartani, és a tizenhatos előtti területet folyamatosan védeni kell.")
    elif opp_entries_pm >= 11:
        matchup_notes.append("Az ellenfél rendszeresen eljut a támadóharmadba, de ezt nem csak mély védekezéssel kell kezelni; a középső zóna zárása kulcskérdés.")
    else:
        matchup_notes.append("Mivel az ellenfél kevesebb emberrel érkezik a box elé, bátrabban lehet játékost vinni a labda elé és nagyobb területet támadni.")

    if team_entries_pm >= opp_entries_pm and team_keypasses_pm >= opp_keypasses_pm:
        matchup_notes.append("A saját támadóprofil alapján van alap a türelmesebben felépített, több fázisból kialakított támadásokhoz.")
    elif team_entries_pm < opp_entries_pm:
        matchup_notes.append("A saját támadóvolumen önmagában nem ad elég előnyt, ezért inkább a helyzetminőség és az átmenetek hatékonysága dönthet.")
    else:
        matchup_notes.append("A két csapat támadóprofilja hasonló, ezért a meccset inkább a szerkezeti döntések és a jó ütemű váltások fogják eldönteni.")

    cards = []
    def add_card(title, choice, gains, costs, fit, dims):
        cards.append({
            "title": title,
            "choice": choice,
            "gains": unique_keep_order(gains)[:3],
            "costs": unique_keep_order(costs)[:3],
            "fit": fit,
            "dims": dims,
        })

    build_up = controls.get("build_up_solution", "vegyes")
    block = controls.get("defensive_block", "közepes")
    plan_a = controls.get("primary_model", "KIE")
    plan_b = controls.get("secondary_model", "BAT")

    # richer cards
    if build_up == "rövid":
        add_card("Labdakihozatal döntés", "Rövid build-up",
                 ["Stabilabb első passzsor és több kontroll az első két fázisban.", "Könnyebb a ritmusszabályozás és a pozíciós előkészítés."],
                 ["Nő a presszingcsapda-kitettség.", "A direkt területnyerés sebessége csökkenhet."],
                 "Akkor illeszkedik jól, ha az ellenfél nem tud tartósan hatékony magas nyomást fenntartani.",
                 ["Labdakihozatal", "Labdabirtoklás", "Átmenetek"])
    elif build_up == "direkt":
        add_card("Labdakihozatal döntés", "Direkt build-up",
                 ["Gyorsabban lehet átjátszani az első nyomást.", "Nőhet a második labdák és a kevés passzos helyzetek száma."],
                 ["Csökkenhet a kontroll és a visszatámadás előkészítettsége.", "Pontatlan első passz után hosszabb védekezési szakasz jöhet."],
                 "Akkor működik jól, ha az ellenfél nyomás mögött nyit területet vagy aerial/second-ball fölény építhető.",
                 ["Átmenetek", "Támadó játék", "Labdabirtoklás"])
    else:
        add_card("Labdakihozatal döntés", "Vegyes build-up",
                 ["Rugalmas váltás rövid és direkt megoldások között.", "Kisebb a kiszámíthatóság, több meccsforgatókönyv nyitva marad."],
                 ["Ha nincs egyértelmű trigger, döntési bizonytalanság lassíthatja a progressziót.", "A ritmusszabályozás nehezebb lehet hosszabb szakaszokban."],
                 "Vegyes profilú ellenfél ellen a legstabilabb köztes megoldás.",
                 ["Labdakihozatal", "Átmenetek"])

    if block == "magas":
        add_card("Blokkmagasság döntés", "Magas blokk",
                 ["Felül lehet megszerezni a labdát.", "Rövidülhet az út az ellenfél kapujáig."],
                 ["Megnő a mélységi terület kitettsége.", "Pontatlan kilépésnél gyors ellenátmenet jöhet."],
                 "Különösen akkor vállalható, ha az ellenfél passzbiztonsága nem kiemelkedő és a saját presszinghatékonyság jó.",
                 ["Letámadás", "Labdabirtoklás", "Átmenetek"])
    elif block == "mély":
        add_card("Blokkmagasság döntés", "Mély blokk",
                 ["Jobban védhető a kapu előtere és a mélység.", "Erősebb lehet a kontrás meccskép."],
                 ["Több területi nyomás kerül az ellenfélhez.", "Kevesebb lehet a magasan szerzett labda."],
                 "Akkor logikus, ha az ellenfél magas volumenben támadja a boxot vagy te akarod szűkíteni a meccset.",
                 ["Átmenetek", "Letámadás", "Pontrúgások"])
    else:
        add_card("Blokkmagasság döntés", "Közepes blokk",
                 ["Jobb strukturális egyensúly.", "Könnyebb menet közben váltani Plan A és Plan B között."],
                 ["Kevesebb extrém edge.", "Ha nincs jó pressing-trigger, passzívvá válhat."],
                 "Vegyes matchupoknál jó kompromisszum, főleg ha több szakaszban másképp akarod kezelni a meccset.",
                 ["Letámadás", "Átmenetek"])

    focus_areas = controls.get("focus_areas", []) or []
    if focus_areas:
        gains, costs, affected = [], [], []
        area_templates = {
            "pressing": ("Több labdaszerzés jöhet az ellenfél első két fázisában.", "Ha nem zár mögötte a szerkezet, nő a mélységi kitettség.", ["Letámadás"]),
            "build-up": ("Tisztább lesz a saját első és második passzsor.", "A támadási ritmus lassulhat, ha túl sok az előkészítő passz.", ["Labdakihozatal", "Labdabirtoklás"]),
            "transition": ("Nőhet a kevés passzból kialakított helyzetek száma.", "Több lehet a gyors labdavesztés utáni rendezetlenség.", ["Átmenetek", "Támadó játék"]),
            "set pieces": ("A pontrúgásból származó edge jobban kiaknázható.", "Nyílt játékban kevesebb fókusz maradhat.", ["Pontrúgások"]),
            "rest defense": ("Erősebb lehet az átmeneti védekezés és a második hullám kontrollja.", "Kevesebb játékos csatlakozik támadásban a labda elé.", ["Letámadás", "Lövésprofil"]),
        }
        for area in focus_areas:
            if area in area_templates:
                g, c, a = area_templates[area]
                gains.append(g); costs.append(c); affected += a
        add_card("Meccskép-prioritás", ", ".join(focus_areas), gains, costs,
                 f"A fókuszterületek együtt adják a meccsidentitást; a {label_strategy(plan_a)} tervet ezek az elemek teszik konkréttá.",
                 unique_keep_order(affected))

    scenario = controls.get("match_scenario", "balanced")
    scenario_label = {"conservative": "konzervatív", "balanced": "kiegyensúlyozott", "aggressive": "agresszív"}.get(scenario, scenario)
    add_card("Meccsdinamika forgatókönyv", scenario_label,
             {
                 "conservative": ["Kisebb variancia, több kontroll a meccs elején.", "Jobb szerkezeti stabilitás labdavesztés után."],
                 "balanced": ["Könnyebb váltani a két terv között.", "Nem feszíti túl korán a meccset."],
                 "aggressive": ["Gyorsabb meccsnyitás és több támadó akció.", "Erősebb pszichológiai nyomás az ellenfélen."],
             }.get(scenario, []),
             {
                 "conservative": ["Nehezebb lehet korán dominálni a területet.", "A támadó volumen visszafogottabb maradhat."],
                 "balanced": ["Kevesebb szélsőértékű edge.", "A döntési helyzetek egy része nyitva marad a pályán."],
                 "aggressive": ["Nő a strukturális kockázat és az átmeneti sebezhetőség.", "Gyors fáradás vagy pontrúgás-kitettség jöhet."],
             }.get(scenario, []),
             "A forgatókönyv nem csak tempót, hanem kockázatvállalási szintet is kijelöl.",
             ["Letámadás", "Támadó játék", "Labdakihozatal"])

    special_gains, special_costs, special_dims = [], [], []
    if controls.get("second_ball_focus"):
        special_gains.append("Tisztább lehet a direkt játék utáni második akció.")
        special_costs.append("A második labdára rendezés miatt kevesebb játékos marad magas pozícióban.")
        special_dims += ["Átmenetek", "Támadó játék"]
    if controls.get("halfspace_defense_priority"):
        special_gains.append("Jobban védhető az ellenfél belső kombinációs csatornája.")
        special_costs.append("A szélső terület felé terelődhet az ellenfél támadása.")
        special_dims += ["Letámadás", "Lövésprofil"]
    set_piece = controls.get("set_piece_priority", "mindkettő")
    if set_piece:
        special_gains.append(f"Pontrúgás-fókusz: {set_piece}.")
        special_dims.append("Pontrúgások")
    if special_gains or special_costs:
        add_card("Speciális hangsúlyok", " / ".join([x for x in ["second ball" if controls.get("second_ball_focus") else "", "half-space" if controls.get("halfspace_defense_priority") else "", f"pontrúgás:{set_piece}" if set_piece else ""] if x]),
                 special_gains or ["Nincs külön extra hangsúly."],
                 special_costs or ["Nincs külön extra kompromisszum megjelölve."],
                 "Ezek a jelölések finomhangolják a meccstervet, főleg a részhelyzetek kezelésében.",
                 unique_keep_order(special_dims))

    top_changes = [f"{x['dim']} ({x['delta']:+.1f})" for x in changes[:3]]
    baseline = baseline_coach_controls(
        controls.get("suggested_plan_a", controls.get("primary_model", "KIE")),
        controls.get("suggested_plan_b", controls.get("secondary_model", "BAT")),
        int(controls.get("suggested_split", controls.get("plan_a_emphasis", 60))),
    )
    has_manual = has_meaningful_coach_intervention(controls, baseline)

    if has_manual:
        executive = (
            f"Az edzői finomhangolás az alap adatalapú matchup-képhez képest leginkább a következő dimenziókat mozdítja el: {', '.join(top_changes) or 'nincs számottevő eltolás'}. "
            f"Ez a gyakorlatban azt jelenti, hogy a terv a(z) {label_strategy(plan_a)} irányába tolódik, miközben tartalék opcióként a(z) {label_strategy(plan_b)} megmarad. "
            f"A súlypont {controls.get('plan_a_emphasis', 60)}/{100-int(controls.get('plan_a_emphasis', 60))} arányban az A terv felé húz."
        )
    else:
        executive = ""

    recommendation = []
    if block == "magas" and opp_pass < 72:
        recommendation.append("A magasabb blokk is vállalható, mert az ellenfél passzbiztonsága nem olyan erős, hogy folyamatosan átbontsa a nyomást.")
    elif block == "magas":
        recommendation.append("A magas blokk inkább szakaszosan ajánlott; az ellenfél passzjátéka miatt a pressinget célszerű váltási jelekhez kötni.")
    if build_up == "direkt" and opp_entries_pm >= 15:
        recommendation.append("Ha direkt labdakihozatalt választunk, a rest defense-et külön biztosítani kell, mert az ellenfél a visszatámadásokból is veszélyes lehet.")
    if build_up == "rövid" and team_press < 50:
        recommendation.append("Rövid build-upnál kulcsfontosságú az első labdavesztés utáni azonnali reakció, mert a saját pressinghatékonyság nem kiemelkedő.")
    if controls.get("second_ball_focus"):
        recommendation.append("A second ball fókusz jól illeszkedik ehhez a matchuphoz, főleg ha nő a direkt szakaszok száma.")

    return {
        "executive_summary": executive,
        "top_dimension_changes": top_changes if has_manual else [],
        "matchup_notes": unique_keep_order(matchup_notes)[:3],
        "recommendation": unique_keep_order(recommendation)[:4] if has_manual else [],
        "cards": cards if has_manual else [],
        "has_manual_intervention": has_manual,
        "archetype": archetype,
        "top_for": top_for,
        "top_against": top_against,
        "opp_shots_pm": opp_shots_pm,
        "opp_entries_pm": opp_entries_pm,
        "opp_keypasses_pm": opp_keypasses_pm,
        "team_entries_pm": team_entries_pm,
        "team_keypasses_pm": team_keypasses_pm,
        "opp_pass": opp_pass,
    }


def render_methodology_block():
    with st.expander("Metodika / hogyan dolgozik az app", expanded=False):
        st.markdown(
            """
Ez az alkalmazás **adatalapú taktikai döntéselőkészítő**, amely a match Excel, player Excel és célzott PDF-scouting inputokból épít egységes **matchup-profilt**. A modell a két csapatot **10 tényező mentén** hasonlítja össze: a 7 alapdimenzió mellett külön kezeli a **build-up sebezhetőséget (BUVI)**, az **átmeneti fenyegetést (TTS)** és a **press resistance-et (PRS2)**. Ezt a képet illeszti rá a **9 alapstratégiára**: **KON** kontra mély blokkból, **GAT** gyors átmenet, **BAT** középső blokk + átmenet, **KIE** kiegyensúlyozott játék, **PRS** presszing + átmenet, **MLT** magas letámadás, **DOM** dominancia, **POZ** pozíciós támadás, **LAB** mélyebb labdatartás. A javaslat tehát nem tipp, hanem több adatforrásból épített matchup-vizsgálat, amelyben **MI-alapú strukturálás** és a saját szakmai finomhangolásod egyszerre jelenik meg. A narratíva sem fix sablon: a rendszer több száz szövegfragmentumból és kontextusfüggő logikai ágból építkezik, amelyek együtt több ezer lehetséges briefingváltozatot adnak. Az edzői beavatkozás után a rendszer végig következetesen újrasúlyozza a képet, így az export már a módosított döntési logikát mutatja.
            """
        )


def get_methodology_summary() -> str:
    return (
        "Ez a briefing egy adatalapú taktikai döntéselőkészítő rendszerből készül. "
        "A modell 10 tényező mentén hasonlítja össze a két csapatot: letámadás, labdakihozatal, átmenetek, támadó játék, pontrúgások, labdabirtoklás, lövésprofil, build-up sebezhetőség (BUVI), átmeneti fenyegetés (TTS) és press resistance (PRS2). "
        "Ezt a képet 9 alapstratégiára vetítjük: KON kontra mély blokkból, GAT gyors átmenet, BAT középső blokk + átmenet, KIE kiegyensúlyozott, PRS presszing + átmenet, MLT magas letámadás, DOM dominancia, POZ pozíciós támadás és LAB mélyebb labdatartás. "
        "A Plan A és Plan B ezért nem megérzésből születik, hanem statisztikai matchup-vizsgálatból, MI-alapú strukturálásból és szakmai modellezésből. "
        "A narratíva sem fix sablon: a rendszer több száz szövegfragmentumból és kontextusfüggő logikai ágból építkezik, amelyek együtt több ezer lehetséges briefingváltozatot adnak. "
        "Az eredmény egy gyorsan értelmezhető, edzői döntést támogató összkép."
    )

def _safe_player_name(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _player_record_name(record) -> str:
    if isinstance(record, dict):
        return _safe_player_name(record.get("player") or record.get("Player") or record.get("name") or record.get("Name"))
    return _safe_player_name(record)


def _player_record_position(record) -> str:
    if isinstance(record, dict):
        return _safe_player_name(record.get("position") or record.get("Position") or record.get("pos") or record.get("Pos"))
    return ""


def _dimension_order(dims: Dict[str, Dict[str, float]]):
    rows = []
    for dim, vals in (dims or {}).items():
        edge = float(vals.get("Edge", 0) or 0)
        rows.append((dim, edge, float(vals.get("KTE", 0) or 0), float(vals.get("ELL", 0) or 0)))
    rows.sort(key=lambda x: abs(x[1]), reverse=True)
    return rows


def _infer_opponent_archetype(dims: Dict[str, Dict[str, float]], opp_pdf_insights=None) -> str:
    kte_poss = float((dims or {}).get("Labdabirtoklás", {}).get("KTE", 0) or 0)
    opp_poss = float((dims or {}).get("Labdabirtoklás", {}).get("ELL", 0) or 0)
    opp_trans = float((dims or {}).get("Átmenetek", {}).get("ELL", 0) or 0)
    opp_buildup = float((dims or {}).get("Labdakihozatal", {}).get("ELL", 0) or 0)
    opp_press = float((dims or {}).get("Letámadás", {}).get("ELL", 0) or 0)
    opp_attack = float((dims or {}).get("Támadó játék", {}).get("ELL", 0) or 0)

    if opp_trans >= 7.2 and opp_attack >= 6.0:
        return "átmenet-orientált"
    if opp_buildup >= 7.0 and opp_poss >= 6.8:
        return "build-up / labdabirtoklás-orientált"
    if opp_press >= 7.0:
        return "presszing-orientált"
    if opp_attack < 5.5 and opp_poss < 5.5:
        return "reaktív / alacsony blokkos"
    if opp_attack >= 7.0 and opp_trans < 6.0:
        return "pozíciós támadó"
    return "vegyes profilú"


def _plan_identity(plan_code: str) -> str:
    mapping = {
        "PRS": "triggerelt presszingre és gyors átmenetekre építő",
        "MLT": "agresszív magas letámadásra építő",
        "BAT": "középső blokkos, átmenetekre támaszkodó",
        "DOM": "dominancia- és területkontroll-alapú",
        "POZ": "pozíciós támadásokkal kontrolláló",
        "KIE": "kiegyensúlyozott, több forgatókönyvet nyitva hagyó",
        "LAB": "labdatartásra és ritmusszabályozásra építő",
        "GAT": "gyors átmenetekkel operáló",
        "KON": "reaktív, kontrákból veszélyeztető",
    }
    return mapping.get(plan_code, label_strategy(plan_code))


def _edge_rankings(dims: Dict[str, Dict[str, float]]):
    rows = [(dim, float(vals.get("Edge", 0) or 0)) for dim, vals in (dims or {}).items()]
    top_for = sorted([x for x in rows if x[1] > 0], key=lambda x: x[1], reverse=True)
    top_against = sorted([x for x in rows if x[1] < 0], key=lambda x: x[1])
    return top_for, top_against


def _dim_action_hint(dim: str, positive: bool = True) -> str:
    positive_map = {
        "Letámadás": "itt lehet ráerőltetni a saját ritmusunkat a meccsre",
        "Labdakihozatal": "innen lehet tisztán felhozni a labdát és nyugodtan felépíteni a támadást",
        "Átmenetek": "labdaszerzés után innen lehet gyorsan veszélyt kialakítani",
        "Támadó játék": "ebben a fázisban lehet a legtöbb minőségi helyzetet kialakítani",
        "Pontrúgások": "itt külön pluszt lehet hozzátenni a meccshez",
        "Labdabirtoklás": "itt lehet kézben tartani a tempót és a területeket",
        "Lövésprofil": "itt lehet jobb helyzetekig eljutni, nem csak lövésig",
    }
    negative_map = {
        "Letámadás": "ha nem jó az időzítés, mögénk lehet játszani",
        "Labdakihozatal": "az első két passz környékén könnyen elakadhatunk",
        "Átmenetek": "labdavesztés után gyorsabban kell visszarendeződni",
        "Támadó játék": "önmagában a volumen kevés, jobb helyzeteket kell kialakítani",
        "Pontrúgások": "az állított szituációkat külön fegyelemmel kell védeni",
        "Labdabirtoklás": "nem szabad önmagáért birtokolni a labdát",
        "Lövésprofil": "a box előtti területet szorosabban kell védeni",
    }
    return (positive_map if positive else negative_map).get(dim, "ez a terület külön figyelmet kér")

def _plan_text_bank(plan_code: str) -> List[str]:
    banks = {
        "PRS": [
            "A fő terv alapja a triggerelt pressing.",
            "A nyomást nem folyamatosan kell indítani, hanem a kijelölt pillanatokban, hogy kizökkentsük az ellenfél build-upját.",
            "Labdaszerzés után gyorsan kell támadni, mielőtt az ellenfél visszarendeződik.",
        ],
        "MLT": [
            "A fő terv magas letámadásra épül.",
            "Az ellenfél első passzaira kell nyomást tenni, hogy minél több labdát szerezzünk az ő térfelükön.",
            "A magasan megszerzett labdákból rögtön kapura kell támadni.",
        ],
        "BAT": [
            "A fő terv középső blokkos szerkezetből indul.",
            "A presszinget inkább csapdákban kell használni, nem végig teljes pályán.",
            "Labdaszerzés után gyors, de kontrollált átmenetekre kell törekedni.",
        ],
        "DOM": [
            "A fő terv a területi fölényre és a meccs kontrolljára épül.",
            "A hangsúly a ritmus szabályozásán és a tartós támadóharmadbeli jelenléten van.",
            "Labdával türelmes, szervezett játékra van szükség.",
        ],
        "POZ": [
            "A fő terv pozíciós támadásokkal bontaná az ellenfelet.",
            "A szélesség, a half-space jelenlét és a jó ütemű helycserék döntőek lehetnek.",
            "A labdabirtoklás itt eszköz: az a cél, hogy megbontsuk az ellenfél szerkezetét.",
        ],
        "KIE": [
            "A fő terv kiegyensúlyozott meccsvezetést ad.",
            "A stabilitás az első, és onnan lehet rágyorsítani a megfelelő pillanatokban.",
            "Nem egyetlen extrém döntésre épít, hanem fokozatos előnyszerzésre.",
        ],
        "LAB": [
            "A fő terv mélyebb labdatartásból szabályozná a ritmust.",
            "A cél az, hogy az ellenfelet mozgatni kelljen, és türelmetlenségbe hajtsuk.",
            "Ehhez stabil rest defense kell, hogy labdavesztés után se nyíljon meg a csapat.",
        ],
        "GAT": [
            "A fő terv gyors átmenetekből keres előnyt.",
            "Az első előre játék minősége fontosabb lesz, mint a hosszú előkészítés.",
            "A szélek és a második hullám érkezése külön hangsúlyt kap.",
        ],
        "KON": [
            "A fő terv reaktívabb, kontrákra építő meccset vetít előre.",
            "A blokk stabilitása és a visszazárás megelőzi a támadóvolument.",
            "A kulcs az első labdaszerzés utáni gyors és tiszta döntés.",
        ],
    }
    return banks.get(plan_code, [label_strategy(plan_code)])

def build_runtime_narrative_texts(dims, controls, team_metrics, opp_metrics, team_matches, opp_matches, opp_pdf_insights, opp_players, ds=None) -> Dict[str, str]:
    dims = dims or {}
    controls = controls or {}
    ds = ds or {}
    archetype = ds.get("archetype") or _infer_opponent_archetype(dims, opp_pdf_insights)
    top_for, top_against = _edge_rankings(dims)
    plan_a = controls.get("primary_model", st.session_state.get("selected_plan_a", "KIE"))
    plan_b = controls.get("secondary_model", st.session_state.get("selected_plan_b", "BAT"))
    split = int(controls.get("plan_a_emphasis", st.session_state.get("selected_split", 60)))
    build_up = controls.get("build_up_solution", "vegyes")
    block = controls.get("defensive_block", "közepes")
    scenario = label_scenario(controls.get("match_scenario", "balanced"))
    zone = controls.get("pressing_zone", "közép")
    danger = summarize_danger_players({
        "creators": df_to_records(opp_players["creators"]) if opp_players and "creators" in opp_players else [],
        "progressors": df_to_records(opp_players["progressors"]) if opp_players and "progressors" in opp_players else [],
        "build_up": df_to_records(opp_players["build_up"]) if opp_players and "build_up" in opp_players else [],
        "defenders": df_to_records(opp_players["defenders"]) if opp_players and "defenders" in opp_players else [],
        "duel_players": df_to_records(opp_players["duel_players"]) if opp_players and "duel_players" in opp_players else [],
    }) if opp_players else []

    opp_profile_lines = [
        f"Az ellenfél összképe alapján {archetype} profil rajzolódik ki.",
        f"A fő meccsterv a {label_strategy(plan_a)}, tartalék váltásként pedig a {label_strategy(plan_b)} marad készenlétben; a súlyozás most {split}/{100-split}.",
    ]
    if ds.get("opp_pass"):
        opp_profile_lines.append(
            f"Az ellenfél passzbiztonsága {round(float(ds['opp_pass']), 1)}%, ezért a build-up elleni nyomást ehhez a szinthez kell igazítani."
        )
    if top_against:
        opp_profile_lines.append(
            f"Jelenleg a legnagyobb ellenféloldali veszély a(z) {top_against[0][0].lower()} területén jelenik meg."
        )

    own_state_lines = [
        f"Az ajánlott alapkeret: {build_up} build-up, {block} blokk és {scenario.lower()} meccskezelés.",
        f"A pressing fő fókusza: {zone}; a pontrúgásoknál a prioritás: {controls.get('set_piece_priority', 'mindkettő')}.",
    ]
    if controls.get("second_ball_focus"):
        own_state_lines.append("A second ball helyzeteket külön kell kezelni, főleg a direkt vagy lepattanós fázisokban.")
    if controls.get("halfspace_defense_priority"):
        own_state_lines.append("A half-space védelme kapjon külön hangsúlyt, mert az ellenfél innen tud a legveszélyesebben összekapcsolódni.")

    key_lines = []
    if top_for:
        dim, edge = top_for[0]
        key_lines.append(
            f"Az első kapaszkodó a(z) {dim.lower()} legyen, mert itt van a legnagyobb saját előny ({edge:+.1f})."
        )
        key_lines.append(_dim_action_hint(dim, True).capitalize() + ".")
    if top_against:
        dim, edge = top_against[0]
        key_lines.append(
            f"A legfontosabb biztosítási pont a(z) {dim.lower()} kezelése, mert itt az ellenfélnek van fölénye ({edge:+.1f})."
        )

    combo_map = {
        ("PRS", "MLT"): "A két terv együtt nyomásalapú meccstervet ad: az A terv inkább triggerelt pressing, a B terv pedig agresszívebb magas letámadás.",
        ("BAT", "DOM"): "A két terv együtt szerkezeti kontrollt ad: alapból középső blokk, labdával pedig dominánsabb irányba lehet váltani.",
        ("KIE", "BAT"): "A két terv együtt fokozatos meccsvezetést ad: stabil alap, majd célzott gyorsítás a megfelelő pillanatban.",
        ("DOM", "POZ"): "A két terv együtt tartós labdás kontrollt ad, eltérő bontási ritmussal és kellő türelemmel.",
        ("GAT", "KON"): "A két terv együtt gyors átmenetekre épít: az egyik támadóbb, a másik reaktívabb formában.",
    }
    combo_line = combo_map.get((plan_a, plan_b)) or (
        f"A két terv lényege, hogy a meccs alakulásától függően lehessen váltani a {label_strategy(plan_a)} és a {label_strategy(plan_b)} között."
    )
    key_lines.append(combo_line)
    if danger:
        key_lines.append(f"Személyi fókusz: {danger[0]}.")
    key_lines = unique_keep_order(key_lines)[:4]

    risk_lines = []
    if top_against:
        for dim, edge in top_against[:2]:
            risk_lines.append(f"Kockázati pont: {dim} – {_dim_action_hint(dim, False)}.")
    if archetype == "átmenet-orientált":
        risk_lines.append("Az ellenfél kevés passzból is gyorsan odaérhet a kapunk elé, ezért a rest defense egy pillanatra sem lazulhat fel.")
    elif archetype == "build-up / labdabirtoklás-orientált":
        risk_lines.append("Ha az első pressinghullámot átjátsszák, az ellenfél hosszabb labdás szakaszokat építhet fel.")
    elif archetype == "presszing-orientált":
        risk_lines.append("A saját build-up könnyen nyomás alá kerülhet, ezért az első két döntésnek tisztának és gyorsnak kell lennie.")
    elif archetype == "reaktív / alacsony blokkos":
        risk_lines.append("Ha türelmetlenül támadunk, könnyen belemehetünk az ellenfél kontrákra épülő meccsébe.")
    risk_lines = unique_keep_order(risk_lines)[:4]

    dyn_lines = []
    dyn_lines.append(
        f"A meccs alaphangja várhatóan {scenario.lower()} lesz, de a ritmust leginkább a(z) {label_strategy(plan_a)} terv aktiválási pontjai szabják majd meg."
    )
    dyn_lines += _plan_text_bank(plan_a)[:2]
    if archetype == "átmenet-orientált":
        dyn_lines.append("Ha a középső zónában sok szabad lepattanó marad, a meccs könnyen nyitottá válhat.")
    elif archetype == "build-up / labdabirtoklás-orientált":
        dyn_lines.append("Hosszabb ellenfél-labdabirtoklási szakaszokra is fel kell készülni, ezért a türelmes blokk fontosabb lehet, mint az állandó rohanás.")
    elif archetype == "reaktív / alacsony blokkos":
        dyn_lines.append("Az ellenfél valószínűleg nem fogja végig felvállalni a területet, ezért a meccs ritmusa sokszor rajtunk múlik majd.")
    elif archetype == "presszing-orientált":
        dyn_lines.append("Az első félidő kulcsa az lehet, mennyire tudunk rendezett szerkezettel kijönni az ellenfél nyomása alól.")
    if danger:
        player_name = danger[0].split(" – ")[0]
        dyn_lines.append(f"Személyi fókuszban {player_name} mozgása és kapcsolatai külön figyelmet kérnek.")
    dyn_lines = unique_keep_order(dyn_lines)[:5]

    conc_lines = []
    conc_lines.append(f"Az alapjavaslat a(z) {label_strategy(plan_a)}. Ha a meccs ezt kívánja, a(z) {label_strategy(plan_b)} irányába lehet váltani.")
    if top_for:
        conc_lines.append(
            f"A meccstervet érdemes a(z) {top_for[0][0].lower()} területére építeni, mert itt látszik a legnagyobb saját előny."
        )
    if top_against:
        conc_lines.append(
            f"A biztosítás első pontja a(z) {top_against[0][0].lower()} legyen, mert itt a legerősebb az ellenfél oldali veszély."
        )
    conc_lines.append(combo_line)
    if ds.get("matchup_notes"):
        conc_lines.append(ds["matchup_notes"][0])
    if danger:
        primary = danger[0]
        secondary = danger[1] if len(danger) > 1 else ""
        if secondary:
            conc_lines.append(f"Személyspecifikus fókusz: {primary}; másodlagos figyelmi pont: {secondary}.")
        else:
            conc_lines.append(f"Személyspecifikus fókusz: {primary}.")
    conc_lines = unique_keep_order(conc_lines)[:6]

    return {
        "opponent_profile_text": "\n".join(f"- {x}" for x in opp_profile_lines),
        "own_state_text": "\n".join(f"- {x}" for x in own_state_lines),
        "three_keys_text": "\n".join(f"- {x}" for x in key_lines),
        "risks_text": "\n".join(f"- {x}" for x in risk_lines),
        "match_dynamics_text": "\n".join(f"- {x}" for x in dyn_lines),
        "conclusion_text": "\n".join(f"- {x}" for x in conc_lines),
    }

def summarize_danger_players(key_player_threats: Dict[str, List[dict]]) -> List[str]:
    priority = ["creators", "progressors", "build_up", "duel_players", "defenders"]
    summaries = []
    seen = set()
    label_map = {
        "creators": "kreatív végrehajtó",
        "progressors": "előrejáték / területnyerés",
        "build_up": "build-up stabilitás",
        "duel_players": "párharc / második labda",
        "defenders": "labdaszerzés / védekezés",
    }
    payload = key_player_threats or {}
    for group in priority:
        rows = payload.get(group, []) if isinstance(payload, dict) else []
        for r in rows[:3]:
            name = _player_record_name(r)
            pos = _player_record_position(r)
            if not name or name in seen:
                continue
            seen.add(name)
            role = label_map.get(group, group)
            summaries.append(f"{name}{f' ({pos})' if pos else ''} – fő veszély: {role}")
            if len(summaries) >= 3:
                return summaries
    return summaries


def build_full_conclusion(package: Dict[str, object]) -> List[str]:
    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]
    ds = package.get("decision_support", {}) or {}
    dims = p1.get("dimensions", {})
    coach = package.get("coach_controls", {}) or {}
    top_for, top_against = _edge_rankings(dims)
    archetype = ds.get("archetype") or _infer_opponent_archetype(dims)
    danger = summarize_danger_players(p3.get("key_player_threats", {}))
    plan_a = p1.get("plan_a", "KIE")
    plan_b = p1.get("plan_b", "BAT")

    bullets = []
    bullets.append(f"Alapjavaslat: {label_strategy(plan_a)} legyen a fő terv, miközben a(z) {label_strategy(plan_b)} tartalék váltásként készenlétben marad.")
    bullets.append(_plan_text_bank(plan_a)[0])
    if top_for:
        bullets.append(f"A saját oldali legnagyobb edge a(z) {top_for[0][0].lower()} dimenzióban látszik, ezért a meccstervet erre a fölényre kell ráfűzni.")
        bullets.append(_dim_action_hint(top_for[0][0], True).capitalize() + ".")
    if top_against:
        bullets.append(f"A legnagyobb ellenfélfenyegetés a(z) {top_against[0][0].lower()} dimenzióban jelenik meg, ezért ezt kell elsőként biztosítani.")
        bullets.append(_dim_action_hint(top_against[0][0], False).capitalize() + ".")
    bullets.append(f"Az ellenfél összképe {archetype} profilra utal, ezért a választott terv akkor működik jól, ha a meccset nem általánosságban, hanem ehhez az archetípushoz igazítva menedzseljük.")
    if danger:
        bullets.append(f"Személyspecifikus fókusz: {danger[0]}; ezt érdemes külön mérkőzésen belüli jelzéssel is követni.")
    if ds.get("matchup_notes"):
        bullets.extend(ds.get("matchup_notes", [])[:2])
    return unique_keep_order([localize_summary_text(x) for x in bullets])[:7]


def get_full_conclusion_text(package: Dict[str, object]) -> str:
    return "\n".join([f"- {x}" for x in build_full_conclusion(package)])


def fit_drawing_to_width(drawing, max_width, max_height=None):
    if drawing is None:
        return None
    width = getattr(drawing, 'width', None) or 1
    height = getattr(drawing, 'height', None) or 1
    scale = max_width / width
    if max_height:
        scale = min(scale, max_height / height)
    drawing.width = width * scale
    drawing.height = height * scale
    drawing.scale(scale, scale)
    return drawing


def svg_string_to_drawing(svg_string: str, max_width_pts: float, max_height_pts: Optional[float] = None):
    if not (REPORTLAB_AVAILABLE and SVGLIB_AVAILABLE):
        return None
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.svg', delete=False, encoding='utf-8') as tmp:
        tmp.write(svg_string)
        tmp_path = tmp.name
    try:
        drawing = svg2rlg(tmp_path)
        drawing = fit_drawing_to_width(drawing, max_width_pts, max_height_pts)
        return drawing
    except Exception:
        return None
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

def svg_to_png_bytes(svg_string: str, width_px: int = 1600) -> Optional[bytes]:
    if not CAIROSVG_AVAILABLE:
        return None
    try:
        return cairosvg.svg2png(bytestring=svg_string.encode("utf-8"), output_width=width_px)
    except Exception:
        return None


def svg_to_base64_img_tag(svg_string: str, alt_text: str, width_style: str = "100%") -> str:
    png = svg_to_png_bytes(svg_string)
    if png:
        b64 = base64.b64encode(png).decode("ascii")
        return f"<img src='data:image/png;base64,{b64}' alt='{alt_text}' style='width:{width_style}; border-radius:12px;' />"
    return svg_string


def build_reportlab_chart_flowable(svg_string: str, max_width_pts: float, max_height_pts: Optional[float] = None):
    drawing = svg_string_to_drawing(svg_string, max_width_pts, max_height_pts)
    if drawing is not None:
        return drawing
    png = svg_to_png_bytes(svg_string)
    if png and REPORTLAB_AVAILABLE:
        img = Image(io.BytesIO(png))
        width = getattr(img, "drawWidth", max_width_pts) or max_width_pts
        height = getattr(img, "drawHeight", max_height_pts or max_width_pts * 0.6) or (max_height_pts or max_width_pts * 0.6)
        scale = min(max_width_pts / width, (max_height_pts / height) if max_height_pts else 1.0)
        img.drawWidth = width * scale
        img.drawHeight = height * scale
        return img
    return None


def png_bytes_to_base64_img_tag(png: Optional[bytes], alt_text: str, width_style: str = "100%") -> str:
    if png:
        b64 = base64.b64encode(png).decode("ascii")
        return f"<img src='data:image/png;base64,{b64}' alt='{alt_text}' style='width:{width_style}; border-radius:12px;' />"
    return f"<div>{alt_text}</div>"


def fig_to_png_bytes(fig) -> Optional[bytes]:
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        try:
            plt.close(fig)
        except Exception:
            pass
        return None


def get_radar_png_bytes(dims: Dict[str, Dict[str, float]]) -> Optional[bytes]:
    if not MATPLOTLIB_AVAILABLE:
        return svg_to_png_bytes(get_radar_svg(dims), 1800)
    labels = list(dims.keys())
    kte = [dims[k]["KTE"] for k in labels]
    ell = [dims[k]["ELL"] for k in labels]
    angles = [n / float(len(labels)) * 2 * math.pi for n in range(len(labels))]
    angles += angles[:1]
    kte += kte[:1]
    ell += ell[:1]
    fig = plt.figure(figsize=(8.4, 5.7), facecolor="#FBF8FE")
    ax = plt.subplot(111, polar=True)
    ax.set_facecolor("white")
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_rlabel_position(0)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], fontsize=8)
    ax.set_ylim(0, 10)
    ax.plot(angles, kte, linewidth=2.5, color="#5B2C83")
    ax.fill(angles, kte, color="#5B2C83", alpha=0.12)
    ax.plot(angles, ell, linewidth=2.0, color="#9D8ABA", linestyle="--")
    ax.fill(angles, ell, color="#B7A3C9", alpha=0.08)
    ax.legend(["KTE", "ELL"], loc="upper right", bbox_to_anchor=(1.18, 1.12), frameon=False)
    fig.suptitle("7 dimenziós radar", fontsize=15, fontweight="bold", color="#2F1D4A")
    fig.tight_layout()
    return fig_to_png_bytes(fig)


def get_bar_chart_png_bytes(dims: Dict[str, Dict[str, float]]) -> Optional[bytes]:
    if not MATPLOTLIB_AVAILABLE:
        return svg_to_png_bytes(get_bar_chart_svg(dims), 1800)
    labels = list(dims.keys())
    kte = [dims[k]["KTE"] for k in labels]
    ell = [dims[k]["ELL"] for k in labels]
    x = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(10.2, 4.6), facecolor="#FBF8FE")
    ax.set_facecolor("white")
    w = 0.36
    ax.bar([i - w/2 for i in x], kte, width=w, label="KTE", color="#5B2C83")
    ax.bar([i + w/2 for i in x], ell, width=w, label="ELL", color="#B7A3C9", edgecolor="#5B2C83")
    ax.set_ylim(0, 10)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    ax.set_title("Dimenzió-összehasonlítás", fontsize=15, fontweight="bold", color="#2F1D4A")
    fig.tight_layout()
    return fig_to_png_bytes(fig)


def get_strategy_map_png_bytes(selected_a: Optional[str] = None, selected_b: Optional[str] = None) -> Optional[bytes]:
    if not MATPLOTLIB_AVAILABLE:
        return svg_to_png_bytes(get_strategy_map_svg(selected_a, selected_b), 1800)
    rows = strategy_scatter_data(selected_a, selected_b)
    fig, ax = plt.subplots(figsize=(9.2, 5.2), facecolor="#FBF8FE")
    ax.set_facecolor("white")
    color_map = {"Paletta": "#5B2C83", "Plan A": "#E0A500", "Plan B": "#2AA7A1"}
    for row in rows:
        size = 210 if row["marker_type"] != "Paletta" else 130
        edge = "#2F1D4A" if row["marker_type"] != "Paletta" else "white"
        ax.scatter(row["x"], row["y"], s=size, color=color_map.get(row["marker_type"], "#5B2C83"), edgecolors=edge, linewidths=1.0, zorder=3)
        ax.text(row["x"], row["y"], row["code"], ha="center", va="center", fontsize=8.5, fontweight="bold", color="white" if row["marker_type"] != "Paletta" else "#F8F5FC", zorder=4)
    ax.set_xlim(0.5, 6.5)
    ax.set_ylim(0.5, 5.5)
    ax.set_xticks([1, 2, 3, 4, 5, 6])
    ax.set_xticklabels(["Direkt", "D/P", "Vegyes", "Kiegy.", "Kontroll", "Agresszív"], fontsize=9)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["Mély", "Alacsony-közép", "Közép", "Közép-magas", "Magas"], fontsize=9)
    ax.grid(alpha=0.25)
    ax.set_title("Stratégiai térkép", fontsize=15, fontweight="bold", color="#2F1D4A")
    ax.text(3.5, 5.72, "Blokkmagasság: mély → magas", ha="center", va="bottom", fontsize=9, color="#5C4A7A")
    ax.text(3.5, 0.22, "Játékstílus: direkt → kontroll", ha="center", va="top", fontsize=9, color="#5C4A7A")
    fig.tight_layout()
    return fig_to_png_bytes(fig)


def build_reportlab_png_flowable(png_bytes: Optional[bytes], max_width_pts: float, max_height_pts: Optional[float] = None):
    if not png_bytes or not REPORTLAB_AVAILABLE:
        return None
    try:
        img = Image(io.BytesIO(png_bytes))
        width = getattr(img, "drawWidth", max_width_pts) or max_width_pts
        height = getattr(img, "drawHeight", max_height_pts or max_width_pts * 0.6) or (max_height_pts or max_width_pts * 0.6)
        scale = min(max_width_pts / width, (max_height_pts / height) if max_height_pts else 1.0)
        img.drawWidth = width * scale
        img.drawHeight = height * scale
        return img
    except Exception:
        return None


def get_bar_chart_svg(dims: Dict[str, Dict[str, float]]) -> str:
    labels = list(dims.keys())
    width = 980
    height = 420
    left = 70
    bottom = 60
    top = 35
    chart_h = 280
    plot_w = 850
    groups = len(labels)
    group_w = plot_w / max(groups, 1)
    bar_w = min(26, group_w * 0.28)

    svg = [f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    svg.append('<rect width="100%" height="100%" rx="18" ry="18" fill="white" />')

    for tick in range(0, 11, 2):
        y = top + chart_h - (tick / 10.0) * chart_h
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#ECE7F4" stroke-width="1" />')
        svg.append(f'<text x="{left - 12}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="#7E7097">{tick}</text>')

    for i, label in enumerate(labels):
        center = left + i * group_w + group_w / 2
        kte = dims[label]["KTE"]
        ell = dims[label]["ELL"]
        x1 = center - bar_w - 4
        x2 = center + 4
        h1 = (kte / 10.0) * chart_h
        h2 = (ell / 10.0) * chart_h
        y1 = top + chart_h - h1
        y2 = top + chart_h - h2
        svg.append(f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{bar_w:.1f}" height="{h1:.1f}" rx="4" fill="#5B2C83" />')
        svg.append(f'<rect x="{x2:.1f}" y="{y2:.1f}" width="{bar_w:.1f}" height="{h2:.1f}" rx="4" fill="#B7A3C9" stroke="#5B2C83" stroke-width="0.8" />')
        wrapped = label.replace(' ', '\n').split('\n')
        wrapped = wrapped[:2] if len(wrapped) > 2 else wrapped
        base_y = top + chart_h + 18
        for j, part in enumerate(wrapped):
            svg.append(f'<text x="{center:.1f}" y="{base_y + 14*j:.1f}" font-size="11" text-anchor="middle" fill="#2F1D4A">{part}</text>')

    svg.append(f'<rect x="{width - 215}" y="26" width="180" height="58" rx="10" fill="#F8F5FC" stroke="#E1D8EE" />')
    svg.append(f'<rect x="{width - 195}" y="43" width="12" height="12" rx="2" fill="#5B2C83" />')
    svg.append(f'<text x="{width - 175}" y="54" font-size="13" fill="#2F1D4A">KTE</text>')
    svg.append(f'<rect x="{width - 120}" y="43" width="12" height="12" rx="2" fill="#B7A3C9" stroke="#5B2C83" stroke-width="0.8" />')
    svg.append(f'<text x="{width - 100}" y="54" font-size="13" fill="#2F1D4A">ELL</text>')
    svg.append('</svg>')
    return ''.join(svg)


def get_strategy_map_svg(selected_a: Optional[str] = None, selected_b: Optional[str] = None) -> str:
    rows = strategy_scatter_data(selected_a, selected_b)
    width = 980
    height = 470
    left = 110
    top = 50
    plot_w = 760
    plot_h = 300

    def px_x(v):
        return left + ((v - 1) / 5.0) * plot_w

    def px_y(v):
        return top + plot_h - ((v - 1) / 4.0) * plot_h

    colors = {"Paletta": "#5B2C83", "Plan A": "#E0A500", "Plan B": "#2AA7A1"}
    svg = [f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    svg.append('<rect width="100%" height="100%" rx="18" ry="18" fill="white" />')

    for x in range(1, 7):
        px = px_x(x)
        svg.append(f'<line x1="{px:.1f}" y1="{top}" x2="{px:.1f}" y2="{top + plot_h}" stroke="#ECE7F4" stroke-width="1" />')
    for y in range(1, 6):
        py = px_y(y)
        svg.append(f'<line x1="{left}" y1="{py:.1f}" x2="{left + plot_w}" y2="{py:.1f}" stroke="#ECE7F4" stroke-width="1" />')

    x_labels = ["Direkt", "D/P", "Vegyes", "Kiegy.", "Kontroll", "Agresszív"]
    for i, lab in enumerate(x_labels, start=1):
        svg.append(f'<text x="{px_x(i):.1f}" y="{top + plot_h + 28}" font-size="12" text-anchor="middle" fill="#2F1D4A">{lab}</text>')
    y_labels = {1: "Mély", 2: "Alacsony-közép", 3: "Közép", 4: "Közép-magas", 5: "Magas"}
    for i, lab in y_labels.items():
        svg.append(f'<text x="{left - 12}" y="{px_y(i) + 4:.1f}" font-size="12" text-anchor="end" fill="#2F1D4A">{lab}</text>')

    svg.append(f'<text x="{left + plot_w/2:.1f}" y="{height - 18}" font-size="13" text-anchor="middle" fill="#6D5B88">Játékstílus: Direkt → Kontroll</text>')
    svg.append(f'<text x="26" y="{top + plot_h/2:.1f}" font-size="13" transform="rotate(-90 26 {top + plot_h/2:.1f})" text-anchor="middle" fill="#6D5B88">Blokkmagasság: Mély → Magas</text>')

    for row in rows:
        x = px_x(row['x'])
        y = px_y(row['y'])
        fill = colors.get(row['marker_type'], '#5B2C83')
        size = 19 if row['marker_type'] != 'Paletta' else 16
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size}" fill="{fill}" opacity="0.92" />')
        svg.append(f'<text x="{x:.1f}" y="{y+5:.1f}" font-size="12" text-anchor="middle" fill="white" font-weight="700">{row["code"]}</text>')
    svg.append(f'<rect x="{width - 230}" y="26" width="190" height="76" rx="10" fill="#F8F5FC" stroke="#E1D8EE" />')
    for idx, (lab, col) in enumerate([('Paletta','#5B2C83'),('Plan A','#E0A500'),('Plan B','#2AA7A1')]):
        cy = 48 + idx*20
        svg.append(f'<circle cx="{width - 205}" cy="{cy}" r="6" fill="{col}" />')
        svg.append(f'<text x="{width - 190}" y="{cy+4}" font-size="12" fill="#2F1D4A">{lab}</text>')
    svg.append('</svg>')
    return ''.join(svg)


def build_html_export(package: Dict[str, object]) -> str:
    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]
    ds = package.get("decision_support", {}) or {}
    coach = package.get("coach_controls", {}) or {}
    danger = summarize_danger_players(p3.get("key_player_threats", {}))
    dims = p1["dimensions"]
    radar_img = png_bytes_to_base64_img_tag(get_radar_png_bytes(dims), "7 dimenziós radar")
    bar_img = png_bytes_to_base64_img_tag(get_bar_chart_png_bytes(dims), "Dimenzió-összehasonlítás")
    map_img = png_bytes_to_base64_img_tag(get_strategy_map_png_bytes(p1["plan_a"], p1["plan_b"]), "Stratégiai térkép")
    final_summary = build_full_conclusion(package)

    def bullets(items):
        return ''.join(f'<li>{x}</li>' for x in items) or '<li>n.a.</li>'

    dim_rows = ''.join(
        f"<tr><td>{dim}</td><td>{vals['KTE']}</td><td>{vals['ELL']}</td><td>{vals['Edge']}</td></tr>"
        for dim, vals in dims.items()
    )

    decision_block = ''
    if ds.get("has_manual_intervention"):
        decision_block = f"<div class='card'><h3>Edzői finomhangolás hatása</h3><p>{ds.get('executive_summary', '')}</p><ul>{bullets(ds.get('recommendation', []))}</ul></div>"

    return f"""<html><head><meta charset='utf-8'><title>Taktikai döntéselőkészítő</title>
    <style>
    body {{ font-family: DejaVu Sans, Arial, sans-serif; background:#FFFFFF; color:#24173A; margin:0; padding:24px; }}
    .page {{ background:white; border-radius:20px; padding:26px; margin-bottom:22px; box-shadow:0 14px 34px rgba(55,31,91,.10); page-break-after: always; border:1px solid #E7DDF2; }}
    .page:last-child {{ page-break-after:auto; }}
    .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    .grid3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:18px; }}
    .card {{ background:#FBF8FE; border:1px solid #E1D8EE; border-radius:14px; padding:16px; }}
    h1,h2,h3 {{ margin:0 0 12px 0; color:#2F1D4A; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ border:1px solid #E1D8EE; padding:8px; text-align:left; }}
    th {{ background:#EEE8F5; }}
    ul {{ margin:8px 0 0 18px; }}
    .hero {{ display:flex; justify-content:space-between; gap:18px; align-items:flex-start; }}
    .brand {{ display:flex; align-items:center; gap:14px; margin-bottom:12px; }}
    .badge {{ width:54px; height:54px; border-radius:50%; background:#5B2C83; color:white; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:18px; box-shadow:0 8px 20px rgba(91,44,131,.25); }}
    .pill {{ display:inline-block; background:#EEE8F5; color:#4A2B71; padding:5px 10px; border-radius:999px; font-size:12px; margin-right:6px; }}
    .small {{ color:#6C5A88; font-size:12px; }}
    </style></head><body>
    <div class='page'>
      <div class='brand'><div class='badge'>KTE</div><div><h1>Taktikai döntéselőkészítő ⚽</h1><div class='small'>Adatalapú briefing • 10 tényező • 9 stratégia</div></div></div>
      <div class='hero'>
        <div>
          <div style='margin-bottom:10px'><span class='pill'>7 dimenzió</span><span class='pill'>9 stratégia</span><span class='pill'>MI + szakmai modell</span></div>
          <p>{get_methodology_summary()}</p>
        </div>
        <div class='card'>
          <strong>A terv:</strong> {label_strategy(p1['plan_a'])}<br>
          <strong>B terv:</strong> {label_strategy(p1['plan_b'])}<br>
          <strong>Arány:</strong> {p1['plan_split']}<br>
          <strong>Labdakihozatal:</strong> {coach.get('build_up_solution', 'n.a.')}<br>
          <strong>Blokk:</strong> {coach.get('defensive_block', 'n.a.')}<br>
          <strong>Forgatókönyv:</strong> {label_scenario(coach.get('match_scenario', ''))}
        </div>
      </div>
      <div class='card' style='margin-top:18px'>
        <h2>Teljes konklúzió</h2>
        <ul>{bullets(final_summary)}</ul>
      </div>
    </div>

    <div class='page'><div class='brand'><div class='badge'>KTE</div><h2>7 dimenziós radar</h2></div><div class='card'>{radar_img}</div></div>
    <div class='page'><div class='brand'><div class='badge'>KTE</div><h2>Dimenzió-összehasonlítás</h2></div><div class='card'>{bar_img}</div></div>
    <div class='page'><div class='brand'><div class='badge'>KTE</div><h2>Stratégiai térkép</h2></div><div class='card'>{map_img}</div></div>

    <div class='page'>
      <div class='brand'><div class='badge'>KTE</div><h2>7 dimenziós összehasonlítás</h2></div>
      <table><thead><tr><th>Dimenzió</th><th>KTE</th><th>Ellenfél</th><th>Különbség</th></tr></thead><tbody>{dim_rows}</tbody></table>
    </div>

    <div class='page'>
      <div class='grid2'>
        <div class='card'><h3>Ellenfél profil</h3><p>{p1['opponent_profile']}</p></div>
        <div class='card'><h3>Saját állapot</h3><p>{p1['own_state']}</p></div>
        <div class='card'><h3>Ellenfél-DNS</h3><p>{p3['opponent_dna']}</p></div>
        <div class='card'><h3>Rövid konklúzió</h3><p>{p1['conclusion']}</p></div>
      </div>
    </div>

    <div class='page'>
      <div class='grid3'>
        <div class='card'><h3>3 kulcs</h3><ul>{bullets(p1.get('three_keys', []))}</ul></div>
        <div class='card'><h3>Kockázatok</h3><ul>{bullets(p1.get('risks', []))}</ul></div>
        <div class='card'><h3>Meccsdinamika</h3><ul>{bullets(p3.get('match_dynamics', []))}</ul></div>
      </div>
    </div>

    <div class='page'>
      <div class='grid2'>
        <div class='card'><h3>Legveszélyesebb ellenfél-játékosok</h3><ul>{bullets(danger)}</ul></div>
        {decision_block}
      </div>
    </div>
    </body></html>"""



def _pdf_draw_page_bg(c, width, height, title):
    c.setFillColor(colors.HexColor("#F6F0FB"))
    c.rect(0, 0, width, height, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#E9DDF6"))
    c.roundRect(16, height - 92, width - 32, 64, 18, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#5B2C83"))
    c.circle(42, height - 60, 18, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(PDF_FONT_BOLD_NAME, 12)
    c.drawCentredString(42, height - 64, "KTE")
    c.setFillColor(colors.HexColor("#2F1D4A"))
    c.setFont(PDF_FONT_BOLD_NAME, 22)
    c.drawString(70, height - 54, pdf_safe_text(title))
    c.setFillColor(colors.HexColor("#6E5A87"))
    c.setFont(PDF_FONT_NAME, 10)
    c.drawString(70, height - 72, pdf_safe_text("Adatalapú briefing · 10 tényező · 9 stratégia"))
    c.setFillColor(colors.HexColor("#D8C7EB"))
    c.circle(width - 38, height - 48, 8, stroke=0, fill=1)
    c.circle(width - 62, height - 72, 5, stroke=0, fill=1)


def _pdf_draw_wrapped(c, text, x, y, width, font_name=None, font_size=10.5, color="#2F1D4A", leading=14, bullet=False, max_lines=None):
    if not text:
        return y
    font_name = font_name or PDF_FONT_NAME
    c.setFillColor(colors.HexColor(color))
    c.setFont(font_name, font_size)
    lines = []
    for raw in str(text).replace("\r", "").split("\n"):
        raw = raw.strip()
        if not raw:
            lines.append("")
            continue
        wrapped = simpleSplit(pdf_safe_text(raw), font_name, font_size, width - (10 if bullet else 0))
        if bullet and wrapped:
            lines.append("• " + wrapped[0])
            lines.extend(["  " + w for w in wrapped[1:]])
        else:
            lines.extend(wrapped or [pdf_safe_text(raw)])
    if max_lines is not None:
        lines = lines[:max_lines]
    text_obj = c.beginText(x, y)
    text_obj.setFont(font_name, font_size)
    text_obj.setLeading(leading)
    text_obj.setFillColor(colors.HexColor(color))
    for ln in lines:
        text_obj.textLine(ln)
    c.drawText(text_obj)
    return y - leading * len(lines)

def _pdf_draw_card(c, x, y_top, w, h, title, body_lines, fill="#FFFFFF"):
    c.setFillColor(colors.HexColor(fill))
    c.roundRect(x, y_top - h, w, h, 14, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#2F1D4A"))
    c.setFont(PDF_FONT_BOLD_NAME, 12)
    c.drawString(x + 12, y_top - 20, pdf_safe_text(title))
    yy = y_top - 38
    for item in body_lines:
        yy = _pdf_draw_wrapped(c, item, x + 12, yy, w - 24, font_size=10.0, color="#35254E", leading=12.5, bullet=True) - 2
        if yy < y_top - h + 18:
            break


def _pdf_draw_radar_chart(c, dims, x, y_bottom, w, h):
    labels = list(dims.keys())
    if not labels:
        return False
    cx = x + w * 0.50
    cy = y_bottom + h * 0.53
    radius = min(w * 0.24, h * 0.27)
    rings = 5
    c.setStrokeColor(colors.HexColor("#D8C7EB"))
    c.setLineWidth(0.8)
    for ring in range(1, rings + 1):
        pts = []
        r = radius * ring / rings
        for i in range(len(labels)):
            ang = math.pi / 2 - (2 * math.pi * i / len(labels))
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            c.line(x1, y1, x2, y2)
    c.setStrokeColor(colors.HexColor("#E6DDF2"))
    for i in range(len(labels)):
        ang = math.pi / 2 - (2 * math.pi * i / len(labels))
        x2 = cx + radius * math.cos(ang)
        y2 = cy + radius * math.sin(ang)
        c.line(cx, cy, x2, y2)
        lx = cx + (radius + 22) * math.cos(ang)
        ly = cy + (radius + 22) * math.sin(ang)
        c.setFillColor(colors.HexColor("#35254E"))
        c.setFont(PDF_FONT_NAME, 8.5)
        c.drawCentredString(lx, ly, pdf_safe_text(labels[i]))
    for value in [2, 4, 6, 8, 10]:
        ry = cy + radius * value / 10
        c.setFont(PDF_FONT_NAME, 7.5)
        c.setFillColor(colors.HexColor("#7E6A98"))
        c.drawString(cx + 4, ry - 2, str(value))

    def poly_points(key):
        pts = []
        for i, label in enumerate(labels):
            val = max(0, min(10, float(dims[label].get(key, 0))))
            ang = math.pi / 2 - (2 * math.pi * i / len(labels))
            r = radius * val / 10
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        return pts

    def draw_poly(pts, stroke_hex, fill_hex):
        p = c.beginPath()
        p.moveTo(*pts[0])
        for px, py in pts[1:]:
            p.lineTo(px, py)
        p.close()
        c.setStrokeColor(colors.HexColor(stroke_hex))
        c.setFillColor(colors.HexColor(fill_hex))
        c.drawPath(p, stroke=1, fill=1)

    c.setFillAlpha(0.10)
    draw_poly(poly_points("ELL"), "#9D8ABA", "#E6DDF2")
    c.setFillAlpha(0.16)
    draw_poly(poly_points("KTE"), "#5B2C83", "#D6C3EA")
    c.setFillAlpha(1)

    # legend
    lx = x + w - 112
    ly = y_bottom + h - 28
    c.setFillColor(colors.HexColor("#5B2C83"))
    c.circle(lx, ly, 4, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#35254E"))
    c.setFont(PDF_FONT_NAME, 9)
    c.drawString(lx + 10, ly - 3, "KTE")
    c.setFillColor(colors.HexColor("#9D8ABA"))
    c.circle(lx + 58, ly, 4, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#35254E"))
    c.drawString(lx + 68, ly - 3, pdf_safe_text("Ellenfél"))
    return True


def _pdf_draw_bar_chart(c, dims, x, y_bottom, w, h):
    labels = list(dims.keys())
    if not labels:
        return False
    left = x + 48
    right = x + w - 18
    bottom = y_bottom + 48
    top = y_bottom + h - 28
    plot_h = top - bottom
    plot_w = right - left
    c.setStrokeColor(colors.HexColor("#D8C7EB"))
    for tick in [0, 2, 4, 6, 8, 10]:
        yy = bottom + plot_h * tick / 10
        c.line(left, yy, right, yy)
        c.setFillColor(colors.HexColor("#7E6A98"))
        c.setFont(PDF_FONT_NAME, 7.5)
        c.drawRightString(left - 6, yy - 2, str(tick))
    n = len(labels)
    group_w = plot_w / max(n, 1)
    bar_w = min(16, group_w * 0.26)
    for i, label in enumerate(labels):
        center = left + group_w * (i + 0.5)
        for offset, key, fill in [(-bar_w/2 - 2, "KTE", "#5B2C83"), (bar_w/2 + 2, "ELL", "#B7A3C9")]:
            val = max(0, min(10, float(dims[label].get(key, 0))))
            bh = plot_h * val / 10
            c.setFillColor(colors.HexColor(fill))
            c.roundRect(center + offset - bar_w/2, bottom, bar_w, bh, 3, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#35254E"))
        c.setFont(PDF_FONT_NAME, 7.2)
        c.saveState()
        c.translate(center, bottom - 8)
        c.rotate(25)
        c.drawString(0, 0, pdf_safe_text(label))
        c.restoreState()
    return True


def _pdf_draw_strategy_map(c, selected_a, selected_b, x, y_bottom, w, h):
    rows = strategy_scatter_data(selected_a, selected_b)
    left = x + 56
    right = x + w - 26
    bottom = y_bottom + 44
    top = y_bottom + h - 34
    c.setStrokeColor(colors.HexColor("#E0D5EF"))
    for i in range(1, 7):
        xx = left + (right-left) * (i-1) / 5
        c.line(xx, bottom, xx, top)
    for i in range(1, 6):
        yy = bottom + (top-bottom) * (i-1) / 4
        c.line(left, yy, right, yy)
    xlabels = ["Direkt", "Direkt+pressz.", "Vegyes", "Kiegy.", "Kontroll", "Agresszív"]
    ylabels = ["Mély", "Alacsony-közép", "Közép", "Közép-magas", "Magas"]
    c.setFont(PDF_FONT_NAME, 7.8)
    c.setFillColor(colors.HexColor("#35254E"))
    for i, lab in enumerate(xlabels):
        xx = left + (right-left) * i / 5
        c.drawCentredString(xx, bottom - 16, pdf_safe_text(lab))
    for i, lab in enumerate(ylabels):
        yy = bottom + (top-bottom) * i / 4
        c.drawRightString(left - 8, yy - 3, pdf_safe_text(lab))
    color_map = {"Paletta": "#5B2C83", "Plan A": "#E0A500", "Plan B": "#2AA7A1"}
    for row in rows:
        xx = left + (right-left) * (row["x"] - 1) / 5
        yy = bottom + (top-bottom) * (row["y"] - 1) / 4
        c.setFillColor(colors.HexColor(color_map.get(row["marker_type"], "#5B2C83")))
        c.circle(xx, yy, 7 if row["marker_type"] != "Paletta" else 5.5, stroke=0, fill=1)
        c.setFillColor(colors.white if row["marker_type"] != "Paletta" else colors.HexColor("#F6F1FB"))
        c.setFont(PDF_FONT_BOLD_NAME if row["marker_type"] != "Paletta" else PDF_FONT_NAME, 6.8)
        c.drawCentredString(xx, yy - 2.3, pdf_safe_text(row["code"]))
    return True


def _pdf_draw_chart_panel(c, kind, png_bytes, x, y_bottom, w, h, dims=None, selected_a=None, selected_b=None):
    c.setFillColor(colors.white)
    c.roundRect(x, y_bottom, w, h, 14, stroke=0, fill=1)
    pad_x = 12
    pad_y = 14
    if png_bytes:
        try:
            img = ImageReader(io.BytesIO(png_bytes))
            iw, ih = img.getSize()
            scale = min((w - 2 * pad_x) / iw, (h - 2 * pad_y) / ih)
            dw, dh = iw * scale, ih * scale
            dx = x + (w - dw) / 2
            dy = y_bottom + (h - dh) / 2
            c.drawImage(img, dx, dy, width=dw, height=dh, preserveAspectRatio=True, mask='auto')
            return
        except Exception:
            pass
    ok = False
    if kind == "radar":
        ok = _pdf_draw_radar_chart(c, dims or {}, x, y_bottom, w, h)
    elif kind == "bar":
        ok = _pdf_draw_bar_chart(c, dims or {}, x, y_bottom, w, h)
    elif kind == "strategy":
        ok = _pdf_draw_strategy_map(c, selected_a, selected_b, x, y_bottom, w, h)
    if not ok:
        c.setFillColor(colors.HexColor("#7E6A98"))
        c.setFont(PDF_FONT_NAME, 11)
        c.drawCentredString(x + w/2, y_bottom + h/2, pdf_safe_text("A diagram betöltése nem sikerült."))


def _pdf_draw_image_fit(c, png_bytes, x, y_bottom, w, h):
    c.setFillColor(colors.white)
    c.roundRect(x, y_bottom, w, h, 14, stroke=0, fill=1)
    if not png_bytes:
        c.setFillColor(colors.HexColor("#7E6A98"))
        c.setFont(PDF_FONT_NAME, 11)
        c.drawCentredString(x + w/2, y_bottom + h/2, pdf_safe_text("A diagram ebben a környezetben nem renderelhető."))
        return
    try:
        img = ImageReader(io.BytesIO(png_bytes))
        iw, ih = img.getSize()
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        dx = x + (w - dw) / 2
        dy = y_bottom + (h - dh) / 2
        c.drawImage(img, dx, dy, width=dw, height=dh, preserveAspectRatio=True, mask='auto')
    except Exception:
        c.setFillColor(colors.HexColor("#7E6A98"))
        c.setFont(PDF_FONT_NAME, 11)
        c.drawCentredString(x + w/2, y_bottom + h/2, pdf_safe_text("A diagram betöltése nem sikerült."))

def build_pdf_export_bytes(package: Dict[str, object]) -> bytes:
    if not REPORTLAB_AVAILABLE:
        return build_html_export(package).encode("utf-8")
    ensure_pdf_font()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 24

    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]
    coach = package.get("coach_controls", {}) or {}
    ds = package.get("decision_support", {}) or {}
    danger = summarize_danger_players(p3.get("key_player_threats", {}))
    final_summary = build_full_conclusion(package)

    _pdf_draw_page_bg(c, width, height, "Taktikai döntéselőkészítő")
    c.setFillColor(colors.white)
    c.roundRect(margin, height - 310, width - 2 * margin, 178, 18, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#5B2C83"))
    c.setFont(PDF_FONT_BOLD_NAME, 14)
    c.drawString(margin + 16, height - 156, "Metodika")
    _pdf_draw_wrapped(c, get_methodology_summary(), margin + 16, height - 178, width - 2 * margin - 32, font_size=10.5, color="#35254E", leading=14, max_lines=8)

    c.setFillColor(colors.white)
    c.roundRect(margin, height - 508, width - 2 * margin, 176, 18, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#2F1D4A"))
    c.setFont(PDF_FONT_BOLD_NAME, 14)
    c.drawString(margin + 16, height - 354, "Vezetői összefoglaló")
    yy = height - 376
    for item in final_summary[:6]:
        yy = _pdf_draw_wrapped(c, item, margin + 16, yy, width - 2 * margin - 32, font_size=10.8, color="#35254E", leading=15, bullet=True) - 2
    if ds.get("has_manual_intervention") and ds.get("executive_summary"):
        c.setFillColor(colors.HexColor("#F1E8FA"))
        c.roundRect(margin, 54, width - 2 * margin, 76, 16, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#2F1D4A"))
        c.setFont(PDF_FONT_BOLD_NAME, 12)
        c.drawString(margin + 14, 108, "Edzői finomhangolás")
        _pdf_draw_wrapped(c, ds.get("executive_summary", ""), margin + 14, 90, width - 2 * margin - 28, font_size=9.6, color="#4B3A66", leading=12, max_lines=4)
    c.showPage()

    for title, kind, png in [
        ("7 dimenziós radar", "radar", get_radar_png_bytes(p1["dimensions"])),
        ("Dimenzió-összehasonlítás", "bar", get_bar_chart_png_bytes(p1["dimensions"])),
        ("Stratégiai térkép", "strategy", get_strategy_map_png_bytes(p1["plan_a"], p1["plan_b"])),
    ]:
        _pdf_draw_page_bg(c, width, height, title)
        _pdf_draw_chart_panel(c, kind, png, 42, 155, width - 84, height - 270, dims=p1["dimensions"], selected_a=p1["plan_a"], selected_b=p1["plan_b"])
        c.showPage()

    _pdf_draw_page_bg(c, width, height, "Matchup-kép és kulcspontok")
    half = (width - 3 * margin) / 2
    _pdf_draw_card(c, margin, height - 110, half, 150, "Terv és fókusz", [
        f"A terv: {label_strategy(str(p1['plan_a']))}",
        f"B terv: {label_strategy(str(p1['plan_b']))}",
        f"Arány: {p1['plan_split']}",
        f"Meccsfókusz: {format_focus_areas(coach.get('focus_areas', []))}",
        f"Labdakihozatal: {coach.get('build_up_solution', '-')}",
        f"Védelmi blokk: {coach.get('defensive_block', '-')}",
    ])
    _pdf_draw_card(c, margin * 2 + half, height - 110, half, 150, "Szöveges olvasat", [
        p1.get('opponent_profile', ''),
        p1.get('own_state', ''),
        p3.get('opponent_dna', ''),
        p1.get('conclusion', ''),
    ])
    _pdf_draw_card(c, margin, height - 280, half, 220, "3 kulcs és kockázatok", p1.get('three_keys', [])[:3] + p1.get('risks', [])[:3])
    _pdf_draw_card(c, margin * 2 + half, height - 280, half, 220, "Meccsdinamika és veszélyforrás", p3.get('match_dynamics', [])[:3] + danger[:4])
    c.showPage()

    _pdf_draw_page_bg(c, width, height, "7 dimenziós összkép")
    c.setFillColor(colors.white)
    c.roundRect(margin, 88, width - 2 * margin, height - 200, 18, stroke=0, fill=1)
    table_x = margin + 10
    table_y = height - 130
    col_w = [180, 70, 90, 90]
    row_h = 24
    headers = ["Dimenzió", "KTE", "Ellenfél", "Különbség"]
    c.setFillColor(colors.HexColor("#EEE8F5"))
    c.roundRect(table_x, table_y - row_h, sum(col_w), row_h, 8, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#2F1D4A"))
    c.setFont(PDF_FONT_BOLD_NAME, 11)
    xx = table_x + 8
    for i, htxt in enumerate(headers):
        c.drawString(xx, table_y - 16, htxt)
        xx += col_w[i]
    c.setFont(PDF_FONT_NAME, 10.5)
    y = table_y - row_h - 4
    for idx, (dim, vals) in enumerate(p1["dimensions"].items()):
        c.setFillColor(colors.HexColor("#F9F6FD" if idx % 2 == 0 else "#FFFFFF"))
        c.rect(table_x, y - row_h + 4, sum(col_w), row_h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#35254E"))
        xx = table_x + 8
        for i, cell in enumerate([dim, str(vals["KTE"]), str(vals["ELL"]), str(vals["Edge"])]):
            c.drawString(xx, y - 12, pdf_safe_text(cell))
            xx += col_w[i]
        y -= row_h
    c.save()
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
    decision_support: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    package = {
        "page_1_onepager": {
            "plan_a": selected_plan_a,
            "plan_b": selected_plan_b,
            "opponent_name": st.session_state.get("opponent_name", "").strip(),
            "plan_split": f"{selected_split}/{100 - selected_split}",
            "dimensions": dims,
            "dimension_mode": "adjusted" if st.session_state.get("use_adjusted_dims", True) else "base",
            "base_dimensions": st.session_state.get("dims"),
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
        "decision_support": decision_support or {},
    }
    return package


def build_markdown_export(package: Dict[str, object]) -> str:
    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]

    md = []
    md.append("# Taktikai döntéselőkészítő export")
    md.append("")
    md.append("## 1. oldal – Onepager")
    md.append(f"- Plan A: {p1['plan_a']}")
    md.append(f"- Plan B: {p1['plan_b']}")
    md.append(f"- Arány: {p1['plan_split']}")
    md.append(f"- Dimenzió mód: {p1.get('dimension_mode', 'base')}")
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
    md.append("### Teljes konklúzió")
    for x in build_full_conclusion(package):
        md.append(f"- {x}")
    md.append("")
    md.append("### Edzői beállítások")
    for k, v in package.get("coach_controls", {}).items():
        md.append(f"- {k}: {v}")
    md.append("")
    ds = package.get("decision_support", {})
    if ds:
        md.append("### Edzői finomhangolás hatása")
        md.append(ds.get("executive_summary", ""))
        for x in ds.get("matchup_notes", []):
            md.append(f"- Matchup: {x}")
        for x in ds.get("recommendation", []):
            md.append(f"- Javaslat: {x}")
        md.append("")
    md.append("## 3. oldal – Taktikai áttekintés")
    md.append("")
    md.append("### Ellenfél-DNS")
    md.append(p3["opponent_dna"])
    md.append("")
    md.append("### Várható meccsdinamika")
    for x in p3["match_dynamics"]:
        md.append(f"- {x}")
    md.append("")
    md.append("### Legveszélyesebb ellenfél-játékosok")
    for x in summarize_danger_players(p3.get("key_player_threats", {})):
        md.append(f"- {x}")
    md.append("")
    return "\n".join(md)




def control_status_rows(linked_mode: bool) -> List[dict]:
    auto = "Automatikus a játékmodellből" if linked_mode else "Kézi"
    return [
        {"Elem": "Elsődleges játékmodell", "Állapot": "Szerkeszthető", "Logika": "Fő taktikai driver"},
        {"Elem": "Alternatív játékmodell", "Állapot": "Szerkeszthető", "Logika": "Plan B"},
        {"Elem": "Meccskép prioritás", "Állapot": "Fixált" if linked_mode else "Szerkeszthető", "Logika": auto},
        {"Elem": "Labdakihozatal", "Állapot": "Fixált" if linked_mode else "Szerkeszthető", "Logika": auto},
        {"Elem": "Védelmi blokk", "Állapot": "Fixált" if linked_mode else "Szerkeszthető", "Logika": auto},
        {"Elem": "Meccsdinamika", "Állapot": "Fixált" if linked_mode else "Szerkeszthető", "Logika": auto},
        {"Elem": "Pressing fókuszterület", "Állapot": "Szerkeszthető", "Logika": "Mindig külön finomhangolható"},
        {"Elem": "Pontrúgás prioritás", "Állapot": "Szerkeszthető", "Logika": "Mindig külön finomhangolható"},
        {"Elem": "Fő kockázat prioritások", "Állapot": "Szerkeszthető", "Logika": "Coach override"},
        {"Elem": "Kulcsjátékos fókusz", "Állapot": "Fix", "Logika": "Parser-alapú ellenfél lista"},
    ]


def render_export_preview(package: Dict[str, object]):
    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]
    ds = package.get("decision_support", {}) or {}
    coach = package.get("coach_controls", {}) or {}
    danger = summarize_danger_players(p3.get("key_player_threats", {}))

    st.markdown("### Briefing deck preview")
    st.info(get_methodology_summary())
    st.markdown("### Teljes konklúzió - ha csak ezt olvassa az edző")
    for x in build_full_conclusion(package):
        st.write(f"- {x}")

    top1, top2, top3 = st.columns([1.1, 1.1, 1])
    with top1:
        st.markdown("### Match plan")
        st.metric("Plan A", p1["plan_a"])
        st.metric("Plan B", p1["plan_b"])
    with top2:
        st.markdown("### Arány")
        st.metric("Plan split", p1["plan_split"])
        st.caption(f"Dimenzió mód: {p1.get('dimension_mode', 'base')}")
    with top3:
        st.markdown("### Coach mode")
        st.write(f"- Build-up: {coach.get('build_up_solution', 'n.a.')}")
        st.write(f"- Blokk: {coach.get('defensive_block', 'n.a.')}")
        st.write(f"- Szenárió: {coach.get('match_scenario', 'n.a.')}")

    st.markdown("### Három fő diagram")
    components.html(get_radar_svg(p1["dimensions"]), height=770)
    components.html(get_bar_chart_svg(p1["dimensions"]), height=430)
    components.html(get_strategy_map_svg(p1["plan_a"], p1["plan_b"]), height=480)

    st.markdown("### 7 dimenziós összkép")
    dim_df = pd.DataFrame(p1["dimensions"]).T.reset_index().rename(columns={"index": "Dimenzió"})
    st.dataframe(dim_df, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Ellenfél profil")
        st.info(p1["opponent_profile"])
        st.markdown("### Ellenfél-DNS")
        st.code(p3["opponent_dna"])
    with c2:
        st.markdown("### Saját állapot")
        st.info(p1["own_state"])
        st.markdown("### Konklúzió")
        st.success(p1["conclusion"])

    c3, c4, c5 = st.columns(3)
    with c3:
        st.markdown("### 3 kulcs")
        for x in p1.get("three_keys", []):
            st.write(f"- {x}")
    with c4:
        st.markdown("### Kockázatok")
        for x in p1.get("risks", []):
            st.write(f"- {x}")
    with c5:
        st.markdown("### Meccsdinamika")
        for x in p3.get("match_dynamics", []):
            st.write(f"- {x}")

    st.markdown("### Legveszélyesebb ellenfél-játékosok")
    if danger:
        cols = st.columns(min(3, len(danger)))
        for col, item in zip(cols, danger[:3]):
            with col:
                st.warning(item)
    else:
        st.caption("Nincs kiemelt ellenfél-veszélyforrás azonosítva.")

    if ds:
        st.markdown("### Taktikai döntési blokk")
        st.warning(ds.get("executive_summary", ""))
        d1, d2 = st.columns(2)
        with d1:
            st.markdown("**Matchup notes**")
            for x in ds.get("matchup_notes", []):
                st.write(f"- {x}")
        with d2:
            st.markdown("**Vezetői javaslatok**")
            for x in ds.get("recommendation", []):
                st.write(f"- {x}")


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

def render_bar_chart(dims: Dict[str, Dict[str, float]], height: int = 360):
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
    ).properties(height=height)

    st.altair_chart(chart, use_container_width=True)



def get_radar_svg(dims: Dict[str, Dict[str, float]], compact: bool = False) -> str:
    labels = list(dims.keys())
    kte_vals = [dims[x]["KTE"] for x in labels]
    ell_vals = [dims[x]["ELL"] for x in labels]

    if compact:
        width = 880
        height = 360
        cx, cy = 300, 188
        max_r = 126
        legend_x, legend_y, legend_w, legend_h = 600, 30, 178, 58
        label_offset = 40
        label_font = 13
        level_font = 10
        circle_r = 3.8
    else:
        width = 960
        height = 540
        cx, cy = 330, 245
        max_r = 155
        legend_x, legend_y, legend_w, legend_h = 650, 58, 220, 74
        label_offset = 85
        label_font = 16
        level_font = 11
        circle_r = 4.8
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
        level_labels.append(f'<text x="{cx + 8}" y="{cy - (lvl / 10.0) * max_r + 4:.1f}" font-size="{level_font}" fill="#8B7CA3">{lvl}</text>')

    for i, label in enumerate(labels):
        ang = -math.pi / 2 + (2 * math.pi * i / n)
        x2 = cx + math.cos(ang) * max_r
        y2 = cy + math.sin(ang) * max_r
        axes.append(f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#D8D2E3" stroke-width="1" />')
        lx = cx + math.cos(ang) * (max_r + label_offset)
        ly = cy + math.sin(ang) * (max_r + label_offset)
        anchor = "middle"
        if lx < cx - 40:
            anchor = "end"
        elif lx > cx + 40:
            anchor = "start"
        wrapped = wrap_label(label, 12 if compact else 14)
        tspans = []
        for j, part in enumerate(wrapped):
            dy = 0 if j == 0 else (15 if compact else 18)
            tspans.append(f'<tspan x="{lx:.1f}" dy="{dy}">{part}</tspan>')
        label_svg.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="{label_font}" text-anchor="{anchor}" fill="#2F1D4A" font-weight="600">{"".join(tspans)}</text>')

    kte_poly, kte_pts = polygon_points(kte_vals)
    ell_poly, ell_pts = polygon_points(ell_vals)
    kte_circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{circle_r}" fill="#5B2C83" stroke="white" stroke-width="1.2" />' for x, y in kte_pts)
    ell_circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{circle_r}" fill="#B7A3C9" stroke="#5B2C83" stroke-width="1.0" />' for x, y in ell_pts)

    return f"""
    <svg width="100%" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" rx="18" ry="18" fill="white" />
      {''.join(grid_polys)}
      {''.join(level_labels)}
      {''.join(axes)}
      <polygon points="{ell_poly}" fill="rgba(183,163,201,0.24)" stroke="#9D8ABA" stroke-width="2.4" stroke-dasharray="6 4" />
      <polygon points="{kte_poly}" fill="rgba(91,44,131,0.16)" stroke="#5B2C83" stroke-width="2.8" />
      {ell_circles}
      {kte_circles}
      {''.join(label_svg)}
      <rect x="{legend_x}" y="{legend_y}" width="{legend_w}" height="{legend_h}" rx="12" fill="#F8F5FC" stroke="#E1D8EE"/>
      <circle cx="{legend_x+18}" cy="{legend_y+20}" r="6" fill="#5B2C83" />
      <text x="{legend_x+34}" y="{legend_y+25}" font-size="14" fill="#2F1D4A" font-weight="600">KTE</text>
      <circle cx="{legend_x+18}" cy="{legend_y+42}" r="6" fill="#B7A3C9" stroke="#5B2C83" stroke-width="1" />
      <text x="{legend_x+34}" y="{legend_y+47}" font-size="14" fill="#2F1D4A" font-weight="600">ELL</text>
      <text x="{legend_x+18}" y="{legend_y+62}" font-size="10" fill="#6D5B88">Skála: 1-10</text>
    </svg>
    """

def render_radar_svg(dims: Dict[str, Dict[str, float]], height: int = 770, compact: bool = False):
    components.html(get_radar_svg(dims, compact=compact), height=height)


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
    "dims_adjusted": None,
    "coach_impact_df": None,
    "coach_dim_comparison": None,
    "decision_support": None,
    "use_adjusted_dims": True,
    "coach_primary_model": "GAT",
    "coach_secondary_model": "BAT",
    "coach_link_controls": True,
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

st.markdown("""
<style>
.stApp { background: linear-gradient(180deg, #F6F1FF 0%, #F9F7FD 52%, #FFFFFF 100%); color:#121826; }
.kte-hero { display:flex; align-items:center; justify-content:space-between; gap:14px; background:rgba(255,255,255,.92); color:#18212F; padding:16px 18px; border-radius:20px; margin-bottom:16px; border:1px solid #E7DEF8; box-shadow:0 10px 28px rgba(76,46,131,.08); }
.kte-hero-left { display:flex; align-items:center; gap:14px; min-width:0; }
.kte-hero-meta { text-align:right; color:#344054; font-weight:700; line-height:1.32; font-size:1rem; white-space:pre-line; }
.kte-badge { width:52px; height:52px; border-radius:50%; background:linear-gradient(135deg,#F3EFFF,#E7DEFF); color:#5A38A6; border:1px solid #D7C7FB; display:flex; align-items:center; justify-content:center; font-weight:800; }
.block-container { padding-top: 1.25rem; }
[data-testid="stSidebar"] { background:#FFFFFF; border-right:1px solid #E6EAF2; }
[data-testid="stSidebar"] * { color:#18212F !important; }
h1,h2,h3,h4,p,li,span,label,div { color:#18212F; }
.summary-shell { margin-top: .45rem; }
.summary-kpi { display:grid; grid-template-columns:1fr 1fr .88fr; gap:10px; background:transparent; border:none; padding:0; margin-bottom:10px; }
.summary-kpi .k { background:rgba(255,255,255,.98); border:1px solid #E7DEF8; border-radius:18px; padding:12px 14px; box-shadow:0 10px 24px rgba(76,46,131,.06); min-height:94px; }
.summary-kpi .n { font-size:1.42rem; font-weight:800; color:#4B2E83; line-height:1.02; margin:2px 0 4px 0; }
.summary-note { color:#5B6474; font-size:.9rem; line-height:1.25; }
.summary-grid-tight { display:grid; grid-template-columns:1.2fr .85fr; gap:10px; }
.summary-micro { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.summary-pill { background:#F2ECFF; color:#4B2E83; border:1px solid #DED1FF; padding:4px 9px; border-radius:999px; font-size:.79rem; font-weight:600; }
.summary-page-break { break-before: page; page-break-before: always; margin-top: 0; }
.summary-avoid-break, .summary-block, .summary-chartbox, .summary-viz-page { break-inside: avoid; page-break-inside: avoid; }
.summary-viz-page { margin-top:0; padding-top:0; }
.summary-page-title { margin:0 0 .35rem 0 !important; }
.viz-page { break-inside: avoid; page-break-inside: avoid; }
.viz-unit { break-inside: avoid; page-break-inside: avoid; }
.viz-unit-radar .summary-chartbox { min-height: 560px; }
.viz-unit-bar .summary-chartbox { min-height: 520px; }
.viz-unit-map .summary-chartbox { min-height: 560px; }
.summary-unit { break-inside: avoid; page-break-inside: avoid; margin-bottom: .4rem; }
.summary-unit h4, .summary-unit h5, .summary-unit h3 { margin-bottom:.15rem !important; page-break-after: avoid; break-after: avoid; }
.summary-chartbox { margin-top:0 !important; margin-bottom:4px !important; }
.summary-chartbox h4, .summary-chartbox h5 { margin-bottom:0 !important; }
.summary-chartbox iframe { margin-top:-6px !important; margin-bottom:-8px !important; }
.summary-chartbox.radar-box iframe { margin-top:-22px !important; margin-bottom:-10px !important; }
.summary-chartbox.bar-box iframe { margin-top:-4px !important; margin-bottom:-6px !important; }
.summary-chartbox.map-box iframe { margin-top:-20px !important; margin-bottom:-10px !important; }
.summary-compact-list { margin:0; padding-left:1rem; }
.summary-compact-list li { margin:0 0 .18rem 0; line-height:1.22; }
.summary-method { font-size:.92rem; line-height:1.35; color:#273142; margin-top:4px; }
.summary-method.compact { font-size:.88rem; line-height:1.28; margin-top:2px; }
.summary-method-title { font-size:1.05rem; font-weight:700; color:#241D33; margin:2px 0 4px 0; }
.summary-section-tight h3, .summary-section-tight h4, .summary-section-tight p { margin-bottom: .2rem !important; margin-top: .2rem !important; }
.summary-footer-note { margin-top: 6px; font-size:.84rem; color:#5B6474; text-align:right; }
.summary-section-wrap { break-inside: avoid; page-break-inside: avoid; }
@media (max-width: 980px) {
  .summary-kpi { grid-template-columns:1fr; }
  .summary-grid-tight { grid-template-columns:1fr; }
}
@media print {
  html, body, [data-testid="stAppViewContainer"], .stApp { background:#F6F1FF !important; color:#111111 !important; }
  .kte-hero, .summary-kpi .k { background:#FFFFFF !important; box-shadow:none !important; }
  .summary-page-break { break-before: page; page-break-before: always; }
  .summary-avoid-break, .summary-block, .summary-chartbox, .summary-viz-page, .summary-unit, .summary-section-wrap { break-inside: avoid; page-break-inside: avoid; }
  .summary-chartbox iframe { margin-top:-8px !important; margin-bottom:-12px !important; }
  .viz-unit-radar .summary-chartbox { min-height: 540px !important; }
  .viz-unit-bar .summary-chartbox { min-height: 500px !important; }
  .viz-unit-map .summary-chartbox { min-height: 540px !important; }
  h1, h2, h3, h4, h5 { break-after: avoid; page-break-after: avoid; }
}
</style>
""", unsafe_allow_html=True)
hero_opponent = st.session_state.get("opponent_name", "").strip()
hero_meta = f"KTE vs {hero_opponent}\nKészítette: Sziegl Gábor" if hero_opponent else "Készítette: Sziegl Gábor"
st.markdown(f"""<div class='kte-hero'><div class='kte-hero-left'><div class='kte-badge'>KTE</div><div><div style='font-size:1.55rem;font-weight:800;color:#18212F;'>Taktikai döntéselőkészítő ⚽</div><div style='opacity:.9;color:#475467;'>Adatalapú briefing • 10 tényező • 9 stratégia</div></div></div><div class='kte-hero-meta'>{hero_meta}</div></div>""", unsafe_allow_html=True)
st.sidebar.caption("A rövidítések a stratégiai paletta elemeit jelölik")

step = st.sidebar.radio(
    "Lépés",
    ["1. Input", "2. Review", "3. Debug", "4. Export Prep", "5. Összegző oldal"],
    index=0,
)


# =========================================================
# INPUT
# =========================================================

if step == "1. Input":
    st.header("Inputok feltöltése")
    opponent_name = st.text_input(
        "Ellenfél neve",
        value=st.session_state.get("opponent_name", ""),
        key="opponent_name_input",
        placeholder="pl. Aqvital FC Csákvár",
    )
    st.session_state["opponent_name"] = opponent_name.strip()

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("KTE")
        kte_match = st.file_uploader("KTE Match Excel", type=["xlsx"], key="kte_match")
        kte_player = st.file_uploader("KTE Player Excel", type=["xlsx"], key="kte_player")
        kte_pdf_1 = st.file_uploader("KTE PDF 1", type=["pdf"], key="kte_pdf_1")
        kte_pdf_2 = st.file_uploader("KTE PDF 2", type=["pdf"], key="kte_pdf_2")
        kte_pdf_3 = st.file_uploader("KTE PDF 3", type=["pdf"], key="kte_pdf_3")

    with c2:
        st.subheader("Opponent")
        opp_match = st.file_uploader("Opponent Match Excel", type=["xlsx"], key="opp_match")
        opp_player = st.file_uploader("Opponent Player Excel", type=["xlsx"], key="opp_player")
        opp_pdf_1 = st.file_uploader("Opponent PDF 1", type=["pdf"], key="opp_pdf_1")
        opp_pdf_2 = st.file_uploader("Opponent PDF 2", type=["pdf"], key="opp_pdf_2")
        opp_pdf_3 = st.file_uploader("Opponent PDF 3", type=["pdf"], key="opp_pdf_3")

    if st.session_state.get("excel_import_error"):
        st.error(st.session_state.get("excel_import_error"))

    if kte_match and opp_match:
        st.session_state["excel_import_error"] = ""
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
            [kte_pdf_1, kte_pdf_2, kte_pdf_3],
            [opp_pdf_1, opp_pdf_2, opp_pdf_3],
        )

        if st.session_state.get("excel_import_error"):
            st.error(st.session_state.get("excel_import_error"))
        elif not team_metrics or not opp_metrics:
            st.error("Az Excel-feldolgozás nem sikerült. Ellenőrizd, hogy az openpyxl telepítve van-e a futtatási környezetben.")
        st.session_state["opponent_name"] = st.session_state.get("opponent_name", "").strip()
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
    adjusted_dims = st.session_state.get("dims_adjusted")
    active_dims = adjusted_dims if st.session_state.get("use_adjusted_dims", True) and adjusted_dims else dims
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

        adjusted_dims = st.session_state.get("dims_adjusted")
        active_dims = adjusted_dims if st.session_state.get("use_adjusted_dims", True) and adjusted_dims else dims
        top1, top2, top3 = st.columns(3)
        top1.metric("Ajánlott / választott Plan A", st.session_state["selected_plan_a"])
        top2.metric("Ajánlott / választott Plan B", st.session_state["selected_plan_b"])
        top3.metric("Arány", f"{st.session_state['selected_split']}/{100 - st.session_state['selected_split']}")

        st.subheader("9 taktikai opció – stratégiai térkép")
        render_strategy_map(st.session_state["selected_plan_a"], st.session_state["selected_plan_b"])

        coach_left, coach_right = st.columns([1.15, 1])
        with coach_left:
            st.subheader("Coach finomhangolás")
            st.session_state["coach_link_controls"] = st.checkbox(
                "A játékmodell kapcsolja össze a rész-döntéseket",
                value=st.session_state.get("coach_link_controls", True),
                help="Bekapcsolva az elsődleges játékmodell automatikusan javasolja a build-upot, blokkot, meccsdinamikát és fókuszterületeket.",
            )

            c1, c2 = st.columns(2)
            with c1:
                prev_primary = st.session_state.get("coach_primary_model")
                st.session_state["coach_primary_model"] = st.selectbox(
                    "Elsődleges játékmodell",
                    options=list(STRATEGY_PALETTE.keys()),
                    index=list(STRATEGY_PALETTE.keys()).index(st.session_state["coach_primary_model"]),
                    format_func=lambda x: f"{x} – {STRATEGY_PALETTE[x]['name']}",
                )
                if st.session_state.get("coach_link_controls", True) and st.session_state["coach_primary_model"] != prev_primary:
                    apply_linked_coach_controls(st.session_state["coach_primary_model"])
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

            if st.session_state.get("coach_link_controls", True):
                linked_preview = linked_controls_from_model(st.session_state["coach_primary_model"])
                st.info(
                    f"Kapcsolt mód: build-up = {linked_preview['build_up_solution']}, blokk = {linked_preview['defensive_block']}, "
                    f"meccsdinamika = {linked_preview['match_scenario']}, fókusz = {', '.join(linked_preview['focus_areas'])}."
                )

            st.caption("Mi fix és mi szerkeszthető jelenleg")
            st.dataframe(pd.DataFrame(control_status_rows(st.session_state.get("coach_link_controls", True))), use_container_width=True, hide_index=True)

            st.session_state["coach_focus_areas"] = st.multiselect(
                "Meccskép prioritás",
                options=["pressing", "build-up", "transition", "set pieces", "rest defense"],
                default=st.session_state["coach_focus_areas"],
                disabled=st.session_state.get("coach_link_controls", True),
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
                    disabled=st.session_state.get("coach_link_controls", True),
                )
            with z3:
                st.session_state["coach_defensive_block"] = st.selectbox(
                    "Védelmi blokk",
                    ["mély", "közepes", "magas"],
                    index=["mély", "közepes", "magas"].index(st.session_state["coach_defensive_block"]),
                    disabled=st.session_state.get("coach_link_controls", True),
                )

            s1, s2 = st.columns(2)
            with s1:
                st.session_state["coach_match_scenario"] = st.selectbox(
                    "Meccsdinamika forgatókönyv",
                    ["conservative", "balanced", "aggressive"],
                    index=["conservative", "balanced", "aggressive"].index(st.session_state["coach_match_scenario"]),
                    disabled=st.session_state.get("coach_link_controls", True),
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

            fixed_focus_players = player_focus_options(opp_players)[:3]
            st.session_state["coach_focus_players"] = fixed_focus_players
            st.markdown("**Fix ellenfél kulcsjátékos-fókusz**")
            if fixed_focus_players:
                st.caption("Ez parser-alapú, nem szerkeszthető lista.")
                for fp in fixed_focus_players:
                    st.write(f"- {fp}")
            else:
                st.caption("Nincs elérhető ellenfél kulcsjátékos lista.")

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

        st.session_state["use_adjusted_dims"] = st.checkbox(
            "Coach-hatások beépítése a dimenziókba és exportba",
            value=st.session_state.get("use_adjusted_dims", True),
            help="Ha be van kapcsolva, a coach választások szimuláltan módosítják a KTE 7 dimenziós profilját.",
        )
        active_dims = st.session_state.get("dims_adjusted") if st.session_state.get("use_adjusted_dims", True) and st.session_state.get("dims_adjusted") else dims

        st.subheader("Coach-hatás a mutatókra")
        impact_df = st.session_state.get("coach_impact_df")
        comparison_df = st.session_state.get("coach_dim_comparison")
        if comparison_df is not None and not comparison_df.empty:
            cimp1, cimp2 = st.columns([1.15, 1])
            with cimp1:
                st.dataframe(comparison_df, use_container_width=True, hide_index=True)
            with cimp2:
                if impact_df is not None and not impact_df.empty:
                    st.dataframe(impact_df, use_container_width=True, hide_index=True)
                else:
                    st.info("Még nincs számottevő coach-hatás rögzítve.")
        st.caption("Az itt látható hatások szabályalapú taktikai döntéselőkészítő logikából jönnek: a rendszer a választott game plan várható előnyeit, kompromisszumait és matchup-illeszkedését mutatja meg.")

        decision_support = st.session_state.get("decision_support") or {}
        if decision_support:
            st.subheader("Taktikai döntési hatásmotor")
            if decision_support.get("has_manual_intervention"):
                st.info(decision_support.get("executive_summary", ""))

                ds1, ds2 = st.columns(2)
                with ds1:
                    st.markdown("**Matchup-olvasat**")
                    for line in decision_support.get("matchup_notes", []):
                        st.write(f"- {line}")
                with ds2:
                    st.markdown("**Vezetői javaslatok**")
                    for line in decision_support.get("recommendation", []):
                        st.write(f"- {line}")

                for card in decision_support.get("cards", []):
                    with st.expander(f"{card['title']} – {card['choice']}", expanded=False):
                        cga, cgb = st.columns(2)
                        with cga:
                            st.markdown("**Várható nyereség**")
                            for line in card.get("gains", []):
                                st.write(f"- {line}")
                        with cgb:
                            st.markdown("**Trade-off / ár**")
                            for line in card.get("costs", []):
                                st.write(f"- {line}")
                        st.markdown(f"**Matchup-fit:** {card.get('fit', '-')}")
                        st.markdown(f"**Érintett dimenziók:** {', '.join(card.get('dims', [])) or '-'}")
            else:
                st.info("Nincs külön edzői finomhangolás rögzítve: jelenleg az alap adatalapú javaslat és matchup-kép érvényes.")

        st.subheader("Dimenzió tábla")
        st.dataframe(pd.DataFrame(active_dims).T, use_container_width=True)

        c1, c2 = st.columns([1.25, 1])
        with c1:
            st.subheader("Pókháló")
            render_radar_svg(active_dims)
        with c2:
            st.subheader("Dimenziók")
            render_bar_chart(active_dims)

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


def localize_summary_text(text: str) -> str:
    s = str(text or "")
    replacements = [
        ("balanced", "kiegyensúlyozott"),
        ("aggressive", "agresszív"),
        ("conservative", "konzervatív"),
        ("second ball", "second ball"),
        ("half-space", "half-space"),
        ("build-up", "build-up"),
        ("trigger", "váltási jel"),
        ("rest defense", "rest defense"),
        ("boxelőtti", "tizenhatos előtti"),
        ("Plan A", "A terv"),
        ("Plan B", "B terv"),
    ]
    for a, b in replacements:
        s = s.replace(a, b).replace(a.title(), b[:1].upper() + b[1:])
    return s


def build_quarter_flow(package: Dict[str, object]) -> List[str]:
    p1 = package.get("page_1_onepager", {})
    p3 = package.get("page_3_tactical_overview", {})
    controls = package.get("coach_controls", {}) or {}
    ds = package.get("decision_support", {}) or {}
    plan_a = p1.get("plan_a", "KIE")
    plan_b = p1.get("plan_b", "BAT")
    split = p1.get("plan_split", "60/40")
    scenario = localize_summary_text(label_scenario(controls.get("match_scenario") or "balanced")).lower()
    pressing_zone = localize_summary_text(str(controls.get("pressing_zone") or "közép")).lower()
    buildup = localize_summary_text(str(controls.get("build_up_solution") or "vegyes")).lower()
    block = localize_summary_text(str(controls.get("defensive_block") or "közepes")).lower()
    archetype = ds.get("archetype") or _infer_opponent_archetype(p1.get("dimensions", {}))
    top_for = ds.get("top_for") or []
    top_against = ds.get("top_against") or []

    q = []
    opener = {
        "PRS": f"0–15 perc: A meccset triggerelt presszinggel érdemes nyitni, főleg {pressing_zone} oldali csapdákkal.",
        "BAT": f"0–15 perc: A kezdésben a {block} blokk stabilitása legyen az elsődleges, nem a túl korai kinyílás.",
        "DOM": "0–15 perc: A nyitó szakaszban a ritmus és a területi kontroll megszerzése legyen a cél.",
        "MLT": f"0–15 perc: Korai, agresszív nyomás javasolt, hogy az ellenfél build-upját már az elején megbontsuk.",
    }.get(plan_a, f"0–15 perc: A nyitó szakaszban a {label_strategy(plan_a)} terv alapelveit kell érvényesíteni.")
    q.append(opener)
    if top_against:
        q.append(f"16–30 perc: A(z) {top_against[0][0].lower()} dimenzió ellen külön biztosítás kell, mert itt jön az ellenfél legerősebb szakasza.")
    else:
        q.append(f"16–30 perc: A középső szakasz elején a {label_strategy(plan_a)} terv ritmusát kell stabilizálni.")
    if archetype == "átmenet-orientált":
        q.append("31–45 perc: Az első félidő végén nőhet az átmeneti helyzetek száma, ezért a rest defense és a second ball védelme kiemelt marad.")
    elif archetype == "build-up / labdabirtoklás-orientált":
        q.append("31–45 perc: Hosszabb ellenfél-labdás periódusokra kell számítani, ezért a pressing-triggerek és a türelem minősége válik döntővé.")
    else:
        q.append("31–45 perc: A félidő végén a pontrúgás- és boxkontroll külön jelentőséget kap.")
    q.append(f"46–60 perc: A második félidő elején a {buildup} build-up és a {block} blokk legyen az újraindítási alap, innen kell olvasni a meccs ritmusát.")
    if top_for:
        q.append(f"61–75 perc: Ekkor érdemes tudatosan ráterhelni a(z) {top_for[0][0].lower()} dimenzióban meglévő saját edge-re.")
    else:
        q.append(f"61–75 perc: A {split} arányú tervsúly maradjon érvényben, de a váltási triggerre végig készen kell állni.")
    q.append(f"76–90 perc: A végjátékban a(z) {label_strategy(plan_b)} elemei aktiválhatók, ha a meccsállapot magasabb intenzitást vagy más ritmust kíván.")
    return q[:6]



def build_detailed_match_dynamics(package: Dict[str, object]) -> List[str]:
    p1 = package.get("page_1_onepager", {})
    p3 = package.get("page_3_tactical_overview", {})
    controls = package.get("coach_controls", {}) or {}
    ds = package.get("decision_support", {}) or {}
    scenario = localize_summary_text(label_scenario(controls.get("match_scenario") or "balanced")).lower()
    zone = localize_summary_text(str(controls.get("pressing_zone") or "közép")).lower()
    buildup = localize_summary_text(str(controls.get("build_up_solution") or "vegyes")).lower()
    block = localize_summary_text(str(controls.get("defensive_block") or "közepes")).lower()
    plan_a = p1.get("plan_a", "KIE")
    archetype = ds.get("archetype") or _infer_opponent_archetype(p1.get("dimensions", {}))
    top_for = ds.get("top_for") or []
    top_against = ds.get("top_against") or []

    bullets = [f"Alapforgatókönyv: {scenario} meccskép várható, de a ritmusváltások erősen függnek attól, hogy a(z) {label_strategy(plan_a)} terv mikor aktiválódik."]
    bullets.extend(_plan_text_bank(plan_a)[1:3])
    bullets.append(f"Presszingben a {zone} zóna legyen az elsődleges indítási pont, labdával pedig a {buildup} build-up maradjon az alapreakció.")
    bullets.append(f"Védekezésben a {block} blokk a kiindulás, de ezt a meccsállapot szerint kell feljebb vagy mélyebbre tolni.")
    if archetype == "átmenet-orientált":
        bullets.append("Az ellenfél átmeneti profilja miatt a meccs könnyen széttörhet, ha a második labdákra nincs azonnali reakció.")
    elif archetype == "build-up / labdabirtoklás-orientált":
        bullets.append("Az ellenfél build-up orientált profilja miatt hosszabb kontrollszakaszokra kell készülni, ezért a szerkezeti türelem fontosabb, mint a folyamatos rohanás.")
    elif archetype == "presszing-orientált":
        bullets.append("Az ellenfél presszing-orientált, ezért az első és második passzsor tisztasága meghatározza a meccs ritmusát.")
    if top_against:
        bullets.append(f"A fő védelmi reakció a(z) {top_against[0][0].lower()} köré szerveződjön.")
    if top_for:
        bullets.append(f"A saját támadó súlypont a(z) {top_for[0][0].lower()} dimenzióban lévő edge-re fűzhető rá.")
    return unique_keep_order(bullets)[:6]

# =========================================================
# EXPORT PREP
# =========================================================


def render_summary_page(package: Dict[str, object]):
    p1 = package["page_1_onepager"]
    p3 = package["page_3_tactical_overview"]
    ds = package.get("decision_support", {}) or {}
    dims = p1.get("dimensions", {})
    danger = summarize_danger_players(p3.get("key_player_threats", {}))
    conclusion_lines = [localize_summary_text(x) for x in build_full_conclusion(package)]
    mode_label = "korrigált döntési profil" if p1.get("dimension_mode") == "adjusted" else "alap matchup-profil"
    quarter_flow = build_quarter_flow(package)

    def html_bullets(items, limit=None, empty_text="-"):
        rows = items[:limit] if limit else items
        if not rows:
            return f"<div class='summary-note'>{pdf_safe_text(localize_summary_text(empty_text))}</div>"
        return "<ul class='summary-compact-list'>" + "".join(f"<li>{pdf_safe_text(localize_summary_text(str(x)))}</li>" for x in rows) + "</ul>"

    st.markdown("<div class='summary-shell'>", unsafe_allow_html=True)
    st.markdown("<div style='height:0.8rem;'></div>", unsafe_allow_html=True)
    st.markdown("### Vezetői összegző")

    st.markdown(f"""
    <div class='summary-kpi'>
        <div class='k'>
            <div class='summary-note'>⚔️ A terv</div>
            <div class='n'>{pdf_safe_text(p1.get('plan_a','-'))}</div>
            <div class='summary-note'>{pdf_safe_text(localize_summary_text(label_strategy(p1.get('plan_a',''))))}</div>
        </div>
        <div class='k'>
            <div class='summary-note'>🛡️ B terv</div>
            <div class='n'>{pdf_safe_text(p1.get('plan_b','-'))}</div>
            <div class='summary-note'>{pdf_safe_text(localize_summary_text(label_strategy(p1.get('plan_b',''))))}</div>
        </div>
        <div class='k'>
            <div class='summary-note'>⚖️ Arány</div>
            <div class='n'>{pdf_safe_text(p1.get('plan_split','-'))}</div>
            <div class='summary-note'>{mode_label}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    top_left, top_right = st.columns([1.0, 1.0], gap="medium")
    with top_left:
        st.subheader("🎯 Teljes konklúzió")
        st.markdown(html_bullets(conclusion_lines, limit=4), unsafe_allow_html=True)
    with top_right:
        st.subheader("⚠️ 3 kulcs • kockázatok • legveszélyesebb ellenfél-játékosok")
        merged = [f"Kulcs: {item}" for item in p1.get('three_keys', [])[:3]]
        merged += [f"Kockázat: {item}" for item in p1.get('risks', [])[:2]]
        merged += [f"Ellenfél: {item}" for item in danger[:2]]
        st.markdown(html_bullets(merged, empty_text="Nincs elérhető gyors összegző lista."), unsafe_allow_html=True)

    # Vizualizációk külön, rendezett nyomtatási oldalakra bontva
    radar_png = get_radar_png_bytes(dims)
    bar_png = get_bar_chart_png_bytes(dims)
    map_png = get_strategy_map_png_bytes(p1.get("plan_a"), p1.get("plan_b"))

    st.markdown("<div class='summary-page-break summary-viz-page summary-section-tight summary-section-wrap viz-page'>", unsafe_allow_html=True)
    st.markdown("<h4 class='summary-page-title'>📊 Vizualizációk</h4>", unsafe_allow_html=True)
    st.markdown("<div class='summary-unit viz-unit viz-unit-radar'><h5>7 dimenziós profil</h5><div class='summary-chartbox radar-box'>", unsafe_allow_html=True)
    if radar_png:
        st.markdown(png_bytes_to_base64_img_tag(radar_png, "7 dimenziós profil", width_style="100%"), unsafe_allow_html=True)
    else:
        render_radar_svg(dims, height=560, compact=True)
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='summary-page-break summary-section-tight summary-section-wrap viz-page'>", unsafe_allow_html=True)
    st.markdown("<div class='summary-unit viz-unit viz-unit-bar'><h5>📊 Dimenziók összehasonlítása</h5><div class='summary-chartbox bar-box'>", unsafe_allow_html=True)
    if bar_png:
        st.markdown(png_bytes_to_base64_img_tag(bar_png, "Dimenziók összehasonlítása", width_style="100%"), unsafe_allow_html=True)
    else:
        render_bar_chart(dims, height=500)
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='summary-page-break summary-section-tight summary-section-wrap viz-page'>", unsafe_allow_html=True)
    st.markdown("<div class='summary-unit viz-unit viz-unit-map'><h5>🧭 9 stratégia térképe</h5><div class='summary-note' style='margin-bottom:.35rem;'>A térkép a két csapat profilja alapján javasolt játékmodelleket mutatja a blokkmagasság és a játékstílus tengelyén.</div><div class='summary-chartbox map-box'>", unsafe_allow_html=True)
    if map_png:
        st.markdown(png_bytes_to_base64_img_tag(map_png, "9 stratégia térképe", width_style="100%"), unsafe_allow_html=True)
    else:
        render_strategy_map(p1.get("plan_a"), p1.get("plan_b"), height=500)
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='summary-page-break summary-section-tight summary-section-wrap'>", unsafe_allow_html=True)
    info_left, info_right = st.columns([1.02, 0.98], gap="medium")
    with info_left:
        st.markdown("<div class='summary-unit'>", unsafe_allow_html=True)
        st.subheader("Matchup-olvasat")
        st.markdown(html_bullets([localize_summary_text(x) for x in ds.get("matchup_notes", [])], limit=4, empty_text="Nincs külön matchup-olvasat."), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div class='summary-unit'>", unsafe_allow_html=True)
        st.subheader("Várható meccsdinamika")
        dyn = build_detailed_match_dynamics(package)
        st.markdown(html_bullets(dyn, limit=5, empty_text="Nincs külön meccsdinamika-megjegyzés."), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with info_right:
        st.markdown("<div class='summary-unit'>", unsafe_allow_html=True)
        st.subheader("Miért ezt a taktikát?")
        rec = [localize_summary_text(x) for x in ds.get("recommendation", [])]
        if not rec:
            top_for = ds.get("top_for") or []
            top_against = ds.get("top_against") or []
            key_edge = top_for[0][0].lower() if top_for else "átmenetek"
            risk_edge = top_against[0][0].lower() if top_against else "labdakihozatal"
            rec = [
                f"A fő javaslat azért a(z) {localize_summary_text(label_strategy(p1.get('plan_a', 'KIE')).lower())}, mert ebben a modellben a saját legnagyobb edge a(z) {key_edge} területén jelenik meg, miközben az ellenfél fő veszélye a(z) {risk_edge} oldalon kezelhető marad.",
                f"A(z) {localize_summary_text(label_strategy(p1.get('plan_b', 'BAT')).lower())} inkább váltási opció: akkor érdemes elővenni, ha a meccs ritmusa megemelkedik, vagy az ellenfél túl kényelmesen tudja felhozni a labdát.",
                "A blokk alaphelyzetben maradjon rendezett, a pressing pedig ne folyamatos legyen, hanem a kijelölt váltási jelekhez kötődjön.",
                "Saját labdával az első cél ne a puszta labdabirtoklás legyen, hanem az, hogy a belső progresszió és a second ball kontroll révén a saját erősségeinket hozzuk játékba.",
            ]
        st.markdown(html_bullets(rec, limit=4), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='summary-unit'>", unsafe_allow_html=True)
    st.subheader("Negyedórás várható lefolyás")
    st.markdown(html_bullets(quarter_flow, empty_text="Nincs becsült negyedórás meccslefolyás."), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='summary-page-break summary-section-tight summary-section-wrap'>", unsafe_allow_html=True)
    st.markdown("<div class='summary-unit'>", unsafe_allow_html=True)
    st.markdown("<div class='summary-method-title'>🧠 Módszertan röviden</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='summary-method compact'>{pdf_safe_text(localize_summary_text(get_methodology_summary()))}</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


if step == "5. Összegző oldal":
    dims = st.session_state.get("dims")
    adjusted_dims = st.session_state.get("dims_adjusted")
    active_dims = adjusted_dims if st.session_state.get("use_adjusted_dims", True) and adjusted_dims else dims
    opp_players = st.session_state.get("opp_players")

    if not dims:
        st.warning("Előbb tölts fel adatot az Input fülön.")
    else:
        sync_coach_texts_from_controls()
        package = build_export_package(
            selected_plan_a=st.session_state["selected_plan_a"],
            selected_plan_b=st.session_state["selected_plan_b"],
            selected_split=st.session_state["selected_split"],
            dims=active_dims,
            opponent_profile_text=st.session_state["opponent_profile_text"],
            own_state_text=st.session_state["own_state_text"],
            three_keys_text=st.session_state["three_keys_text"],
            risks_text=st.session_state["risks_text"],
            match_dynamics_text=st.session_state["match_dynamics_text"],
            conclusion_text=st.session_state["conclusion_text"],
            opponent_dna_text=st.session_state["opponent_dna_text"],
            opp_players=opp_players,
            coach_controls= {
                "primary_model": st.session_state.get("coach_primary_model"),
                "secondary_model": st.session_state.get("coach_secondary_model"),
                "focus_areas": st.session_state.get("coach_focus_areas"),
                "selected_risks": st.session_state.get("coach_selected_risks"),
                "focus_players": st.session_state.get("coach_focus_players"),
                "pressing_zone": st.session_state.get("coach_pressing_zone"),
                "build_up_solution": st.session_state.get("coach_build_up_solution"),
                "defensive_block": st.session_state.get("coach_defensive_block"),
                "match_scenario": st.session_state.get("coach_match_scenario"),
                "plan_a_emphasis": st.session_state.get("coach_plan_a_emphasis"),
                "set_piece_priority": st.session_state.get("coach_set_piece_priority"),
                "second_ball_focus": st.session_state.get("coach_second_ball_focus"),
                "halfspace_defense_priority": st.session_state.get("coach_halfspace_defense_priority"),
            },
            decision_support=st.session_state.get("decision_support"),
        )
        render_summary_page(package)


if step == "4. Export Prep":
    dims = st.session_state.get("dims")
    adjusted_dims = st.session_state.get("dims_adjusted")
    active_dims = adjusted_dims if st.session_state.get("use_adjusted_dims", True) and adjusted_dims else dims
    opp_players = st.session_state.get("opp_players")

    if not dims:
        st.warning("Előbb tölts fel adatot az Input fülön.")
    else:
        sync_coach_texts_from_controls()
        render_methodology_block()
        st.header("Export Prep – template előkészítés")
        if not REPORTLAB_AVAILABLE:
            st.warning("A reportlab nincs telepítve, ezért a PDF gomb szöveges fallback fájlt ad vissza. A teljes, diagramokat is tartalmazó export ilyenkor a HTML fájlban látszik.")

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
            dims=active_dims,
            opponent_profile_text=st.session_state["opponent_profile_text"],
            own_state_text=st.session_state["own_state_text"],
            three_keys_text=st.session_state["three_keys_text"],
            risks_text=st.session_state["risks_text"],
            match_dynamics_text=st.session_state["match_dynamics_text"],
            conclusion_text=st.session_state["conclusion_text"],
            opponent_dna_text=st.session_state["opponent_dna_text"],
            opp_players=opp_players,
            coach_controls=coach_controls,
            decision_support=st.session_state.get("decision_support"),
        )

        md_export = build_markdown_export(package)
        json_export = json.dumps(package, ensure_ascii=False, indent=2)
        pdf_export = build_pdf_export_bytes(package)
        html_export = build_html_export(package)

        st.subheader("Jelenlegi végtermék preview")
        preview_tab, md_tab, json_tab = st.tabs(["Deck preview", "Markdown", "JSON / letöltések"])

        with preview_tab:
            render_export_preview(package)

        with md_tab:
            st.text_area("Markdown", value=md_export, height=520)

        with json_tab:
            dl1, dl2 = st.columns(2)
            with dl1:
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
                    file_name="briefing_export_package.pdf" if REPORTLAB_AVAILABLE else "briefing_export_package.txt",
                    mime="application/pdf" if REPORTLAB_AVAILABLE else "text/plain",
                )
                st.download_button(
                    "HTML briefing letöltése",
                    data=html_export.encode("utf-8"),
                    file_name="briefing_export_package.html",
                    mime="text/html",
                )
                st.download_button(
                    "Markdown letöltése",
                    data=md_export.encode("utf-8"),
                    file_name="briefing_export_package.md",
                    mime="text/markdown",
                )
            with dl2:
                st.markdown("#### Control státusz")
                st.dataframe(pd.DataFrame(control_status_rows(st.session_state.get("coach_link_controls", True))), use_container_width=True, hide_index=True)
                st.markdown("#### Coach control snapshot")
                st.json(coach_controls)
        st.info(f"Export mód: {'szimulált coach-hatással korrigált dimenziók' if st.session_state.get('use_adjusted_dims', True) else 'alap dimenziók'}")

        if st.session_state.get("decision_support"):
            st.subheader("Exportba kerülő taktikai döntési blokk")
            st.write(st.session_state["decision_support"].get("executive_summary", ""))
            for line in st.session_state["decision_support"].get("recommendation", [])[:4]:
                st.write(f"- {line}")

        st.subheader("Mi jön ezután?")
        st.write("- Következő lépés: a JSON/PDF package mezőit rámapeljük a gold standard PPT template konkrét textboxaira.")
        st.write("- Utána: tényleges PPT generálás és visszaadás kész briefing deckként.")
