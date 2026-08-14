# -*- coding: utf-8 -*-
"""
AI · 데이터센터 크레딧 위험지수 모듈
=====================================
기존 scoring.py 와 방향이 정반대라서 별도로 둔다.

  scoring.py  : 값이 낮을수록 '좋다' → 점수 높음 (주식 환경 점수)
  aicredit.py : 위험이 클수록 점수 높음 (위험지수)

구성
  1층 자동수집 : config.AI_CREDIT_INDICATORS (FRED · yfinance · 파생)
  3층 체크리스트: config.AI_CREDIT_CHECKLIST (정성 판단, Dropbox 보관)

최종 위험지수 = min(100, 자동지표 점수 + 체크리스트 가점)
  체크리스트는 더하기만 한다. 구조적 사건은 위험을 더할 뿐 빼주지 않는다.
"""

import pandas as pd

import config
import data as data_mod
import journal

CHECKLIST_TABLE = "ai_credit_checklist"
CHECKLIST_COLUMNS = ["항목", "확인", "확인일자", "메모"]


# ---------------------------------------------------------------------------
# 1층 — 시계열 수집
# ---------------------------------------------------------------------------
def _fetch_one(source, sid, keys, use_cache=True):
    """data.py 의 차트 캐시 경로를 그대로 재사용해 시리즈 하나를 받는다."""
    spec = {"label": sid, "source": source, "id": sid}
    return data_mod.fetch_chart_series(spec, keys, use_cache=use_cache)


def _yoy(s):
    """전년동월 대비 상승률(%)."""
    monthly = s.resample("MS").last()
    return ((monthly / monthly.shift(12) - 1.0) * 100.0).dropna()


def _ret6m(s):
    """6개월 수익률(%) 시계열. 가격 시리즈를 '수준'으로 쓰기 위한 변환."""
    if s.empty:
        return s
    # 영업일 기준 약 126봉 ≒ 6개월. 달력 기준으로 맞춰 흔들림을 줄인다.
    daily = s.resample("D").ffill()
    return ((daily / daily.shift(182) - 1.0) * 100.0).dropna()


def load_series(indicators, keys, use_cache=True):
    """지표별 시계열을 모은다. 반환: ({key: Series}, 오류메시지 리스트)"""
    out, errors = {}, []

    for ind in indicators:
        key = ind["key"]
        try:
            if ind["source"] == "derived":
                a, e1 = _fetch_one(ind["minuend"]["source"], ind["minuend"]["id"],
                                   keys, use_cache)
                b, e2 = _fetch_one(ind["subtrahend"]["source"], ind["subtrahend"]["id"],
                                   keys, use_cache)
                for e in (e1, e2):
                    if e:
                        errors.append(f"{ind['name']}: {e}")
                if a.empty or b.empty:
                    out[key] = pd.Series(dtype="float64",
                                         index=pd.DatetimeIndex([], name="date"))
                    continue
                # 두 시리즈를 공통 일자에 맞춘 뒤 차를 구한다
                idx = a.index.union(b.index)
                raw = (a.reindex(idx).ffill() - b.reindex(idx).ffill()).dropna()
            else:
                raw, err = _fetch_one(ind["source"], ind["series_id"], keys, use_cache)
                if err:
                    errors.append(f"{ind['name']}: {err}")

            tf = ind.get("transform")
            if tf == "yoy":
                raw = _yoy(raw)
            elif tf == "ret6m":
                raw = _ret6m(raw)

            raw.name = key
            out[key] = raw
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ind['name']}: {e}")
            out[key] = pd.Series(dtype="float64",
                                 index=pd.DatetimeIndex([], name="date"))

    return out, errors


# ---------------------------------------------------------------------------
# 1층 — 점수화 (1~5, 5가 가장 위험)
# ---------------------------------------------------------------------------
def level_risk(value, bands):
    """현재값이 속한 구간의 위험점수. 구간을 못 찾으면 None."""
    if value is None or pd.isna(value):
        return None
    for low, high, score in bands:
        if low <= value < high:
            return score
    return None


def trend_risk(current, past, trend_type, trend_dir):
    """
    최근 3개월 변화 → 위험점수(1~5).
    trend_dir='up'   : 값이 오르면 위험 증가
    trend_dir='down' : 값이 내리면 위험 증가
    """
    if current is None or past is None or pd.isna(current) or pd.isna(past):
        return None

    cfg = config.AI_TREND_THRESHOLDS[trend_type]
    if cfg["mode"] == "pct":
        change = 0.0 if past == 0 else (current / past - 1.0)
    else:
        change = current - past

    # 위험이 커지는 방향을 항상 '양수'가 되도록 뒤집는다
    if trend_dir == "down":
        change = -change

    flat, small = cfg["flat"], cfg["small"]
    if change > small:
        return 5   # 위험 방향으로 크게 이동
    if change > flat:
        return 4   # 위험 방향으로 소폭 이동
    if change >= -flat:
        return 3   # 보합
    if change >= -small:
        return 2   # 안전 방향으로 소폭
    return 1       # 안전 방향으로 크게


def _value_months_ago(s, months):
    s = s.dropna()
    if s.empty:
        return None
    target = s.index[-1] - pd.DateOffset(months=months)
    idx = s.index.asof(target)
    if pd.isna(idx):
        return None
    return float(s.loc[idx])


def score_indicator(series, ind):
    """지표 하나의 위험점수 dict."""
    s = series.dropna() if series is not None else pd.Series(dtype="float64")
    current = float(s.iloc[-1]) if not s.empty else None
    past = _value_months_ago(s, config.AI_TREND_MONTHS)

    lvl = level_risk(current, ind["risk_bands"])
    trd = trend_risk(current, past, ind["trend_type"], ind["trend_dir"])

    if lvl is not None and trd is not None:
        final = round(0.5 * lvl + 0.5 * trd)
    else:
        final = lvl if lvl is not None else trd

    return {
        "key": ind["key"],
        "name": ind["name"],
        "unit": ind["unit"],
        "decimals": ind["decimals"],
        "weight": ind["weight"],
        "why": ind["why"],
        "asof": s.index[-1] if not s.empty else None,
        "current": current,
        "past": past,
        "level": lvl,
        "trend": trd,
        "final": final,
    }


def score_auto(series_map, indicators=None):
    """
    자동수집 지표 전체 점수.
    반환: (지표별 결과 리스트, 자동점수 0~100 or None)
    """
    indicators = indicators or config.AI_CREDIT_INDICATORS
    results = [score_indicator(series_map.get(i["key"]), i) for i in indicators]

    num = den = 0.0
    for r in results:
        if r["final"] is not None:
            num += r["weight"] * r["final"]
            den += r["weight"]
    auto = round(num / den * 20, 1) if den > 0 else None
    return results, auto


# ---------------------------------------------------------------------------
# 3층 — 정성 체크리스트 (Dropbox 보관)
# ---------------------------------------------------------------------------
def empty_checklist():
    """체크리스트 초기 상태(전부 미확인)."""
    return pd.DataFrame([
        {"항목": c["key"], "확인": False, "확인일자": "", "메모": ""}
        for c in config.AI_CREDIT_CHECKLIST
    ])


def load_checklist(dbx=None):
    """보관된 체크리스트를 읽는다. 없거나 실패하면 빈 체크리스트."""
    df = journal.load_table(CHECKLIST_TABLE, dbx=dbx)
    if df is None or df.empty:
        return empty_checklist()

    for col in CHECKLIST_COLUMNS:
        if col not in df.columns:
            df[col] = False if col == "확인" else ""

    # config 에 항목이 추가됐을 수 있으므로 항상 정의 기준으로 다시 맞춘다
    saved = {str(r["항목"]): r for _, r in df.iterrows()}
    rows = []
    for c in config.AI_CREDIT_CHECKLIST:
        r = saved.get(c["key"])
        if r is None:
            rows.append({"항목": c["key"], "확인": False, "확인일자": "", "메모": ""})
        else:
            rows.append({
                "항목": c["key"],
                "확인": bool(r["확인"]) if pd.notna(r["확인"]) else False,
                "확인일자": "" if pd.isna(r["확인일자"]) else str(r["확인일자"]),
                "메모": "" if pd.isna(r["메모"]) else str(r["메모"]),
            })
    return pd.DataFrame(rows)


def save_checklist(df, dbx=None):
    """체크리스트를 Dropbox에 보관. 반환: (성공여부, 오류메시지)"""
    return journal.save_table(df[CHECKLIST_COLUMNS], CHECKLIST_TABLE, dbx=dbx)


def checklist_points(df):
    """체크된 항목의 가점 합계와 체크된 항목 정의 목록."""
    if df is None or df.empty:
        return 0, []
    checked = set(df.loc[df["확인"].astype(bool), "항목"].astype(str))
    hits = [c for c in config.AI_CREDIT_CHECKLIST if c["key"] in checked]
    return sum(c["points"] for c in hits), hits


def checklist_max_points():
    return sum(c["points"] for c in config.AI_CREDIT_CHECKLIST)


# ---------------------------------------------------------------------------
# 최종 위험지수
# ---------------------------------------------------------------------------
def total_index(auto_score, points):
    """자동점수 + 체크리스트 가점, 100 상한."""
    if auto_score is None:
        return None
    return round(min(100.0, auto_score + points), 1)


def interpret(risk_index):
    """위험지수 → (라벨, 색상, 설명)."""
    if risk_index is None:
        return ("데이터 없음", "#888888", "")
    for low, high, label, color, desc in config.AI_RISK_INTERPRETATION:
        if low <= risk_index < high:
            return (label, color, desc)
    return ("범위 밖", "#888888", "")
