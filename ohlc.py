# -*- coding: utf-8 -*-
"""
종목 일별 시세(캔들) 조회 + 기술적 지표
=====================================
캔들차트에는 시가·고가·저가·종가가 하루씩 필요하다.

  · 주 경로 : yfinance (한 번에 전 기간 → 6개월 2초)
  · 대비책 : KRX 일별매매정보 (하루씩 조회라 6개월 약 2분, 느리지만 확실)

KRX 는 '어느 하루의 전 종목'을 주는 구조라 기간 조회에 불리하다.
그래서 평소엔 yfinance 를 쓰고, 막히면 KRX 로 넘어간다.
"""

import pandas as pd

import krx_api

# 시장별 야후 티커 접미사
YF_SUFFIX = {"코스피": "KS", "코스닥150": "KQ", "코스닥": "KQ"}

PERIODS = {"3개월": 90, "6개월": 180, "1년": 365, "2년": 730, "3년": 1095}

COLS = ["날짜", "시가", "고가", "저가", "종가", "거래량"]


def yf_ticker(code, market):
    """'388210' + 코스닥150 → '388210.KQ'"""
    return f"{str(code).zfill(6)}.{YF_SUFFIX.get(market, 'KS')}"


def fetch_yf(code, market, days):
    """yfinance 로 일별 시세를 한 번에 받는다."""
    import yfinance as yf

    start = (pd.Timestamp.today().normalize() - pd.Timedelta(days=days))
    df = yf.download(yf_ticker(code, market), start=start.strftime("%Y-%m-%d"),
                     progress=False, auto_adjust=False)
    if df is None or len(df) == 0:
        raise RuntimeError("yfinance 데이터 없음")

    # 단일 종목이어도 컬럼이 MultiIndex 로 올 수 있다
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    out = pd.DataFrame({
        "날짜": pd.to_datetime(df.index),
        "시가": pd.to_numeric(df["Open"], errors="coerce"),
        "고가": pd.to_numeric(df["High"], errors="coerce"),
        "저가": pd.to_numeric(df["Low"], errors="coerce"),
        "종가": pd.to_numeric(df["Close"], errors="coerce"),
        "거래량": pd.to_numeric(df["Volume"], errors="coerce"),
    }).dropna(subset=["종가"]).reset_index(drop=True)
    return out


def fetch_krx(code, market, days, key=None, progress=None):
    """KRX 일별매매정보를 하루씩 모은다(대비책). 느리므로 진행률을 알려준다."""
    code = str(code).zfill(6)
    cat, ep = krx_api.MARKETS[market]["stock"]
    key = krx_api.get_key(key)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(),
                           start=pd.Timestamp.today().normalize() - pd.Timedelta(days=days))
    rows = []
    for i, d in enumerate(dates):
        try:
            recs = krx_api._call(cat, ep, d.strftime("%Y%m%d"), key)
            hit = next((r for r in recs if str(r.get("ISU_CD", "")).zfill(6) == code), None)
            if hit:
                rows.append({
                    "날짜": d,
                    "시가": hit.get("TDD_OPNPRC"), "고가": hit.get("TDD_HGPRC"),
                    "저가": hit.get("TDD_LWPRC"), "종가": hit.get("TDD_CLSPRC"),
                    "거래량": hit.get("ACC_TRDVOL"),
                })
        except Exception:
            pass
        if progress:
            progress(i + 1, len(dates))

    if not rows:
        raise RuntimeError("KRX에서도 시세를 찾지 못했습니다.")
    out = pd.DataFrame(rows)
    for c in ["시가", "고가", "저가", "종가", "거래량"]:
        out[c] = krx_api._to_num(out[c])
    return out.dropna(subset=["종가"]).reset_index(drop=True)


def fetch_ohlc(code, market, days, progress=None):
    """일별 시세를 받는다. 반환: (DataFrame, 사용한 소스, 안내문 or None)"""
    try:
        return fetch_yf(code, market, days), "yfinance", None
    except Exception as e:  # noqa: BLE001
        try:
            df = fetch_krx(code, market, days, progress=progress)
            return df, "KRX", f"야후 조회가 안 돼 KRX로 받았습니다. ({e})"
        except Exception as e2:  # noqa: BLE001
            raise RuntimeError(f"시세를 받지 못했습니다. yfinance: {e} / KRX: {e2}")


def add_indicators(df, mas=(5, 20, 60)):
    """이동평균선을 붙인다(종가 기준)."""
    out = df.sort_values("날짜").reset_index(drop=True)
    for m in mas:
        if len(out) >= m:
            out[f"MA{m}"] = out["종가"].rolling(m).mean()
    return out


def summarize(df):
    """현재가·등락률·기간 최고/최저 등 요약."""
    d = df.dropna(subset=["종가"]).sort_values("날짜")
    if d.empty:
        return {}
    last, first = d.iloc[-1], d.iloc[0]
    prev = d.iloc[-2] if len(d) >= 2 else last
    hi_row, lo_row = d.loc[d["고가"].idxmax()], d.loc[d["저가"].idxmin()]
    return {
        "기준일": last["날짜"],
        "종가": float(last["종가"]),
        "전일대비": float(last["종가"] - prev["종가"]),
        "전일대비율": float((last["종가"] / prev["종가"] - 1) * 100) if prev["종가"] else 0.0,
        "기간수익률": float((last["종가"] / first["종가"] - 1) * 100) if first["종가"] else 0.0,
        "기간최고": float(hi_row["고가"]), "최고일": hi_row["날짜"],
        "기간최저": float(lo_row["저가"]), "최저일": lo_row["날짜"],
        "거래량": float(last["거래량"]) if pd.notna(last["거래량"]) else None,
        "일수": int(len(d)),
    }
