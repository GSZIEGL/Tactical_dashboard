import streamlit as st
from dataclasses import dataclass
from typing import Dict, Optional, List

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
    three_keys: List[str]
    risks: List[str]
    match_dynamics: List[str]
    conclusion: List[str]


# ---------- Tactical palette ----------
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


# ---------- Helpers ----------
def strategy_palette_rows() -> List[dict]:
    return [
        {"Code": k, "Strategy": v["name"], "Block height": v["block"], "Style": v["style"]}
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
        2: "Direkt / Presszing",
        3: "Vegyes",
        4: "Kiegy. kontroll",
        5: "Kontroll",
        6: "Agresszív",
    }
    block_label = {
        1: "Mély blokk",
        2: "Alacsony-közép blokk",
        3: "Közép blokk",
        4: "Közép-magas blokk",
        5: "Magas blokk",
    }

    rows = []
    for code, data in STRATEGY_PALETTE.items():
        x = style_map.get(data["style"], 3)
        y = block_map.get(data["block"], 3)
        rows.append(
            {
                "x": x,
                "y": y,
                "code": code,
                "strategy": data["name"],
                "style_label": style_label[x],
                "block_label": block_label[y],
                "marker_size": 260 if code in [selected_a, selected_b] else 170,
                "marker_type": "Plan A" if code == selected_a else "Plan B" if code == selected_b else "Palette",
            }
        )
    return rows


def render_strategy_map(selected_a: Optional[str] = None, selected_b: Optional[str] = None):
    rows = strategy_scatter_data(selected_a, selected_b)
    spec = {
        "width": "container",
        "height": 380,
        "data": {"values": rows},
        "layer": [
            {
                "mark": {"type": "circle", "opacity": 0.95, "stroke": "#5B2C83", "strokeWidth": 2},
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
                    "size": {"field": "marker_size", "type": "quantitative", "legend": None},
                    "color": {
                        "field": "marker_type",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Palette", "Plan A", "Plan B"],
                            "range": ["#FFFFFF", "#F3D34A", "#63D2C6"],
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
            },
            {
                "mark": {"type": "text", "dy": 1, "fontSize": 13, "fontWeight": "bold", "color": "#5B2C83"},
                "encoding": {
                    "x": {"field": "x", "type": "quantitative"},
                    "y": {"field": "y", "type": "quantitative"},
                    "text": {"field": "code"},
                },
            },
        ],
        "config": {"view": {"stroke": "#D9D9D9"}},
    }
    st.vega_lite_chart(rows, spec, use_container_width=True)


def dimension_rows(result: BriefingResult) -> List[dict]:
    rows = []
    for dim, vals in result.dimensions.items():
        rows.append({
            "Dimenzió": dim,
            "KTE": float(vals["KTE"]),
            "ELL": float(vals["ELL"]),
            "Edge": float(vals["Edge"]),
        })
    return rows


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
            "y": {"field": "Érték", "type": "quantitative", "scale": {"domain": [0, 10]}, "axis": {"title": "Score (1–10)"}},
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
    radar_rows = []
    for row in rows:
        radar_rows.append({"Dimenzió": row["Dimenzió"], "Csapat": "KTE", "Érték": row["KTE"]})
        radar_rows.append({"Dimenzió": row["Dimenzió"], "Csapat": "ELL", "Érték": row["ELL"]})

    spec = {
        "width": 420,
        "height": 420,
        "data": {"values": radar_rows},
        "layer": [
            {
                "mark": {"type": "line", "point": True},
                "encoding": {
                    "theta": {"field": "Dimenzió", "type": "nominal"},
                    "radius": {"field": "Érték", "type": "quantitative", "scale": {"domain": [0, 10]}},
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
        ],
    }
    st.vega_lite_chart(radar_rows, spec, use_container_width=True)


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
if "selected_plan_a" not in st.session_state:
    st.session_state.selected_plan_a = "GAT"
if "selected_plan_b" not in st.session_state:
    st.session_state.selected_plan_b = "BAT"
if "selected_split" not in st.session_state:
    st.session_state.selected_split = 60

if step == "1. Input":
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Match setup")
        opponent_name = st.text_input("Opponent name", value=st.session_state.opponent_name)
        st.date_input("Match date")
        st.text_input("Competition", value="NB II")
        st.text_area("Optional notes")
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
                st.session_state.selected_plan_a = st.session_state.result.plan_a
                st.session_state.selected_plan_b = st.session_state.result.plan_b
                try:
                    st.session_state.selected_split = int(st.session_state.result.split.split("/")[0])
                except Exception:
                    st.session_state.selected_split = 60
                st.success("A briefing draft elkészült. Menj a Review fülre.")

elif step == "2. Review":
    st.subheader("Review / Tactical Engine")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget az Input képernyőn.")
    else:
        top1, top2, top3 = st.columns([1, 1, 1])
        top1.metric("Ajánlott Plan A", st.session_state.selected_plan_a)
        top2.metric("Ajánlott Plan B", st.session_state.selected_plan_b)
        top3.metric("Megoszlás", f"{st.session_state.selected_split}/{100 - st.session_state.selected_split}")

        st.markdown("### 9 taktikai opció – 2D stratégiai térkép")
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
            st.session_state.selected_split = st.slider("Plan A súly (%)", min_value=50, max_value=70, value=st.session_state.selected_split)

        with st.expander("A 9 taktikai opció táblázata", expanded=False):
            st.table(strategy_palette_rows())

        col1, col2 = st.columns([1.2, 1])
        with col1:
            st.markdown("### 7 dimenzió")
            rows = []
            for dim, vals in result.dimensions.items():
                rows.append({"Dimenzió": dim, **vals})
            st.dataframe(rows, use_container_width=True)
            st.markdown("### 7 dimenzió – oszlopdiagram")
            render_dimensions_bar(result)
            st.markdown("### 7 dimenzió – pókháló diagram")
            render_radar_like_chart(result)

        with col2:
            st.markdown("### Gyors briefing draft")
            st.text_area("Opponent profile", value=result.opponent_profile, height=90)
            st.text_area("Own state", value=result.own_state, height=90)
            st.text_area("3 kulcs", value="\\n".join(result.three_keys), height=100)
            st.text_area("Kockázatok", value="
".join(result.risks), height=100)
            st.text_area("Konklúzió", value="
".join(result.conclusion), height=120)

elif step == "3. Output":
    st.subheader("Coach View")
    result = st.session_state.result
    if result is None:
        st.info("Előbb generálj briefinget.")
    else:
        st.markdown("### 9 taktikai opció – 2D stratégiai térkép")
        render_strategy_map(st.session_state.selected_plan_a, st.session_state.selected_plan_b)

        with st.expander("A 9 taktikai opció táblázata", expanded=False):
            st.table(strategy_palette_rows())

        tab1, tab2, tab3 = st.tabs(["Onepager", "Tactical overview", "Print preview"])

        with tab1:
            st.markdown(f"## KTE vs {st.session_state.opponent_name}")
            viz1, viz2 = st.columns([1, 1])
            with viz1:
                st.markdown("### Pókháló diagram")
                render_radar_like_chart(result)
            with viz2:
                st.markdown("### 7 dimenzió – oszlopdiagram")
                render_dimensions_bar(result)
            st.markdown(
                f"**Plan A:** {st.session_state.selected_plan_a} – {STRATEGY_PALETTE[st.session_state.selected_plan_a]['name']} | "
                f"**Plan B:** {st.session_state.selected_plan_b} – {STRATEGY_PALETTE[st.session_state.selected_plan_b]['name']} | "
                f"**Arány:** {st.session_state.selected_split}/{100 - st.session_state.selected_split}"
            )
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
        st.markdown(
            f"**Jóváhagyott stratégia:** {st.session_state.selected_plan_a} / {st.session_state.selected_plan_b} "
            f"({st.session_state.selected_split}/{100 - st.session_state.selected_split})"
        )
        export_name = f"KTE_vs_{st.session_state.opponent_name.strip().replace(' ', '_') or 'Opponent'}_briefing"
        st.code(f"{export_name}.pptx")
        st.code(f"{export_name}.pdf")
        st.button("Export PPT")
        st.button("Export PDF")
        st.button("Print now")
