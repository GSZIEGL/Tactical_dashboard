import math
import re
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import pdfplumber

st.set_page_config(page_title="Taktikai meccs-briefing generátor", layout="wide")


@dataclass
class UploadedFiles:
    team_match_stats: Optional[object] = None
    team_player_stats: Optional[object] = None
    team_reference_report: Optional[object] = None
    opp_match_stats: Optional[object] = None
    opp_player_stats: Optional[object] = None
    opp_report_1: Optional[object] = None
    opp_report_2: Optional[object] = None
    opp_report_3: Optional[object] = None
    template_ppt: Optional[object] = None

    def required_ok(self) -> bool:
        return all([
            self.team_match_stats,
            self.team_player_stats,
            self.team_reference_report,
            self.opp_match_stats,
            self.opp_player_stats,
            self.opp_report_1,
            self.opp_report_2,
            self.template_ppt,
        ])


@dataclass
class BriefingResult:
    plan_a: str
    plan_b: str
    split: str
    dimensions: Dict[str, Dict[str, float]]
    opponent_profile: str
    own_state: str
    three_keys: List[str]
    risks: List[str]
    match_dynamics: List[str]
    conclusion: List[str]
    debug_metrics_team: Dict[str, float]
    debug_metrics_opp: Dict[str, float]
    team_metric_count: int
    opp_metric_count: int


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


def clamp(v: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


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


def extract_first_numeric_from_label(df: pd.DataFrame, labels: List[str]) -> float:
    for _, row in df.iterrows():
        row_vals = [str(v) for v in row.tolist()]
        row_text = " | ".join(row_vals).lower()
        if any(label in row_text for label in labels):
            nums = numbers_from_row(row_vals)
            if nums:
                return nums[0]
    return 0.0


def extract_second_numeric_from_label(df: pd.DataFrame, labels: List[str]) -> float:
    for _, row in df.iterrows():
        row_vals = [str(v) for v in row.tolist()]
        row_text = " | ".join(row_vals).lower()
        if any(label in row_text for label in labels):
            nums = numbers_from_row(row_vals)
            if len(nums) >= 2:
                return nums[1]
            if nums:
                return nums[0]
    return 0.0


def extract_pct_from_label(df: pd.DataFrame, labels: List[str]) -> float:
    for _, row in df.iterrows():
        row_vals = [str(v) for v in row.tolist()]
        row_text = " | ".join(row_vals).lower()
        if any(label in row_text for label in labels):
            pct_matches = re.findall(r"(\d+(?:[\.,]\d+)?)%", " | ".join(row_vals))
            if pct_matches:
                return safe_float(pct_matches[-1])
            nums = numbers_from_row(row_vals)
            if nums:
                return nums[-1]
    return 0.0


def extract_mmss_from_label(df: pd.DataFrame, labels: List[str]) -> float:
    for _, row in df.iterrows():
        row_vals = [str(v) for v in row.tolist()]
        row_text = " | ".join(row_vals).lower()
        if any(label in row_text for label in labels):
            for val in row_vals:
                sec = parse_mmss_to_seconds(val)
                if sec > 0:
                    return sec
    return 0.0


@st.cache_data(show_spinner=False)
def parse_excel_metrics(file_bytes: bytes) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    xls = pd.ExcelFile(file_bytes)

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)
        except Exception:
            continue

        if "ppda" not in metrics:
            metrics["ppda"] = extract_first_numeric_from_label(df, METRIC_ALIASES["ppda"])
        if "pressing_success_pct" not in metrics:
            metrics["pressing_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["pressing_success_pct"])
        if "high_pressing_success_pct" not in metrics:
            metrics["high_pressing_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["high_pressing_success_pct"])
        if "passes_accurate_pct" not in metrics:
            metrics["passes_accurate_pct"] = extract_pct_from_label(df, METRIC_ALIASES["passes_accurate_pct"])
        if "short_pass_acc_pct" not in metrics:
            metrics["short_pass_acc_pct"] = extract_pct_from_label(df, METRIC_ALIASES["short_pass_acc_pct"])
        if "medium_pass_acc_pct" not in metrics:
            metrics["medium_pass_acc_pct"] = extract_pct_from_label(df, METRIC_ALIASES["medium_pass_acc_pct"])
        if "passes_open_play_acc_pct" not in metrics:
            metrics["passes_open_play_acc_pct"] = extract_pct_from_label(df, METRIC_ALIASES["passes_open_play_acc_pct"])
        if "lost_balls_own_half" not in metrics:
            metrics["lost_balls_own_half"] = extract_second_numeric_from_label(df, METRIC_ALIASES["lost_balls_own_half"])
        if "avg_possession_duration_sec" not in metrics:
            metrics["avg_possession_duration_sec"] = extract_mmss_from_label(df, METRIC_ALIASES["avg_possession_duration_sec"])
        if "counter_attacks" not in metrics:
            metrics["counter_attacks"] = extract_first_numeric_from_label(df, METRIC_ALIASES["counter_attacks"])
        if "counter_attacks_with_shots_pct" not in metrics:
            metrics["counter_attacks_with_shots_pct"] = extract_pct_from_label(df, METRIC_ALIASES["counter_attacks_with_shots_pct"])
        if "entries_final_quarter" not in metrics:
            metrics["entries_final_quarter"] = extract_first_numeric_from_label(df, METRIC_ALIASES["entries_final_quarter"])
        if "entries_box" not in metrics:
            metrics["entries_box"] = extract_first_numeric_from_label(df, METRIC_ALIASES["entries_box"])
        if "attacks_with_shots_pct" not in metrics:
            metrics["attacks_with_shots_pct"] = extract_pct_from_label(df, METRIC_ALIASES["attacks_with_shots_pct"])
        if "avg_pass_length" not in metrics:
            metrics["avg_pass_length"] = extract_first_numeric_from_label(df, METRIC_ALIASES["avg_pass_length"])
        if "positional_attacks" not in metrics:
            metrics["positional_attacks"] = extract_first_numeric_from_label(df, METRIC_ALIASES["positional_attacks"])
        if "positional_attacks_with_shots_pct" not in metrics:
            metrics["positional_attacks_with_shots_pct"] = extract_pct_from_label(df, METRIC_ALIASES["positional_attacks_with_shots_pct"])
        if "passes_into_final_third" not in metrics:
            metrics["passes_into_final_third"] = extract_first_numeric_from_label(df, METRIC_ALIASES["passes_into_final_third"])
        if "passes_into_box" not in metrics:
            metrics["passes_into_box"] = extract_first_numeric_from_label(df, METRIC_ALIASES["passes_into_box"])
        if "key_passes" not in metrics:
            metrics["key_passes"] = extract_first_numeric_from_label(df, METRIC_ALIASES["key_passes"])
        if "final_third_possession_pct" not in metrics:
            metrics["final_third_possession_pct"] = extract_pct_from_label(df, METRIC_ALIASES["final_third_possession_pct"])
        if "xg" not in metrics:
            metrics["xg"] = extract_first_numeric_from_label(df, METRIC_ALIASES["xg"])
        if "shots" not in metrics:
            metrics["shots"] = extract_first_numeric_from_label(df, METRIC_ALIASES["shots"])
        if "shots_on_target" not in metrics:
            metrics["shots_on_target"] = extract_second_numeric_from_label(df, METRIC_ALIASES["shots_on_target"])
        if "defensive_duels_success_pct" not in metrics:
            metrics["defensive_duels_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["defensive_duels_success_pct"])
        if "set_piece_attacks" not in metrics:
            metrics["set_piece_attacks"] = extract_first_numeric_from_label(df, METRIC_ALIASES["set_piece_attacks"])
        if "set_piece_attacks_with_shots_pct" not in metrics:
            metrics["set_piece_attacks_with_shots_pct"] = extract_pct_from_label(df, METRIC_ALIASES["set_piece_attacks_with_shots_pct"])
        if "corners" not in metrics:
            metrics["corners"] = extract_first_numeric_from_label(df, METRIC_ALIASES["corners"])
        if "corners_with_shots_pct" not in metrics:
            metrics["corners_with_shots_pct"] = extract_pct_from_label(df, METRIC_ALIASES["corners_with_shots_pct"])
        if "free_kick_combinations_with_shots_pct" not in metrics:
            metrics["free_kick_combinations_with_shots_pct"] = extract_pct_from_label(
                df, METRIC_ALIASES["free_kick_combinations_with_shots_pct"]
            )
        if "challenge_intensity_index" not in metrics:
            metrics["challenge_intensity_index"] = extract_first_numeric_from_label(df, METRIC_ALIASES["challenge_intensity_index"])
        if "challenges_total" not in metrics:
            metrics["challenges_total"] = extract_first_numeric_from_label(df, METRIC_ALIASES["challenges_total"])
        if "challenges_success_pct" not in metrics:
            metrics["challenges_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["challenges_success_pct"])
        if "air_duels_success_pct" not in metrics:
            metrics["air_duels_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["air_duels_success_pct"])
        if "ground_duels_success_pct" not in metrics:
            metrics["ground_duels_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["ground_duels_success_pct"])
        if "tackles_success_pct" not in metrics:
            metrics["tackles_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["tackles_success_pct"])
        if "dribbles_success_pct" not in metrics:
            metrics["dribbles_success_pct"] = extract_pct_from_label(df, METRIC_ALIASES["dribbles_success_pct"])
        if "possession_pct" not in metrics:
            metrics["possession_pct"] = extract_first_numeric_from_label(df, METRIC_ALIASES["possession_pct"])

    return metrics


@st.cache_data(show_spinner=False)
def parse_pdf_context(file_bytes: bytes) -> Dict[str, str]:
    text = ""
    try:
        with pdfplumber.open(file_bytes) as pdf:
            for page in pdf.pages[:8]:
                text += "\n" + (page.extract_text() or "")
    except Exception:
        return {}

    out: Dict[str, str] = {}
    form_match = re.search(r"Match start\s+([0-9\-–]+)", text)
    if form_match:
        out["formation_start"] = form_match.group(1).replace("–", "-")
    return out


@st.cache_data(show_spinner=False)
def parse_player_spike(file_bytes: bytes) -> float:
    try:
        xls = pd.ExcelFile(file_bytes)
        values = []
        for sheet in xls.sheet_names:
            df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)
            flat = df.astype(str).values.flatten().tolist()
            for val in flat:
                nums = re.findall(r"\d+(?:[\.,]\d+)?", str(val))
                for n in nums:
                    f = safe_float(n)
                    if 0 < f < 200:
                        values.append(f)
        if not values:
            return 0.0
        values.sort(reverse=True)
        return float(values[0])
    except Exception:
        return 0.0


def nonzero_metric_count(metrics: Dict[str, float]) -> int:
    return sum(1 for v in metrics.values() if isinstance(v, (int, float)) and v > 0)


def normalize_direct(value: float, lo: float, hi: float, fallback: float = 5.0) -> float:
    if value <= 0:
        return fallback
    if hi <= lo:
        return fallback
    return clamp(1 + 9 * ((value - lo) / (hi - lo)))


def normalize_inverse(value: float, lo: float, hi: float, fallback: float = 5.0) -> float:
    if value <= 0:
        return fallback
    if hi <= lo:
        return fallback
    return clamp(10 - 9 * ((value - lo) / (hi - lo)))


def score_dimensions(metrics: Dict[str, float]) -> Dict[str, float]:
    pressing = (
        normalize_inverse(metrics.get("ppda", 0), 1, 8) * 0.35
        + normalize_direct(metrics.get("pressing_success_pct", 0), 20, 80) * 0.25
        + normalize_direct(metrics.get("high_pressing_success_pct", 0), 10, 85) * 0.20
        + normalize_direct(metrics.get("challenge_intensity_index", 0), 8, 18) * 0.20
    )
    buildup = (
        normalize_direct(metrics.get("passes_accurate_pct", 0), 55, 85) * 0.30
        + normalize_direct(metrics.get("short_pass_acc_pct", 0), 45, 90) * 0.15
        + normalize_direct(metrics.get("medium_pass_acc_pct", 0), 50, 85) * 0.15
        + normalize_direct(metrics.get("passes_open_play_acc_pct", 0), 50, 82) * 0.20
        + normalize_inverse(metrics.get("lost_balls_own_half", 0), 5, 25) * 0.20
    )
    transition = (
        normalize_direct(metrics.get("counter_attacks_with_shots_pct", 0), 0, 35) * 0.35
        + normalize_direct(metrics.get("counter_attacks", 0), 0, 30) * 0.20
        + normalize_direct(metrics.get("entries_box", 0), 5, 30) * 0.20
        + normalize_direct(metrics.get("avg_pass_length", 0), 15, 30) * 0.10
        + normalize_direct(metrics.get("attacks_with_shots_pct", 0), 3, 18) * 0.15
    )
    attack = (
        normalize_direct(metrics.get("positional_attacks", 0), 20, 90) * 0.20
        + normalize_direct(metrics.get("positional_attacks_with_shots_pct", 0), 1, 15) * 0.20
        + normalize_direct(metrics.get("passes_into_final_third", 0), 40, 220) * 0.20
        + normalize_direct(metrics.get("passes_into_box", 0), 5, 60) * 0.25
        + normalize_direct(metrics.get("key_passes", 0), 0, 15) * 0.15
    )
    defense = (
        normalize_inverse(metrics.get("xg", 0), 0.3, 2.0) * 0.15
        + normalize_inverse(metrics.get("shots", 0), 4, 20) * 0.20
        + normalize_inverse(metrics.get("shots_on_target", 0), 1, 8) * 0.20
        + normalize_inverse(metrics.get("passes_into_box", 0), 5, 60) * 0.20
        + normalize_inverse(metrics.get("lost_balls_own_half", 0), 5, 25) * 0.10
        + normalize_direct(metrics.get("defensive_duels_success_pct", 0), 35, 70) * 0.15
    )
    setpieces = (
        normalize_direct(metrics.get("set_piece_attacks", 0), 0, 25) * 0.25
        + normalize_direct(metrics.get("set_piece_attacks_with_shots_pct", 0), 0, 50) * 0.30
        + normalize_direct(metrics.get("corners", 0), 0, 12) * 0.15
        + normalize_direct(metrics.get("corners_with_shots_pct", 0), 0, 80) * 0.20
        + normalize_direct(metrics.get("free_kick_combinations_with_shots_pct", 0), 0, 50) * 0.10
    )
    physical = (
        normalize_direct(metrics.get("challenge_intensity_index", 0), 8, 18) * 0.25
        + normalize_direct(metrics.get("challenges_total", 0), 120, 260) * 0.20
        + normalize_direct(metrics.get("challenges_success_pct", 0), 35, 65) * 0.15
        + normalize_direct(metrics.get("air_duels_success_pct", 0), 30, 70) * 0.15
        + normalize_direct(metrics.get("ground_duels_success_pct", 0), 35, 65) * 0.10
        + normalize_direct(metrics.get("tackles_success_pct", 0), 35, 75) * 0.10
        + normalize_direct(metrics.get("dribbles_success_pct", 0), 35, 75) * 0.05
    )

    return {
        "Letámadás": round(pressing, 1),
        "Labdakihozatal": round(buildup, 1),
        "Átmenetek": round(transition, 1),
        "Támadó játék": round(attack, 1),
        "Védekezési stabilitás": round(defense, 1),
        "Pontrúgások": round(setpieces, 1),
        "Fizikai profil": round(physical, 1),
    }


def pick_plans(team_scores: Dict[str, float], opp_scores: Dict[str, float]) -> Tuple[str, str, str]:
    edge_transition = team_scores["Átmenetek"] - opp_scores["Védekezési stabilitás"]
    edge_press = team_scores["Letámadás"] - opp_scores["Labdakihozatal"]
    edge_control = team_scores["Labdakihozatal"] + team_scores["Támadó játék"] - opp_scores["Letámadás"]

    if edge_transition >= max(edge_press, edge_control):
        plan_a = "GAT"
        plan_b = "BAT" if opp_scores["Átmenetek"] > 6 else "KIE"
        split = "60/40"
    elif edge_press >= max(edge_transition, edge_control):
        plan_a = "PRS"
        plan_b = "MLT" if team_scores["Letámadás"] > 6.8 else "BAT"
        split = "55/45"
    else:
        plan_a = "KIE" if team_scores["Támadó játék"] < 6.5 else "POZ"
        plan_b = "BAT"
        split = "55/45"

    return plan_a, plan_b, split


def generate_profiles(
    opponent_name: str,
    team_scores: Dict[str, float],
    opp_scores: Dict[str, float],
    team_ctx: Dict[str, str],
    opp_ctx: Dict[str, str],
) -> Tuple[str, str, List[str], List[str], List[str], List[str]]:
    opp_form = opp_ctx.get("formation_start", "n.a.")
    team_form = team_ctx.get("formation_start", "n.a.")

    opp_strengths = []
    if opp_scores["Átmenetek"] >= 6:
        opp_strengths.append("direkt átmenetek")
    if opp_scores["Fizikai profil"] >= 6:
        opp_strengths.append("középső zóna párharcok")
    if opp_scores["Pontrúgások"] >= 6:
        opp_strengths.append("pontrúgás-veszély")
    if not opp_strengths:
        opp_strengths = ["kiegyensúlyozott játék", "szerkezeti fegyelem"]

    opp_danger = "második labdák és korai progresszió" if opp_scores["Átmenetek"] >= 6 else "beadások és visszatámadás"
    opponent_profile = f"Felállás: {opp_form} | Erősség: {', '.join(opp_strengths[:2])} | Veszély: {opp_danger} ({opponent_name})"

    team_strengths = []
    if team_scores["Átmenetek"] >= 6:
        team_strengths.append("átmeneti támadás")
    if team_scores["Labdakihozatal"] >= 6:
        team_strengths.append("mélységi kijövetel")
    if team_scores["Támadó játék"] >= 6:
        team_strengths.append("félterületi progresszió")
    if not team_strengths:
        team_strengths = ["szerkezeti fegyelem", "munkabírás"]

    team_risk = "labdavesztés utáni visszarendeződés" if team_scores["Védekezési stabilitás"] < 6 else "középső zónás labdavesztés"
    own_state = f"Felállás: {team_form} | Erősség: {', '.join(team_strengths[:2])} | Kockázat: {team_risk}"

    three_keys = [
        "Presszing mögötti terület támadása" if team_scores["Átmenetek"] >= opp_scores["Védekezési stabilitás"] else "Játékfelépítés stabilizálása",
        "Második labdák kontrollja középen",
        "Gyors oldalváltások és félterületi belépések" if team_scores["Labdakihozatal"] >= 6 else "Középső blokk szerkezeti védelme",
    ]

    risks = [
        "Középső zónás labdavesztés",
        "Második labdák az első kontakt után",
        "Átmeneti védekezés nyitott szerkezetben" if opp_scores["Átmenetek"] >= 6 else "Pontrúgások utáni lecsorgók",
    ]

    match_dynamics = [
        "0–20: intenzív kezdés, sok középső zónás párharc",
        "20–45: kiegyenlített szerkezeti játék",
        "45–70: átmeneti fázis, gyors területváltások" if team_scores["Átmenetek"] >= 6 or opp_scores["Átmenetek"] >= 6 else "45–70: kontrolláltabb labdabirtoklás",
        "70–90: nyíltabb végjáték",
    ]

    conclusion = [
        "A legjobb illeszkedés a gyors átmeneti játék." if team_scores["Átmenetek"] >= opp_scores["Védekezési stabilitás"] else "A legjobb illeszkedés a kiegyensúlyozott szerkezeti játék.",
        "A fő előny a KTE átmeneti és mélységi progressziójában lehet.",
        f"A fő kockázat: {risks[0].lower()}.",
        "Plan A és Plan B aránya a meccsprofil megoszlását jelzi, nem szavazást.",
    ]

    return opponent_profile, own_state, three_keys, risks, match_dynamics, conclusion


def run_briefing_engine(opponent_name: str, files: UploadedFiles) -> BriefingResult:
    team_metrics = parse_excel_metrics(files.team_match_stats.getvalue()) if files.team_match_stats else {}
    opp_metrics = parse_excel_metrics(files.opp_match_stats.getvalue()) if files.opp_match_stats else {}

    team_metrics["player_spike"] = parse_player_spike(files.team_player_stats.getvalue()) if files.team_player_stats else 0.0
    opp_metrics["player_spike"] = parse_player_spike(files.opp_player_stats.getvalue()) if files.opp_player_stats else 0.0

    team_ctx = parse_pdf_context(files.team_reference_report.getvalue()) if files.team_reference_report else {}
    opp_ctx = parse_pdf_context(files.opp_report_1.getvalue()) if files.opp_report_1 else {}

    team_scores = score_dimensions(team_metrics)
    opp_scores = score_dimensions(opp_metrics)

    dimensions = {}
    for dim in team_scores.keys():
        dimensions[dim] = {
            "KTE": team_scores[dim],
            "ELL": opp_scores[dim],
            "Edge": round(team_scores[dim] - opp_scores[dim], 1),
        }

    plan_a, plan_b, split = pick_plans(team_scores, opp_scores)
    opponent_profile, own_state, three_keys, risks, match_dynamics, conclusion = generate_profiles(
        opponent_name, team_scores, opp_scores, team_ctx, opp_ctx
    )

    return BriefingResult(
        plan_a=plan_a,
        plan_b=plan_b,
        split=split,
        dimensions=dimensions,
        opponent_profile=opponent_profile,
        own_state=own_state,
        three_keys=three_keys,
        risks=risks,
        match_dynamics=match_dynamics,
        conclusion=conclusion,
        debug_metrics_team=team_metrics,
        debug_metrics_opp=opp_metrics,
        team_metric_count=nonzero_metric_count(team_metrics),
        opp_metric_count=nonzero_metric_count(opp_metrics),
    )


def strategy_palette_rows() -> List[dict]:
    label_block = {"low": "mély", "low_mid": "alacsony-közép", "mid": "közép", "mid_high": "közép-magas", "high": "magas"}
    label_style = {
        "direct": "direkt",
        "transition_press": "presszing+átmenet",
        "balanced": "vegyes",
        "balanced_control": "kiegyensúlyozott",
        "control": "kontroll",
        "aggressive": "agresszív",
    }
    return [
        {"Kód": k, "Stratégia": v["name"], "Blokkmagasság": label_block[v["block"]], "Játékstílus": label_style[v["style"]]}
        for k, v in STRATEGY_PALETTE.items()
    ]


def strategy_scatter_data(selected_a: Optional[str] = None, selected_b: Optional[str] = None) -> List[dict]:
    block_map = {"low": 1, "low_mid": 2, "mid": 3, "mid_high": 4, "high": 5}
    style_map = {"direct": 1, "transition_press": 2, "balanced": 3, "balanced_control": 4, "control": 5, "aggressive": 6}
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


def dimension_rows(result: BriefingResult) -> List[dict]:
    return [
        {"Dimenzió": dim, "KTE": float(vals["KTE"]), "ELL": float(vals["ELL"]), "Edge": float(vals["Edge"])}
        for dim, vals in result.dimensions.items()
    ]


def render_dimensions_bar(result: BriefingResult):
    rows = dimension_rows(result)
    long_rows = []
    for row in rows:
        long_rows.append({"Dimenzió": row["Dimenzió"], "Csapat": "KTE", "Érték": row["KTE"]})
        long_rows.append({"Dimenzió": row["Dimenzió"], "Csapat": "ELL", "Érték": row["ELL"]})

    spec = {
        "width": "container",
        "height": 320,
        "data": {"values": long_rows},
        "mark": {"type": "bar", "cornerRadiusTopLeft": 3, "cornerRadiusTopRight": 3},
        "encoding": {
            "x": {"field": "Dimenzió", "type": "nominal", "axis": {"title": None, "labelAngle": -20}},
            "xOffset": {"field": "Csapat"},
            "y": {"field": "Érték", "type": "quantitative", "scale": {"domain": [0, 10]}, "axis": {"title": "Pontszám (1–10)"}},
            "color": {
                "field": "Csapat",
                "type": "nominal",
                "scale": {"domain": ["KTE", "ELL"], "range": ["#5B2C83", "#B7A3C9"]},
                "legend": {"title": "Csapat"},
            },
            "tooltip": [
                {"field": "Dimenzió"},
                {"field": "Csapat"},
                {"field": "Érték", "format": ".1f"},
            ],
        },
    }
    st.vega_lite_chart(long_rows, spec, use_container_width=True)


def render_radar_like_chart(result: BriefingResult):
    rows = dimension_rows(result)
    labels = [r["Dimenzió"] for r in rows]
    kte_vals = [r["KTE"] for r in rows]
    ell_vals = [r["ELL"] for r in rows]

    size = 560
    cx, cy = 250, 250
    max_r = 165

    def polygon_points(values: List[float]) -> Tuple[str, List[Tuple[float, float]]]:
        pts = []
        n = len(values)
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
    n = len(labels)

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

        lx = cx + math.cos(ang) * (max_r + 34)
        ly = cy + math.sin(ang) * (max_r + 34)
        anchor = "middle"
        if lx < cx - 20:
            anchor = "end"
        elif lx > cx + 20:
            anchor = "start"

        label_svg.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="13" text-anchor="{anchor}" fill="#2F1D4A" font-weight="600">{label}</text>'
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
      <polygon points="{ell_poly}" fill="rgba(183,163,201,0.32)" stroke="#9D8ABA" stroke-width="3" stroke-dasharray="6 4" />
      <polygon points="{kte_poly}" fill="rgba(91,44,131,0.20)" stroke="#5B2C83" stroke-width="3.2" />
      {ell_circles}
      {kte_circles}
      {''.join(label_svg)}
      <circle cx="410" cy="495" r="7" fill="#5B2C83" />
      <text x="425" y="500" font-size="14" fill="#2F1D4A">KTE</text>
      <circle cx="470" cy="495" r="7" fill="#B7A3C9" stroke="#5B2C83" stroke-width="1" />
      <text x="485" y="500" font-size="14" fill="#2F1D4A">ELL</text>
    </svg>
    """
    components.html(svg, height=580)


st.title("Taktikai meccs-briefing generátor v1")
st.sidebar.caption("D/P = Direkt / Presszing")

step = st.sidebar.radio("Lépés", ["1. Input", "2. Elemzés", "3. Edzői nézet", "4. Exportálás"], index=0)

if "result" not in st.session_state:
    st.session_state.result = None
if "opponent_name" not in st.session_state:
    st.session_state.opponent_name = ""
if "selected_plan_a" not in st.session_state:
    st.session_state.selected_plan_a = "GAT"
if "selected_plan_b" not in st.session_state:
    st.session_state.selected_plan_b = "BAT"
if "selected_split" not in st.session_state:
    st.session_state.selected_split = 60

if step == "1. Input":
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Meccs beállítások")
        opponent_name = st.text_input("Ellenfél neve", value=st.session_state.opponent_name)
        st.date_input("Mérkőzés dátuma")
        st.text_input("Versenysorozat", value="NB II")
        st.text_area("Opcionális megjegyzések")
        st.session_state.opponent_name = opponent_name

    with col2:
        st.subheader("Fájlok feltöltése")
        files = UploadedFiles(
            team_match_stats=st.file_uploader("KTE meccsstatisztika (.xlsx)", type=["xlsx"], key="tm"),
            team_player_stats=st.file_uploader("KTE játékosstatisztika (.xlsx)", type=["xlsx"], key="tp"),
            team_reference_report=st.file_uploader("KTE referencia report (.pdf)", type=["pdf"], key="tr"),
            opp_match_stats=st.file_uploader("Ellenfél meccsstatisztika (.xlsx)", type=["xlsx"], key="om"),
            opp_player_stats=st.file_uploader("Ellenfél játékosstatisztika (.xlsx)", type=["xlsx"], key="op"),
            opp_report_1=st.file_uploader("Ellenfél report 1 (.pdf)", type=["pdf"], key="or1"),
            opp_report_2=st.file_uploader("Ellenfél report 2 (.pdf)", type=["pdf"], key="or2"),
            opp_report_3=st.file_uploader("Ellenfél report 3 (.pdf, opcionális)", type=["pdf"], key="or3"),
            template_ppt=st.file_uploader("Template PPT (.pptx)", type=["pptx"], key="ppt"),
        )
        st.session_state["uploaded_files"] = files

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Inputok ellenőrzése"):
            if files.required_ok():
                st.success("Minden kötelező input rendben van.")
            else:
                st.error("Hiányzik legalább egy kötelező fájl.")
    with c2:
        if st.button("Briefing generálása"):
            if not opponent_name.strip():
                st.error("Adj meg ellenfélnevet.")
            elif not files.required_ok():
                st.error("A generáláshoz minden kötelező fájl szükséges.")
            else:
                with st.spinner("Excel és PDF feldolgozása, dimenziók számítása..."):
                    st.session_state.result = run_briefing_engine(opponent_name, files)
                st.session_state.selected_plan_a = st.session_state.result.plan_a
                st.session_state.selected_plan_b = st.session_state.result.plan_b
                try:
                    st.session_state.selected_split = int(st.session_state.result.split.split("/")[0])
                except Exception:
                    st.session_state.selected_split = 60
                st.success("A briefing elkészült. Menj az Elemzés fülre.")

elif step == "2. Elemzés":
    st.subheader("Elemzés / Taktikai motor")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget az Input képernyőn.")
    else:
        if result.team_metric_count < 8 or result.opp_metric_count < 8:
            st.warning(
                f"Kevés nyers metrika került beolvasásra. KTE: {result.team_metric_count}, "
                f"Ellenfél: {result.opp_metric_count}. Ilyenkor a score-ok bizonytalanok lehetnek."
            )

        top1, top2, top3 = st.columns([1, 1, 1])
        top1.metric("Ajánlott Plan A", st.session_state.selected_plan_a)
        top2.metric("Ajánlott Plan B", st.session_state.selected_plan_b)
        top3.metric("Arány", f"{st.session_state.selected_split}/{100 - st.session_state.selected_split}")

        st.markdown("### 9 taktikai opció – stratégiai térkép")
        render_strategy_map(st.session_state.selected_plan_a, st.session_state.selected_plan_b)

        pick1, pick2, pick3 = st.columns([1, 1, 1])
        with pick1:
            st.session_state.selected_plan_a = st.selectbox(
                "Plan A",
                options=list(STRATEGY_PALETTE.keys()),
                index=list(STRATEGY_PALETTE.keys()).index(st.session_state.selected_plan_a),
                format_func=lambda x: f"{x} – {STRATEGY_PALETTE[x]['name']}",
            )
        with pick2:
            available_plan_b = [k for k in STRATEGY_PALETTE.keys() if k != st.session_state.selected_plan_a]
            current_b = st.session_state.selected_plan_b if st.session_state.selected_plan_b in available_plan_b else available_plan_b[0]
            st.session_state.selected_plan_b = st.selectbox(
                "Plan B",
                options=available_plan_b,
                index=available_plan_b.index(current_b),
                format_func=lambda x: f"{x} – {STRATEGY_PALETTE[x]['name']}",
            )
        with pick3:
            st.session_state.selected_split = st.slider(
                "Plan A arány a meccsmodellben (%)",
                min_value=50,
                max_value=70,
                value=st.session_state.selected_split,
            )

        st.info("Az arány nem szavazás. A Plan A az alap játékmodell, a Plan B az alkalmazkodó viselkedés. A százalék a két modell várható meccsbeli megoszlását mutatja.")

        with st.expander("A 9 taktikai opció táblázata", expanded=False):
            st.table(strategy_palette_rows())

        c1, c2 = st.columns([1.25, 1])
        with c1:
            st.markdown("### 7 dimenzió")
            st.dataframe(dimension_rows(result), use_container_width=True)
            st.markdown("### 7 dimenzió – oszlopdiagram")
            render_dimensions_bar(result)
            st.markdown("### 7 dimenzió – pókhálódiagram")
            render_radar_like_chart(result)

        with c2:
            st.markdown("### Gyors briefing vázlat")
            st.text_area("Ellenfél profil", value=result.opponent_profile, height=90)
            st.text_area("Saját állapot", value=result.own_state, height=90)
            st.text_area("3 kulcs", value="\n".join(result.three_keys), height=110)
            st.text_area("Kockázatok", value="\n".join(result.risks), height=100)
            st.text_area("Konklúzió", value="\n".join(result.conclusion), height=120)

            with st.expander("Kinyert nyers metrikák – KTE", expanded=False):
                st.json(result.debug_metrics_team)
            with st.expander("Kinyert nyers metrikák – Ellenfél", expanded=False):
                st.json(result.debug_metrics_opp)

elif step == "3. Edzői nézet":
    st.subheader("Edzői nézet")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget.")
    else:
        st.markdown("### 9 taktikai opció – stratégiai térkép")
        render_strategy_map(st.session_state.selected_plan_a, st.session_state.selected_plan_b)

        with st.expander("A 9 taktikai opció táblázata", expanded=False):
            st.table(strategy_palette_rows())

        tab1, tab2, tab3 = st.tabs(["Onepager", "Taktikai overview", "Nyomtatási nézet"])

        with tab1:
            st.markdown(f"## KTE vs {st.session_state.opponent_name}")

            v1, v2 = st.columns([1, 1])
            with v1:
                st.markdown("### Pókhálódiagram")
                render_radar_like_chart(result)
            with v2:
                st.markdown("### 7 dimenzió – oszlopdiagram")
                render_dimensions_bar(result)

            st.markdown(
                f"**Plan A:** {st.session_state.selected_plan_a} – {STRATEGY_PALETTE[st.session_state.selected_plan_a]['name']} | "
                f"**Plan B:** {st.session_state.selected_plan_b} – {STRATEGY_PALETTE[st.session_state.selected_plan_b]['name']} | "
                f"**Arány:** {st.session_state.selected_split}/{100 - st.session_state.selected_split}"
            )

            st.info("Az arány azt mutatja, hogy a mérkőzés várhatóan milyen megoszlásban követi a két modellt. A Plan A az alapjáték, a Plan B az alkalmazkodó viselkedés.")

            st.markdown(f"**Ellenfél profil:** {result.opponent_profile}")
            st.markdown(f"**Saját állapot:** {result.own_state}")

            st.markdown("**3 kulcs**")
            for item in result.three_keys:
                st.write(f"- {item}")

            st.markdown("**Konklúzió**")
            for item in result.conclusion:
                st.write(f"- {item}")

        with tab2:
            st.markdown("### Kockázatok")
            for item in result.risks:
                st.write(f"- {item}")

            st.markdown("### Várható meccsdinamika")
            for item in result.match_dynamics:
                st.write(f"- {item}")

        with tab3:
            st.info("A következő iterációban ide kerül a nyomtatható, fekvő A4-es nézet és a PPT-export.")

elif step == "4. Exportálás":
    st.subheader("Exportálás")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget.")
    else:
        st.success("Az export modul helye kész. Következő körben ide kerül a PPT/PDF generálás.")
        st.markdown(
            f"**Jóváhagyott stratégia:** {st.session_state.selected_plan_a} / {st.session_state.selected_plan_b} "
            f"({st.session_state.selected_split}/{100 - st.session_state.selected_split})"
        )
        export_name = f"KTE_vs_{st.session_state.opponent_name.strip().replace(' ', '_') or 'Opponent'}_briefing"
        st.code(f"{export_name}.pptx")
        st.code(f"{export_name}.pdf")
        st.button("PPT export")
        st.button("PDF export")
        st.button("Nyomtatás")
