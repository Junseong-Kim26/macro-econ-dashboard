# -*- coding: utf-8 -*-
"""
KRX OpenAPI 클라이언트
=====================================
openapi.krx.co.kr 에서 발급받은 인증키로 시세 데이터를 받아온다.

호출 규격
  URL   : https://data-dbg.krx.co.kr/svc/apis/{분류}/{서비스}
  파라미터: AUTH_KEY(인증키), basDd(기준일 YYYYMMDD)
  응답  : JSON, 레코드는 "OutBlock_1" 리스트

※ KRX OpenAPI는 PER/PBR/EPS/BPS 같은 재무지표를 제공하지 않는다.
   재무 항목은 dart_api.py(금융감독원 DART)에서 받아 결합한다.
"""

import datetime as dt
import os

import pandas as pd
import requests

BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"

# 쓰는 서비스 (분류, 엔드포인트)
EP_STOCK_DAILY = ("sto", "stk_bydd_trd")   # 유가증권(코스피) 일별매매정보
EP_KOSPI_INDEX = ("idx", "kospi_dd_trd")   # KOSPI 시리즈 일별시세정보

# 시장별 엔드포인트 — 시장을 추가하려면 여기에 한 줄 넣으면 된다.
#  ※ KRX는 서비스마다 '이용신청·승인'이 따로 필요하다(미승인 시 401).
MARKETS = {
    "코스피": {
        "stock": ("sto", "stk_bydd_trd"),
        "index": ("idx", "kospi_dd_trd"),
        "index_name": "코스피",
        "index_options": ["코스피"],
    },
    # 코스닥은 전체 1,800여 종목 중 상당수가 적자·소형주라 대표성이 떨어져
    # 시가총액 상위 200종목만 대상으로 한다(코스피200과 같은 규모로 맞춤).
    "코스닥": {
        "stock": ("sto", "ksq_bydd_trd"),
        "index": ("idx", "kosdaq_dd_trd"),
        "index_name": "코스닥",
        # 화면에서 고를 수 있는 지수 (첫 번째가 기본)
        "index_options": ["코스닥", "코스닥 150"],
        "top_n": 200,
        "note": "코스닥 전체 1,800여 종목 중 **시가총액 상위 200종목**만 대상으로 합니다. "
                "소형·적자 종목이 많아 대표성을 위해 제한했습니다.",
    },
}
DEFAULT_MARKET = "코스피"


def find_secret(name):
    """환경변수 → Streamlit secrets에서 키를 찾는다.

    secrets.toml 에서 키를 [dropbox] 같은 섹션 '아래'에 붙여넣으면 TOML 규칙상
    그 섹션 안으로 들어가 버린다. 그래서 최상위뿐 아니라 각 섹션 안까지 뒤진다.
    """
    val = os.getenv(name, "")
    if val:
        return val
    try:
        import streamlit as st

        secrets = st.secrets
        if name in secrets:
            return str(secrets[name])
        # 섹션 안에 들어가 있는 경우까지 탐색
        for section in secrets:
            try:
                sub = secrets[section]
                if hasattr(sub, "keys") and name in sub:
                    return str(sub[name])
            except Exception:
                continue
    except Exception:
        pass
    return ""


def get_key(explicit=None):
    """KRX 인증키를 찾는다."""
    return explicit or find_secret("KRX_API_KEY")


def _call(category, endpoint, bas_dd, key, timeout=30):
    """KRX API 한 번 호출 → 레코드 리스트."""
    url = f"{BASE_URL}/{category}/{endpoint}"
    r = requests.get(url, params={"AUTH_KEY": key, "basDd": bas_dd}, timeout=timeout)

    if r.status_code == 401:
        raise PermissionError(
            "KRX 인증 실패(401). 인증키가 맞는지, 그리고 해당 서비스의 "
            "'이용신청'이 승인되었는지 확인하세요.")
    r.raise_for_status()

    try:
        payload = r.json()
    except ValueError:
        raise RuntimeError(f"KRX 응답을 해석할 수 없습니다: {r.text[:200]}")

    if "OutBlock_1" not in payload:
        raise RuntimeError(f"KRX 응답 형식이 예상과 다릅니다: {str(payload)[:200]}")
    return payload["OutBlock_1"]


def _to_num(s):
    """'1,234' 같은 문자열을 숫자로."""
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.replace("-", "", regex=False)
        .replace("", None), errors="coerce")


def recent_business_day(days_back=10):
    """오늘부터 거슬러 올라가며 시도할 날짜 문자열 목록(YYYYMMDD)."""
    today = dt.date.today()
    return [(today - dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(days_back)]


def fetch_stock_daily(bas_dd, key=None, market=DEFAULT_MARKET):
    """시장별 종목 일별매매정보 → DataFrame(종목코드·종목명·종가·시가총액·상장주식수)."""
    key = get_key(key)
    if not key:
        raise ValueError("KRX_API_KEY 가 없습니다.")
    if market not in MARKETS:
        raise ValueError(f"알 수 없는 시장: {market}")

    rows = _call(*MARKETS[market]["stock"], bas_dd=bas_dd, key=key)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    out = pd.DataFrame()
    # KRX 필드명: ISU_CD(단축코드), ISU_ABBRV(한글종목약명),
    #             TDD_CLSPRC(종가), MKTCAP(시가총액), LIST_SHRS(상장주식수)
    def pick(*names):
        for n in names:
            if n in df.columns:
                return df[n]
        return None

    code = pick("ISU_CD", "ISU_SRT_CD", "SRT_CD")
    name = pick("ISU_ABBRV", "ISU_NM", "ISU_KOR_ABBRV")
    close = pick("TDD_CLSPRC", "CLSPRC")
    cap = pick("MKTCAP", "MKT_CAP")
    shrs = pick("LIST_SHRS", "LISTED_SHRS")

    if code is None or cap is None:
        raise RuntimeError(f"예상한 필드가 없습니다. 실제 컬럼: {list(df.columns)}")

    out["종목코드"] = code.astype(str).str.strip().str.zfill(6)
    out["종목명"] = name.astype(str).str.strip() if name is not None else out["종목코드"]
    out["종가"] = _to_num(close) if close is not None else None
    out["시가총액"] = _to_num(cap)
    if shrs is not None:
        out["상장주식수"] = _to_num(shrs)
    out["기준일"] = bas_dd

    out = out[out["시가총액"] > 0].reset_index(drop=True)

    # 상위 N개만 쓰는 시장(코스닥)은 시가총액 기준으로 여기서 잘라낸다
    top_n = MARKETS[market].get("top_n")
    if top_n:
        out = out.nlargest(top_n, "시가총액").reset_index(drop=True)
    return out


def fetch_index(bas_dd, key=None, market=DEFAULT_MARKET, index_name=None):
    """시장 대표지수 일별시세 → 지수명·지수 종가.

    응답에는 그 시장의 모든 지수(섹터·규모별)가 들어 있어 대표지수만 골라낸다.
    index_name 을 주면 그 이름으로, 안 주면 시장 기본 지수명으로 찾는다.
    """
    key = get_key(key)
    if not key:
        raise ValueError("KRX_API_KEY 가 없습니다.")
    if market not in MARKETS:
        raise ValueError(f"알 수 없는 시장: {market}")
    index_name = index_name or MARKETS[market]["index_name"]

    rows = _call(*MARKETS[market]["index"], bas_dd=bas_dd, key=key)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    name_col = next((c for c in ("IDX_NM", "IDX_KOR_NM", "INDX_NM") if c in df.columns), None)
    close_col = next((c for c in ("CLSPRC_IDX", "CLS_IDX", "TDD_CLSPRC") if c in df.columns), None)
    if name_col is None or close_col is None:
        raise RuntimeError(f"예상한 필드가 없습니다. 실제 컬럼: {list(df.columns)}")

    out = pd.DataFrame({
        "지수명": df[name_col].astype(str).str.strip(),
        "지수": _to_num(df[close_col]),
        "기준일": bas_dd,
    }).dropna(subset=["지수"])

    if not index_name:
        return out.reset_index(drop=True)

    # 1) 정확히 일치
    exact = out[out["지수명"] == index_name]
    if not exact.empty:
        return exact.reset_index(drop=True)

    # 2) 이름을 포함하는 것 중 가장 짧은 것(= 하위지수가 아닌 대표지수)
    cand = out[out["지수명"].str.contains(index_name, na=False)]
    if not cand.empty:
        pick = cand.loc[cand["지수명"].str.len().idxmin()]
        return pd.DataFrame([pick]).reset_index(drop=True)

    # 3) 못 찾으면 후보를 보여주고 중단 — 엉뚱한 지수를 쓰는 것보다 낫다
    raise RuntimeError(
        f"'{index_name}' 지수를 찾지 못했습니다. 응답에 있는 지수명: "
        f"{', '.join(out['지수명'].head(15))} ...")


# ---------------------------------------------------------------------------
# 업종별 거래대금·시가총액
# ---------------------------------------------------------------------------
# KRX 업종지수에는 상위분류가 섞여 있어 그대로 더하면 중복된다.
#   · '제조' 는 전기전자·화학·기계장비 등의 상위 (검증: 제조 3,984조 = 하위합 3,983조)
#   · '증권'·'보험' 은 '금융' 의 하위 (금융은 은행 등을 포함해 따로 지수가 없음)
# 아래 3개를 빼면 합계가 시장 전체의 100.0%(코스피)·99.9%(코스닥)로 맞는다.
SECTOR_PARENTS = {"제조", "증권", "보험"}


def fetch_sectors(bas_dd, key=None, market=DEFAULT_MARKET, leaf_only=True):
    """업종별 거래대금·시가총액 → DataFrame(업종·거래대금·시가총액·기준일).

    leaf_only=True 면 상위분류(SECTOR_PARENTS)를 빼서 중복 없이 합산되게 한다.
    """
    key = get_key(key)
    if not key:
        raise ValueError("KRX_API_KEY 가 없습니다.")
    if market not in MARKETS:
        raise ValueError(f"알 수 없는 시장: {market}")

    rows = _call(*MARKETS[market]["index"], bas_dd=bas_dd, key=key)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    need = {"IDX_NM", "ACC_TRDVAL", "MKTCAP"}
    if not need.issubset(df.columns):
        raise RuntimeError(f"예상한 필드가 없습니다. 실제 컬럼: {list(df.columns)}")

    out = pd.DataFrame({
        "업종": df["IDX_NM"].astype(str).str.strip(),
        "거래대금": _to_num(df["ACC_TRDVAL"]),
        "시가총액": _to_num(df["MKTCAP"]),
        "기준일": bas_dd,
    })

    # 시장 대표지수·규모지수(코스피 200 등)를 빼고 업종지수만 남긴다
    prefix = "코스피" if MARKETS[market]["index"][1].startswith("kospi") else "코스닥"
    out = out[~out["업종"].str.startswith(prefix)]
    if leaf_only:
        out = out[~out["업종"].isin(SECTOR_PARENTS)]

    return out.dropna(subset=["거래대금"]).reset_index(drop=True)


def period_end_dates(years_back=3, months=6, weeks=None, end=None):
    """일정 간격의 시점 목록(과거→현재).

    weeks 를 주면 주 단위(금요일 기준), 아니면 months 단위(월말 기준).
    아직 오지 않은 날짜는 오늘로 자르고, 마지막이 오늘과 떨어져 있으면 오늘을 덧붙인다.
    """
    end = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years_back)

    if weeks:
        # 주간 시점은 그 주의 금요일(주 마지막 거래일)로 잡는다
        dates = list(pd.date_range(start, end, freq=f"{int(weeks)}W-FRI"))
        gap_days = 7 * int(weeks)
    else:
        dates = [d + pd.offsets.MonthEnd(0) if d.day != d.days_in_month else d
                 for d in pd.date_range(start, end, freq=pd.DateOffset(months=months))]
        gap_days = 20

    out = [min(d, end) for d in dates]
    if out and (end - out[-1]).days > gap_days // 2:
        out.append(end)
    return sorted(set(out))


def fetch_kospi_index(bas_dd, key=None, index_name="코스피"):
    """(호환용) 예전 이름 — fetch_index 의 코스피 버전."""
    return fetch_index(bas_dd, key, market="코스피", index_name=index_name)


def fetch_near(fetch_fn, date, key=None, back=7):
    """해당 날짜가 휴장일이면 직전 영업일까지 거슬러 시도한다.

    fetch_fn : fetch_stock_daily / fetch_index (시장은 partial 로 미리 묶어 전달)
    반환: (DataFrame, 실제 사용된 기준일) — 못 찾으면 (빈 DF, None)
    """
    d = pd.Timestamp(date)
    for i in range(back):
        bas = (d - pd.Timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = fetch_fn(bas, key)
            if df is not None and not df.empty:
                return df, bas
        except PermissionError:
            raise
        except Exception:
            continue
    return pd.DataFrame(), None


def month_end_dates(years_back=3, end=None):
    """최근 N년치 월말 날짜 목록(과거→현재)."""
    end = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years_back)
    return list(pd.date_range(start, end, freq="ME"))


def fetch_latest_stock_daily(key=None, days_back=10, market=DEFAULT_MARKET):
    """가장 최근 영업일 데이터를 자동으로 찾아 반환. 반환: (DataFrame, 기준일)."""
    key = get_key(key)
    last_err = None
    for d in recent_business_day(days_back):
        try:
            df = fetch_stock_daily(d, key, market=market)
            if not df.empty:
                return df, d
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"최근 {days_back}일 내 데이터를 찾지 못했습니다. ({last_err})")
