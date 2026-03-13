import streamlit as st
import pandas as pd
import re
import math
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

st.set_page_config(page_title="Tactical Briefing Engine", layout="wide")

# ---------------------------------------------------------
# UTIL
# ---------------------------------------------------------

def safe_float(x, default=0.0):
    try:
        return float(str(x).replace(",", ".").replace("%", "").strip())
    except:
        return default


def numeric_from_cell(v):
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(?:[.,]\d+)?%?", s):
        return safe_float(s)
    return None


def percent_from_cell(v):
    s = str(v)
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*%", s)
    if m:
        return safe_float(m.group(1))
    return None


def ratio_from_cell(v):
    s = str(v)
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*/\s*(-?\d+(?:[.,]\d+)?)", s)
    if m:
        return safe_float(m.group(1)), safe_float(m.group(2))
    return None


# ---------------------------------------------------------
# METRIC ALIASES
# ---------------------------------------------------------

METRIC_ALIASES = {

"ppda":["ppda"],

"pressing_success_pct":[
"pressing / successful",
"pressing successful",
"pressing"
],

"passes_accurate_pct":[
"passes / accurate",
"passes accurate"
],

"entries_box":[
"entrances to the opponent's box",
"entrances to the opponents box"
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

"xg":[
"xg"
],

"shots":[
"shots"
]

}


# ---------------------------------------------------------
# PARSER
# ---------------------------------------------------------

def find_label_position(df, labels):

    for r in range(df.shape[0]):
        for c in range(df.shape[1]):

            txt=str(df.iat[r,c]).lower()

            for label in labels:

                if label in txt:
                    return r,c

    return None


def first_numeric_right(df,r,c):

    for col in range(c+1,df.shape[1]):

        val=df.iat[r,col]

        num=numeric_from_cell(val)

        if num is not None:
            return num

        ratio=ratio_from_cell(val)

        if ratio:
            return ratio[0]

    return 0


def pct_right(df,r,c):

    for col in range(c+1,df.shape[1]):

        val=df.iat[r,col]

        pct=percent_from_cell(val)

        if pct is not None:
            return pct

        num=numeric_from_cell(val)

        if num and num<=100:
            return num

    return 0


@st.cache_data
def parse_excel_metrics(file_bytes):

    metrics={}

    xls=pd.ExcelFile(file_bytes)

    for sheet in xls.sheet_names:

        df=pd.read_excel(file_bytes,sheet_name=sheet,header=None)

        for key,labels in METRIC_ALIASES.items():

            if key in metrics:
                continue

            pos=find_label_position(df,labels)

            if not pos:
                continue

            r,c=pos

            if "pct" in key:
                metrics[key]=pct_right(df,r,c)

            else:
                metrics[key]=first_numeric_right(df,r,c)

    return metrics


# ---------------------------------------------------------
# DIMENSIONS
# ---------------------------------------------------------

def clamp(x):
    return max(1,min(10,x))


def score(metrics):

    def n(v,a,b):
        if v==0:
            return 5
        return clamp(1+9*(v-a)/(b-a))

    return{

"Letámadás":round(n(metrics.get("pressing_success_pct",0),30,70),1),

"Labdakihozatal":round(n(metrics.get("passes_accurate_pct",0),60,90),1),

"Átmenetek":round(n(metrics.get("entries_box",0),5,30),1),

"Támadó játék":round(n(metrics.get("key_passes",0),1,15),1),

"Védekezési stabilitás":round(n(metrics.get("shots",0),4,20),1),

"Pontrúgások":round(n(metrics.get("corners",0),1,12),1),

"Fizikai profil":round(n(metrics.get("ppda",0),3,12),1)

}


# ---------------------------------------------------------
# STRATEGY
# ---------------------------------------------------------

STRATEGY_PALETTE={

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


# ---------------------------------------------------------
# ENGINE
# ---------------------------------------------------------

def run_engine(team_file,opp_file):

    team_metrics=parse_excel_metrics(team_file.getvalue())
    opp_metrics=parse_excel_metrics(opp_file.getvalue())

    team_scores=score(team_metrics)
    opp_scores=score(opp_metrics)

    dims={}

    for k in team_scores:

        dims[k]={

"KTE":team_scores[k],
"ELL":opp_scores[k],
"Edge":round(team_scores[k]-opp_scores[k],1)

}

    return dims,team_metrics,opp_metrics


# ---------------------------------------------------------
# UI
# ---------------------------------------------------------

st.title("Tactical Briefing Engine")

step=st.sidebar.radio(

"Lépés",

["Input","Debug"]

)

# ---------------------------------------------------------
# INPUT
# ---------------------------------------------------------

if step=="Input":

    st.header("Feltöltés")

    kte=st.file_uploader("KTE Excel",type=["xlsx"])

    opp=st.file_uploader("Opponent Excel",type=["xlsx"])

    if kte and opp:

        dims,tm,om=run_engine(kte,opp)

        st.subheader("Dimenziók")

        st.dataframe(dims)

# ---------------------------------------------------------
# DEBUG
# ---------------------------------------------------------

if step=="Debug":

    kte=st.file_uploader("KTE Excel",type=["xlsx"],key="d1")

    opp=st.file_uploader("Opponent Excel",type=["xlsx"],key="d2")

    if kte:

        st.subheader("KTE parser")

        st.json(parse_excel_metrics(kte.getvalue()))

    if opp:

        st.subheader("Opponent parser")

        st.json(parse_excel_metrics(opp.getvalue()))
