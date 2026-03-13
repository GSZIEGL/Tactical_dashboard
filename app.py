import streamlit as st
import pandas as pd
import re
from typing import Dict

st.set_page_config(page_title="Tactical Briefing Engine", layout="wide")

# ----------------------------------------------------
# UTIL
# ----------------------------------------------------

def safe_float(x):
    try:
        return float(str(x).replace(",", ".").replace("%", "").strip())
    except:
        return 0


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


# ----------------------------------------------------
# ALIAS LISTA
# ----------------------------------------------------

METRIC_ALIASES = {

"pressing_success_pct":[

"pressing",
"pressing successful"

],

"passes_accurate_pct":[

"passes accurate",
"passes / accurate"

],

"entries_box":[

"entrances to the opponent's box",
"entrances to opponents box"

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

]

}


# ----------------------------------------------------
# LABEL KERESÉS
# ----------------------------------------------------

def find_label_position(df, labels):

    for r in range(df.shape[0]):

        for c in range(df.shape[1]):

            txt = str(df.iat[r,c]).lower()

            for label in labels:

                if label in txt:

                    return r,c

    return None


def read_numeric_right(df,r,c):

    for col in range(c+1, df.shape[1]):

        val=df.iat[r,col]

        num=numeric_from_cell(val)

        if num is not None:

            return num

    return 0


def read_percent_right(df,r,c):

    for col in range(c+1, df.shape[1]):

        val=df.iat[r,col]

        pct=percent_from_cell(val)

        if pct is not None:

            return pct

        num=numeric_from_cell(val)

        if num and num<=100:

            return num

    return 0


# ----------------------------------------------------
# PARSER
# ----------------------------------------------------

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

                metrics[key]=read_percent_right(df,r,c)

            else:

                metrics[key]=read_numeric_right(df,r,c)

    return metrics


# ----------------------------------------------------
# DIMENZIÓ SZÁMÍTÁS
# ----------------------------------------------------

def clamp(x):

    return max(1,min(10,x))


def normalize(v,a,b):

    if v==0:

        return 5

    return clamp(1+9*(v-a)/(b-a))


def score(metrics):

    return{

"Letámadás":round(normalize(metrics.get("pressing_success_pct",0),30,70),1),

"Labdakihozatal":round(normalize(metrics.get("passes_accurate_pct",0),60,90),1),

"Átmenetek":round(normalize(metrics.get("entries_box",0),5,30),1),

"Támadó játék":round(normalize(metrics.get("key_passes",0),1,15),1),

"Pontrúgások":round(normalize(metrics.get("corners",0),1,10),1),

"Labdabirtoklás":round(normalize(metrics.get("possession_pct",0),40,65),1),

"Lövések":round(normalize(metrics.get("shots",0),4,20),1)

}


# ----------------------------------------------------
# ENGINE
# ----------------------------------------------------

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


# ----------------------------------------------------
# UI
# ----------------------------------------------------

st.title("Tactical Briefing Engine")

step=st.sidebar.radio(

"Lépés",

["Input","Debug"]

)

# ----------------------------------------------------
# INPUT
# ----------------------------------------------------

if step=="Input":

    st.header("Excel feltöltés")

    kte=st.file_uploader("KTE Excel",type=["xlsx"])

    opp=st.file_uploader("Opponent Excel",type=["xlsx"])

    if kte and opp:

        dims,tm,om=run_engine(kte,opp)

        st.subheader("Dimenziók")

        st.dataframe(dims)


# ----------------------------------------------------
# DEBUG
# ----------------------------------------------------

if step=="Debug":

    kte=st.file_uploader("KTE Excel",type=["xlsx"],key="d1")

    opp=st.file_uploader("Opponent Excel",type=["xlsx"],key="d2")


    if kte:

        st.subheader("KTE parser")

        st.json(parse_excel_metrics(kte.getvalue()))

        xls=pd.ExcelFile(kte)

        for sheet in xls.sheet_names:

            df=pd.read_excel(kte,sheet_name=sheet,header=None)

            st.write("KTE sheet:",sheet)

            st.write(df.iloc[:,0].astype(str).tolist()[:80])


    if opp:

        st.subheader("Opponent parser")

        st.json(parse_excel_metrics(opp.getvalue()))

        xls=pd.ExcelFile(opp)

        for sheet in xls.sheet_names:

            df=pd.read_excel(opp,sheet_name=sheet,header=None)

            st.write("Opponent sheet:",sheet)

            st.write(df.iloc[:,0].astype(str).tolist()[:80])
