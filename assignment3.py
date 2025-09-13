import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

# ───────── Page setup ─────────
st.set_page_config(page_title="Parks Distribution and Conditions in Lebanon", layout="wide")
st.title("Parks Distribution and Conditions in Lebanon")
st.caption("Data: Public_spaces-Lebanon-2023 (PKGCube). CSV is read from the same folder as this app.")

# ───────── Load & prep data ─────────
@st.cache_data
def load_data():
    data_path = Path(__file__).parent / "Parks Data.csv"
    if not data_path.exists():
        st.error(f"CSV not found at: {data_path}. Ensure the file is named exactly 'Parks Data.csv'.")
        st.stop()

    df = pd.read_csv(data_path)
    df.columns = [c.strip() for c in df.columns]  # trim accidental spaces

    # Rename to concise, consistent names (works after trimming)
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

    # Human-readable area name
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

    # Short label for visuals
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

    # Single condition labels (for treemap split choices)
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

# ───────── Sidebar (affects BOTH charts) ─────────
with st.sidebar:
    st.header("Filters")
    level = st.radio("Administrative level", ["Governorate", "District"], horizontal=True)
    areas_all = sorted(df.loc[df["Level"] == level, "Area"].dropna().unique())
    sel_areas = st.multiselect("Areas", areas_all, default=areas_all)
    norm_pct = st.toggle("Normalize bar chart to %", value=False)

    st.markdown("---")
    split_mode = st.selectbox("Treemap split", ["Park Existence", "Park Condition", "Lighting Condition"], index=0)

# Filtered data
fdf = df[(df["Level"] == level) & (df["Area"].isin(sel_areas))].copy()

# ───────── KPI row ─────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("Towns (filtered)", f"{len(fdf):,}")
k2.metric("Towns with a park", f"{100 * fdf['parks_exist'].mean():.1f}%" if len(fdf) else "—")
k3.metric("Areas selected", f"{len(sel_areas)}")
k4.metric("Level", level)
st.markdown("---")

# Helpers for insights
def safe_pct(num, den):
    return 0.0 if den == 0 else round(100.0 * num / den, 1)

# ───────── Visualization TWO (now FIRST) — Treemap ─────────
tdf = fdf.copy()
if split_mode == "Park Existence":
    tdf["TreemapGroup"] = tdf["parks_exist"].map({1: "Parks exist", 0: "No parks"}).fillna("No data")
    color_map = {"Parks exist": "#34a853", "No parks": "#9e9e9e", "No data": "#bdbdbd"}
    ordered_groups = ["Parks exist", "No parks", "No data"]
    subtitle = "Park Existence"
elif split_mode == "Park Condition":
    tdf["TreemapGroup"] = tdf["park_condition"].fillna("Unknown")
    color_map = {"Good": "#34a853", "Acceptable": "#fbbc05", "Bad": "#ea4335", "Unknown": "#9e9e9e"}
    ordered_groups = ["Good", "Acceptable", "Bad", "Unknown"]
    subtitle = "Park Condition"
else:  # Lighting Condition
    tdf["TreemapGroup"] = tdf["lighting_condition"].fillna("Unknown")
    color_map = {"Good": "#34a853", "Acceptable": "#fbbc05", "Bad": "#ea4335", "Unknown": "#9e9e9e"}
    ordered_groups = ["Good", "Acceptable", "Bad", "Unknown"]
    subtitle = "Lighting Condition"

# Aggregate counts for treemap
if "Town" in tdf.columns:
    agg = tdf.groupby(["AreaShort", "TreemapGroup"], as_index=False).agg(count=("Town", "count"))
else:
    agg = tdf.groupby(["AreaShort", "TreemapGroup"], as_index=False).size().rename(columns={"size": "count"})

if not agg.empty:
    # Avoid categoricals to prevent errors; sort manually for readability
    agg["AreaShort"] = agg["AreaShort"].astype(str)
    agg["TreemapGroup"] = agg["TreemapGroup"].astype(str)
    order_index = {v: i for i, v in enumerate(ordered_groups)}
    agg["group_order"] = agg["TreemapGroup"].map(order_index).fillna(999).astype(int)
    agg = agg.sort_values(["AreaShort", "group_order", "TreemapGroup"])

    fig2 = px.treemap(
        agg,
        path=["AreaShort", "TreemapGroup"],
        values="count",
        color="TreemapGroup",
        color_discrete_map=color_map,
        title=f"Towns per {level} — {subtitle}"
    )
    fig2.update_traces(textinfo="label+value")
    st.plotly_chart(fig2, use_container_width=True)

    # —— Notes & Insights (Chart 2) —— 
    with st.expander(f"Notes & Insights — {subtitle}"):
        total_towns = int(agg["count"].sum())
        by_group = agg.groupby("TreemapGroup", as_index=False)["count"].sum()
        by_group["order"] = by_group["TreemapGroup"].map(order_index).fillna(999).astype(int)
        by_group = by_group.sort_values("order")
        bullets = []
        for _, r in by_group.iterrows():
            bullets.append(f"- **{r['TreemapGroup']}**: {int(r['count'])} towns ({safe_pct(int(r['count']), total_towns)}%).")
        st.markdown("\n".join(bullets))

        if split_mode == "Park Existence":
            exist_df = agg[agg["TreemapGroup"] == "Parks exist"].sort_values("count", ascending=False)
            if not exist_df.empty:
                st.markdown(f"- **Largest concentration of towns with parks:** **{exist_df.iloc[0]['AreaShort']}** ({int(exist_df.iloc[0]['count'])}).")
        elif split_mode in ("Park Condition", "Lighting Condition"):
            good_df = agg[agg["TreemapGroup"] == "Good"].sort_values("count", ascending=False)
            if not good_df.empty:
                st.markdown(f"- **Most ‘Good’ entries:** **{good_df.iloc[0]['AreaShort']}** ({int(good_df.iloc[0]['count'])}).")
else:
    st.info("No data after filters to draw the treemap.")

# ───────── Visualization ONE (now SECOND) — Public Park Condition by Area (stacked bar) ─────────
parks_cols = [c for c in ["parks_bad","parks_acceptable","parks_good"] if c in fdf.columns]
if parks_cols and not fdf.empty:
    g = fdf.groupby("Area", as_index=False)[parks_cols].sum()
    long = g.melt(id_vars="Area", var_name="state", value_name="count")
    state_labels = {"parks_bad":"Bad","parks_acceptable":"Acceptable","parks_good":"Good"}
    long["state"] = long["state"].map(state_labels)

    if norm_pct:
        denom = long.groupby("Area")["count"].transform("sum").replace(0, 1)
        long["value"] = (long["count"] / denom * 100).round(2)
        ycol, ytitle = "value", "Share (%)"
    else:
        ycol, ytitle = "count", "Count (towns)"

    # Sort areas by total
    area_order = long.groupby("Area")[ycol].sum().sort_values(ascending=False).index.tolist()
    long["Area"] = pd.Categorical(long["Area"], categories=area_order, ordered=True)
    long = long.sort_values("Area")

    fig1 = px.bar(
        long, x="Area", y=ycol, color="state",
        labels={"Area": level, ycol: ytitle, "state": "Condition"},
        title=f"Public park condition by {level.lower()}",
    )
    fig1.update_layout(barmode="stack", xaxis_tickangle=-30, legend_title_text="Condition")
    st.plotly_chart(fig1, use_container_width=True)

    # —— Notes & Insights (Chart 1) —— 
    with st.expander("Notes & Insights — Public Park Condition"):
        totals = g.assign(total=g[parks_cols].sum(axis=1))
        good_share = (g["parks_good"] / totals["total"].replace(0, 1)).fillna(0)
        bad_share  = (g["parks_bad"]  / totals["total"].replace(0, 1)).fillna(0)

        top_total = totals.sort_values("total", ascending=False).head(1)
        top_good  = good_share.sort_values(ascending=False).head(1).index
        top_bad   = bad_share.sort_values(ascending=False).head(1).index

        if not top_total.empty:
            tt_area = top_total["Area"].iloc[0]
            tt_val  = int(top_total["total"].iloc[0])
            st.markdown(f"- **Highest overall volume:** **{tt_area}** ({tt_val} town-condition flags).")

        if len(top_good) > 0:
            area_g = g.loc[top_good[0], "Area"] if "Area" in g.columns else g.iloc[top_good[0]]["Area"]
            pct_g  = safe_pct(int(g.loc[top_good[0], "parks_good"]), int(totals.loc[top_good[0], "total"]))
            st.markdown(f"- **Highest share Good:** **{area_g}** (~{pct_g}%).")

        if len(top_bad) > 0:
            area_b = g.loc[top_bad[0], "Area"] if "Area" in g.columns else g.iloc[top_bad[0]]()["Area"]
            pct_b  = safe_pct(int(g.loc[top_bad[0], "parks_bad"]), int(totals.loc[top_bad[0], "total"]))
            st.markdown(f"- **Highest share Bad:** **{area_b}** (~{pct_b}%).")

        if norm_pct:
            st.markdown("- Percent view is enabled: comparisons reflect **composition** rather than raw counts.")
        else:
            st.markdown("- Count view is enabled: larger areas naturally show higher totals.")
else:
    st.info("Park condition columns not found.")
