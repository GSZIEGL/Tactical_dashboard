import streamlit as st
import pandas as pd
import re
import math
import altair as alt
from typing import Dict, Optional, List, Tuple

st.set_page_config(page_title="Tactical Briefing Engine", layout="wide")

# ----------------------------------------------------
# UTIL
# ----------------------------------------------------

def safe_float(x, default=0.0):
    try:
        return float(str(x).replace(",", ".").replace("%", "").strip())
    except:
        return default


def normalize_text(x):
    return str(x).strip().lower()


def parse_percent(x):

    s = str(x)

    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*%", s)

    if m:
        return safe_float(m.group(1))

    return None


def parse_number(x):

    s = str(x)

    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", s):

        return safe_float(s)

    return None


def coerce_value(x):

    pct = parse_percent(x)

    if pct is not None:
        return pct

    num = parse_number(x)

    if num is not None:
        return num

    return x


# ----------------------------------------------------
# METRIC ALIASES
# ----------------------------------------------------

METRIC_ALIASES = {

"pressing_success_pct":[
"pressing",
"successful pressing"
],

"passes_accurate_pct":[
"passes accurate",
"pass accuracy"
],

"entries_box":[
"entrances to the opponent's box",
"box entries"
],

"key_passes":[
"key passes"
],

"corners":[
"corners"
],

"possession_pct":[
"ball possession"
],

"shots":[
"shots"
],

"xg":[
"xg"
]

}


# ----------------------------------------------------
# PARSER
# ----------------------------------------------------

def find_total_row(df):

    for r in range(df.shape[0]):

        if normalize_text(df.iat[r,0]) == "total":

            return r

    return None


def build_headers(df):

    headers = {}

    for c in range(df.shape[1]):

        headers[c] = normalize_text(df.iat[0,c])

    return headers


def find_column(headers, aliases):

    for c,h in headers.items():

        for alias in aliases:

            if alias in h:

                return c

    return None


def parse_main_sheet(df):

    metrics = {}

    total_row = find_total_row(df)

    if total_row is None:

        return metrics

    headers = build_headers(df)

    for key,aliases in METRIC_ALIASES.items():

        col = find_column(headers, aliases)

        if col is None:
            continue

        val = coerce_value(df.iat[total_row,col])

        if isinstance(val,(int,float)):

            metrics[key] = val

    return metrics


@st.cache_data
def parse_excel_metrics(file_bytes):

    metrics = {}

    xls = pd.ExcelFile(file_bytes)

    for sheet in xls.sheet_names:

        df = pd.read_excel(file_bytes, sheet_name=sheet, header=None)

        if "main statistics" in normalize_text(sheet):

            metrics.update(parse_main_sheet(df))

    return metrics


# ----------------------------------------------------
# SCORING
# ----------------------------------------------------

def clamp(x):

    return max(1,min(10,x))


def normalize(v,a,b):

    if v == 0:
        return 5

    return clamp(1 + 9 * (v-a)/(b-a))


def score(metrics):

    return {

"Letámadás":round(normalize(metrics.get("pressing_success_pct",0),25,70),1),

"Labdakihozatal":round(normalize(metrics.get("passes_accurate_pct",0),60,90),1),

"Átmenetek":round(normalize(metrics.get("entries_box",0),5,30),1),

"Támadó játék":round(normalize(metrics.get("key_passes",0),1,15),1),

"Pontrúgások":round(normalize(metrics.get("corners",0),1,10),1),

"Labdabirtoklás":round(normalize(metrics.get("possession_pct",0),40,65),1),

"Lövések":round(normalize(metrics.get("shots",0),4,20),1)

}


# ----------------------------------------------------
# STRATEGY PALETTE
# ----------------------------------------------------

STRATEGY_PALETTE = {

"KON":"Kontra mély blokkból",
"GAT":"Gyors átmenet",
"BAT":"Középső blokk + átmenet",
"KIE":"Kiegyensúlyozott",
"PRS":"Presszing + átmenet",
"MLT":"Magas letámadás",
"DOM":"Dominancia",
"POZ":"Pozíciós támadás",
"LAB":"Labdatartás"

}


# ----------------------------------------------------
# ENGINE
# ----------------------------------------------------

def run_engine(team_file, opp_file):

    team_metrics = parse_excel_metrics(team_file.getvalue())

    opp_metrics = parse_excel_metrics(opp_file.getvalue())

    team_scores = score(team_metrics)

    opp_scores = score(opp_metrics)

    dims = {}

    for k in team_scores:

        dims[k] = {

"KTE":team_scores[k],
"ELL":opp_scores[k],
"Edge":round(team_scores[k]-opp_scores[k],1)

}

    return dims, team_metrics, opp_metrics


# ----------------------------------------------------
# RADAR
# ----------------------------------------------------

def radar_chart(dims):

    categories = list(dims.keys())

    kte = [dims[x]["KTE"] for x in categories]

    opp = [dims[x]["ELL"] for x in categories]

    df = pd.DataFrame({

"dim":categories,
"KTE":kte,
"ELL":opp

})

    df = df.melt("dim", var_name="team", value_name="score")

    chart = alt.Chart(df).mark_line(point=True).encode(

theta="dim:N",
radius="score:Q",
color="team:N"

).properties(height=400)

    st.altair_chart(chart, use_container_width=True)


# ----------------------------------------------------
# BAR
# ----------------------------------------------------

def bar_chart(dims):

    rows=[]

    for k,v in dims.items():

        rows.append({"dim":k,"team":"KTE","score":v["KTE"]})
        rows.append({"dim":k,"team":"ELL","score":v["ELL"]})

    df=pd.DataFrame(rows)

    chart=alt.Chart(df).mark_bar().encode(

x="dim:N",
y="score:Q",
color="team:N",
xOffset="team:N"

)

    st.altair_chart(chart,use_container_width=True)


# ----------------------------------------------------
# UI
# ----------------------------------------------------

st.title("Tactical Briefing Engine")

step = st.sidebar.radio(

"Lépés",

["Input","Review","Debug"]

)


# ----------------------------------------------------
# INPUT
# ----------------------------------------------------

if step=="Input":

    kte = st.file_uploader("KTE Excel",type=["xlsx"])

    opp = st.file_uploader("Opponent Excel",type=["xlsx"])

    if kte and opp:

        dims, tm, om = run_engine(kte,opp)

        st.session_state["dims"] = dims
        st.session_state["team_metrics"] = tm
        st.session_state["opp_metrics"] = om

        st.success("Adatok feldolgozva")


# ----------------------------------------------------
# REVIEW
# ----------------------------------------------------

if step=="Review":

    dims = st.session_state.get("dims")

    if not dims:

        st.warning("Előbb tölts fel adatot")

    else:

        col1,col2 = st.columns(2)

        with col1:

            st.subheader("Pókháló")

            radar_chart(dims)

        with col2:

            st.subheader("Dimenziók")

            bar_chart(dims)

        st.subheader("Stratégiai opciók")

        plan_a = st.selectbox("Plan A",list(STRATEGY_PALETTE.keys()))

        plan_b = st.selectbox("Plan B",list(STRATEGY_PALETTE.keys()))

        split = st.slider("Plan A arány",50,70,60)

        st.write("Plan A:",STRATEGY_PALETTE[plan_a])
        st.write("Plan B:",STRATEGY_PALETTE[plan_b])


# ----------------------------------------------------
# DEBUG
# ----------------------------------------------------

if step=="Debug":

    kte = st.file_uploader("KTE Excel",type=["xlsx"],key="d1")

    if kte:

        st.json(parse_excel_metrics(kte.getvalue()))

        xls = pd.ExcelFile(kte)

        for sheet in xls.sheet_names:

            df = pd.read_excel(kte,sheet_name=sheet)

            st.write(sheet)

            st.dataframe(df.head())
