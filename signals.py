# -*- coding: utf-8 -*-
"""
매수 타점 조건 판정
=====================================
사용자가 쓰는 표현(우상향·평평한 각도·상승각도)을 숫자로 바꿔 판정한다.

기울기 정의
  slope = (마지막값 / N봉전값 - 1) × 100 ÷ N   → "봉당 몇 %"
  · 상승(우상향) : slope >  기준
  · 평평         : |slope| ≤ 기준
  · 하락         : slope < -기준
  기준값(FLAT_EPS)은 화면에서 조절할 수 있게 인자로 받는다.

조건_1 (최소 매수 타점)
  ① 주봉 일목 전환선이 우상향
  ② 일봉에서 3~4일 연속 음봉 진행 중
  ③ 그 구간에 60분 5이평이 '하락 → 평평'으로 전환
  · 추가매수 : 60분 5이평이 '상승각도'로 전환

조건_2 (스윙)
  ① 주봉 종가가 5주 이평 위
  ② 주봉 일목 전환선이 상승각도이고 기준선 위
  ③ 60분 종가가 5이평 아래(대기) → 5이평 위로 올라서면 매수 타점
"""

import numpy as np
import pandas as pd

import ohlc

FLAT_EPS = 0.05        # 봉당 %. 이 안이면 '평평'으로 본다
DOWN_MIN, DOWN_MAX = 3, 4   # 연속 음봉 개수 범위


def slope_pct(series, bars=3):
    """최근 bars봉 동안의 '봉당 몇 %' 기울기. 값이 모자라면 None."""
    s = pd.Series(series).dropna()
    if len(s) < bars + 1:
        return None
    prev, last = float(s.iloc[-1 - bars]), float(s.iloc[-1])
    if prev == 0:
        return None
    return (last / prev - 1) * 100.0 / bars


def slope_state(sl, eps=FLAT_EPS):
    """기울기를 상승/평평/하락 세 글자로."""
    if sl is None:
        return "판정불가"
    if sl > eps:
        return "상승"
    if sl < -eps:
        return "하락"
    return "평평"


def consecutive_down(df, max_n=6):
    """마지막 봉부터 연속된 음봉(종가<시가) 개수."""
    d = df.dropna(subset=["시가", "종가"])
    n = 0
    for _, r in list(d.iterrows())[::-1][:max_n + 1]:
        if r["종가"] < r["시가"]:
            n += 1
        else:
            break
    return n


def ma(series, n=5):
    return pd.Series(series).rolling(n).mean()


def weekly_state(daily_df, eps=FLAT_EPS, slope_bars=2):
    """주봉 기준 상태: 일목 전환선·기준선, 5주 이평 대비 위치."""
    wk = ohlc.resample_ohlc(daily_df, "W")
    out = {"주봉수": len(wk)}
    if len(wk) < 10:
        out["판정불가"] = True
        return out, wk

    ich, _ = ohlc.ichimoku(wk)
    out["전환선"] = float(ich["전환선"].iloc[-1]) if pd.notna(ich["전환선"].iloc[-1]) else None
    out["기준선"] = float(ich["기준선"].iloc[-1]) if pd.notna(ich["기준선"].iloc[-1]) else None
    sl = slope_pct(ich["전환선"], slope_bars)
    out["전환선기울기"] = sl
    out["전환선상태"] = slope_state(sl, eps)
    out["전환선우상향"] = out["전환선상태"] == "상승"

    ma5 = ma(wk["종가"], 5)
    close = float(wk["종가"].iloc[-1])
    out["종가"] = close
    out["5주이평"] = float(ma5.iloc[-1]) if pd.notna(ma5.iloc[-1]) else None
    out["5주이평위"] = (out["5주이평"] is not None and close >= out["5주이평"])
    out["전환선>기준선"] = (out["전환선"] is not None and out["기준선"] is not None
                       and out["전환선"] > out["기준선"])
    return out, wk


def h60_state(h60_df, eps=FLAT_EPS, slope_bars=3):
    """60분봉 5이평 상태: 지금 기울기와 직전 기울기(전환 여부 판단용)."""
    out = {"60분봉수": len(h60_df)}
    if len(h60_df) < 12:
        out["판정불가"] = True
        return out

    m5 = ma(h60_df["종가"], 5)
    out["5이평"] = float(m5.iloc[-1]) if pd.notna(m5.iloc[-1]) else None
    out["종가"] = float(h60_df["종가"].iloc[-1])

    now = slope_pct(m5, slope_bars)
    prev = slope_pct(m5.iloc[:-slope_bars], slope_bars)   # 직전 구간
    out["5이평기울기"] = now
    out["직전기울기"] = prev
    out["5이평상태"] = slope_state(now, eps)
    out["직전상태"] = slope_state(prev, eps)

    # 하락하던 것이 평평해졌는가 / 상승으로 돌아섰는가
    out["하락→평평"] = (out["직전상태"] == "하락" and out["5이평상태"] == "평평")
    out["상승전환"] = (out["직전상태"] in ("하락", "평평") and out["5이평상태"] == "상승")
    out["5이평아래"] = (out["5이평"] is not None and out["종가"] < out["5이평"])
    out["5이평위"] = (out["5이평"] is not None and out["종가"] >= out["5이평"])
    return out


def evaluate(daily_df, h60_df, eps=FLAT_EPS,
             down_min=DOWN_MIN, down_max=DOWN_MAX):
    """조건_1·조건_2 를 판정한다. 반환: dict(상세 + 점수)"""
    wk, _ = weekly_state(daily_df, eps)
    h6 = h60_state(h60_df, eps)
    down_n = consecutive_down(daily_df)

    r = {"연속음봉": down_n}
    r.update({f"주봉_{k}": v for k, v in wk.items()})
    r.update({f"60분_{k}": v for k, v in h6.items()})

    # ---- 조건_1 : 최소 매수 타점 ----
    c1a = bool(wk.get("전환선우상향"))
    c1b = down_min <= down_n <= down_max
    c1c = bool(h6.get("하락→평평"))
    c1_add = bool(h6.get("상승전환"))
    r["조건1_주봉전환선우상향"] = c1a
    r["조건1_일봉연속음봉"] = c1b
    r["조건1_60분평평전환"] = c1c
    r["조건1_충족"] = c1a and c1b and c1c
    r["조건1_추가매수"] = c1a and c1b and c1_add

    # ---- 조건_2 : 스윙 ----
    c2a = bool(wk.get("5주이평위"))
    c2b = bool(wk.get("전환선우상향")) and bool(wk.get("전환선>기준선"))
    c2c_wait = bool(h6.get("5이평아래"))          # 대기 상태
    c2c_go = bool(h6.get("5이평위")) and bool(h6.get("상승전환"))  # 올라섬
    r["조건2_주봉5이평위"] = c2a
    r["조건2_전환선상승·기준선위"] = c2b
    r["조건2_60분대기"] = c2a and c2b and c2c_wait
    r["조건2_충족"] = c2a and c2b and c2c_go

    # ---- 매수 우선순위 점수 ----
    # 실제로 '지금 사도 되는' 신호에 높은 점수, '준비 단계'는 낮게.
    score = 0
    if r["조건1_추가매수"]:
        score += 50          # 1차 매수 후 추가매수 신호
    if r["조건1_충족"]:
        score += 40          # 최소 매수 타점
    if r["조건2_충족"]:
        score += 45          # 스윙 진입
    if r["조건2_60분대기"]:
        score += 15          # 스윙 대기(곧 신호 가능)
    if c1a:
        score += 5
    if c2a:
        score += 5
    r["신호점수"] = score

    labels = []
    if r["조건1_추가매수"]:
        labels.append("조건1 추가매수")
    if r["조건1_충족"]:
        labels.append("조건1 최소타점")
    if r["조건2_충족"]:
        labels.append("조건2 스윙진입")
    if r["조건2_60분대기"]:
        labels.append("조건2 대기")
    r["신호"] = " · ".join(labels) if labels else "해당없음"
    return r
