import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Parks Distribution and Conditions in Lebanon", layout="wide")
st.title("Parks Distribution and Conditions in Lebanon")
st.caption("Data: Public_spaces-Lebanon-2023 (PKGCube). CSV is read from the same folder as this app.")
st.markdown("<style>div.block-container{padding-top:1rem;padding-bottom:1rem}</style>", unsafe_allow_html=True)

# ── Load & prep data ─────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    data_path = Path(__file__).parent / "Parks Data.csv"
    if not data_path.exists():
        st.error(f"CSV not found at: {data_path}. Ensure the file is named exactly 'Parks Data.csv'.")
        st.stop()

    df = pd.read_csv(data_path)
    df.columns = [c.strip() for c in df.columns]  # trim accidental spaces

    # Normalize headers (after trimming)
    df = df.rename(columns={
        "State of public parks - bad": "parks_bad",
        "State of public parks - acceptable": "parks_acceptable",
        "State of public parks - good": "parks_good",
        "State of the lighting network - bad": "light_bad",
        "State of the lighting network - acceptable": "light_acceptable",
        "State of the lighting network - good": "light_good",
        "Existence of public parks - exists": "parks_exist",
    })

    if "refArea" not in df.columns:
        st.error("Column 'refArea' is required to derive administrative areas.")
        st.stop()

    # Human-readable area from refArea
    def area_label(u):
        if not isinstance(u, str): return u
        return u.rsplit("/", 1)[-1].replace("_", " ")

    df["Area"] = df["refArea"].apply(area_label)

    # Administrative level
    def level_from_area(s):
        if isinstance(s, str):
            if "Governorate" in s: return "Governorate"
            if "District" in s:    return "District"
        return "Other"
    df["Level"] = df["Area"].apply(level_from_area)

    # Shorter area label for display
    def area_core(s):
        if not isinstance(s, str): return s
        return (s.replace("Governorate", "")
                 .replace("District, Lebanon", "")
                 .replace("District", "")
                 .strip())
    df["AreaShort"] = df["Area"].apply(area_core)

    # Cast flags to ints
    for c in ["parks_bad","parks_acceptable","parks_good",
              "light_bad","light_acceptable","light_good","parks_exist"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    # One label for park & lighting condition (for notes)
    def tri_label(row, bad, ok, good):
        vals = {"Bad": row.get(bad, 0), "Acceptable": row.get(ok, 0), "Good": row.get(good, 0)}
        label = max(vals, key=vals.get)
        return label if vals[label] > 0 else "Unknown"

    df["park_condition"] = (
        df.apply(lambda r: tri_label(r, "parks_bad", "parks_acceptable", "parks_good"), axis=1)
        if {"parks_bad","parks_acceptable","parks_good"}.issubset(df.columns)
        else "Unknown"
    )
    df["lighting_condition"] = (
        df.apply(lambda r: tri_label(r, "light_bad", "light_acceptable", "light_good"), axis=1)
        if {"light_bad","light_acceptable","light_good"}.issubset(df.columns)
        else "Unknown"
    )

    return df

df = load_data()

# ── Build Town→District/Governorate mapping (for ranking chart) ──────────────
@st.cache_data
def build_geo_mappings(df: pd.DataFrame):
    # Infer each Town's district and governorate from dataset
    dist_series = (
        df[(df["Level"] == "District") & df["AreaShort"].notna() & df["AreaShort"].astype(str).ne("")]
        .dropna(subset=["Town"])
        .groupby("Town")["AreaShort"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0])
    )
    gov_series = (
        df[(df["Level"] == "Governorate") & df["AreaShort"].notna() & df["AreaShort"].astype(str).ne("")]
        .dropna(subset=["Town"])
        .groupby("Town")["AreaShort"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0])
    )

    # parks_exist per Town (max across duplicates)
    px_series = (
        df.dropna(subset=["Town"])
          .groupby("Town")["parks_exist"]
          .max()
          .astype(int)
    )

    towns = pd.DataFrame({"Town": sorted(set(dist_series.index) | set(gov_series.index))})
    towns["District"] = towns["Town"].map(dist_series.to_dict())
    towns["Governorate"] = towns["Town"].map(gov_series.to_dict())
    towns["parks_exist"] = towns["Town"].map(px_series.to_dict()).fillna(0).astype(int)

    all_governorates = sorted(df.loc[df["Level"] == "Governorate", "AreaShort"].dropna().astype(str).unique())
    return towns, all_governorates

towns_map, ALL_GOVS = build_geo_mappings(df)

# ── Sidebar (clean; no Top N slider) ─────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    level = st.radio("Administrative level", ["Governorate", "District"], horizontal=True)
    areas_all = sorted(df.loc[df["Level"] == level, "Area"].dropna().unique())
    sel_areas = st.multiselect("Areas", areas_all, default=areas_all)
    norm_pct = st.toggle("Normalize park condition bars to %", value=False)

# Filtered data for second chart (park conditions)
fdf = df[(df["Level"] == level) & (df["Area"].isin(sel_areas))].copy()

# ── KPIs ─────────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("Towns (filtered)", f"{len(fdf):,}")
k2.metric("Towns with a park", f"{100 * fdf['parks_exist'].mean():.1f}%" if len(fdf) else "—")
k3.metric("Areas selected", f"{len(sel_areas)}")
k4.metric("Level", level)
st.markdown("---")

def safe_pct(n, d):  # helper
    return 0.0 if d == 0 else round(100.0 * n / d, 1)

# ═════════════════════════════════════════════════════════════════════════════
# CHART 1 — Governorates by Park Existence (%)
#   - If Level=Governorate, respects selected governorates
#   - If Level=District, it still shows all governorates (no district limiter)
# ═════════════════════════════════════════════════════════════════════════════
if "Town" in df.columns and not towns_map.empty:
    tdf = towns_map.copy()

    if level == "Governorate":
        # Map selected governorate Areas → AreaShort
        sel_gov = set(
            df.loc[(df["Level"] == "Governorate") & (df["Area"].isin(sel_areas)), "AreaShort"]
              .dropna().astype(str).unique()
        )
        if sel_gov:
            tdf = tdf[tdf["Governorate"].isin(sel_gov)]

    gov = (
        tdf.dropna(subset=["Governorate"])
           .groupby("Governorate", as_index=False)
           .agg(towns=("Town", "count"), parks=("parks_exist", "sum"))
    )
    if gov.empty:
        st.info("No data to compute governorate rankings with current settings.")
    else:
        gov["parks_pct"] = (gov["parks"] / gov["towns"] * 100).round(1)
        gov_sorted = gov.sort_values(["parks_pct", "towns"], ascending=[False, False])

        # Order so the highest is at the top (horizontal bar)
        y_order = list(gov_sorted["Governorate"])[::-1]

        fig_rank = px.bar(
            gov_sorted,
            x="parks_pct",
            y="Governorate",
            orientation="h",
            text="parks_pct",
            labels={"parks_pct": "% towns with parks", "Governorate": "Governorate"},
            title="Governorates by park existence (%)",
        )
        fig_rank.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig_rank.update_layout(
            xaxis=dict(range=[0, 100]),
            yaxis=dict(categoryorder="array", categoryarray=y_order),
            height=520
        )
        st.plotly_chart(fig_rank, use_container_width=True)

        # Notes & Insights (Ranking)
        with st.expander("Notes & Insights — Governorate Ranking", expanded=False):
            best = gov_sorted.iloc[0]
            worst = gov_sorted.iloc[-1]
            st.markdown(f"- **Highest park existence:** **{best['Governorate']}** — {best['parks_pct']:.1f}% of towns ({int(best['parks'])}/{int(best['towns'])}).")
            st.markdown(f"- **Lowest park existence:** **{worst['Governorate']}** — {worst['parks_pct']:.1f}% of towns ({int(worst['parks'])}/{int(worst['towns'])}).")
else:
    st.info("Town column not found; cannot compute governorate ranking from towns.")

st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# CHART 2 — Public Park Condition by Selected Areas (stacked bar)
# ═════════════════════════════════════════════════════════════════════════════
parks_cols = [c for c in ["parks_bad","parks_acceptable","parks_good"] if c in fdf.columns]
if parks_cols and not fdf.empty:
    g = fdf.groupby("Area", as_index=False)[parks_cols].sum()
    long = g.melt(id_vars="Area", var_name="state", value_name="count")
    long["state"] = long["state"].map({"parks_bad":"Bad","parks_acceptable":"Acceptable","parks_good":"Good"})

    if norm_pct:
        denom = long.groupby("Area")["count"].transform("sum").replace(0, 1)
        long["value"] = (long["count"] / denom * 100).round(2)
        ycol, ytitle = "value", "Share (%)"
    else:
        ycol, ytitle = "count", "Count (towns)"

    area_order = long.groupby("Area")[ycol].sum().sort_values(ascending=False).index.tolist()
    long["Area"] = pd.Categorical(long["Area"], categories=area_order, ordered=True)
    long = long.sort_values("Area")

    fig1 = px.bar(
        long, x="Area", y=ycol, color="state",
        labels={"Area": level, ycol: ytitle, "state": "Condition"},
        title=f"Public park condition by {level.lower()}",
    )
    fig1.update_layout(barmode="stack", xaxis_tickangle=-30, legend_title_text="Condition", height=520)
    st.plotly_chart(fig1, use_container_width=True)

    with st.expander("Notes & Insights — Public Park Condition", expanded=False):
        totals = g.assign(total=g[parks_cols].sum(axis=1))
        def sp(a, b): return 0 if b == 0 else round(100*a/b, 1)
        if not g.empty:
            gi = (g["parks_good"] / totals["total"].replace(0, 1)).idxmax()
            bi = (g["parks_bad"]  / totals["total"].replace(0, 1)).idxmax()
            st.markdown(f"- **Highest share Good:** **{g.loc[gi,'Area']}** (~{sp(int(g.loc[gi,'parks_good']), int(totals.loc[gi,'total']))}%).")
            st.markdown(f"- **Highest share Bad:** **{g.loc[bi,'Area']}** (~{sp(int(g.loc[bi,'parks_bad']),  int(totals.loc[bi,'total']))}%).")
        st.markdown(f"- View: **{'% composition' if norm_pct else 'absolute counts'}**.")
else:
    st.info("Park condition columns not found.")
