# -*- coding: utf-8 -*-
"""
데이터 수집 모듈
=====================================
- FRED(미국) / ECOS(한국은행) 에서 시계열을 받아온다.
- 변수마다 주기(일/월/분기)가 다르므로, 공통 '일별' 인덱스에 맞춰
  직전값 유지(forward-fill)로 정렬한다.
- 받은 원자료는 cache/ 폴더에 parquet으로 저장해 재요청을 줄인다.
"""

import os
import datetime as dt

import pandas as pd
import requests

import config

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 개별 소스 조회
# ---------------------------------------------------------------------------
def fetch_fred(series_id, api_key, start=config.DATA_START):
    """FRED 시리즈를 pandas Series(index=날짜)로 반환."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        return pd.Series(dtype="float64", name=series_id)
    df = pd.DataFrame(obs)
    df["date"] = pd.to_datetime(df["date"])
    # FRED는 결측을 '.' 으로 표시
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.set_index("date")["value"].dropna()
    s.name = series_id
    return s


def fetch_ecos(ecos_info, api_key, start=config.DATA_START):
    """한국은행 ECOS StatisticSearch 조회 → pandas Series(index=날짜)."""
    stat = ecos_info["stat_code"]
    item = ecos_info["item_code"]
    cycle = ecos_info.get("cycle", "D")

    # ECOS 날짜 포맷: 일(D)=YYYYMMDD, 월(M)=YYYYMM, 분기(Q)=YYYYQn
    start_dt = pd.to_datetime(start)
    today = dt.date.today()
    if cycle == "D":
        s_date, e_date = start_dt.strftime("%Y%m%d"), today.strftime("%Y%m%d")
    elif cycle == "M":
        s_date, e_date = start_dt.strftime("%Y%m"), today.strftime("%Y%m")
    else:  # Q, A 등은 필요 시 확장
        s_date, e_date = start_dt.strftime("%Y"), today.strftime("%Y")

    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/"
        f"1/100000/{stat}/{cycle}/{s_date}/{e_date}/{item}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    payload = r.json()

    if "StatisticSearch" not in payload:
        # ECOS는 오류도 200으로 주며 RESULT 안에 메시지를 담는다
        msg = payload.get("RESULT", {}).get("MESSAGE", str(payload)[:200])
        raise RuntimeError(f"ECOS 오류({stat}/{item}): {msg}")

    rows = payload["StatisticSearch"]["row"]
    df = pd.DataFrame(rows)

    def _parse_time(t):
        if cycle == "D":
            return pd.to_datetime(t, format="%Y%m%d")
        if cycle == "M":
            return pd.to_datetime(t, format="%Y%m")
        return pd.to_datetime(t[:4])  # 연도

    df["date"] = df["TIME"].apply(_parse_time)
    df["value"] = pd.to_numeric(df["DATA_VALUE"], errors="coerce")
    s = df.set_index("date")["value"].dropna().sort_index()
    s.name = stat + "_" + item
    return s


# ---------------------------------------------------------------------------
# 변환 / 캐시 / 통합
# ---------------------------------------------------------------------------
def _apply_transform(s, transform):
    """transform='yoy' 이면 전년동월대비 상승률(%)로 변환."""
    if transform == "yoy":
        monthly = s.resample("MS").last()
        yoy = (monthly / monthly.shift(12) - 1.0) * 100.0
        return yoy.dropna()
    return s


def _cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.parquet")


def fetch_variable(var, keys, use_cache=True, max_age_hours=12):
    """
    변수 하나의 원자료(네이티브 주기, 변환 적용 후)를 Series로 반환.
    실패하면 캐시로 대체하고, 그래도 없으면 예외를 그대로 올린다.
    반환: (Series, 오류메시지 or None)
    """
    path = _cache_path(var["key"])

    # 1) 신선한 캐시가 있으면 사용
    if use_cache and os.path.exists(path):
        age_h = (dt.datetime.now().timestamp() - os.path.getmtime(path)) / 3600.0
        if age_h < max_age_hours:
            s = pd.read_parquet(path)["value"]
            s.name = var["key"]
            return s, None

    # 2) 실제 조회
    try:
        if var["source"] == "fred":
            raw = fetch_fred(var["series_id"], keys.get("fred", ""))
        elif var["source"] == "ecos":
            raw = fetch_ecos(var["ecos"], keys.get("ecos", ""))
        else:
            raise ValueError(f"알 수 없는 source: {var['source']}")

        s = _apply_transform(raw, var.get("transform"))
        s.name = var["key"]
        # 캐시 저장
        s.to_frame("value").to_parquet(path)
        return s, None
    except Exception as e:  # noqa: BLE001
        # 3) 조회 실패 → 오래된 캐시라도 있으면 사용
        if os.path.exists(path):
            s = pd.read_parquet(path)["value"]
            s.name = var["key"]
            return s, f"{var['name']}: 최신 조회 실패, 캐시 사용 ({e})"
        return pd.Series(dtype="float64", name=var["key"]), f"{var['name']}: {e}"


def build_daily_frame(variables, keys, use_cache=True):
    """
    모든 변수를 공통 '일별' 인덱스에 맞춰 forward-fill 한 DataFrame 반환.
    반환: (DataFrame[일별, 변수별 컬럼], 오류메시지 리스트)
    """
    series_map = {}
    errors = []
    for var in variables:
        s, err = fetch_variable(var, keys, use_cache=use_cache)
        if err:
            errors.append(err)
        if not s.empty:
            series_map[var["key"]] = s

    if not series_map:
        return pd.DataFrame(), errors

    # 공통 일별 인덱스: 가장 이른 시작 ~ 오늘
    start = min(s.index.min() for s in series_map.values())
    idx = pd.date_range(start=start, end=pd.Timestamp.today().normalize(), freq="D")

    frame = pd.DataFrame(index=idx)
    for key, s in series_map.items():
        frame[key] = s.reindex(idx, method="ffill")

    return frame, errors
