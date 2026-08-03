# -*- coding: utf-8 -*-
"""
ROE·PBR 회귀분석 모듈
=====================================
KRX 정보데이터시스템에서 받은 파일(엑셀/CSV)을 읽어
  ① 종목별 ROE vs PBR 횡단면 회귀
  ② 코스피지수 vs 전체 PBR 시계열 회귀
를 수행한다.

KRX 다운로드 형식이 조금씩 달라도 되도록 컬럼명을 유연하게 찾는다.
ROE 컬럼이 없으면 EPS/BPS 로 계산한다(트레일링 ROE 근사).
"""

import io
import re

import numpy as np
import pandas as pd

# 컬럼 자동 인식용 후보 이름들
ALIASES = {
    "종목명": ["종목명", "한글 종목약명", "한글종목약명", "한글 종목명", "종목", "name"],
    "종목코드": ["종목코드", "단축코드", "표준코드", "code"],
    "PBR": ["pbr", "주가순자산비율"],
    "PER": ["per", "주가수익비율"],
    "EPS": ["eps", "주당순이익"],
    "BPS": ["bps", "주당순자산", "주당순자산가치"],
    "ROE": ["roe", "자기자본이익률"],
    "종가": ["종가", "현재가", "close", "지수", "종가지수"],
    "시가총액": ["시가총액", "시총", "marketcap"],
    "날짜": ["날짜", "일자", "기준일", "date", "거래일"],
}


def _norm(s):
    """컬럼명 비교용 정규화: 공백·괄호·특수문자 제거 + 소문자."""
    return re.sub(r"[\s()\[\]./_-]", "", str(s)).lower()


def find_col(df, key):
    """ALIASES[key] 후보 중 df에 실제 존재하는 컬럼명을 찾아 반환. 없으면 None."""
    cands = [_norm(a) for a in ALIASES.get(key, [])]
    for col in df.columns:
        if _norm(col) in cands:
            return col
    # 부분 일치(예: 'PBR(배)')도 허용
    for col in df.columns:
        n = _norm(col)
        for c in cands:
            if c and (n.startswith(c) or c in n):
                return col
    return None


def read_table(uploaded):
    """업로드된 파일(엑셀/CSV)을 DataFrame으로 읽는다. 한글 인코딩 자동 대응."""
    name = getattr(uploaded, "name", "").lower()
    raw = uploaded.read() if hasattr(uploaded, "read") else uploaded

    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))

    # CSV: KRX는 보통 EUC-KR(cp949)
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=enc)
            if len(df.columns) > 1:
                return df
        except Exception:
            continue
    raise ValueError("파일을 읽을 수 없습니다. 엑셀(.xlsx) 또는 CSV로 저장해 올려주세요.")


def _to_num(s):
    """'1,234.5', '12.3배' 같은 문자열도 숫자로 변환."""
    if s.dtype.kind in "if":
        return s
    cleaned = (s.astype(str)
               .str.replace(",", "", regex=False)
               .str.replace(r"[^\d.\-]", "", regex=True)
               .replace("", np.nan))
    return pd.to_numeric(cleaned, errors="coerce")


# ---------------------------------------------------------------------------
# ① 종목별 ROE · PBR
# ---------------------------------------------------------------------------
def parse_stocks(df):
    """종목별 표에서 종목명·PBR·ROE를 뽑아낸다.
    반환: (정리된 DataFrame, 안내메시지)
    """
    c_name = find_col(df, "종목명")
    c_pbr = find_col(df, "PBR")
    if c_pbr is None:
        raise ValueError("PBR 컬럼을 찾지 못했습니다. PER/PBR 자료인지 확인해주세요.")

    out = pd.DataFrame()
    out["종목명"] = df[c_name].astype(str) if c_name else [f"종목{i}" for i in range(len(df))]
    out["PBR"] = _to_num(df[c_pbr])

    note = ""
    c_roe = find_col(df, "ROE")
    if c_roe is not None:
        out["ROE"] = _to_num(df[c_roe])
        note = "파일의 ROE 컬럼을 사용했습니다."
    else:
        c_eps, c_bps = find_col(df, "EPS"), find_col(df, "BPS")
        if c_eps is None or c_bps is None:
            raise ValueError(
                "ROE 컬럼도, EPS·BPS 컬럼도 없습니다. "
                "KRX 'PER/PBR/배당수익률' 자료를 올려주세요.")
        eps, bps = _to_num(df[c_eps]), _to_num(df[c_bps])
        out["ROE"] = np.where(bps > 0, eps / bps * 100.0, np.nan)
        note = "ROE = EPS ÷ BPS × 100 으로 계산했습니다(트레일링 ROE 근사)."

    c_cap = find_col(df, "시가총액")
    if c_cap is not None:
        out["시가총액"] = _to_num(df[c_cap])

    # 결측·비정상 제거 (적자기업 ROE 음수는 유지, PBR<=0은 제외)
    out = out.replace([np.inf, -np.inf], np.nan)
    out = out[(out["PBR"] > 0) & out["ROE"].notna()].reset_index(drop=True)
    return out, note


# ---------------------------------------------------------------------------
# ② 지수 · PBR 시계열
# ---------------------------------------------------------------------------
def parse_index(df):
    """지수 시계열 표에서 날짜·지수·PBR을 뽑아낸다.

    ※ '날짜별 코스피 추이'가 필요하므로 날짜 컬럼이 반드시 있어야 한다.
       날짜가 없으면 대개 '하루치 여러 지수 목록'을 받은 경우다.
    """
    c_date = find_col(df, "날짜")
    c_pbr = find_col(df, "PBR")
    c_idx = find_col(df, "종가")
    if c_pbr is None:
        raise ValueError("PBR 컬럼을 찾지 못했습니다.")
    if c_idx is None:
        raise ValueError("지수(종가) 컬럼을 찾지 못했습니다.")
    if c_date is None:
        raise ValueError(
            "날짜 컬럼이 없습니다. 이 화면은 '코스피의 날짜별 추이'가 필요합니다.\n"
            "혹시 '하루치 전체 지수 목록'(코스피·코스피200·섹터지수가 한 줄씩 있는 파일)을 "
            "올리지 않으셨나요? KRX에서 지수를 **코스피 하나만 고르고 기간을 지정**해 "
            "받아주세요. (또는 위에서 'API 자동 수집'을 쓰시면 가장 간단합니다)")

    out = pd.DataFrame()
    out["날짜"] = pd.to_datetime(df[c_date].astype(str).str.replace(r"[^\d]", "-", regex=True),
                                errors="coerce")
    out["지수"] = _to_num(df[c_idx])
    out["PBR"] = _to_num(df[c_pbr])
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["지수", "PBR", "날짜"])
    out = out.sort_values("날짜")
    if out.empty:
        raise ValueError("읽을 수 있는 행이 없습니다. 날짜·종가·PBR 열을 확인해주세요.")
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# API 결합 (KRX 시가총액 + DART 재무) → parse_stocks 와 같은 스키마
# ---------------------------------------------------------------------------
def build_from_api(krx_df, dart_df, corp_map, annualize=None):
    """KRX 시세 + DART 재무를 합쳐 종목명·ROE·PBR·시가총액 표를 만든다.

    PBR = 시가총액 ÷ 자본총계,  ROE = 당기순이익 ÷ 자본총계 × 100
    (KRX 시가총액과 DART 재무 모두 '원' 단위라 그대로 나눈다.)
    """
    df = krx_df.copy()
    df["corp_code"] = df["종목코드"].map(corp_map)
    df = df.dropna(subset=["corp_code"])

    merged = df.merge(dart_df, on="corp_code", how="inner")
    merged["자본총계"] = pd.to_numeric(merged["자본총계"], errors="coerce")
    merged["당기순이익"] = pd.to_numeric(merged["당기순이익"], errors="coerce")

    if annualize is not None:
        merged["당기순이익"] = merged["당기순이익"].apply(annualize)

    # 자본잠식(자본총계<=0)은 PBR·ROE 해석이 불가 → 제외
    merged = merged[merged["자본총계"] > 0]

    out = pd.DataFrame({
        "종목명": merged["종목명"],
        "PBR": merged["시가총액"] / merged["자본총계"],
        "ROE": merged["당기순이익"] / merged["자본총계"] * 100.0,
        "시가총액": merged["시가총액"],
    })
    out = out.replace([np.inf, -np.inf], np.nan)
    out = out[(out["PBR"] > 0) & out["ROE"].notna()]
    return out.reset_index(drop=True)


def aggregate_pbr(krx_df, dart_df, corp_map):
    """시장 전체 PBR = Σ시가총액 ÷ Σ자본총계 (구성종목 합산)."""
    df = krx_df.copy()
    df["corp_code"] = df["종목코드"].map(corp_map)
    merged = df.dropna(subset=["corp_code"]).merge(dart_df, on="corp_code", how="inner")
    merged["자본총계"] = pd.to_numeric(merged["자본총계"], errors="coerce")
    merged = merged[merged["자본총계"] > 0]
    if merged.empty:
        return np.nan
    return float(merged["시가총액"].sum() / merged["자본총계"].sum())


def filter_outliers(df, pbr_max=10.0, roe_min=-50.0, roe_max=100.0):
    """회귀를 왜곡하는 극단값을 걸러낸다.

    자본이 거의 잠식된 회사는 PBR이 수백~수천 배, ROE가 ±수백 %로 나와
    소수의 종목이 회귀선을 통째로 끌고 간다(R²≈0). 실제 값이지만
    '같은 ROE면 PBR이 얼마나 되는가'라는 질문에는 방해가 되므로 제외한다.

    반환: (걸러진 DataFrame, 제외된 개수)
    """
    n0 = len(df)
    out = df[(df["PBR"] > 0) & (df["PBR"] <= pbr_max)
             & (df["ROE"] >= roe_min) & (df["ROE"] <= roe_max)]
    return out.reset_index(drop=True), n0 - len(out)


# ---------------------------------------------------------------------------
# ROE·PBR 4분면 (수익성 × 밸류에이션)
# ---------------------------------------------------------------------------
Q_GOOD_CHEAP = "저평가 우량주"
Q_GOOD_RICH = "프리미엄 우량주"
Q_WEAK_CHEAP = "저수익 저평가"
Q_WEAK_RICH = "고평가 주의"

QUADRANT_INFO = {
    Q_GOOD_CHEAP: {
        "pos": "고ROE · 저PBR",
        "color": "#1a9850",
        "desc": "돈은 잘 버는데 싸게 거래되는 구간. 네 분면 중 가장 매력적이며, "
                "가치투자에서 1차 관심 대상입니다. 다만 싼 이유(지배구조·업황 등)가 "
                "있는지 확인이 필요합니다.",
    },
    Q_GOOD_RICH: {
        "pos": "고ROE · 고PBR",
        "color": "#4575b4",
        "desc": "우량하지만 이미 비싼 구간. 성장이 계속되면 정당화되지만, "
                "기대가 꺾이면 조정폭이 큽니다. 실적 추세를 함께 봐야 합니다.",
    },
    Q_WEAK_CHEAP: {
        "pos": "저ROE · 저PBR",
        "color": "#fdae61",
        "desc": "싸지만 수익성이 낮은 구간. 흔히 말하는 '밸류 트랩'이 숨어 있어, "
                "자산가치나 turnaround 근거가 없으면 오래 싼 채로 머무를 수 있습니다.",
    },
    Q_WEAK_RICH: {
        "pos": "저ROE · 고PBR",
        "color": "#d73027",
        "desc": "수익성은 낮은데 비싼 구간. 미래 기대가 선반영된 상태로 "
                "네 분면 중 위험이 가장 큽니다. 기대가 실적으로 확인되는지가 관건입니다.",
    },
}

# 화면에 보여줄 순서 (매력적인 것부터)
QUADRANT_ORDER = [Q_GOOD_CHEAP, Q_GOOD_RICH, Q_WEAK_CHEAP, Q_WEAK_RICH]


def quadrants(df, roe_cut=None, pbr_cut=None):
    """ROE·PBR을 기준선으로 4분면 분류.

    기준선을 안 주면 분석 대상의 중앙값을 쓴다(시장 대비 상대 평가).
    반환: (분면 컬럼이 붙은 DataFrame, roe_cut, pbr_cut)
    """
    d = df.copy()
    roe_cut = float(d["ROE"].median()) if roe_cut is None else float(roe_cut)
    pbr_cut = float(d["PBR"].median()) if pbr_cut is None else float(pbr_cut)

    hi_roe = d["ROE"] >= roe_cut
    hi_pbr = d["PBR"] >= pbr_cut
    d["분면"] = np.select(
        [hi_roe & ~hi_pbr, hi_roe & hi_pbr, ~hi_roe & ~hi_pbr, ~hi_roe & hi_pbr],
        [Q_GOOD_CHEAP, Q_GOOD_RICH, Q_WEAK_CHEAP, Q_WEAK_RICH],
        default="",
    )
    return d, roe_cut, pbr_cut


def fiscal_year_for(date, month_cutoff=4):
    """그 시점에 이미 공시되어 있었을 '가장 최근 사업연도'를 고른다.

    사업보고서는 결산 후 3개월 이내(대개 3월 말)에 제출되므로,
    4월 이후면 직전 연도, 1~3월이면 그 전 연도 재무를 쓴다.
    (미래 정보를 끌어다 쓰지 않기 위한 처리)
    """
    d = pd.Timestamp(date)
    return d.year - 1 if d.month >= month_cutoff else d.year - 2


def bin_by_roe(df, nbin=8, stat="median"):
    """ROE를 같은 개수씩 구간으로 나눠 대표값(중앙값)을 낸다.

    개별 종목은 성장기대·업종·리스크 때문에 같은 ROE라도 PBR이 크게 흩어진다.
    구간별로 묶으면 그 잡음이 상쇄되어 'ROE↑ → PBR↑' 추세가 선명해진다.
    (단, 이 R²는 '구간 평균의 설명력'이지 개별 종목 예측력이 아니다.)
    """
    d = df[["ROE", "PBR"]].dropna()
    if len(d) < nbin * 2:
        nbin = max(3, len(d) // 3)
    d = d.copy()
    d["_q"] = pd.qcut(d["ROE"], nbin, duplicates="drop")
    g = (d.groupby("_q", observed=True)
           .agg(ROE=("ROE", stat), PBR=("PBR", stat), 종목수=("PBR", "size"))
           .reset_index(drop=True))
    return g.dropna().reset_index(drop=True)


# ---------------------------------------------------------------------------
# 회귀분석
# ---------------------------------------------------------------------------
def regress(x, y):
    """단순선형회귀. 반환 dict: slope, intercept, r2, n, predict(함수)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 3:
        raise ValueError("회귀분석에 필요한 데이터가 부족합니다(3개 이상 필요).")

    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": float(r2),
        "n": int(len(x)),
        "corr": float(np.corrcoef(x, y)[0, 1]),
    }


def with_residuals(df, xcol, ycol, fit):
    """회귀선 대비 잔차(실제-예측)를 붙인다. 음수면 회귀선 아래(상대 저평가)."""
    out = df.copy()
    out["예측"] = fit["slope"] * out[xcol] + fit["intercept"]
    out["잔차"] = out[ycol] - out["예측"]
    out["평가"] = np.where(out["잔차"] < 0, "저평가(선 아래)", "고평가(선 위)")
    return out


def fit_line(fit, x):
    """회귀선을 그리기 위한 (x, y) 좌표."""
    xs = np.linspace(float(np.min(x)), float(np.max(x)), 100)
    return xs, fit["slope"] * xs + fit["intercept"]
