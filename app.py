import streamlit as st
from dataclasses import dataclass
from typing import Dict, Optional

st.set_page_config(page_title="Tactical Briefing Engine", layout="wide")


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
    three_keys: list[str]
    risks: list[str]
    match_dynamics: list[str]
    conclusion: list[str]


# ---------- Placeholder engine layer ----------
def run_briefing_engine(opponent_name: str) -> BriefingResult:
    """MVP placeholder. Replace with real parsing + scoring engine."""
    return BriefingResult(
        plan_a="GAT",
        plan_b="BAT",
        split="60/40",
        dimensions={
            "Letámadás": {"KTE": 6.4, "ELL": 5.8, "Edge": 0.6},
            "Labdakihozatal": {"KTE": 6.1, "ELL": 5.9, "Edge": 0.2},
            "Átmenetek": {"KTE": 7.2, "ELL": 5.6, "Edge": 1.6},
            "Támadó játék": {"KTE": 5.8, "ELL": 5.7, "Edge": 0.1},
            "Védekezési stabilitás": {"KTE": 5.9, "ELL": 5.5, "Edge": 0.4},
            "Pontrúgások": {"KTE": 5.1, "ELL": 6.0, "Edge": -0.9},
            "Fizikai profil": {"KTE": 6.0, "ELL": 6.4, "Edge": -0.4},
        },
        opponent_profile=f"Felállás: 3-5-2 / 3-4-3 | Erősség: direkt átmenetek, középső zóna párharcok | Veszély: második labdák és korai progresszió ({opponent_name})",
        own_state="Felállás: 3-5-2 | Erősség: átmeneti támadás, mélységi futások | Kockázat: labdavesztés utáni visszarendeződés",
        three_keys=[
            "Presszing mögötti terület támadása",
            "Második labdák kontrollja középen",
            "Gyors oldalváltások és félterületi belépések",
        ],
        risks=[
            "Középső zónás labdavesztés",
            "Második labdák az első kontakt után",
            "Átmeneti védekezés nyitott szerkezetben",
        ],
        match_dynamics=[
            "0–20: intenzív kezdés, sok középső zónás párharc",
            "20–45: kiegyenlített szerkezeti játék",
            "45–70: átmeneti fázis, gyors területváltások",
            "70–90: nyíltabb végjáték",
        ],
        conclusion=[
            "A legjobb illeszkedés a gyors átmeneti játék.",
            "Átmenetekben KTE-előny várható.",
            "A fő kockázat a középső zónás második labdák kezelése.",
            "Plan A: GAT, Plan B: BAT.",
        ],
    )


# ---------- UI ----------
st.title("Tactical Briefing Engine v1")

step = st.sidebar.radio(
    "Lépés",
    ["1. Input", "2. Review", "3. Output", "4. Export"],
    index=0,
)

if "result" not in st.session_state:
    st.session_state.result = None
if "opponent_name" not in st.session_state:
    st.session_state.opponent_name = ""

if step == "1. Input":
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Match setup")
        opponent_name = st.text_input("Opponent name", value=st.session_state.opponent_name)
        match_date = st.date_input("Match date")
        competition = st.text_input("Competition", value="NB II")
        notes = st.text_area("Optional notes")
        st.session_state.opponent_name = opponent_name

    with col2:
        st.subheader("Fájlfeltöltés")
        files = UploadedFiles(
            team_match_stats=st.file_uploader("KTE match stats (.xlsx)", type=["xlsx"], key="tm"),
            team_player_stats=st.file_uploader("KTE player stats (.xlsx)", type=["xlsx"], key="tp"),
            team_reference_report=st.file_uploader("KTE reference report (.pdf)", type=["pdf"], key="tr"),
            opp_match_stats=st.file_uploader("Opponent match stats (.xlsx)", type=["xlsx"], key="om"),
            opp_player_stats=st.file_uploader("Opponent player stats (.xlsx)", type=["xlsx"], key="op"),
            opp_report_1=st.file_uploader("Opponent report 1 (.pdf)", type=["pdf"], key="or1"),
            opp_report_2=st.file_uploader("Opponent report 2 (.pdf)", type=["pdf"], key="or2"),
            opp_report_3=st.file_uploader("Opponent report 3 (.pdf, optional)", type=["pdf"], key="or3"),
            template_ppt=st.file_uploader("Template PPT (.pptx)", type=["pptx"], key="ppt"),
        )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Validate inputs"):
            if files.required_ok():
                st.success("Minden kötelező input bent van.")
            else:
                st.error("Hiányzik legalább egy kötelező fájl.")
    with c2:
        if st.button("Generate briefing"):
            if not opponent_name.strip():
                st.error("Adj meg ellenfélnevet.")
            elif not files.required_ok():
                st.error("A briefing generálásához minden kötelező fájl kell.")
            else:
                st.session_state.result = run_briefing_engine(opponent_name)
                st.success("A briefing draft elkészült. Menj a Review fülre.")

elif step == "2. Review":
    st.subheader("Review / Tactical Engine")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget az Input képernyőn.")
    else:
        top1, top2, top3 = st.columns([1, 1, 1])
        top1.metric("Plan A", result.plan_a)
        top2.metric("Plan B", result.plan_b)
        top3.metric("Megoszlás", result.split)

        col1, col2 = st.columns([1.2, 1])
        with col1:
            st.markdown("### 7 dimenzió")
            rows = []
            for dim, vals in result.dimensions.items():
                rows.append({"Dimenzió": dim, **vals})
            st.dataframe(rows, use_container_width=True)

        with col2:
            st.markdown("### Gyors briefing draft")
            st.text_area("Opponent profile", value=result.opponent_profile, height=90)
            st.text_area("Own state", value=result.own_state, height=90)
            st.text_area("3 kulcs", value="\n".join(result.three_keys), height=100)
            st.text_area("Kockázatok", value="\n".join(result.risks), height=100)
            st.text_area("Konklúzió", value="\n".join(result.conclusion), height=120)

elif step == "3. Output":
    st.subheader("Coach View")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget.")
    else:
        tab1, tab2, tab3 = st.tabs(["Onepager", "Tactical overview", "Print preview"])

        with tab1:
            st.markdown(f"## KTE vs {st.session_state.opponent_name}")
            st.markdown(f"**Plan A:** {result.plan_a} | **Plan B:** {result.plan_b} | **Arány:** {result.split}")
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
            st.info("Itt lesz a nyomtatható, A4 landscape preview a következő iterációban.")

elif step == "4. Export":
    st.subheader("Export")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget.")
    else:
        st.success("Az export motor helye kész. Következő iterációban ide kerül a PPT/PDF generálás.")
        st.button("Export PPT")
        st.button("Export PDF")
        st.button("Print now")
