import re
from typing import Dict, List

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Parser debug", layout="wide")
st.title("Excel parser debug – KTE vs Ellenfél")

METRIC_ALIASES = {
    "ppda": ["ppda"],
    "pressing_success_pct": ["pressing / successful", "pressing successful", "pressing"],
    "high_pressing_success_pct": ["high pressing / successful", "high pressing"],
    "passes_accurate_pct": ["passes / accurate", "passes accurate"],
    "short_pass_acc_pct": ["short passes, 0-10 m."],
    "medium_pass_acc_pct": ["medium passes, 10-40 m."],
    "passes_open_play_acc_pct": ["passes from open play"],
    "lost_balls_own_half": ["lost balls / in own half"],
    "avg_possession_duration_sec": ["average duration of ball poss."],
    "counter_attacks": ["counter-attacks / with shots", "counter attacks / with shots"],
    "counter_attacks_with_shots_pct": ["counter-attacks / with shots", "counter attacks / with shots"],
    "entries_final_quarter": ["entrances to the final quarter"],
    "entries_box": ["entrances to the opponent's box", "entrances to the opponents box"],
    "attacks_with_shots_pct": ["attacks / with shots"],
    "avg_pass_length": ["average lenght of the pass", "average length of the pass"],
    "positional_attacks": ["positional attacks / with shots"],
    "positional_attacks_with_shots_pct": ["positional attacks / with shots"],
    "passes_into_final_third": ["passes into the final third of the pitch"],
    "passes_into_box": ["passes into the penalty box"],
    "key_passes": ["key passes"],
    "final_third_possession_pct": ["ball possession on final third"],
    "xg": ["xg"],
    "shots": ["shots / on target"],
    "shots_on_target": ["shots / on target"],
    "defensive_duels_success_pct": ["defensive challenges / successful"],
    "set_piece_attacks": ["set-piece attacks / with shots", "set-piece attacks/ with shots"],
    "set_piece_attacks_with_shots_pct": ["set-piece attacks / with shots", "set-piece attacks/ with shots"],
    "corners": ["corners / with shots", "corners"],
    "corners_with_shots_pct": ["corners / with shots"],
    "free_kick_combinations_with_shots_pct": ["free-kick combinations / with shots", "free kick combinations / with shots"],
    "challenge_intensity_index": ["challenge intensity index"],
    "challenges_total": ["challenges / successful"],
    "challenges_success_pct": ["challenges / successful"],
    "air_duels_success_pct": ["air challenges / successful"],
    "ground_duels_success_pct": ["ground challenges / successful"],
    "tackles_success_pct": ["tackles / successful"],
    "dribbles_success_pct": ["dribbles / successful"],
    "possession_pct": ["ball possession"],
}


def safe_float(x, default: float = 0.0) -> float:
    try:
        return float(str(x).replace(",", ".").replace("%", "").strip())
    except Exception:
        return default


def parse_mmss_to_seconds(text: str) -> float:
    m = re.search(r"(\d{1,2}):(\d{2})", str(text))
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + int(m.group(2))


def numbers_from_row(row_values: List[str]) -> List[float]:
    text = " | ".join([str(v) for v in row_values if str(v) != "nan"])
    matches = re.findall(r"-?\d+(?:[\.,]\d+)?%?", text)
    out = []
    for m in matches:
        if ":" in m:
            continue
        out.append(safe_float(m))
    return out


def find_matches_in_sheet(df: pd.DataFrame, labels: List[str]) -> List[dict]:
    found = []
    for idx, row in df.iterrows():
        row_vals = [str(v) for v in row.tolist()]
        row_text = " | ".join(row_vals).lower()
        hits = [label for label in labels if label in row_text]
        if hits:
            pct_matches = re.findall(r"(\d+(?:[\.,]\d+)?)%", " | ".join(row_vals))
            found.append(
                {
                    "row_index": int(idx),
                    "hits": ", ".join(hits),
                    "row_text": " | ".join(row_vals)[:500],
                    "numbers": numbers_from_row(row_vals),
                    "pct": [safe_float(x) for x in pct_matches],
                    "time_sec": max([parse_mmss_to_seconds(v) for v in row_vals] + [0.0]),
                }
            )
    return found


def parse_excel_debug(file_bytes: bytes) -> Dict[str, dict]:
    result = {}
    xls = pd.ExcelFile(file_bytes)
    for key, labels in METRIC_ALIASES.items():
        result[key] = {"matches": []}
        for sheet in xls.sheet_names:
            try:
                df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)
            except Exception:
                continue
            matches = find_matches_in_sheet(df, labels)
            if matches:
                result[key]["matches"].append({"sheet": sheet, "rows": matches[:5]})
    return result


def workbook_preview(file_bytes: bytes) -> Dict[str, pd.DataFrame]:
    previews = {}
    xls = pd.ExcelFile(file_bytes)
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)
            previews[sheet] = df.head(12)
        except Exception:
            continue
    return previews


kte_file = st.file_uploader("KTE meccs Excel", type=["xlsx"], key="kte")
ell_file = st.file_uploader("Ellenfél meccs Excel", type=["xlsx"], key="ell")

if kte_file and ell_file:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("KTE – munkalap előnézet")
        kte_prev = workbook_preview(kte_file.getvalue())
        for sheet, df in kte_prev.items():
            st.markdown(f"**{sheet}**")
            st.dataframe(df, use_container_width=True)

    with col2:
        st.subheader("Ellenfél – munkalap előnézet")
        ell_prev = workbook_preview(ell_file.getvalue())
        for sheet, df in ell_prev.items():
            st.markdown(f"**{sheet}**")
            st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("Alias-találatok")
    kte_debug = parse_excel_debug(kte_file.getvalue())
    ell_debug = parse_excel_debug(ell_file.getvalue())

    rows = []
    for key in METRIC_ALIASES.keys():
        rows.append(
            {
                "metric": key,
                "kte_hits": sum(len(x["rows"]) for x in kte_debug[key]["matches"]),
                "ell_hits": sum(len(x["rows"]) for x in ell_debug[key]["matches"]),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    metric_pick = st.selectbox("Részletes vizsgálat metrika szerint", list(METRIC_ALIASES.keys()))
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"### KTE – {metric_pick}")
        st.json(kte_debug[metric_pick])
    with d2:
        st.markdown(f"### Ellenfél – {metric_pick}")
        st.json(ell_debug[metric_pick])
else:
    st.info("Töltsd fel a két meccs Excel fájlt. Ez a debug app megmutatja, melyik alias talál valós sort, és melyik nem.")
