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


# ---------------------------------------------------------------------------
# 봉 주기 변환 (일봉 → 주봉·월봉)
# ---------------------------------------------------------------------------
FREQS = {"일봉": "D", "주봉": "W", "월봉": "M"}


def resample_ohlc(df, freq="D"):
    """일봉을 주봉·월봉으로 묶는다.

    시가=구간 첫날, 고가=최고, 저가=최저, 종가=마지막날, 거래량=합계.
    """
    if freq == "D" or df.empty:
        return df.sort_values("날짜").reset_index(drop=True)

    rule = "W-FRI" if freq == "W" else "ME"
    g = (df.set_index("날짜").sort_index()
         .resample(rule)
         .agg({"시가": "first", "고가": "max", "저가": "min",
               "종가": "last", "거래량": "sum"}))
    return g.dropna(subset=["종가"]).reset_index()


# ---------------------------------------------------------------------------
# 기술적 지표
# ---------------------------------------------------------------------------
def bollinger(df, period=20, k=2.0):
    """볼린저밴드: 이동평균 ± k×표준편차. 밴드폭이 좁아지면 변동성 축소."""
    c = df["종가"]
    mid = c.rolling(period).mean()
    sd = c.rolling(period).std(ddof=0)
    out = df.copy()
    out["BB중심"] = mid
    out["BB상단"] = mid + k * sd
    out["BB하단"] = mid - k * sd
    # %B: 밴드 안에서의 위치(0=하단, 1=상단)
    width = out["BB상단"] - out["BB하단"]
    out["BB위치"] = (c - out["BB하단"]) / width.replace(0, pd.NA)
    return out


def rsi(df, period=14):
    """RSI(상대강도지수). Wilder 방식 지수평활. 70↑ 과열, 30↓ 침체."""
    c = df["종가"]
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    # 하락이 전혀 없으면(avg_loss=0) RSI는 100으로 본다
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out = df.copy()
    val = 100 - 100 / (1 + rs)
    out["RSI"] = val.where(avg_loss > 0, 100.0).astype(float)
    out.loc[avg_gain <= 0, "RSI"] = out.loc[avg_gain <= 0, "RSI"].fillna(0.0)
    return out


def macd(df, fast=12, slow=26, signal=9):
    """MACD: 단기EMA-장기EMA, 그 신호선과 차이(히스토그램)."""
    c = df["종가"]
    ema_f = c.ewm(span=fast, adjust=False).mean()
    ema_s = c.ewm(span=slow, adjust=False).mean()
    out = df.copy()
    out["MACD"] = ema_f - ema_s
    out["MACD신호"] = out["MACD"].ewm(span=signal, adjust=False).mean()
    out["MACD히스토"] = out["MACD"] - out["MACD신호"]
    return out


def volume_spike(df, period=20, mult=2.0):
    """거래량 급증일: 최근 평균 대비 mult배 넘는 날."""
    v = df["거래량"]
    avg = v.rolling(period).mean()
    out = df.copy()
    out["거래량평균"] = avg
    out["거래량배수"] = v / avg.replace(0, pd.NA)
    out["거래량급증"] = out["거래량배수"] >= mult
    return out


def ichimoku(df, conv=9, base=26, span=52, shift=26):
    """일목균형표.

    전환선=9기간 (최고+최저)/2, 기준선=26기간,
    선행스팬1=(전환+기준)/2 를 26기간 **앞으로**, 선행스팬2=52기간을 26기간 앞으로,
    후행스팬=종가를 26기간 **뒤로**. 선행스팬1·2 사이가 '구름대'.

    선행스팬은 미래를 향하므로 날짜를 26기간 더 늘려 붙인다.
    """
    d = df.sort_values("날짜").reset_index(drop=True)
    high, low, close = d["고가"], d["저가"], d["종가"]

    tenkan = (high.rolling(conv).max() + low.rolling(conv).min()) / 2
    kijun = (high.rolling(base).max() + low.rolling(base).min()) / 2
    span_a_raw = (tenkan + kijun) / 2
    span_b_raw = (high.rolling(span).max() + low.rolling(span).min()) / 2

    out = d.copy()
    out["전환선"] = tenkan
    out["기준선"] = kijun
    out["후행스팬"] = close.shift(-shift)

    # 미래 날짜를 만들어 선행스팬을 그 위에 얹는다
    dates = list(d["날짜"])
    if len(dates) >= 2:
        step = pd.Series(dates).diff().median()
        future = [dates[-1] + step * (i + 1) for i in range(shift)]
    else:
        future = []
    all_dates = dates + future

    cloud = pd.DataFrame({"날짜": all_dates})
    pad = [pd.NA] * shift
    cloud["선행스팬1"] = pd.Series(pad + list(span_a_raw))[:len(all_dates)].values
    cloud["선행스팬2"] = pd.Series(pad + list(span_b_raw))[:len(all_dates)].values
    for c in ("선행스팬1", "선행스팬2"):
        cloud[c] = pd.to_numeric(cloud[c], errors="coerce")
    return out, cloud


def add_all(df, bb_period=20, bb_k=2.0, rsi_period=14, vol_mult=2.0):
    """지표를 한꺼번에 붙인다. 반환: (지표 붙은 DataFrame, 일목 구름 DataFrame)"""
    d = add_indicators(df)
    d = bollinger(d, bb_period, bb_k)
    d = rsi(d, rsi_period)
    d = macd(d)
    d = volume_spike(d, mult=vol_mult)
    d, cloud = ichimoku(d)
    return d, cloud


def fetch_intraday(code, market, interval="1h", period="730d"):
    """60분봉 등 장중 시세. yfinance 만 제공(KRX OpenAPI 에는 분봉이 없다)."""
    import yfinance as yf

    df = yf.download(yf_ticker(code, market), period=period, interval=interval,
                     progress=False, auto_adjust=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"{interval} 데이터 없음")
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
