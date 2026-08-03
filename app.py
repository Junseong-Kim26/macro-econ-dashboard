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
import journal
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
tab_graph, tab_combo, tab_table, tab_rule, tab_journal = st.tabs(
    ["📈 그래프", "📈 시장·환율·금리차", "📋 일별 테이블", "📖 점수 기준", "📝 매매일지"]
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

            edited_pf = st.data_editor(
                today_pf, num_rows="dynamic", use_container_width=True, height=260,
                column_config={
                    "종목명": st.column_config.TextColumn("종목명", width="medium"),
                    "금액": st.column_config.NumberColumn(
                        "금액(백만원)", min_value=0.0, step=0.1, format="%.1f",
                        help="백만원 단위, 소수 첫째자리까지 입력 (예: 120.5)"),
                },
                key=f"pf_editor_{date_str}",
            )
            _tot = pd.to_numeric(edited_pf["금액"], errors="coerce").fillna(0).sum()
            st.metric("합계", f"{_tot:,.1f} 백만원")

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
