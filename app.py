# -*- coding: utf-8 -*-
"""
거시경제 대시보드 (Streamlit)
=====================================
실행:  streamlit run app.py
필요:  .env 에 FRED_API_KEY, ECOS_API_KEY 입력 (README 참고)
"""

import os
import io

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

import config
import data as data_mod
import scoring

load_dotenv()

st.set_page_config(page_title="거시경제 대시보드", page_icon="📊", layout="wide")


# ---------------------------------------------------------------------------
# API 키 로드 (.env → st.secrets 순서)
# ---------------------------------------------------------------------------
def load_keys():
    fred = os.getenv("FRED_API_KEY", "")
    ecos = os.getenv("ECOS_API_KEY", "")
    try:
        fred = fred or st.secrets.get("FRED_API_KEY", "")
        ecos = ecos or st.secrets.get("ECOS_API_KEY", "")
    except Exception:  # secrets 파일 없을 때
        pass
    return {"fred": fred, "ecos": ecos}


@st.cache_data(ttl=3600, show_spinner="데이터를 불러오는 중...")
def load_frame(keys, use_cache):
    return data_mod.build_daily_frame(config.VARIABLES, keys, use_cache=use_cache)


@st.cache_data(ttl=3600, show_spinner="시장지수를 불러오는 중...")
def load_combo(keys, use_cache):
    return data_mod.load_combo_series(config.COMBO_CHARTS, keys, use_cache=use_cache)


def fmt(value, decimals, unit):
    if value is None or pd.isna(value):
        return "-"
    return f"{value:,.{decimals}f}{unit}"


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ 설정")
keys = load_keys()

if not keys["fred"]:
    st.sidebar.warning("FRED_API_KEY 가 없습니다. .env 파일에 입력하세요.")
    keys["fred"] = st.sidebar.text_input("FRED API Key", type="password")
if not keys["ecos"]:
    st.sidebar.info("ECOS_API_KEY 가 없으면 한국 금리는 빠집니다.")
    keys["ecos"] = st.sidebar.text_input("ECOS API Key", type="password")

period = st.sidebar.selectbox(
    "표시 기간", ["1년", "3년", "5년", "전체"], index=1
)
period_days = {"1년": 365, "3년": 365 * 3, "5년": 365 * 5, "전체": None}[period]

if st.sidebar.button("🔄 데이터 새로고침 (캐시 무시)"):
    load_frame.clear()
    load_combo.clear()
    st.rerun()

# ---------------------------------------------------------------------------
# 데이터 로드 & 점수 계산
# ---------------------------------------------------------------------------
if not keys["fred"]:
    st.title("📊 거시경제 대시보드")
    st.info("좌측 사이드바에 FRED API Key 를 입력하거나 .env 파일을 설정하세요. "
            "발급: https://fred.stlouisfed.org → My Account → API Keys (무료)")
    st.stop()

frame, errors = load_frame(keys, use_cache=True)
for e in errors:
    st.sidebar.error(e)

if frame.empty:
    st.error("데이터를 불러오지 못했습니다. API 키와 네트워크를 확인하세요.")
    st.stop()

results, composite = scoring.score_all(frame, config.VARIABLES)
label, color, desc = scoring.interpret(composite)

# ---------------------------------------------------------------------------
# 상단: 종합점수
# ---------------------------------------------------------------------------
st.title("📊 거시경제 대시보드")
st.caption("주식 투자 관점 · 점수가 높을수록 우호적 (0~100)")

top_left, top_right = st.columns([1, 2])
with top_left:
    gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=composite if composite is not None else 0,
        number={"suffix": " 점"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 20], "color": "#fde0dd"},
                {"range": [20, 40], "color": "#fcbba1"},
                {"range": [40, 60], "color": "#fff7bc"},
                {"range": [60, 80], "color": "#c7e9c0"},
                {"range": [80, 100], "color": "#a1d99b"},
            ],
        },
    ))
    gauge.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=10))
    st.plotly_chart(gauge, use_container_width=True)
with top_right:
    st.markdown(f"### 종합점수: <span style='color:{color}'>{composite} 점 — {label}</span>",
                unsafe_allow_html=True)
    last_date = frame.dropna(how="all").index[-1].strftime("%Y-%m-%d")
    st.caption(f"기준일: {last_date}")
    # 현재 구간 설명 강조
    st.markdown(
        f"<div style='background:{color}22;border-left:5px solid {color};"
        f"padding:10px 14px;border-radius:6px;'>{desc}</div>",
        unsafe_allow_html=True,
    )
    st.caption("각 변수는 `절대수준 점수`와 `최근 3개월 추세 점수`를 반반 반영합니다.")

# 종합점수 구간별 설명 (전체)
with st.expander("📖 종합점수 구간별 설명 (전체 보기)", expanded=False):
    for low, high, blabel, bcolor, bdesc in config.SCORE_INTERPRETATION:
        rng = f"{low}~{min(high, 100)}점"
        here = "  ⬅ 현재" if (composite is not None and low <= composite < high) else ""
        st.markdown(
            f"<div style='background:{bcolor}22;border-left:5px solid {bcolor};"
            f"padding:8px 14px;margin-bottom:6px;border-radius:6px;'>"
            f"<b>{rng} · {blabel}{here}</b><br>{bdesc}</div>",
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# 변수별 점수 카드
# ---------------------------------------------------------------------------
st.subheader("변수별 점수")
PER_ROW = 5
for start in range(0, len(results), PER_ROW):
    row = results[start:start + PER_ROW]
    cols = st.columns(PER_ROW)
    for col, r in zip(cols, row):
        with col:
            cur = fmt(r["current"], r["decimals"], r["unit"])
            final = r["final"] if r["final"] is not None else "-"
            st.metric(label=r["name"], value=cur, delta=f"{final} / 5 점", delta_color="off")
            st.caption(f"수준 {r['level']} · 추세 {r['trend']} · 가중치 {r['weight']}")

# ---------------------------------------------------------------------------
# 탭: 그래프 / 시장지수(콤보) / 테이블 / 점수 기준
# ---------------------------------------------------------------------------
tab_graph, tab_combo, tab_table, tab_rule = st.tabs(
    ["📈 그래프", "📈 시장지수(콤보)", "📋 일별 테이블", "📖 점수 기준"]
)

# 기간 필터
if period_days:
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=period_days)
    view = frame[frame.index >= cutoff]
else:
    cutoff = None
    view = frame

with tab_graph:
    for var in config.VARIABLES:
        if var["key"] not in view.columns:
            continue
        s = view[var["key"]].dropna()
        if s.empty:
            continue
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=var["name"],
                                 line=dict(width=2)))
        fig.update_layout(
            title=f"{var['name']} ({var['unit']})",
            height=300, margin=dict(l=40, r=20, t=40, b=20),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

with tab_combo:
    combo_data, combo_errors = load_combo(keys, use_cache=True)
    for e in combo_errors:
        st.warning(e)

    for chart in config.COMBO_CHARTS:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        drew_left = drew_right = False
        for spec in chart["series"]:
            s = combo_data.get(spec["id"], pd.Series(dtype="float64")).dropna()
            if cutoff is not None:
                s = s[s.index >= cutoff]
            if s.empty:
                continue
            right = spec["axis"] == "right"
            if spec["kind"] == "bar":
                trace = go.Bar(x=s.index, y=s.values, name=spec["label"],
                               marker_color=spec["color"], opacity=0.35)
            else:
                trace = go.Scatter(x=s.index, y=s.values, mode="lines", name=spec["label"],
                                   line=dict(width=2, color=spec["color"]))
            fig.add_trace(trace, secondary_y=right)
            drew_left = drew_left or (not right)
            drew_right = drew_right or right

        fig.update_layout(
            title=chart["title"],
            height=450, margin=dict(l=50, r=50, t=50, b=20),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            barmode="overlay",
        )
        fig.update_yaxes(title_text=chart.get("left_title", ""), secondary_y=False)
        fig.update_yaxes(title_text=chart.get("right_title", ""), secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "나스닥·다우존스는 왼쪽 축(선), IPO ETF는 오른쪽 축(선)입니다. "
        "지수와 ETF는 스케일이 달라 축을 나눠 표시합니다. "
        "이 지표들은 참고용 그래프이며 종합점수에는 반영되지 않습니다."
    )

with tab_table:
    # 컬럼명을 한글로, 최신순 정렬
    rename = {v["key"]: v["name"] for v in config.VARIABLES if v["key"] in view.columns}
    table = view.rename(columns=rename).sort_index(ascending=False).round(2)
    table.index = table.index.strftime("%Y-%m-%d")
    st.dataframe(table, use_container_width=True, height=500)

    # 다운로드 (CSV / Excel)
    c1, c2 = st.columns(2)
    csv = table.to_csv().encode("utf-8-sig")
    c1.download_button("⬇️ CSV 다운로드", csv, "거시경제_일별.csv", "text/csv")
    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
        table.to_excel(writer, sheet_name="일별데이터")
    c2.download_button("⬇️ Excel 다운로드", xbuf.getvalue(),
                       "거시경제_일별.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab_rule:
    st.markdown("#### 절대수준 점수 구간 (점수가 높을수록 우호적)")
    rows = []
    for var in config.VARIABLES:
        bands = "  |  ".join(
            f"{s}점: "
            + (f"<{high:g}" if low == float('-inf')
               else f"≥{low:g}" if high == float('inf')
               else f"{low:g}~{high:g}")
            for low, high, s in var["level_bands"]
        )
        rows.append({"변수": var["name"], "단위": var["unit"],
                     "가중치": var["weight"], "구간": bands})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown(
        "#### 추세 점수 (최근 3개월 변화)\n"
        "하락=우호. 크게하락 5 · 소폭하락 4 · 보합 3 · 소폭상승 2 · 크게상승 1\n\n"
        "임계값·가중치·점수구간은 모두 `config.py` 에서 숫자만 바꾸면 됩니다."
    )
