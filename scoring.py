# -*- coding: utf-8 -*-
"""
점수화 모듈
=====================================
- level_score : 현재값이 어느 절대수준 구간인지 (1~5)
- trend_score : 최근 3개월 변화 방향/크기 (1~5)
- 변수 최종점수 = round(0.5*level + 0.5*trend)
- 종합점수(0~100) = 가중평균(1~5) * 20
모든 변수는 '값이 낮을수록/내려갈수록 주식에 우호적'으로 방향을 통일했다.
"""

import pandas as pd

import config


def level_score(value, bands):
    """value가 속한 (하한, 상한, 점수) 구간의 점수를 반환."""
    if value is None or pd.isna(value):
        return None
    for low, high, score in bands:
        if low <= value < high:
            return score
    return None


def trend_score(current, past, trend_type):
    """
    최근 3개월 변화로 점수(1~5). 하락=우호(고점), 상승=비우호(저점).
    current : 현재값,  past : 3개월 전 값
    """
    if current is None or past is None or pd.isna(current) or pd.isna(past):
        return None

    cfg = config.TREND_THRESHOLDS[trend_type]
    if cfg["mode"] == "pct":
        if past == 0:
            return 3
        change = current / past - 1.0
    else:  # abs
        change = current - past

    flat, small = cfg["flat"], cfg["small"]
    if change < -small:
        return 5   # 크게 하락
    if change < -flat:
        return 4   # 소폭 하락
    if change <= flat:
        return 3   # 보합
    if change <= small:
        return 2   # 소폭 상승
    return 1       # 크게 상승


def _value_months_ago(series, months):
    """series(일별) 에서 마지막 날짜 기준 N개월 전 값을 asof로 조회."""
    s = series.dropna()
    if s.empty:
        return None
    last_date = s.index[-1]
    target = last_date - pd.DateOffset(months=months)
    idx = s.index.asof(target)
    if pd.isna(idx):
        return None
    return s.loc[idx]


def score_variable(series, var):
    """
    변수 하나의 점수 결과 dict 반환.
    keys: current, past, level, trend, final, weight
    """
    s = series.dropna()
    current = float(s.iloc[-1]) if not s.empty else None
    past = _value_months_ago(s, config.TREND_MONTHS)

    lvl = level_score(current, var["level_bands"])
    trd = trend_score(current, past, var["trend_type"])

    if lvl is not None and trd is not None:
        final = round(0.5 * lvl + 0.5 * trd)
    elif lvl is not None:
        final = lvl
    elif trd is not None:
        final = trd
    else:
        final = None

    return {
        "key": var["key"],
        "name": var["name"],
        "unit": var["unit"],
        "decimals": var["decimals"],
        "weight": var["weight"],
        "current": current,
        "past": past,
        "level": lvl,
        "trend": trd,
        "final": final,
    }


def score_all(frame, variables):
    """모든 변수 점수 + 종합점수 계산.
    반환: (변수별 결과 리스트, 종합점수 0~100 or None)
    """
    results = []
    for var in variables:
        if var["key"] in frame.columns:
            results.append(score_variable(frame[var["key"]], var))

    # 종합점수: final 점수가 있는 변수만 가중평균
    num = 0.0
    den = 0.0
    for r in results:
        if r["final"] is not None:
            num += r["weight"] * r["final"]
            den += r["weight"]
    composite = round(num / den * 20, 1) if den > 0 else None
    return results, composite


def score_color(final):
    """변수 하나의 점수(1~5)를 종합점수와 같은 색 체계로 바꾼다.

    새 색상표를 만들지 않고 config.SCORE_INTERPRETATION 을 그대로 쓴다.
    1점을 10, 2점을 30 … 5점을 90 으로 놓으면 각 구간 한가운데에 떨어진다.
    덕분에 게이지·구간설명·변수카드의 색이 서로 어긋나지 않는다.
    """
    if final is None:
        return "#888888"
    return interpret(final * 20 - 10)[1]


def interpret(composite):
    """종합점수 → (라벨, 색상, 설명)."""
    if composite is None:
        return ("데이터 없음", "#888888", "")
    for band in config.SCORE_INTERPRETATION:
        low, high, label, color, desc = band
        if low <= composite < high:
            return (label, color, desc)
    return ("범위 밖", "#888888", "")
