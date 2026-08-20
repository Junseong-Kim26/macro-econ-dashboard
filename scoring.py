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


TREND_LABELS = {5: "크게 하락", 4: "소폭 하락", 3: "보합",
                2: "소폭 상승", 1: "크게 상승"}


def trend_label(score):
    """추세 점수를 방향이 드러나는 말로 바꾼다.

    점수만 보면 오르는 중인지 내리는 중인지 알 수 없어서 필요하다.
    모든 변수를 '내려갈수록 우호' 로 통일했으므로 점수가 높을수록 하락이다.
    """
    return TREND_LABELS.get(score, "판단 불가")


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
        # 화면에서 3개월 변화량을 %p 로 쓸지 % 로 쓸지 정하는 데 쓴다
        "trend_type": var["trend_type"],
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


def _level_series(values, bands):
    """level_score 의 시계열판. 구간마다 마스크로 한 번에 채운다."""
    out = pd.Series(float("nan"), index=values.index)
    for low, high, score in bands:
        out[(values >= low) & (values < high)] = score
    return out


def _trend_series(values, past, trend_type):
    """trend_score 의 시계열판. 경계 조건은 scalar 판과 똑같이 맞춘다.

        change < -small          → 5 (크게 하락)
        -small <= change < -flat → 4 (소폭 하락)
        -flat  <= change <= flat → 3 (보합)
        flat   <  change <= small→ 2 (소폭 상승)
        change > small           → 1 (크게 상승)
    """
    cfg = config.TREND_THRESHOLDS[trend_type]
    if cfg["mode"] == "pct":
        change = values / past.replace(0, float("nan")) - 1.0
    else:
        change = values - past

    flat, small = cfg["flat"], cfg["small"]
    out = pd.Series(3.0, index=values.index)          # 기본은 보합
    out[change < -small] = 5.0
    out[(change >= -small) & (change < -flat)] = 4.0
    out[(change > flat) & (change <= small)] = 2.0
    out[change > small] = 1.0
    out[change.isna()] = float("nan")
    return out


def score_history(frame, variables):
    """날짜별 종합점수(0~100)를 시계열로 되돌려 계산한다.

    화면의 게이지는 '오늘의 점수' 한 값뿐이라, 점수가 좋아지는 중인지
    나빠지는 중인지 알 수 없다. 그래서 과거 각 날짜에 같은 방식으로
    점수를 매겨 추세선을 그린다.

    frame 은 이미 일별로 forward-fill 된 표이므로, 각 날짜의 값은
    '그 날까지 알려진 마지막 값' 이다. score_variable 이 쓰는 asof 조회와
    같은 뜻이라 오늘 값은 score_all 결과와 정확히 일치한다.

    반환: (종합점수 Series, 그 날짜에 점수가 매겨진 변수 개수 Series)
    """
    if frame.empty:
        empty = pd.Series(dtype="float64")
        return empty, empty

    past_idx = frame.index - pd.DateOffset(months=config.TREND_MONTHS)

    num = pd.Series(0.0, index=frame.index)   # 가중치 × 점수 합
    den = pd.Series(0.0, index=frame.index)   # 점수가 있는 변수의 가중치 합
    cnt = pd.Series(0, index=frame.index)     # 점수가 매겨진 변수 개수

    for var in variables:
        key = var["key"]
        if key not in frame.columns:
            continue
        cur = frame[key]
        # 3개월 전 값 — 일별 연속 인덱스라 날짜를 그대로 당겨 오면 된다
        past = pd.Series(cur.reindex(past_idx).values, index=frame.index)

        lvl = _level_series(cur, var["level_bands"])
        trd = _trend_series(cur, past, var["trend_type"])

        # 둘 다 있으면 반반, 한쪽만 있으면 그 값 (score_variable 과 동일)
        final = (0.5 * lvl + 0.5 * trd).round()
        final = final.fillna(lvl).fillna(trd)

        has = final.notna()
        num += var["weight"] * final.fillna(0.0)
        den += var["weight"] * has
        cnt += has.astype(int)

    composite = (num / den.replace(0, float("nan")) * 20).round(1)
    return composite, cnt


def interpret(composite):
    """종합점수 → (라벨, 색상, 설명)."""
    if composite is None:
        return ("데이터 없음", "#888888", "")
    for band in config.SCORE_INTERPRETATION:
        low, high, label, color, desc = band
        if low <= composite < high:
            return (label, color, desc)
    return ("범위 밖", "#888888", "")
