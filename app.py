# -*- coding: utf-8 -*-
"""
거시경제 대시보드 (Streamlit)
=====================================
실행:  streamlit run app.py
필요:  .env 에 FRED_API_KEY, ECOS_API_KEY 입력 (README 참고)
"""

import os
import io
from functools import partial

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
import ohlc
import scoring
import signals

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


def save_dart_cache(cmap, fin, year, rcode):
    """DART 재무·기업코드를 Dropbox에 보관 (분기마다 한 번만 갱신하면 됨).

    ★ 기존 보관본과 **합쳐서** 저장한다. 코스피만 받아두고 코스닥을 조회하면
      보관본에 코스닥 종목이 없어 결합이 비는 문제를 막기 위함.
    """
    mdf = pd.DataFrame({"종목코드": list(cmap.keys()), "corp_code": list(cmap.values())})
    journal.save_table(mdf, "dart_corpmap")

    fin = fin.copy()
    fin["corp_code"] = fin["corp_code"].astype(str).str.zfill(8)
    prev = journal.load_table(f"dart_fin_{year}_{rcode}")
    if prev is not None and not prev.empty and "corp_code" in prev.columns:
        prev = prev.copy()
        prev["corp_code"] = prev["corp_code"].astype(str).str.zfill(8)
        fin = (pd.concat([prev, fin], ignore_index=True)
               .drop_duplicates(subset=["corp_code"], keep="last"))
    journal.save_table(fin, f"dart_fin_{year}_{rcode}")


def load_dart_cache(year, rcode):
    """보관해 둔 DART 자료를 읽는다. 없으면 (None, None)."""
    mdf = journal.load_table("dart_corpmap")
    fin = journal.load_table(f"dart_fin_{year}_{rcode}")
    if mdf is None or fin is None or mdf.empty or fin.empty:
        return None, None
    cmap = dict(zip(mdf["종목코드"].astype(str).str.zfill(6),
                    mdf["corp_code"].astype(str).str.zfill(8)))
    fin["corp_code"] = fin["corp_code"].astype(str).str.zfill(8)
    return cmap, fin


def get_dart(year, rcode, codes_fn, progress=None):
    """DART 재무를 확보한다.

    ① 직접 조회(로컬에서 됨) → 성공하면 Dropbox에 보관
    ② 조회 불가(클라우드) → 보관해 둔 자료 사용
    반환: (corp_map, 재무DF, 안내문 or None)
    """
    try:
        cmap = dart_api.load_corp_map()
        fin = dart_api.fetch_financials(codes_fn(cmap), int(year), rcode,
                                        progress=progress)
        save_dart_cache(cmap, fin, year, rcode)
        return cmap, fin, None
    except dart_api.DartUnreachable:
        cmap, fin = load_dart_cache(year, rcode)
        if cmap is None:
            raise

        # 보관본이 이 시장 종목을 담고 있는지 확인 (다른 시장 것만 있으면 결합이 빈다)
        want = set(codes_fn(cmap))
        have = set(fin["corp_code"]) if not fin.empty else set()
        covered = len(want & have)
        if want and covered / len(want) < 0.3:
            raise dart_api.DartUnreachable(
                f"보관된 재무에 이 시장 종목이 거의 없습니다 "
                f"({covered}/{len(want)}건).\n\n"
                "**Streamlit Cloud에서는 DART에 접속할 수 없습니다.** "
                "이 시장은 아직 로컬에서 한 번도 수집하지 않아 보관본이 없습니다.\n\n"
                "➡️ **내 PC에서** `거시경제대시보드_실행하기.bat` 를 실행하고, "
                "이 시장을 골라 `API로 불러오기` 를 **한 번만** 눌러주세요. "
                "그 뒤로는 클라우드에서도 됩니다.")

        return cmap, fin, (
            f"DART에 직접 접속할 수 없어 **보관된 재무({year}년)** 를 사용했습니다"
            f"(이 시장 {covered}/{len(want)}종목). "
            "주가·시가총액은 방금 KRX에서 받은 최신 값입니다.")


def _q_table(df, keep_quadrant=False):
    """4분면 화면·다운로드에서 공통으로 쓰는 표 모양 정리."""
    cols = (["분면"] if keep_quadrant and "분면" in df.columns else []) + \
           ["종목명", "업종", "ROE", "PBR"]
    out = df[[c for c in cols if c in df.columns]].copy()
    out["ROE"] = out["ROE"].round(2)
    out["PBR"] = out["PBR"].round(2)
    if "시가총액" in df.columns:
        out["시가총액(억)"] = (df["시가총액"] / 1e8).round(0)
    return out.reset_index(drop=True)


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
(tab_screen, tab_candle, tab_graph, tab_combo, tab_table,
 tab_rule, tab_roepbr, tab_sector, tab_journal) = st.tabs(
    ["🎯 매수 후보", "🕯️ 종목 캔들차트", "📈 그래프", "📈 시장·환율·금리차",
     "📋 일별 테이블", "📖 점수 기준", "📉 ROE·PBR 분석",
     "🏭 업종별 자금흐름", "📝 매매일지"]
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

    mkt = st.radio("시장 선택", list(krx_api.MARKETS.keys()),
                   horizontal=True, key="roepbr_market")
    if krx_api.MARKETS[mkt].get("note"):
        st.caption(f"ℹ️ {krx_api.MARKETS[mkt]['note']}")
    KEY_STOCKS = f"roe_pbr_stocks_{mkt}"
    KEY_INDEX = f"roe_pbr_index_{mkt}"

    sub1, sub2 = st.tabs([f"종목별 ROE-PBR ({mkt})", f"{mkt}지수 - PBR"])

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
                            kdf, basdd = krx_api.fetch_latest_stock_daily(market=mkt)
                        st.caption(f"KRX 기준일: {basdd} · {len(kdf):,}개 종목")

                        bar = st.progress(0.0, text="DART 재무 조회 중...")
                        cmap, fin, note = get_dart(
                            year, rcode,
                            lambda m: [m[c] for c in kdf["종목코드"] if c in m],
                            progress=lambda d, t: bar.progress(
                                d / t, text=f"DART 재무 조회 중... {d}/{t}"))
                        bar.empty()
                        if note:
                            st.info(note)

                        annf = ((lambda p: dart_api.annualize_profit(p, rcode))
                                if ann else None)
                        built = equity.build_from_api(kdf, fin, cmap, annualize=annf)
                        if built.empty:
                            st.error("결합 결과가 비었습니다. 연도·보고서를 바꿔보세요.")
                        else:
                            journal.save_table(built, KEY_STOCKS)
                            st.session_state[f"roepbr_api_{mkt}"] = built
                            st.success(f"{len(built):,}개 종목 완성 "
                                       f"(KRX {basdd} 시총 ÷ DART {year}년 {rname})")
                    except PermissionError as e:
                        st.error(str(e))
                    except dart_api.DartUnreachable as e:
                        st.error(str(e))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"수집 중 오류: {e}")

                sdf = st.session_state.get(f"roepbr_api_{mkt}")
                if sdf is None:
                    saved = journal.load_table(KEY_STOCKS)
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
                ok, err = journal.save_table(sdf, KEY_STOCKS)
                st.success(f"{len(sdf)}개 종목을 읽었습니다. {note}"
                           + ("" if ok else f" (보관 실패: {err})"))
            except Exception as e:  # noqa: BLE001
                st.error(f"파일을 읽지 못했습니다: {e}")
        elif src == "파일 업로드":
            saved = journal.load_table(KEY_STOCKS)
            if saved is not None and not saved.empty:
                sdf = saved
                st.info("이전에 올린 자료를 사용 중입니다. 새 파일을 올리면 갱신됩니다.")

        if sdf is None or sdf.empty:
            st.warning("아직 자료가 없습니다. 위에서 API로 불러오거나 파일을 올려주세요.")
        else:
            # --- 업종 분류 붙이기 (KRX 업종분류 현황 업로드) ---
            with st.expander("🏭 업종 분류 붙이기 (선택)"):
                st.caption(
                    "KRX 정보데이터시스템 → [업종분류 현황] 엑셀을 올리면 "
                    "종목마다 업종이 붙어 **업종별로 걸러 보거나 색으로 구분**할 수 있습니다. "
                    "한 번 올리면 보관되어 다시 올릴 필요가 없습니다."
                )
                up_sec = st.file_uploader("업종분류 현황 (엑셀/CSV)",
                                          type=["xlsx", "xls", "csv"],
                                          key=f"up_sector_{mkt}")
                if up_sec is not None:
                    try:
                        smap, skey = equity.parse_sector_map(equity.read_table(up_sec))
                        journal.save_table(smap, f"sector_map_{mkt}")
                        st.success(f"{len(smap):,}개 종목의 업종을 읽었습니다 "
                                   f"({skey} 기준, 업종 {smap['업종'].nunique()}종).")
                    except Exception as e:  # noqa: BLE001
                        st.error(f"읽지 못했습니다: {e}")

            smap_saved = journal.load_table(f"sector_map_{mkt}")
            if smap_saved is not None and not smap_saved.empty:
                sdf, matched, used_key = equity.attach_sector(sdf, smap_saved)
                secs = sorted(s for s in sdf["업종"].unique() if s != "미분류")
                if secs:
                    pick_sec = st.multiselect(
                        f"업종으로 걸러 보기 (전체 {len(secs)}종 · "
                        f"{used_key} 기준 매칭 {matched:,}/{len(sdf):,}종목)",
                        secs, key=f"sec_filter_{mkt}")
                    if pick_sec:
                        sdf = sdf[sdf["업종"].isin(pick_sec)]
                        st.caption(f"선택한 업종 {len(pick_sec)}개 · {len(sdf):,}종목만 분석합니다.")
                else:
                    # 전부 미분류면 왜 그런지 알려준다 (조용히 넘어가지 않게)
                    st.warning(
                        "업종이 하나도 붙지 않았습니다. "
                        f"분석표 컬럼={list(sdf.columns)[:4]}, "
                        f"업종맵 컬럼={list(smap_saved.columns)}\n\n"
                        "→ **`🔄 API로 불러오기`** 를 한 번 눌러 자료를 새로 받거나, "
                        "업종분류 엑셀을 다시 올려주세요. "
                        "(예전에 저장된 자료에는 종목코드가 없어 이어붙일 수 없습니다)")

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
                hint = " (코스피200 근사)" if mkt == "코스피" and topn == 200 else ""
                st.caption(f"{mkt} 중 시가총액 상위 {topn}개 종목으로 분석합니다{hint}.")
            else:
                use = filt.reset_index(drop=True)
                st.caption(f"{len(use)}개 종목 전체로 분석합니다.")

            view = st.radio(
                "보기 방식",
                ["개별 종목", "ROE 구간 평균 (추세 뚜렷)", "🎯 4분면 분석"],
                horizontal=True, key="roepbr_view",
            )

            # ---- 4분면 분석 (수익성 × 밸류에이션) ----
            if view.startswith("🎯"):
                q1, q2 = st.columns(2)
                cut_mode = q1.radio("기준선", ["중앙값 (시장 대비)", "직접 지정"],
                                    key="q_cut_mode")
                if cut_mode == "직접 지정":
                    rc = q2.number_input("ROE 기준 (%)", value=10.0, step=1.0)
                    pc = q2.number_input("PBR 기준 (배)", value=1.0, step=0.1)
                else:
                    rc = pc = None
                    q2.caption("분석 대상의 ROE·PBR 중앙값을 기준선으로 씁니다. "
                               "즉 '시장 평균보다 좋은가/싼가'로 나눕니다.")

                try:
                    qd, roe_cut, pbr_cut = equity.quadrants(use, rc, pc)

                    c1, c2 = st.columns(2)
                    c1.metric("ROE 기준선", f"{roe_cut:.2f} %")
                    c2.metric("PBR 기준선", f"{pbr_cut:.2f} 배")

                    figq = go.Figure()
                    for qname in equity.QUADRANT_ORDER:
                        sub = qd[qd["분면"] == qname]
                        if sub.empty:
                            continue
                        info = equity.QUADRANT_INFO[qname]
                        figq.add_trace(go.Scatter(
                            x=sub["ROE"], y=sub["PBR"], mode="markers",
                            name=f"{qname} ({len(sub)})",
                            marker=dict(size=8, color=info["color"], opacity=0.75),
                            text=sub["종목명"],
                            hovertemplate="%{text}<br>ROE %{x:.2f}%<br>PBR %{y:.2f}"
                                          "<extra></extra>"))

                    # 기준선
                    figq.add_vline(x=roe_cut, line_dash="dash", line_color="gray")
                    figq.add_hline(y=pbr_cut, line_dash="dash", line_color="gray")

                    # 각 분면 이름을 모서리에 표시
                    xr = [qd["ROE"].min(), qd["ROE"].max()]
                    yr = [qd["PBR"].min(), qd["PBR"].max()]
                    corners = [
                        (equity.Q_GOOD_CHEAP, xr[1], yr[0], "right", "bottom"),
                        (equity.Q_GOOD_RICH, xr[1], yr[1], "right", "top"),
                        (equity.Q_WEAK_CHEAP, xr[0], yr[0], "left", "bottom"),
                        (equity.Q_WEAK_RICH, xr[0], yr[1], "left", "top"),
                    ]
                    for qname, xa, ya, xanc, yanc in corners:
                        figq.add_annotation(
                            x=xa, y=ya, text=f"<b>{qname}</b>", showarrow=False,
                            xanchor=xanc, yanchor=yanc,
                            font=dict(size=12, color=equity.QUADRANT_INFO[qname]["color"]),
                            bgcolor="rgba(255,255,255,0.65)")

                    figq.update_layout(
                        height=520, margin=dict(l=50, r=20, t=30, b=40),
                        xaxis_title="ROE (%) — 수익성 →",
                        yaxis_title="PBR (배) — 밸류에이션 ↑",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                    xanchor="left", x=0))
                    st.plotly_chart(figq, use_container_width=True)

                    # 분면별 설명 + 종목 목록
                    st.markdown("##### 각 분면의 뜻과 해당 종목")
                    for qname in equity.QUADRANT_ORDER:
                        info = equity.QUADRANT_INFO[qname]
                        sub = qd[qd["분면"] == qname].sort_values(
                            "시가총액" if "시가총액" in qd.columns else "ROE",
                            ascending=False)
                        st.markdown(
                            f"<div style='background:{info['color']}22;"
                            f"border-left:5px solid {info['color']};"
                            f"padding:10px 14px;margin:6px 0;border-radius:6px;'>"
                            f"<b>{qname}</b> · {info['pos']} · <b>{len(sub)}개</b><br>"
                            f"{info['desc']}</div>", unsafe_allow_html=True)
                        if not sub.empty:
                            with st.expander(f"{qname} 종목 보기 ({len(sub)}개)"):
                                show = _q_table(sub)
                                st.dataframe(show, use_container_width=True,
                                             hide_index=True)
                                st.download_button(
                                    f"⬇️ {qname} {len(sub)}개 CSV",
                                    show.to_csv(index=False).encode("utf-8-sig"),
                                    f"4분면_{qname}.csv", "text/csv",
                                    key=f"q_dl_{qname}")

                    # ---- 전체 다운로드 (엑셀: 분면별 시트 / CSV: 한 장) ----
                    st.markdown("###### 전체 내려받기")
                    d1, d2 = st.columns(2)

                    xbuf2 = io.BytesIO()
                    with pd.ExcelWriter(xbuf2, engine="openpyxl") as writer:
                        summary = pd.DataFrame([
                            {"분면": q,
                             "위치": equity.QUADRANT_INFO[q]["pos"],
                             "종목수": int((qd["분면"] == q).sum()),
                             "설명": equity.QUADRANT_INFO[q]["desc"]}
                            for q in equity.QUADRANT_ORDER
                        ])
                        summary.to_excel(writer, sheet_name="요약", index=False)
                        for q in equity.QUADRANT_ORDER:
                            sub_q = qd[qd["분면"] == q]
                            if sub_q.empty:
                                continue
                            sub_q = sub_q.sort_values(
                                "시가총액" if "시가총액" in qd.columns else "ROE",
                                ascending=False)
                            _q_table(sub_q).to_excel(
                                writer, sheet_name=q[:31], index=False)
                    d1.download_button(
                        "⬇️ 엑셀 (분면별 시트)", xbuf2.getvalue(),
                        f"ROE_PBR_4분면_{pd.Timestamp.today():%Y%m%d}.xlsx",
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet", key="q_dl_xlsx")

                    all_tbl = _q_table(qd.sort_values(
                        "시가총액" if "시가총액" in qd.columns else "ROE",
                        ascending=False), keep_quadrant=True)
                    d2.download_button(
                        "⬇️ 전체 CSV (한 장)",
                        all_tbl.to_csv(index=False).encode("utf-8-sig"),
                        f"ROE_PBR_4분면_{pd.Timestamp.today():%Y%m%d}.csv",
                        "text/csv", key="q_dl")
                    st.caption("엑셀 파일은 '요약' 시트에 각 분면의 뜻과 종목수가, "
                               "나머지 시트에 분면별 종목이 들어 있습니다.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"4분면 계산 중 문제: {e}")
                use = None   # 아래 개별 종목 화면은 생략

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

    # ---------------- 시장 대표지수 vs PBR ----------------
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
                    f"월말마다 **{mkt} 시가총액 합 ÷ 자본총계 합**으로 PBR을 계산합니다. "
                    "각 시점에는 그때 이미 공시돼 있던 재무만 사용합니다."
                )

                # 어떤 지수를 y축에 놓을지 선택 (코스닥은 종합/150 지수 값이 다름)
                idx_opts = krx_api.MARKETS[mkt].get(
                    "index_options", [krx_api.MARKETS[mkt]["index_name"]])
                if len(idx_opts) > 1:
                    idx_name = st.selectbox(
                        "표시할 지수", idx_opts, index=0, key="idx_name_sel",
                        help="종목 범위와 같은 지수를 쓰는 것이 맞지만, "
                             "익숙한 종합지수로 보고 싶으면 바꾸세요.")
                    if idx_name != idx_opts[0]:
                        st.warning(
                            f"PBR은 **{mkt}** 종목으로 계산되는데 지수는 "
                            f"**{idx_name}**입니다. 범위가 달라 해석에 주의하세요.")
                else:
                    idx_name = idx_opts[0]
                st.caption(f"y축 지수: **{idx_name}**")

                yb = st.slider("몇 년치를 모을까요?", 1, 6, 3, key="idx_years")
                st.caption(f"약 {yb*12}개 시점 × 2회 조회 → **{yb*12*4//60}분 내외** 걸립니다.")

                if st.button("🔄 API로 불러오기", type="primary", key="idx_fetch"):
                    try:
                        dates = krx_api.month_end_dates(yb)
                        # 월말 목록에 오늘(최근 영업일)이 없으면 마지막에 추가
                        today = pd.Timestamp.today().normalize()
                        if not dates or (today - dates[-1]).days > 3:
                            dates.append(today)
                        # 종목 목록(최근 시점 기준)으로 필요한 사업연도별 재무를 미리 확보
                        with st.spinner("최근 종목 목록을 받는 중..."):
                            latest_k, _ = krx_api.fetch_latest_stock_daily(market=mkt)

                        years = sorted({equity.fiscal_year_for(d) for d in dates})
                        fin_by_year = {}
                        cmap = None
                        notes = []
                        fb = st.progress(0.0, text="DART 재무 준비 중...")
                        for i, y in enumerate(years):
                            cmap, fin_y, note = get_dart(
                                y, "11011",
                                lambda m: [m[c] for c in latest_k["종목코드"] if c in m])
                            fin_by_year[y] = fin_y
                            if note:
                                notes.append(note)
                            fb.progress((i + 1) / len(years),
                                        text=f"DART 재무 준비 중... {y}년 ({i+1}/{len(years)})")
                        fb.empty()
                        if notes:
                            st.info(notes[0])

                        rows = []
                        pb = st.progress(0.0, text="시점별 수집 중...")
                        for i, d in enumerate(dates):
                            kdf_d, used = krx_api.fetch_near(
                                partial(krx_api.fetch_stock_daily, market=mkt), d)
                            if used is None:
                                continue
                            idx_d, _ = krx_api.fetch_near(
                                partial(krx_api.fetch_index, market=mkt,
                                        index_name=idx_name), used)
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
                            journal.save_table(got, KEY_INDEX)
                            st.session_state[f"idx_api_{mkt}"] = got
                            st.success(f"{len(got)}개 시점을 수집했습니다.")
                    except PermissionError as e:
                        st.error(str(e))
                    except dart_api.DartUnreachable as e:
                        st.error(str(e))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"수집 중 오류: {e}")

                idf = st.session_state.get(f"idx_api_{mkt}")
                if idf is None:
                    saved2 = journal.load_table(KEY_INDEX)
                    if saved2 is not None and not saved2.empty:
                        if "날짜" in saved2.columns:
                            idf = saved2.copy()
                            idf["날짜"] = pd.to_datetime(idf["날짜"], errors="coerce")
                            st.info("이전에 수집한 자료를 보여줍니다. 위 버튼으로 갱신하세요.")
                        else:
                            # 날짜가 없는 예전 업로드 자료 = 하루치 여러 지수 목록
                            st.warning(
                                "저장된 자료에 날짜가 없어 사용할 수 없습니다. "
                                "(예전에 '하루치 전체 지수 목록'을 올리신 것으로 보입니다) "
                                "위 **🔄 API로 불러오기** 를 눌러 새로 모아주세요.")

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
                ok, err = journal.save_table(idf, KEY_INDEX)
                st.success(f"{len(idf)}일치 자료를 읽었습니다."
                           + ("" if ok else f" (보관 실패: {err})"))
            except Exception as e:  # noqa: BLE001
                st.error(f"파일을 읽지 못했습니다: {e}")
        elif src2 == "파일 업로드":
            saved2 = journal.load_table(KEY_INDEX)
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

                has_date = "날짜" in idf.columns
                dstr = (idf["날짜"].dt.strftime("%y.%m") if has_date else None)

                figi = go.Figure()
                # 시간 순서대로 이어 그려 '시장이 지나온 길'이 보이게 한다
                figi.add_trace(go.Scatter(
                    x=idf["PBR"], y=idf["지수"], mode="lines+markers", name="시점별(시간순)",
                    line=dict(width=1, color="#b0c4de"),
                    marker=dict(size=8, color=list(range(len(idf))),
                                colorscale="Blues", showscale=False,
                                line=dict(width=1, color="#4c78a8")),
                    text=(idf["날짜"].dt.strftime("%Y-%m-%d") if has_date else None),
                    hovertemplate="%{text}<br>PBR %{x:.2f}<br>지수 %{y:,.0f}<extra></extra>"))

                xs2, ys2 = equity.fit_line(fit2, idf["PBR"])
                figi.add_trace(go.Scatter(x=xs2, y=ys2, mode="lines", name="회귀선",
                                          line=dict(width=3, color="#e74c3c")))

                # 최근(오늘) 지점 강조
                figi.add_trace(go.Scatter(
                    x=[latest["PBR"]], y=[latest["지수"]], mode="markers+text",
                    name="최근(오늘)",
                    marker=dict(size=18, color="#d62728",
                                line=dict(width=2, color="white")),
                    text=[f"오늘 {latest['날짜'].strftime('%Y-%m-%d')}" if has_date else "최근"],
                    textposition="top center",
                    textfont=dict(size=13, color="#d62728")))

                # 주요 시점(PBR 최고/최저, 지수 최고) 날짜 표시
                if has_date and len(idf) >= 3:
                    marks = {
                        "PBR 최고": idf.loc[idf["PBR"].idxmax()],
                        "PBR 최저": idf.loc[idf["PBR"].idxmin()],
                        "지수 최고": idf.loc[idf["지수"].idxmax()],
                    }
                    seen = set()
                    mx, my, mt = [], [], []
                    for label, row in marks.items():
                        key = row["날짜"]
                        if key in seen or key == latest["날짜"]:
                            continue
                        seen.add(key)
                        mx.append(row["PBR"]); my.append(row["지수"])
                        mt.append(f"{label} {row['날짜'].strftime('%y.%m')}")
                    if mx:
                        figi.add_trace(go.Scatter(
                            x=mx, y=my, mode="markers+text", name="주요 시점",
                            marker=dict(size=13, color="#ff7f0e",
                                        line=dict(width=1, color="white")),
                            text=mt, textposition="bottom center",
                            textfont=dict(size=11, color="#b35900")))

                figi.update_layout(
                    height=460, margin=dict(l=60, r=20, t=30, b=40),
                    xaxis_title="PBR (배) — 오른쪽일수록 비쌈",
                    yaxis_title=f"{mkt}지수",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                xanchor="left", x=0))
                st.plotly_chart(figi, use_container_width=True)

                # ---- 쉬운 설명 ----
                if has_date:
                    first, last = idf.iloc[0], idf.iloc[-1]
                    pmax = idf.loc[idf["PBR"].idxmax()]
                    pmin = idf.loc[idf["PBR"].idxmin()]
                    st.markdown(f"""
##### 📖 이 그래프가 말해주는 것

**PBR이 뭔가요?** 시장 전체를 하나의 회사로 봤을 때, **장부상 순자산(자본)의 몇 배**에
거래되고 있는지를 뜻합니다. `PBR = 시가총액 합계 ÷ 자본총계 합계`

- **PBR 1배** = 시장이 회사들의 순자산만큼만 값을 매김 (싼 편)
- **PBR 2배** = 순자산의 2배를 주고 사고 있음 (비싼 편)

**지금 상황 ({last['날짜'].strftime('%Y년 %m월 %d일')} 기준)**

| 항목 | 값 |
|---|---|
| 오늘 코스피 | **{last['지수']:,.0f}** |
| 오늘 시장 PBR | **{last['PBR']:.2f}배** |
| 기간 중 가장 비쌌을 때 | {pmax['PBR']:.2f}배 ({pmax['날짜'].strftime('%Y년 %m월')}) |
| 기간 중 가장 쌌을 때 | {pmin['PBR']:.2f}배 ({pmin['날짜'].strftime('%Y년 %m월')}) |
| 처음({first['날짜'].strftime('%y년 %m월')}) 대비 | PBR {first['PBR']:.2f} → {last['PBR']:.2f}배 |

**어떻게 읽나요?**

1. **점은 시간 순서로 이어져 있습니다.** 연한 점이 과거, 진한 점이 최근이고,
   빨간 큰 점이 **오늘**입니다. 선을 따라가면 시장이 지나온 길이 보입니다.
2. **오른쪽으로 갈수록 비싸진 것**입니다. PBR이 {first['PBR']:.2f}배에서
   {last['PBR']:.2f}배로 {'올랐다면' if last['PBR']>first['PBR'] else '내렸다면'}
   같은 순자산에 대해 시장이 {'더 비싸게' if last['PBR']>first['PBR'] else '더 싸게'}
   값을 매기고 있다는 뜻입니다.
3. **빨간 회귀선은 평균적인 관계**입니다. 점이 선보다 위에 있으면 그 시점 지수가
   PBR로 설명되는 수준보다 높았다는 뜻입니다.

**⚠️ 주의**: 지수와 PBR은 둘 다 시가총액에서 나오기 때문에 서로 붙어 움직이는 게
당연합니다. 그래서 이 그래프는 **지수를 예측하는 용도가 아니라**, "지금 시장이
순자산 대비 얼마나 비싼가"를 **역사적으로 비교**하는 용도로 보셔야 합니다.
""")

                if "날짜" in idf.columns:
                    figt = make_subplots(specs=[[{"secondary_y": True}]])
                    figt.add_trace(go.Scatter(x=idf["날짜"], y=idf["지수"], mode="lines",
                                              name=f"{mkt}지수",
                                              line=dict(width=2, color="#1f77b4")), False)
                    figt.add_trace(go.Scatter(x=idf["날짜"], y=idf["PBR"], mode="lines",
                                              name="PBR",
                                              line=dict(width=2, color="#ff7f0e")), True)
                    figt.update_layout(title="지수 · PBR 시계열", height=340,
                                       margin=dict(l=50, r=50, t=40, b=20),
                                       hovermode="x unified",
                                       legend=dict(orientation="h", yanchor="bottom",
                                                   y=1.02, xanchor="left", x=0))
                    figt.update_yaxes(title_text=f"{mkt}지수", secondary_y=False)
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

with tab_sector:
    st.markdown("#### 🏭 업종별 자금흐름")
    st.caption(
        "KRX 업종지수의 **거래대금·시가총액**을 6개월 간격으로 모아 "
        "어느 업종에 돈이 몰리는지 봅니다. "
        "상위분류(제조·증권·보험)는 중복이라 빼고 세부 업종만 씁니다."
    )

    smkt = st.radio("시장", list(krx_api.MARKETS.keys()),
                    horizontal=True, key="sector_market")
    SEC_KEY = f"sector_flow_{smkt}"

    # 간격: 주 단위와 월 단위를 함께 제공
    GAPS = {
        "1주": ("W", 1), "2주": ("W", 2), "1개월": ("M", 1),
        "3개월": ("M", 3), "6개월": ("M", 6), "1년": ("M", 12),
    }
    c1, c2 = st.columns(2)
    syb = c1.slider("몇 년치를 모을까요?", 1, 6, 3, key="sector_years")
    gap_label = c2.selectbox("간격", list(GAPS.keys()), index=4, key="sector_gap")
    gap_unit, gap_n = GAPS[gap_label]

    # 예상 시점 수·소요시간 미리 알려주기 (주 단위는 호출이 많아짐)
    _preview = krx_api.period_end_dates(
        syb, months=gap_n if gap_unit == "M" else 6,
        weeks=gap_n if gap_unit == "W" else None)
    st.caption(f"{gap_label} 간격 · 약 **{len(_preview)}개 시점** "
               f"(예상 {max(1, round(len(_preview) * 0.15))}초 내외)")

    if not krx_api.get_key():
        st.error("KRX_API_KEY 가 없습니다.")
    else:
        if st.button("🔄 업종 자료 불러오기", type="primary", key="sector_fetch"):
            try:
                dates = krx_api.period_end_dates(
                    syb, months=gap_n if gap_unit == "M" else 6,
                    weeks=gap_n if gap_unit == "W" else None)
                rows = []
                pb = st.progress(0.0, text="업종 자료 수집 중...")
                for i, d in enumerate(dates):
                    sec, used = krx_api.fetch_near(
                        partial(krx_api.fetch_sectors, market=smkt), d)
                    if used is not None and not sec.empty:
                        sec = sec.copy()
                        sec["날짜"] = pd.to_datetime(used)
                        rows.append(sec)
                    pb.progress((i + 1) / len(dates),
                                text=f"업종 자료 수집 중... {i+1}/{len(dates)}")
                pb.empty()
                if not rows:
                    st.error("수집된 시점이 없습니다.")
                else:
                    got = pd.concat(rows, ignore_index=True)
                    journal.save_table(got, SEC_KEY)
                    st.session_state[SEC_KEY] = got
                    st.success(f"{got['날짜'].nunique()}개 시점 · "
                               f"업종 {got['업종'].nunique()}개 수집 완료")
            except PermissionError as e:
                st.error(str(e))
            except Exception as e:  # noqa: BLE001
                st.error(f"수집 중 오류: {e}")

        sec_df = st.session_state.get(SEC_KEY)
        if sec_df is None:
            saved = journal.load_table(SEC_KEY)
            if saved is not None and not saved.empty:
                sec_df = saved.copy()
                sec_df["날짜"] = pd.to_datetime(sec_df["날짜"], errors="coerce")
                st.info("이전에 수집한 자료입니다. 위 버튼으로 갱신하세요.")

        if sec_df is None or sec_df.empty:
            st.warning("아직 자료가 없습니다. 위 버튼을 눌러 불러오세요.")
        else:
            m1, m2 = st.columns([1, 1])
            metric = m1.radio("볼 지표", ["거래대금", "시가총액"],
                              horizontal=True, key="sector_metric")
            SHOW = {"최근 3개월": 3, "최근 6개월": 6, "최근 1년": 12,
                    "최근 3년": 36, "전체": None}
            show_label = m2.selectbox("표시 기간", list(SHOW.keys()), index=1,
                                      key="sector_show",
                                      help="수집한 자료 중 화면에 보여줄 구간만 고릅니다. "
                                           "다시 수집할 필요는 없습니다.")

            piv = (sec_df.pivot_table(index="날짜", columns="업종",
                                      values=metric, aggfunc="sum")
                   .fillna(0.0).sort_index())

            # 표시 기간으로 자르기 (수집 자료는 그대로 두고 보기만 좁힌다)
            months = SHOW[show_label]
            if months is not None and not piv.empty:
                cut = piv.index.max() - pd.DateOffset(months=months)
                trimmed = piv[piv.index >= cut]
                if len(trimmed) >= 2:
                    piv = trimmed
                else:
                    st.caption(f"{show_label} 안에 시점이 부족해 전체를 보여줍니다.")
            st.caption(f"화면에 표시 중: {len(piv)}개 시점 "
                       f"({piv.index.min():%Y-%m-%d} ~ {piv.index.max():%Y-%m-%d})")

            share = piv.div(piv.sum(axis=1), axis=0) * 100

            latest_d = piv.index[-1]
            topn = st.slider("상위 몇 개 업종을 볼까요?", 3,
                             min(20, len(piv.columns)),
                             min(8, len(piv.columns)), key="sector_topn")
            order = piv.loc[latest_d].sort_values(ascending=False)
            picks = list(order.head(topn).index)

            unit = 1e12
            st.markdown(f"##### 최근 시점({latest_d:%Y-%m-%d}) 업종 순위")
            bar = go.Figure(go.Bar(
                x=(order.head(topn) / unit)[::-1].values,
                y=order.head(topn).index[::-1], orientation="h",
                marker_color="#4575b4",
                text=[f"{v/unit:,.2f}조" for v in order.head(topn).values][::-1],
                textposition="auto"))
            bar.update_layout(height=max(260, 34 * topn + 90),
                              margin=dict(l=40, r=20, t=20, b=30),
                              xaxis_title=f"{metric} (조원)")
            st.plotly_chart(bar, use_container_width=True)

            mode = st.radio("추이 보기", ["금액(조원)", "비중(%)"],
                            horizontal=True, key="sector_mode")
            figs = go.Figure()
            for name in picks:
                if mode.startswith("비중"):
                    figs.add_trace(go.Scatter(
                        x=share.index, y=share[name], mode="lines",
                        name=name, stackgroup="one", line=dict(width=1)))
                else:
                    figs.add_trace(go.Scatter(
                        x=piv.index, y=piv[name] / unit, mode="lines+markers",
                        name=name, line=dict(width=2)))
            figs.update_layout(
                height=420, margin=dict(l=50, r=20, t=20, b=30),
                hovermode="x unified",
                yaxis_title="비중 (%)" if mode.startswith("비중") else f"{metric} (조원)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="left", x=0))
            st.plotly_chart(figs, use_container_width=True)

            # 처음 대비 비중 변화 = 자금이 어디로 옮겨갔나
            if len(share) >= 2:
                delta = (share.iloc[-1] - share.iloc[0]).sort_values(ascending=False)
                st.markdown(
                    f"##### 자금 이동 ({share.index[0]:%y년 %m월} → "
                    f"{share.index[-1]:%y년 %m월}, 비중 변화)")
                d1, d2 = st.columns(2)
                d1.markdown("**비중이 늘어난 업종**")
                d1.dataframe(delta.head(5).round(2).rename("변화(%p)").reset_index(),
                             use_container_width=True, hide_index=True)
                d2.markdown("**비중이 줄어든 업종**")
                d2.dataframe(delta.tail(5).round(2).rename("변화(%p)").reset_index(),
                             use_container_width=True, hide_index=True)

            with st.expander("📋 전체 표 보기 / 내려받기"):
                show = (piv / unit).round(3)
                show.index = show.index.strftime("%Y-%m-%d")
                st.dataframe(show, use_container_width=True)
                xb = io.BytesIO()
                with pd.ExcelWriter(xb, engine="openpyxl") as w:
                    show.to_excel(w, sheet_name=f"{metric}(조원)")
                    share.round(2).set_index(
                        share.index.strftime("%Y-%m-%d")).to_excel(w, sheet_name="비중(%)")
                st.download_button(
                    "⬇️ 엑셀 (금액·비중)", xb.getvalue(),
                    f"업종별_{metric}_{smkt}_{pd.Timestamp.today():%Y%m%d}.xlsx",
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet", key="sector_xlsx")

    with st.expander("ℹ️ 종목별 업종 분류는 왜 없나요?"):
        st.markdown(
            "**KRX OpenAPI에는 '어느 종목이 어느 업종인지' 알려주는 서비스가 없습니다.**\n\n"
            "- 위 업종별 집계는 KRX가 이미 계산해 발표하는 **업종지수**에서 가져온 것이라 "
            "종목을 일일이 분류할 필요가 없고, KRX 공식 수치라 더 정확합니다.\n"
            "- 종목별 분류가 필요하면 `유가증권/코스닥 종목기본정보` 서비스를 "
            "**이용신청**해야 합니다(openapi.krx.co.kr, 승인 ~1일). "
            "다만 그 서비스에 업종 항목이 있는지는 승인 후에야 확인됩니다.\n"
            "- 안 되면 data.krx.co.kr 의 **[업종분류 현황]** 엑셀을 받아 올리는 방식으로 "
            "붙일 수 있습니다."
        )

with tab_screen:
    st.markdown("#### 🎯 매수 후보 스크리닝")
    st.caption(
        "**재무(ROE·PBR)로 거른 뒤 → 차트 조건(주봉·일봉·60분봉)을 확인**해 "
        "매수 우선순위대로 정렬합니다."
    )

    smk = st.radio("시장", list(krx_api.MARKETS.keys()),
                   horizontal=True, key="screen_market")
    base = journal.load_table(f"roe_pbr_stocks_{smk}")

    if base is None or base.empty:
        st.warning("먼저 **📉 ROE·PBR 분석** 탭에서 자료를 불러와 주세요.")
    elif "종목코드" not in base.columns:
        st.warning("저장된 자료에 종목코드가 없습니다. "
                   "ROE·PBR 탭에서 `🔄 API로 불러오기` 를 한 번 눌러주세요.")
    else:
        base = base.copy()
        base["종목코드"] = (base["종목코드"].astype(str)
                        .str.replace(r"\D", "", regex=True).str.zfill(6))

        # 대상 종목군: 두 시장 모두 시가총액 상위 200종목
        #  ※ KRX OpenAPI에 지수 구성종목 서비스가 없어 시가총액 상위로 근사한다.
        UNIVERSE = {"코스피": ("코스피200", 200), "코스닥": ("코스닥 시총 200", 200)}
        uni_name, uni_n = UNIVERSE.get(smk, (smk, None))
        if uni_n and "시가총액" in base.columns and len(base) > uni_n:
            base = base.nlargest(uni_n, "시가총액").reset_index(drop=True)
            st.caption(f"대상: **{uni_name}** (시가총액 상위 {uni_n}종목으로 근사) "
                       f"— 구성종목 명단은 KRX API가 제공하지 않습니다.")
        else:
            st.caption(f"대상: **{uni_name}** {len(base)}종목")

        st.markdown("##### 1단계 · 재무 조건")
        f1, f2, f3 = st.columns(3)
        pbr_max = f1.number_input("PBR 이하", 0.1, 50.0, 5.0, 0.5, key="sc_pbr")
        roe_min = f2.number_input("ROE 이상 (%)", -50.0, 100.0, 10.0, 1.0, key="sc_roe")
        top_n = f3.number_input("최대 검사 종목 수", 5, 200, 40, 5, key="sc_topn",
                                help="종목마다 시세를 받아야 해서, 많을수록 오래 걸립니다.")

        cand = base[(base["PBR"] <= pbr_max) & (base["ROE"] >= roe_min)].copy()
        if "시가총액" in cand.columns:
            cand = cand.sort_values("시가총액", ascending=False)
        cand = cand.head(int(top_n))
        passed = len(base[(base["PBR"] <= pbr_max) & (base["ROE"] >= roe_min)])
        st.caption(f"{uni_name} {len(base):,}종목 중 재무 조건 통과 **{passed:,}종목** → "
                   f"시가총액 상위 **{len(cand)}종목** 검사 "
                   f"(예상 {max(1, round(len(cand) * 1.6))}초).")

        with st.expander("⚙️ 2단계 · 차트 조건 세부설정"):
            eps = st.slider("기울기 판정 기준 (봉당 %)", 0.01, 0.30,
                            float(signals.FLAT_EPS), 0.01, key="sc_eps",
                            help="이 값 안쪽이면 '평평', 넘으면 '상승/하락'으로 봅니다. "
                                 "작게 잡을수록 엄격해집니다.")
            dmin, dmax = st.slider("일봉 연속 음봉 개수", 1, 8, (3, 4), key="sc_down")
            b1, b2, b3 = st.columns(3)
            sc_bbp = b1.number_input("볼린저 기간(일봉)", 5, 60,
                                     int(signals.BB_PERIOD), 1, key="sc_bbp")
            sc_bbk = b2.number_input("볼린저 배수", 1.0, 4.0,
                                     float(signals.BB_K), 0.1, key="sc_bbk")
            sc_bbpos = b3.slider("밴드 하단 기준 (%B 이하)", 0.0, 0.5,
                                 float(signals.BB_LOWER_MAX), 0.05, key="sc_bbpos",
                                 help="%B는 밴드 안 위치입니다. 0=하단선, 1=상단선. "
                                      "0.2면 '하단에서 20% 이내'를 하단 구간으로 봅니다.")
            only_bb = st.checkbox("볼린저 하단 종목만 대상으로", True, key="sc_onlybb",
                                  help="끄면 하단이 아니어도 검사하고, 점수에만 반영합니다.")
            st.markdown("""
**조건_1 (최소 매수 타점)** — 주봉 일목 전환선 우상향 + 일봉 연속 음봉 +
60분 5이평이 *하락→평평*으로 전환. 추가매수는 60분 5이평이 *상승각도*로 전환할 때.

**조건_2 (스윙)** — 주봉 종가가 5주이평 위 + 주봉 전환선 상승·기준선 위 +
60분 종가가 5이평 아래(대기) → 위로 올라서면 진입.

**볼린저 하단** — 일봉 볼린저밴드 하단 구간(%B 기준 이하)에 있는 종목만 대상으로 삼습니다.
""")

        if st.button("🔎 스크리닝 실행", type="primary", key="sc_run"):
            res, fails = [], []
            pb = st.progress(0.0, text="시세를 받아 조건을 확인하는 중...")
            for i, (_, row) in enumerate(cand.iterrows()):
                code, name = row["종목코드"], row["종목명"]
                try:
                    dly, _, _ = ohlc.fetch_ohlc(code, smk, 400)
                    h60 = ohlc.fetch_intraday(code, smk)
                    r = signals.evaluate(dly, h60, eps=eps,
                                         down_min=dmin, down_max=dmax,
                                         bb_period=int(sc_bbp), bb_k=float(sc_bbk),
                                         bb_max_pos=float(sc_bbpos))
                    r.update({"종목명": name, "종목코드": code,
                              "ROE": row["ROE"], "PBR": row["PBR"]})
                    if "업종" in row.index:
                        r["업종"] = row["업종"]
                    res.append(r)
                except Exception as e:  # noqa: BLE001
                    fails.append(f"{name}({code}): {e}")
                pb.progress((i + 1) / len(cand),
                            text=f"확인 중... {i+1}/{len(cand)} — {name}")
            pb.empty()

            if not res:
                st.error("검사에 성공한 종목이 없습니다.")
            else:
                out = pd.DataFrame(res)
                if only_bb:
                    before = len(out)
                    out = out[out["볼린저하단"]].reset_index(drop=True)
                    st.caption(f"볼린저({int(sc_bbp)},{sc_bbk:g}) 하단 조건(%B ≤ "
                               f"{sc_bbpos:g})으로 {before}종목 중 {len(out)}종목이 남았습니다.")
                if out.empty:
                    st.warning("볼린저 하단 구간에 있는 종목이 없습니다. "
                               "기준(%B)을 올리거나 '하단 종목만' 체크를 꺼보세요.")
                # 신호점수 → ROE/PBR 매력도 순으로 정렬
                out["재무매력도"] = out["ROE"] / out["PBR"].replace(0, pd.NA)
                out = out.sort_values(["신호점수", "재무매력도"],
                                      ascending=[False, False]).reset_index(drop=True)
                out.insert(0, "순위", range(1, len(out) + 1))
                st.session_state[f"screen_res_{smk}"] = out
                journal.save_table(out, f"screen_{smk}")
                hit = int((out["신호점수"] >= 40).sum())
                st.success(f"{len(out)}종목 검사 완료 · **매수 신호 {hit}종목**"
                           + (f" · 실패 {len(fails)}건" if fails else ""))
            if fails:
                with st.expander(f"조회 실패 {len(fails)}건"):
                    st.write("\n".join(fails[:30]))

        out = st.session_state.get(f"screen_res_{smk}")
        if out is None:
            saved = journal.load_table(f"screen_{smk}")
            if saved is not None and not saved.empty:
                out = saved
                st.info("이전 스크리닝 결과입니다. 위 버튼으로 새로 돌리세요.")

        if out is not None and not out.empty:
            only_sig = st.checkbox("매수 신호가 있는 종목만 보기", True, key="sc_only")
            view = out[out["신호점수"] >= 40] if only_sig else out
            if view.empty:
                st.warning(
                    "지금 조건을 모두 만족하는 종목이 없습니다. "
                    "이 조건들은 **전환이 일어나는 그 순간**만 잡아내므로 "
                    "평소에는 잘 안 나오는 게 정상입니다. "
                    "기울기 기준을 키우거나 음봉 개수 범위를 넓혀보세요."
                )
                view = out.head(15)
                st.caption("참고로 점수 상위 15종목을 보여드립니다.")

            cols = ["순위", "종목명", "신호", "신호점수", "ROE", "PBR", "BB위치"]
            if "업종" in view.columns:
                cols.insert(2, "업종")
            show = view[cols].copy()
            show["ROE"] = show["ROE"].round(1)
            show["PBR"] = show["PBR"].round(2)
            if "BB위치" in show.columns:
                show["BB위치"] = show["BB위치"].astype(float).round(2)
                show = show.rename(columns={"BB위치": "볼린저%B"})
            st.dataframe(show, use_container_width=True, hide_index=True,
                         height=min(560, 40 * len(show) + 60))

            st.markdown("##### 조건 충족 내역")
            detail_cols = ["종목명", "볼린저하단", "BB위치", "조건1_주봉전환선우상향", "조건1_일봉연속음봉",
                           "조건1_60분평평전환", "조건1_추가매수",
                           "조건2_주봉5이평위", "조건2_전환선상승·기준선위",
                           "조건2_충족", "연속음봉"]
            have = [c for c in detail_cols if c in view.columns]
            det = view[have].copy()
            det.columns = [c.replace("조건1_", "①").replace("조건2_", "②")
                           for c in det.columns]
            st.dataframe(det, use_container_width=True, hide_index=True,
                         height=min(400, 40 * len(det) + 60))
            st.caption("① = 조건_1(최소 매수 타점) 요소, ② = 조건_2(스윙) 요소. "
                       "전부 True 여야 신호가 뜹니다.")

            st.download_button(
                "⬇️ 스크리닝 결과 CSV",
                out.to_csv(index=False).encode("utf-8-sig"),
                f"매수후보_{smk}_{pd.Timestamp.today():%Y%m%d}.csv", "text/csv",
                key="sc_dl")
            st.caption(
                "⚠️ 이 신호는 손님이 정하신 규칙을 기계적으로 계산한 결과입니다. "
                "투자 판단과 책임은 손님에게 있으며, 재무·업황을 함께 확인하시길 권합니다."
            )

with tab_candle:
    st.markdown("#### 🕯️ 종목 캔들차트")
    st.caption("일봉·주봉·월봉과 주요 기술적 지표를 함께 봅니다.")

    cmkt = st.radio("시장", list(krx_api.MARKETS.keys()),
                    horizontal=True, key="candle_market")

    stock_tbl = journal.load_table(f"roe_pbr_stocks_{cmkt}")
    picked_code, picked_name = None, None

    cc1, cc2 = st.columns([3, 2])
    with cc1:
        if (stock_tbl is not None and not stock_tbl.empty
                and "종목코드" in stock_tbl.columns):
            stock_tbl = stock_tbl.copy()
            stock_tbl["종목코드"] = (stock_tbl["종목코드"].astype(str)
                                 .str.replace(r"\D", "", regex=True).str.zfill(6))
            opts = (stock_tbl.sort_values("시가총액", ascending=False)
                    if "시가총액" in stock_tbl.columns else stock_tbl)
            labels = [f"{r['종목명']} ({r['종목코드']})" for _, r in opts.iterrows()]
            sel = st.selectbox("종목 선택", labels, key=f"candle_sel_{cmkt}")
            if sel:
                picked_name = sel.rsplit(" (", 1)[0]
                picked_code = sel.rsplit("(", 1)[1].rstrip(")")
        else:
            st.info("ROE·PBR 자료가 없어 목록을 못 만듭니다. 코드를 직접 입력하세요.")
    with cc2:
        manual = st.text_input("또는 종목코드 직접 입력", "",
                               key=f"candle_manual_{cmkt}", placeholder="예: 388210")
    if manual.strip():
        picked_code = manual.strip().zfill(6)
        picked_name = picked_name or picked_code

    p1, p2 = st.columns(2)
    freq_label = p1.radio("봉 주기", list(ohlc.FREQS.keys()),
                          horizontal=True, key="candle_freq")
    cperiod = p2.selectbox("기간", list(ohlc.PERIODS.keys()), index=2,
                           key="candle_period",
                           help="주봉·월봉은 기간을 길게 잡아야 봉이 충분히 생깁니다.")

    st.markdown("###### 표시할 지표")
    g1, g2, g3, g4, g5 = st.columns(5)
    show_ma = g1.checkbox("이동평균", True, key="ck_ma")
    show_bb = g2.checkbox("볼린저밴드", True, key="ck_bb")
    show_ich = g3.checkbox("일목균형표", False, key="ck_ich")
    show_macd = g4.checkbox("MACD", True, key="ck_macd")
    show_rsi = g5.checkbox("RSI", True, key="ck_rsi")
    s1, s2, s3 = st.columns(3)
    bb_period = s1.number_input("볼린저 기간(봉)", 5, 120, 12, 1, key="ck_bbp",
                                help="이동평균을 몇 봉으로 낼지. 짧을수록 민감합니다.")
    bb_k = s2.number_input("볼린저 배수(표준편차)", 1.0, 4.0, 2.0, 0.1, key="ck_bbk",
                           help="평균에서 표준편차 몇 배만큼 밴드를 벌릴지.")
    vol_mult = s3.slider("거래량 급증 기준(평균 대비)", 1.5, 5.0, 2.0, 0.5,
                         key="ck_volmult")

    if not picked_code:
        st.warning("종목을 고르거나 종목코드를 입력해주세요.")
    else:
        try:
            with st.spinner(f"{picked_name} 시세를 받는 중..."):
                bar = st.progress(0.0)
                raw, src, note = ohlc.fetch_ohlc(
                    picked_code, cmkt, ohlc.PERIODS[cperiod],
                    progress=lambda d, t: bar.progress(
                        d / t, text=f"KRX에서 하루씩 받는 중... {d}/{t}"))
                bar.empty()
            if note:
                st.warning(note)

            bars = ohlc.resample_ohlc(raw, ohlc.FREQS[freq_label])
            # 지표마다 필요한 봉 수가 달라, 부족하면 미리 알려준다
            need = []
            if show_bb and len(bars) < bb_period:
                need.append(f"볼린저밴드 {int(bb_period)}봉")
            if show_ma and len(bars) < 60:
                need.append("60봉 이동평균 60봉")
            if show_ich and len(bars) < 52:
                need.append("일목균형표 52봉")
            if len(bars) < 5:
                st.warning(f"{freq_label}이 {len(bars)}개뿐이라 차트를 그리기 어렵습니다. "
                           "위에서 **기간**을 늘려주세요.")
            elif need:
                st.info(f"현재 {freq_label} {len(bars)}봉입니다. "
                        f"{' · '.join(need)}이 필요해 일부 지표는 비어 보일 수 있습니다. "
                        "**기간**을 늘리면 채워집니다.")
            d, cloud = ohlc.add_all(bars, bb_period=int(bb_period),
                                    bb_k=float(bb_k), vol_mult=vol_mult)
            s = ohlc.summarize(d)

            k1, k2, k3, k4 = st.columns(4)
            k1.metric(f"{picked_name} 종가", f"{s['종가']:,.0f}원",
                      f"{s['전일대비']:+,.0f} ({s['전일대비율']:+.2f}%)")
            k2.metric(f"{cperiod} 수익률", f"{s['기간수익률']:+.1f}%")
            k3.metric("기간 최고", f"{s['기간최고']:,.0f}원",
                      f"{s['최고일']:%y-%m-%d}", delta_color="off")
            k4.metric("기간 최저", f"{s['기간최저']:,.0f}원",
                      f"{s['최저일']:%y-%m-%d}", delta_color="off")

            # 표시할 지표에 따라 단(row)을 동적으로 구성
            rows = [("price", 0.52), ("vol", 0.16)]
            if show_macd:
                rows.append(("macd", 0.16))
            if show_rsi:
                rows.append(("rsi", 0.16))
            heights = [h for _, h in rows]
            heights = [h / sum(heights) for h in heights]
            rmap = {name: i + 1 for i, (name, _) in enumerate(rows)}

            figc = make_subplots(rows=len(rows), cols=1, shared_xaxes=True,
                                 row_heights=heights, vertical_spacing=0.03)

            # ---- 일목 구름 (캔들 뒤에 깔리도록 먼저 그린다) ----
            if show_ich and not cloud.empty:
                figc.add_trace(go.Scatter(
                    x=cloud["날짜"], y=cloud["선행스팬1"], mode="lines",
                    name="선행스팬1", line=dict(width=0.8, color="#26a69a")),
                    row=1, col=1)
                figc.add_trace(go.Scatter(
                    x=cloud["날짜"], y=cloud["선행스팬2"], mode="lines",
                    name="선행스팬2", line=dict(width=0.8, color="#ef5350"),
                    fill="tonexty", fillcolor="rgba(120,144,156,0.25)"),
                    row=1, col=1)
                for cname, col in [("전환선", "#1e88e5"), ("기준선", "#8e24aa")]:
                    figc.add_trace(go.Scatter(
                        x=d["날짜"], y=d[cname], mode="lines", name=cname,
                        line=dict(width=1.2, color=col)), row=1, col=1)
                figc.add_trace(go.Scatter(
                    x=d["날짜"], y=d["후행스팬"], mode="lines", name="후행스팬",
                    line=dict(width=1, color="#6d4c41", dash="dot")), row=1, col=1)

            # ---- 볼린저밴드 ----
            if show_bb:
                figc.add_trace(go.Scatter(
                    x=d["날짜"], y=d["BB상단"], mode="lines", name=f"볼린저 상단({int(bb_period)},{bb_k:g})",
                    line=dict(width=1, color="#90a4ae")), row=1, col=1)
                figc.add_trace(go.Scatter(
                    x=d["날짜"], y=d["BB하단"], mode="lines", name=f"볼린저 하단({int(bb_period)},{bb_k:g})",
                    line=dict(width=1, color="#90a4ae"),
                    fill="tonexty", fillcolor="rgba(144,164,174,0.13)"),
                    row=1, col=1)

            # ---- 캔들 ----
            figc.add_trace(go.Candlestick(
                x=d["날짜"], open=d["시가"], high=d["고가"],
                low=d["저가"], close=d["종가"], name=freq_label,
                increasing_line_color="#d62728", decreasing_line_color="#1f77b4",
                increasing_fillcolor="#d62728", decreasing_fillcolor="#1f77b4"),
                row=1, col=1)

            # ---- 이동평균 ----
            if show_ma:
                for m, col in [(5, "#ff7f0e"), (20, "#2ca02c"), (60, "#9467bd")]:
                    if f"MA{m}" in d.columns:
                        figc.add_trace(go.Scatter(
                            x=d["날짜"], y=d[f"MA{m}"], mode="lines",
                            name=f"MA{m}", line=dict(width=1.3, color=col)),
                            row=1, col=1)

            # ---- 거래량 + 급증일 ----
            vcol = ["#d62728" if c >= o else "#1f77b4"
                    for o, c in zip(d["시가"], d["종가"])]
            figc.add_trace(go.Bar(x=d["날짜"], y=d["거래량"], name="거래량",
                                  marker_color=vcol, showlegend=False),
                           row=rmap["vol"], col=1)
            spikes = d[d["거래량급증"].fillna(False)]
            if not spikes.empty:
                figc.add_trace(go.Scatter(
                    x=spikes["날짜"], y=spikes["거래량"], mode="markers",
                    name=f"거래량 급증(≥{vol_mult}배)",
                    marker=dict(size=9, color="#ffd600", symbol="star",
                                line=dict(width=1, color="#795548"))),
                    row=rmap["vol"], col=1)

            # ---- MACD ----
            if show_macd:
                hcol = ["#d62728" if v >= 0 else "#1f77b4" for v in d["MACD히스토"]]
                figc.add_trace(go.Bar(x=d["날짜"], y=d["MACD히스토"],
                                      name="히스토그램", marker_color=hcol,
                                      showlegend=False), row=rmap["macd"], col=1)
                figc.add_trace(go.Scatter(
                    x=d["날짜"], y=d["MACD"], mode="lines", name="MACD",
                    line=dict(width=1.3, color="#1e88e5")), row=rmap["macd"], col=1)
                figc.add_trace(go.Scatter(
                    x=d["날짜"], y=d["MACD신호"], mode="lines", name="신호선",
                    line=dict(width=1.1, color="#ef6c00")), row=rmap["macd"], col=1)

            # ---- RSI ----
            if show_rsi:
                figc.add_trace(go.Scatter(
                    x=d["날짜"], y=d["RSI"], mode="lines", name="RSI",
                    line=dict(width=1.4, color="#6a1b9a")), row=rmap["rsi"], col=1)
                for lv, lcol in [(70, "#d62728"), (30, "#1f77b4")]:
                    figc.add_hline(y=lv, line_dash="dash", line_color=lcol,
                                   line_width=1, row=rmap["rsi"], col=1)
                figc.update_yaxes(range=[0, 100], row=rmap["rsi"], col=1)

            figc.update_layout(
                height=260 + 180 * len(rows), margin=dict(l=55, r=20, t=30, b=20),
                xaxis_rangeslider_visible=False, hovermode="x unified",
                barmode="overlay",
                legend=dict(orientation="h", yanchor="bottom", y=1.01,
                            xanchor="left", x=0, font=dict(size=10)))
            figc.update_yaxes(title_text="주가(원)", row=1, col=1)
            figc.update_yaxes(title_text="거래량", row=rmap["vol"], col=1)
            if show_macd:
                figc.update_yaxes(title_text="MACD", row=rmap["macd"], col=1)
            if show_rsi:
                figc.update_yaxes(title_text="RSI", row=rmap["rsi"], col=1)
            if ohlc.FREQS[freq_label] == "D":
                figc.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
            st.plotly_chart(figc, use_container_width=True)

            # ---- 현재 상태 요약 ----
            st.markdown("##### 지금 지표는 무엇을 말하나")
            last = d.iloc[-1]
            msgs = []
            if show_ma:
                for m in (5, 20, 60):
                    cn = f"MA{m}"
                    if cn in d.columns and pd.notna(last[cn]):
                        gap = (last["종가"] / last[cn] - 1) * 100
                        msgs.append({
                            "지표": f"{m}봉 이동평균", "값": f"{last[cn]:,.0f}원",
                            "해석": f"현재가가 {gap:+.1f}% "
                                  + ("위 (상승 추세)" if gap >= 0 else "아래 (하락 추세)")})
            if show_bb and pd.notna(last.get("BB위치")):
                pos = float(last["BB위치"])
                msgs.append({"지표": f"볼린저({int(bb_period)},{bb_k:g})", "값": f"밴드 내 {pos*100:.0f}% 지점",
                             "해석": ("상단 근처 — 단기 과열 주의" if pos > 0.8 else
                                    "하단 근처 — 과매도 구간" if pos < 0.2 else
                                    "중간 — 방향성 뚜렷하지 않음")})
            if show_rsi and pd.notna(last.get("RSI")):
                rv = float(last["RSI"])
                msgs.append({"지표": "RSI(14)", "값": f"{rv:.1f}",
                             "해석": ("70 이상 — 과열(단기 조정 가능)" if rv >= 70 else
                                    "30 이하 — 침체(반등 가능)" if rv <= 30 else
                                    "30~70 — 중립")})
            if show_macd and pd.notna(last.get("MACD")):
                hv = float(last["MACD히스토"])
                msgs.append({"지표": "MACD",
                             "값": f"{last['MACD']:,.1f} / 신호 {last['MACD신호']:,.1f}",
                             "해석": ("신호선 위 — 상승 신호" if hv >= 0
                                    else "신호선 아래 — 하락 신호")})
            if show_ich and pd.notna(last.get("기준선")):
                base_v = float(last["기준선"])
                msgs.append({"지표": "일목 기준선", "값": f"{base_v:,.0f}원",
                             "해석": ("기준선 위 — 강세" if last["종가"] >= base_v
                                    else "기준선 아래 — 약세")})
            if pd.notna(last.get("거래량배수")):
                mlt = float(last["거래량배수"])
                msgs.append({"지표": "거래량", "값": f"평균의 {mlt:.1f}배",
                             "해석": ("급증 — 관심 집중" if mlt >= vol_mult
                                    else "평소 수준")})
            if msgs:
                st.dataframe(pd.DataFrame(msgs), use_container_width=True,
                             hide_index=True)
            st.caption(
                "⚠️ 기술적 지표는 과거 가격의 통계일 뿐이며 미래를 보장하지 않습니다. "
                "재무(ROE·PBR)와 함께 보시길 권합니다."
            )

            with st.expander("📋 봉 데이터 표 / 내려받기"):
                show = d.copy()
                show["날짜"] = show["날짜"].dt.strftime("%Y-%m-%d")
                st.dataframe(show.sort_values("날짜", ascending=False).round(1),
                             use_container_width=True, hide_index=True, height=320)
                st.download_button(
                    "⬇️ 시세·지표 CSV",
                    show.to_csv(index=False).encode("utf-8-sig"),
                    f"{picked_name}_{picked_code}_{freq_label}.csv", "text/csv",
                    key="candle_dl")

            st.caption(f"출처 {src} · {freq_label} {len(d)}봉 · "
                       f"기준일 {s['기준일']:%Y-%m-%d}")
        except Exception as e:  # noqa: BLE001
            st.error(f"시세를 불러오지 못했습니다: {e}")

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
