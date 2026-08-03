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
import dart_api
import data as data_mod
import equity
import journal
import krx_api
import scoring

load_dotenv()

st.set_page_config(page_title="거시경제 대시보드", page_icon="📊", layout="wide")


class _SkipIndividual(Exception):
    """ROE 구간 평균 보기일 때 개별 종목 화면을 건너뛰기 위한 내부 신호."""


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
tab_graph, tab_combo, tab_table, tab_rule, tab_roepbr, tab_journal = st.tabs(
    ["📈 그래프", "📈 시장·환율·금리차", "📋 일별 테이블", "📖 점수 기준",
     "📉 ROE·PBR 분석", "📝 매매일지"]
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
            # 수집 실패한 시리즈는 인덱스가 날짜형이 아니므로 날짜 비교 전에 걸러낸다
            if s.empty or not isinstance(s.index, pd.DatetimeIndex):
                continue
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
        if chart.get("zero_line"):
            fig.add_hline(y=0, line_dash="dash", line_color="gray",
                          annotation_text="0 (수익률곡선 역전 기준)",
                          annotation_position="bottom right")
        st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "· 증시지수 콤보: 나스닥·다우존스(왼쪽 축, 선), IPO ETF(오른쪽 축, 선). "
        "지수와 ETF는 스케일이 달라 축을 나눠 표시합니다.\n\n"
        "· 장단기 금리차가 **0 아래(역전)**면 경기침체 경고 신호로 해석됩니다.\n\n"
        "· 이 지표들은 참고용 그래프이며 종합점수에는 반영되지 않습니다."
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

# ---------------------------------------------------------------------------
# 매매일지 (Dropbox 저장 + 비밀번호 잠금)
# ---------------------------------------------------------------------------
with tab_roepbr:
    st.markdown("#### 📉 ROE · PBR 회귀분석")
    st.caption(
        "같은 시점의 여러 종목을 한꺼번에 놓고 봅니다. 점 하나가 종목 하나이고, "
        "회귀선보다 **아래**면 같은 ROE 대비 PBR이 낮다(상대 저평가)는 뜻입니다."
    )

    sub1, sub2 = st.tabs(["종목별 ROE-PBR", "코스피지수 - PBR"])

    # ---------------- 종목별 ROE vs PBR ----------------
    with sub1:
        has_api = bool(krx_api.get_key()) and bool(dart_api.get_key())
        src = st.radio(
            "데이터 가져오는 방법",
            ["API 자동 수집", "파일 업로드"],
            horizontal=True,
            index=0 if has_api else 1,
            key="roepbr_src",
        )

        sdf = None

        # ===== API 자동 수집 =====
        if src == "API 자동 수집":
            if not has_api:
                miss = [n for n, v in [("KRX_API_KEY", krx_api.get_key()),
                                       ("DART_API_KEY", dart_api.get_key())] if not v]
                st.error(f"API 키를 찾지 못했습니다: {', '.join(miss)}")
                st.markdown(
                    "**Streamlit Cloud라면 Secrets 붙여넣은 위치를 확인하세요.** "
                    "TOML은 `[dropbox]` 같은 섹션 아래에 쓰면 그 섹션 *안*으로 들어갑니다. "
                    "아래처럼 **맨 위**(섹션보다 먼저)에 두세요:\n"
                    "```toml\n"
                    'FRED_API_KEY = "..."\n'
                    'ECOS_API_KEY = "..."\n'
                    'KRX_API_KEY = "..."\n'
                    'DART_API_KEY = "..."\n\n'
                    "[dropbox]\n"
                    '...\n'
                    "```\n"
                    "수정 후 **Reboot app** 해야 반영됩니다."
                )
            else:
                a1, a2 = st.columns(2)
                year = a1.number_input("재무 기준 사업연도", 2015,
                                       pd.Timestamp.today().year,
                                       pd.Timestamp.today().year - 1, step=1)
                rname = a2.selectbox("보고서", list(dart_api.REPRT.keys()), index=0)
                rcode = dart_api.REPRT[rname]
                ann = st.checkbox(
                    "분기 순이익을 연환산해서 ROE 계산", value=True,
                    help="분기·반기 보고서는 누적 순이익이라, 연간 기준으로 환산해야 "
                         "ROE를 연율로 비교할 수 있습니다.")

                if st.button("🔄 API로 불러오기", type="primary"):
                    try:
                        with st.spinner("KRX에서 시가총액을 받는 중..."):
                            kdf, basdd = krx_api.fetch_latest_stock_daily()
                        st.caption(f"KRX 기준일: {basdd} · {len(kdf):,}개 종목")

                        with st.spinner("DART 기업코드 매핑을 받는 중..."):
                            cmap = dart_api.load_corp_map()

                        codes = [cmap[c] for c in kdf["종목코드"] if c in cmap]
                        bar = st.progress(0.0, text="DART 재무 조회 중...")
                        fin = dart_api.fetch_financials(
                            codes, int(year), rcode,
                            progress=lambda d, t: bar.progress(
                                d / t, text=f"DART 재무 조회 중... {d}/{t}"))
                        bar.empty()

                        annf = ((lambda p: dart_api.annualize_profit(p, rcode))
                                if ann else None)
                        built = equity.build_from_api(kdf, fin, cmap, annualize=annf)
                        if built.empty:
                            st.error("결합 결과가 비었습니다. 연도·보고서를 바꿔보세요.")
                        else:
                            journal.save_table(built, "roe_pbr_stocks")
                            st.session_state["roepbr_api"] = built
                            st.success(f"{len(built):,}개 종목 완성 "
                                       f"(KRX {basdd} 시총 ÷ DART {year}년 {rname})")
                    except PermissionError as e:
                        st.error(str(e))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"수집 중 오류: {e}")

                sdf = st.session_state.get("roepbr_api")
                if sdf is None:
                    saved = journal.load_table("roe_pbr_stocks")
                    if saved is not None and not saved.empty:
                        sdf = saved
                        st.info("이전에 수집한 자료를 보여줍니다. 위 버튼으로 갱신하세요.")

        # ===== 파일 업로드 =====
        up = None
        if src == "파일 업로드":
            up = st.file_uploader(
                "KRX 'PER/PBR/배당수익률' 종목별 자료 (엑셀 또는 CSV)",
                type=["xlsx", "xls", "csv"], key="up_stocks",
            )

        if up is not None:
            try:
                raw = equity.read_table(up)
                sdf, note = equity.parse_stocks(raw)
                ok, err = journal.save_table(sdf, "roe_pbr_stocks")
                st.success(f"{len(sdf)}개 종목을 읽었습니다. {note}"
                           + ("" if ok else f" (보관 실패: {err})"))
            except Exception as e:  # noqa: BLE001
                st.error(f"파일을 읽지 못했습니다: {e}")
        elif src == "파일 업로드":
            saved = journal.load_table("roe_pbr_stocks")
            if saved is not None and not saved.empty:
                sdf = saved
                st.info("이전에 올린 자료를 사용 중입니다. 새 파일을 올리면 갱신됩니다.")

        if sdf is None or sdf.empty:
            st.warning("아직 자료가 없습니다. 위에서 API로 불러오거나 파일을 올려주세요.")
        else:
            # --- 이상치 필터 (자본잠식 기업이 회귀선을 왜곡하는 것을 방지) ---
            with st.expander("⚙️ 분석 범위 설정", expanded=False):
                fc1, fc2 = st.columns(2)
                pbr_max = fc1.slider("PBR 상한 (배)", 1.0, 50.0, 10.0, step=1.0)
                roe_rng = fc2.slider("ROE 범위 (%)", -200.0, 200.0, (-50.0, 100.0),
                                     step=10.0)
                st.caption(
                    "자본이 거의 잠식된 회사는 PBR이 수백 배, ROE가 ±수백 %로 나와 "
                    "소수 종목이 회귀선을 통째로 끌고 갑니다. 기본값을 권장합니다."
                )

            filt, dropped = equity.filter_outliers(sdf, pbr_max, roe_rng[0], roe_rng[1])
            if dropped:
                st.caption(f"극단값 {dropped}개 종목을 분석에서 제외했습니다.")

            # 시가총액이 있으면 상위 N개만 (코스피200 근사)
            if "시가총액" in filt.columns and filt["시가총액"].notna().any():
                topn = st.slider("시가총액 상위 몇 개 종목으로 분석할까요?",
                                 30, max(30, min(500, len(filt))),
                                 min(200, len(filt)), step=10)
                use = filt.nlargest(topn, "시가총액").reset_index(drop=True)
                st.caption(f"시가총액 상위 {topn}개 종목으로 분석합니다 (코스피200 근사).")
            else:
                use = filt.reset_index(drop=True)
                st.caption(f"{len(use)}개 종목 전체로 분석합니다.")

            view = st.radio(
                "보기 방식",
                ["개별 종목", "ROE 구간 평균 (추세 뚜렷)"],
                horizontal=True, key="roepbr_view",
            )

            # ---- ROE 구간 평균 보기 ----
            if view.startswith("ROE 구간"):
                nbin = st.slider("구간 개수", 4, 12, 8)
                g = equity.bin_by_roe(use, nbin)
                try:
                    gfit = equity.regress(g["ROE"], g["PBR"])
                    b1, b2, b3 = st.columns(3)
                    b1.metric("회귀식",
                              f"PBR = {gfit['slope']:.4f}×ROE + {gfit['intercept']:.3f}")
                    b2.metric("설명력 R²", f"{gfit['r2']:.3f}")
                    b3.metric("구간 수", f"{gfit['n']}개")

                    figg = go.Figure()
                    figg.add_trace(go.Scatter(
                        x=g["ROE"], y=g["PBR"], mode="markers+text", name="구간 중앙값",
                        marker=dict(size=14, color="#2ca02c"),
                        text=[f"{n}개" for n in g["종목수"]], textposition="top center",
                        hovertemplate="ROE %{x:.1f}%<br>PBR %{y:.2f}<extra></extra>"))
                    gx, gy = equity.fit_line(gfit, g["ROE"])
                    figg.add_trace(go.Scatter(x=gx, y=gy, mode="lines", name="회귀선",
                                              line=dict(width=3, color="#e74c3c")))
                    figg.update_layout(
                        height=420, margin=dict(l=50, r=20, t=30, b=40),
                        xaxis_title="ROE (%) — 구간 중앙값",
                        yaxis_title="PBR (배) — 구간 중앙값",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                    xanchor="left", x=0))
                    st.plotly_chart(figg, use_container_width=True)
                    st.dataframe(g.round(2), use_container_width=True, hide_index=True)
                    st.info(
                        "종목을 ROE 순으로 같은 개수씩 묶어 중앙값을 찍은 그림입니다. "
                        "개별 종목의 잡음이 상쇄돼 **ROE가 높을수록 PBR이 높다**는 추세가 "
                        "선명하게 보입니다.\n\n"
                        "⚠️ 여기의 R²는 **구간 평균끼리의 설명력**입니다. "
                        "개별 종목을 맞히는 정확도가 아니라는 점에 유의하세요 "
                        "(개별 종목 기준 R²는 '개별 종목' 보기에 표시됩니다)."
                    )
                except Exception as e:  # noqa: BLE001
                    st.error(f"구간 계산 중 문제: {e}")
                use = None   # 개별 종목 화면은 건너뛴다

            try:
                if use is None:
                    raise _SkipIndividual
                fit = equity.regress(use["ROE"], use["PBR"])
                res = equity.with_residuals(use, "ROE", "PBR", fit)

                m1, m2, m3 = st.columns(3)
                m1.metric("회귀식", f"PBR = {fit['slope']:.4f}×ROE + {fit['intercept']:.3f}")
                m2.metric("설명력 R²", f"{fit['r2']:.3f}")
                m3.metric("표본 수", f"{fit['n']}개")
                if fit["r2"] < 0.3:
                    st.caption(
                        f"R²가 낮은 것은 정상입니다 — 같은 ROE라도 성장기대·업종에 따라 "
                        f"PBR이 크게 갈리기 때문입니다. 추세를 뚜렷하게 보시려면 위에서 "
                        f"**'ROE 구간 평균'** 을 선택하세요."
                    )

                # 종목 강조 선택
                picked = st.multiselect(
                    "특정 종목을 강조해서 보기 (종목명 입력)",
                    options=sorted(res["종목명"].unique()), max_selections=10,
                )

                figr = go.Figure()
                base = res[~res["종목명"].isin(picked)]
                figr.add_trace(go.Scatter(
                    x=base["ROE"], y=base["PBR"], mode="markers", name="종목",
                    marker=dict(size=7, color="#7fb3d5", opacity=0.75),
                    text=base["종목명"],
                    hovertemplate="%{text}<br>ROE %{x:.2f}%<br>PBR %{y:.2f}<extra></extra>"))

                if picked:
                    hi = res[res["종목명"].isin(picked)]
                    figr.add_trace(go.Scatter(
                        x=hi["ROE"], y=hi["PBR"], mode="markers+text", name="선택 종목",
                        marker=dict(size=14, color="#d62728",
                                    line=dict(width=1, color="white")),
                        text=hi["종목명"], textposition="top center",
                        hovertemplate="%{text}<br>ROE %{x:.2f}%<br>PBR %{y:.2f}<extra></extra>"))

                xs, ys = equity.fit_line(fit, use["ROE"])
                figr.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name="회귀선",
                                          line=dict(width=3, color="#e74c3c")))
                figr.update_layout(
                    height=460, margin=dict(l=50, r=20, t=30, b=40),
                    xaxis_title="ROE (%)", yaxis_title="PBR (배)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                xanchor="left", x=0))
                st.plotly_chart(figr, use_container_width=True)

                if picked:
                    st.markdown("###### 선택 종목 위치")
                    hi = res[res["종목명"].isin(picked)][
                        ["종목명", "ROE", "PBR", "예측", "잔차", "평가"]]
                    st.dataframe(hi.round(3), use_container_width=True, hide_index=True)

                c1, c2 = st.columns(2)
                cols = ["종목명", "ROE", "PBR", "예측", "잔차"]
                with c1:
                    st.markdown("###### 회귀선 아래 (상대 저평가) 20")
                    st.dataframe(res.nsmallest(20, "잔차")[cols].round(3),
                                 use_container_width=True, hide_index=True)
                with c2:
                    st.markdown("###### 회귀선 위 (상대 고평가) 20")
                    st.dataframe(res.nlargest(20, "잔차")[cols].round(3),
                                 use_container_width=True, hide_index=True)

                st.download_button(
                    "⬇️ 분석 결과 CSV",
                    res.to_csv(index=False).encode("utf-8-sig"),
                    "ROE_PBR_분석.csv", "text/csv")
            except _SkipIndividual:
                pass          # 구간 평균 보기 중 → 개별 종목 화면 생략
            except Exception as e:  # noqa: BLE001
                st.error(f"분석 중 문제가 발생했습니다: {e}")

    # ---------------- 코스피지수 vs PBR ----------------
    with sub2:
        src2 = st.radio(
            "데이터 가져오는 방법",
            ["API 자동 수집", "파일 업로드"],
            horizontal=True, index=0 if has_api else 1, key="idx_src",
        )

        idf = None
        up2 = None

        # ===== API 자동 수집 (월말 시점별로 시장 전체 PBR 계산) =====
        if src2 == "API 자동 수집":
            if not has_api:
                st.error("API 키가 없습니다. 위 '종목별' 탭의 안내를 참고하세요.")
            else:
                st.caption(
                    "월말마다 **시장 전체 시가총액 ÷ 자본총계**로 코스피 PBR을 계산합니다. "
                    "각 시점에는 그때 이미 공시돼 있던 재무만 사용합니다."
                )
                yb = st.slider("몇 년치를 모을까요?", 1, 6, 3, key="idx_years")
                st.caption(f"약 {yb*12}개 시점 × 2회 조회 → **{yb*12*4//60}분 내외** 걸립니다.")

                if st.button("🔄 API로 불러오기", type="primary", key="idx_fetch"):
                    try:
                        dates = krx_api.month_end_dates(yb)
                        cmap = dart_api.load_corp_map()

                        # 종목 목록(최근 시점 기준)으로 필요한 사업연도별 재무를 미리 확보
                        with st.spinner("최근 종목 목록을 받는 중..."):
                            latest_k, _ = krx_api.fetch_latest_stock_daily()
                        codes = [cmap[c] for c in latest_k["종목코드"] if c in cmap]

                        years = sorted({equity.fiscal_year_for(d) for d in dates})
                        fin_by_year = {}
                        fb = st.progress(0.0, text="DART 재무 준비 중...")
                        for i, y in enumerate(years):
                            fin_by_year[y] = dart_api.fetch_financials(codes, y, "11011")
                            fb.progress((i + 1) / len(years),
                                        text=f"DART 재무 준비 중... {y}년 ({i+1}/{len(years)})")
                        fb.empty()

                        rows = []
                        pb = st.progress(0.0, text="시점별 수집 중...")
                        for i, d in enumerate(dates):
                            kdf_d, used = krx_api.fetch_near(krx_api.fetch_stock_daily, d)
                            if used is None:
                                continue
                            idx_d, _ = krx_api.fetch_near(krx_api.fetch_kospi_index, used)
                            if idx_d is None or idx_d.empty:
                                continue
                            fin = fin_by_year.get(equity.fiscal_year_for(d))
                            if fin is None or fin.empty:
                                continue
                            pbr = equity.aggregate_pbr(kdf_d, fin, cmap)
                            if pd.notna(pbr):
                                rows.append({"날짜": pd.to_datetime(used),
                                             "지수": float(idx_d["지수"].iloc[0]),
                                             "PBR": pbr})
                            pb.progress((i + 1) / len(dates),
                                        text=f"시점별 수집 중... {used} ({i+1}/{len(dates)})")
                        pb.empty()

                        if not rows:
                            st.error("수집된 시점이 없습니다. 기간을 줄여 다시 시도해보세요.")
                        else:
                            got = pd.DataFrame(rows).sort_values("날짜").reset_index(drop=True)
                            journal.save_table(got, "roe_pbr_index")
                            st.session_state["idx_api"] = got
                            st.success(f"{len(got)}개 시점을 수집했습니다.")
                    except PermissionError as e:
                        st.error(str(e))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"수집 중 오류: {e}")

                idf = st.session_state.get("idx_api")
                if idf is None:
                    saved2 = journal.load_table("roe_pbr_index")
                    if saved2 is not None and not saved2.empty:
                        idf = saved2.copy()
                        idf["날짜"] = pd.to_datetime(idf["날짜"], errors="coerce")
                        st.info("이전에 수집한 자료를 보여줍니다. 위 버튼으로 갱신하세요.")

        # ===== 파일 업로드 =====
        if src2 == "파일 업로드":
            up2 = st.file_uploader(
                "KRX 주가지수 'PER/PBR/배당수익률' 기간 자료 (엑셀 또는 CSV)",
                type=["xlsx", "xls", "csv"], key="up_index",
            )

        if up2 is not None:
            try:
                raw2 = equity.read_table(up2)
                idf = equity.parse_index(raw2)
                ok, err = journal.save_table(idf, "roe_pbr_index")
                st.success(f"{len(idf)}일치 자료를 읽었습니다."
                           + ("" if ok else f" (보관 실패: {err})"))
            except Exception as e:  # noqa: BLE001
                st.error(f"파일을 읽지 못했습니다: {e}")
        elif src2 == "파일 업로드":
            saved2 = journal.load_table("roe_pbr_index")
            if saved2 is not None and not saved2.empty:
                idf = saved2
                if "날짜" in idf.columns:
                    idf["날짜"] = pd.to_datetime(idf["날짜"], errors="coerce")
                st.info("이전에 올린 자료를 사용 중입니다. 새 파일을 올리면 갱신됩니다.")

        if idf is None or idf.empty:
            st.warning("아직 자료가 없습니다. 위에서 API로 불러오거나 파일을 올려주세요.")
        else:
            try:
                fit2 = equity.regress(idf["PBR"], idf["지수"])
                n1, n2, n3 = st.columns(3)
                n1.metric("회귀식", f"지수 = {fit2['slope']:,.0f}×PBR + {fit2['intercept']:,.0f}")
                n2.metric("설명력 R²", f"{fit2['r2']:.3f}")
                n3.metric("표본 수", f"{fit2['n']}일")

                latest = idf.iloc[-1]
                pred_now = fit2["slope"] * latest["PBR"] + fit2["intercept"]
                gap = latest["지수"] - pred_now
                st.metric(
                    "현재 지수 vs 회귀선 예측",
                    f"{latest['지수']:,.1f} (예측 {pred_now:,.1f})",
                    f"{gap:+,.1f}p — " + ("회귀선 위" if gap > 0 else "회귀선 아래"),
                    delta_color="off")

                figi = go.Figure()
                figi.add_trace(go.Scatter(
                    x=idf["PBR"], y=idf["지수"], mode="markers", name="일자별",
                    marker=dict(size=6, color="#7fb3d5", opacity=0.6),
                    text=(idf["날짜"].dt.strftime("%Y-%m-%d")
                          if "날짜" in idf.columns else None),
                    hovertemplate="%{text}<br>PBR %{x:.2f}<br>지수 %{y:,.0f}<extra></extra>"))
                figi.add_trace(go.Scatter(
                    x=[latest["PBR"]], y=[latest["지수"]], mode="markers", name="최근",
                    marker=dict(size=15, color="#d62728",
                                line=dict(width=1, color="white"))))
                xs2, ys2 = equity.fit_line(fit2, idf["PBR"])
                figi.add_trace(go.Scatter(x=xs2, y=ys2, mode="lines", name="회귀선",
                                          line=dict(width=3, color="#e74c3c")))
                figi.update_layout(
                    height=420, margin=dict(l=60, r=20, t=30, b=40),
                    xaxis_title="PBR (배)", yaxis_title="코스피지수",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                xanchor="left", x=0))
                st.plotly_chart(figi, use_container_width=True)

                if "날짜" in idf.columns:
                    figt = make_subplots(specs=[[{"secondary_y": True}]])
                    figt.add_trace(go.Scatter(x=idf["날짜"], y=idf["지수"], mode="lines",
                                              name="코스피지수",
                                              line=dict(width=2, color="#1f77b4")), False)
                    figt.add_trace(go.Scatter(x=idf["날짜"], y=idf["PBR"], mode="lines",
                                              name="PBR",
                                              line=dict(width=2, color="#ff7f0e")), True)
                    figt.update_layout(title="지수 · PBR 시계열", height=340,
                                       margin=dict(l=50, r=50, t=40, b=20),
                                       hovermode="x unified",
                                       legend=dict(orientation="h", yanchor="bottom",
                                                   y=1.02, xanchor="left", x=0))
                    figt.update_yaxes(title_text="코스피지수", secondary_y=False)
                    figt.update_yaxes(title_text="PBR (배)", secondary_y=True)
                    st.plotly_chart(figt, use_container_width=True)
            except Exception as e:  # noqa: BLE001
                st.error(f"분석 중 문제가 발생했습니다: {e}")

    with st.expander("🔑 API 자동 수집 설정 방법"):
        st.markdown(
            "ROE·PBR은 **두 곳의 자료를 합쳐** 계산합니다. "
            "KRX OpenAPI에는 재무지표(PER/PBR/EPS/BPS)가 없기 때문입니다.\n\n"
            "| 출처 | 받는 것 | 키 발급 |\n"
            "|---|---|---|\n"
            "| KRX OpenAPI | 시가총액·주가·지수 | openapi.krx.co.kr |\n"
            "| DART (금감원) | 자본총계·당기순이익 | opendart.fss.or.kr |\n\n"
            "- **PBR** = 시가총액 ÷ 자본총계  ·  **ROE** = 당기순이익 ÷ 자본총계 × 100\n"
            "- KRX는 **서비스별 이용신청**이 필요합니다. "
            "`유가증권 일별매매정보`, `KOSPI 시리즈 일별시세정보` 두 개를 신청·승인받으세요. "
            "(승인 전에는 401 오류)\n"
            "- 키는 로컬 `.env` 또는 Streamlit Secrets에 "
            "`KRX_API_KEY`, `DART_API_KEY` 로 넣습니다.\n"
            "- 재무는 분기 단위라 **최근 확정 보고서**(예: 직전 사업연도)를 고르는 게 안전합니다."
        )

    with st.expander("📎 (대안) KRX에서 파일 받는 방법"):
        st.markdown(
            "**data.krx.co.kr** 접속 → 로그인 (2025년 12월부터 회원가입 필수)\n\n"
            "**① 종목별 자료**\n"
            "- [통계] → [주식] → **PER/PBR/배당수익률** → 시장 `KOSPI` 선택 → 조회 → 엑셀 내려받기\n"
            "- 필요한 컬럼: 종목명, PBR, EPS, BPS (ROE는 EPS÷BPS로 자동 계산)\n\n"
            "**② 지수 자료**\n"
            "- [통계] → [지수] → 주가지수 **PER/PBR/배당수익률** → 지수 `코스피` → 기간 지정 → 조회 → 엑셀 내려받기\n"
            "- 필요한 컬럼: 일자, 종가(지수), PBR\n\n"
            "컬럼 이름이 조금 달라도(`PBR(배)`, `한글 종목약명` 등) 자동으로 찾습니다. "
            "한 번 올리면 Dropbox에 보관되어 다음에 다시 올리지 않아도 됩니다."
        )

with tab_journal:
    st.subheader("📝 매매일지")

    _pw = journal.get_password()
    _unlocked = (not _pw) or st.session_state.get("journal_ok", False)

    if not _unlocked:
        # 공개 앱이므로, 비밀번호를 아는 사람만 열람/작성
        st.info("매매일지는 비공개입니다. 비밀번호를 입력하세요.")
        entered = st.text_input("비밀번호", type="password", key="journal_pw")
        if st.button("열기"):
            if entered == _pw:
                st.session_state["journal_ok"] = True
                st.rerun()
            else:
                st.error("비밀번호가 맞지 않습니다.")
    elif journal.get_client() is None:
        st.warning(
            "Dropbox 연결 정보가 없어 매매일지를 저장할 수 없습니다. "
            "`.streamlit/secrets.toml`(또는 Streamlit Cloud > Settings > Secrets)의 "
            "`[dropbox]` 설정을 확인하세요."
        )
    else:
        jdf = journal.load()
        pdf = journal.load_portfolio()

        # 날짜 선택 (일지와 자산내역이 같은 날짜를 공유)
        j_date = st.date_input("날짜", value=pd.Timestamp.today().date())
        date_str = str(j_date)

        # 같은 날짜 글이 이미 있으면 불러와서 수정할 수 있게
        existing = jdf[jdf["날짜"] == date_str]
        prev_sum = existing["요약"].iloc[0] if len(existing) else ""
        prev_body = existing["내용"].iloc[0] if len(existing) else ""
        if len(existing):
            st.info(f"{date_str} 일지가 이미 있습니다. 수정 후 저장하면 덮어씁니다.")

        left, right = st.columns([3, 2])

        # ---- 왼쪽: 매매일지 작성 ----
        with left:
            st.markdown("##### 📝 일지 작성")
            j_summary = st.text_input(
                "핵심 한 줄 (목록에 표시됩니다)", value=prev_sum,
                placeholder="예) 반도체 비중 축소, 금리 상승에 방어적 대응",
            )
            j_body = st.text_area(
                "내용", value=prev_body, height=300,
                placeholder="매매 종목, 이유, 시황 판단, 반성할 점 등을 자유롭게 적으세요.",
            )

        # ---- 오른쪽: 자산 운용내역 ----
        with right:
            st.markdown("##### 💰 자산 운용내역 (백만원)")
            today_pf = journal.snapshot(pdf, date_str)
            if today_pf.empty:
                # 그날 내역이 없으면 직전 보유내역을 그대로 이어받아 표시
                src_date = journal.last_date_before(pdf, date_str)
                today_pf = journal.latest_snapshot_before(pdf, date_str)
                if not today_pf.empty:
                    st.caption(
                        f"📌 {src_date} 내역을 그대로 이어받았습니다. "
                        "바뀐 게 없으면 그대로 저장하시면 됩니다."
                    )
            if today_pf.empty:
                today_pf = pd.DataFrame({"종목명": ["", "", ""], "금액": [0.0, 0.0, 0.0]})

            # 입력 중인 표를 세션에 보관 → 엔터(재실행) 후에도 입력값이 남는다.
            pf_state_key = f"pf_rows_{date_str}"
            if pf_state_key not in st.session_state:
                st.session_state[pf_state_key] = today_pf.reset_index(drop=True)

            edited_pf = st.data_editor(
                st.session_state[pf_state_key],
                num_rows="dynamic", use_container_width=True, height=260,
                column_config={
                    "종목명": st.column_config.TextColumn("종목명", width="medium"),
                    "금액": st.column_config.NumberColumn(
                        "금액(백만원)", min_value=0.0, step=0.1, format="%.1f",
                        help="백만원 단위, 소수 첫째자리까지 입력 (예: 120.5)"),
                },
            )
            # 편집 결과를 세션에 되돌려 저장 → 다음 재실행 때 그대로 이어짐
            st.session_state[pf_state_key] = edited_pf

            _tot = pd.to_numeric(edited_pf["금액"], errors="coerce").fillna(0).sum()
            st.metric("합계", f"{_tot:,.1f} 백만원")
            st.caption("종목명만 입력해도 저장됩니다 (금액은 나중에 채워도 됩니다).")

        # ---- 저장 (일지 + 자산내역 함께) ----
        if st.button("💾 저장", type="primary"):
            msgs = []
            has_journal = bool(j_summary.strip() or j_body.strip())
            has_pf = (edited_pf["종목명"].fillna("").astype(str).str.strip() != "").any()

            if not has_journal and not has_pf:
                st.warning("일지 내용이나 자산 내역을 입력하세요.")
            else:
                ok_all = True
                if has_journal:
                    newdf = journal.upsert(jdf, date_str, j_summary.strip(), j_body.strip())
                    ok, err = journal.save(newdf)
                    ok_all &= ok
                    msgs.append("일지 저장" if ok else f"일지 실패: {err}")
                if has_pf:
                    newpf = journal.upsert_portfolio(pdf, date_str, edited_pf)
                    ok, err = journal.save_portfolio(newpf)
                    ok_all &= ok
                    msgs.append("자산내역 저장" if ok else f"자산내역 실패: {err}")
                if ok_all:
                    # 저장 완료 → 임시 입력값을 비워 Dropbox 최신본을 다시 읽게 함
                    st.session_state.pop(pf_state_key, None)
                    st.success(f"{date_str} — " + " · ".join(msgs))
                    st.rerun()
                else:
                    st.error(" / ".join(msgs))

        st.divider()

        # ---- 일자별 핵심내용 + 총자산 목록 ----
        st.markdown("##### 일자별 기록")
        totals = journal.daily_totals(pdf)

        if jdf.empty and totals.empty:
            st.caption("아직 작성한 기록이 없습니다.")
        else:
            lines = pd.DataFrame({
                "날짜": jdf["날짜"],
                "핵심내용": [journal.one_line(s, b)
                            for s, b in zip(jdf["요약"], jdf["내용"])],
            })
            # 일지가 없는 날에도 자산내역만 있으면 목록에 나오도록 바깥조인
            merged = pd.merge(lines, totals, on="날짜", how="outer")
            merged["핵심내용"] = merged["핵심내용"].fillna("(일지 없음)")
            merged = merged.sort_values("날짜", ascending=False).reset_index(drop=True)
            merged["총자산(백만원)"] = merged["총자산"].map(
                lambda v: "-" if pd.isna(v) else f"{v:,.1f}")
            st.dataframe(merged[["날짜", "핵심내용", "총자산(백만원)"]],
                         use_container_width=True, hide_index=True, height=280)

            # 총자산 추이
            if len(totals) >= 2:
                tchart = totals.sort_values("날짜")
                figa = go.Figure()
                figa.add_trace(go.Scatter(
                    x=pd.to_datetime(tchart["날짜"]), y=tchart["총자산"],
                    mode="lines+markers", name="총자산",
                    line=dict(width=2, color="#2ca02c")))
                figa.update_layout(title="총자산 추이 (백만원)", height=280,
                                   margin=dict(l=40, r=20, t=40, b=20),
                                   hovermode="x unified")
                st.plotly_chart(figa, use_container_width=True)

            # ---- 종목별 자산 추세 ----
            pivot = journal.by_ticker(pdf)
            if not pivot.empty:
                st.markdown("##### 종목별 자산 추세")
                mode = st.radio(
                    "표시 방식", ["선 그래프", "누적 영역(구성)"],
                    horizontal=True, label_visibility="collapsed",
                    key="pf_chart_mode",
                )
                x = pd.to_datetime(pivot.index)
                figb = go.Figure()
                for name in pivot.columns:
                    if mode == "누적 영역(구성)":
                        figb.add_trace(go.Scatter(
                            x=x, y=pivot[name], mode="lines", name=name,
                            stackgroup="one", line=dict(width=1)))
                    else:
                        figb.add_trace(go.Scatter(
                            x=x, y=pivot[name], mode="lines+markers",
                            name=name, line=dict(width=2)))
                figb.update_layout(
                    height=340, margin=dict(l=40, r=20, t=20, b=20),
                    hovermode="x unified",
                    yaxis_title="금액 (백만원)",
                    legend=dict(orientation="h", yanchor="bottom",
                                y=1.02, xanchor="left", x=0),
                )
                st.plotly_chart(figb, use_container_width=True)
                if len(pivot) == 1:
                    st.caption("하루치라 점으로 표시됩니다. 날짜가 쌓이면 자동으로 추세선이 이어집니다.")

            # 전체 글 + 그날 보유내역 펼쳐보기
            st.markdown("##### 전체 내용 보기")
            for _, row in merged.iterrows():
                d = row["날짜"]
                tot = "" if pd.isna(row["총자산"]) else f"  ·  총자산 {row['총자산']:,.1f}백만"
                with st.expander(f"{d} — {row['핵심내용']}{tot}"):
                    jrow = jdf[jdf["날짜"] == d]
                    body = jrow["내용"].iloc[0] if len(jrow) else ""
                    st.write(body if str(body).strip() else "(일지 내용 없음)")
                    day_pf, is_own = journal.effective_snapshot(pdf, d)
                    if not day_pf.empty:
                        st.caption("보유내역 (백만원)" if is_own
                                   else "보유내역 (백만원) — 직전 기록 유지")
                        st.dataframe(day_pf, use_container_width=True, hide_index=True)

            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇️ 매매일지 CSV",
                jdf.to_csv(index=False).encode("utf-8-sig"),
                "매매일지.csv", "text/csv",
            )
            c2.download_button(
                "⬇️ 자산내역 CSV",
                pdf.to_csv(index=False).encode("utf-8-sig"),
                "자산운용내역.csv", "text/csv",
            )
