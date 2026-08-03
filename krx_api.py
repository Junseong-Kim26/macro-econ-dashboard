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


def fetch_stock_daily(bas_dd, key=None):
    """코스피 종목 일별매매정보 → DataFrame(종목코드·종목명·종가·시가총액·상장주식수)."""
    key = get_key(key)
    if not key:
        raise ValueError("KRX_API_KEY 가 없습니다.")

    rows = _call(*EP_STOCK_DAILY, bas_dd=bas_dd, key=key)
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

    return out[out["시가총액"] > 0].reset_index(drop=True)


def fetch_kospi_index(bas_dd, key=None, index_name="코스피"):
    """KOSPI 시리즈 일별시세 → 지수명별 종가. index_name 지정 시 그 지수만."""
    key = get_key(key)
    if not key:
        raise ValueError("KRX_API_KEY 가 없습니다.")

    rows = _call(*EP_KOSPI_INDEX, bas_dd=bas_dd, key=key)
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

    if index_name:
        exact = out[out["지수명"] == index_name]
        if not exact.empty:
            return exact.reset_index(drop=True)
    return out.reset_index(drop=True)


def fetch_latest_stock_daily(key=None, days_back=10):
    """가장 최근 영업일 데이터를 자동으로 찾아 반환. 반환: (DataFrame, 기준일)."""
    key = get_key(key)
    last_err = None
    for d in recent_business_day(days_back):
        try:
            df = fetch_stock_daily(d, key)
            if not df.empty:
                return df, d
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"최근 {days_back}일 내 데이터를 찾지 못했습니다. ({last_err})")
