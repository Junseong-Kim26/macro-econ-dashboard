# -*- coding: utf-8 -*-
"""
점수 로직 검증 (API 키 없이 실행 가능)
=====================================
합성 데이터로 level/trend/composite 계산을 검증한다.
실행:  python test_scoring.py
"""

import pandas as pd

import config
import scoring


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def test_level_bands():
    us10 = config.get_variable("us10y")
    assert scoring.level_score(1.5, us10["level_bands"]) == 5
    assert scoring.level_score(4.2, us10["level_bands"]) == 2   # 계획서 예시
    assert scoring.level_score(6.0, us10["level_bands"]) == 1
    # WTI U자형
    wti = config.get_variable("wti")
    assert scoring.level_score(30, wti["level_bands"]) == 3
    assert scoring.level_score(50, wti["level_bands"]) == 5
    assert scoring.level_score(120, wti["level_bands"]) == 1
    print("[OK] level_score")


def test_trend():
    # 금리류: 3개월간 0.8%p 하락 → 크게 하락 → 5
    assert scoring.trend_score(3.0, 3.8, "rate") == 5
    # 0.3%p 상승 → 소폭 상승 → 2
    assert scoring.trend_score(4.3, 4.0, "rate") == 2
    # 보합
    assert scoring.trend_score(4.05, 4.0, "rate") == 3
    # WTI 비율: 20% 상승 → 크게 상승 → 1
    assert scoring.trend_score(120, 100, "wti") == 1
    print("[OK] trend_score")


def test_composite():
    # 두 변수만으로 종합점수 검증
    idx = pd.date_range("2024-01-01", periods=200, freq="D")
    # us10y: 3.5 유지 (수준3), 값 불변이라 추세3 → final 3
    s1 = pd.Series(3.5, index=idx)
    # wti: 50 유지 (수준5), 추세3 → final 4
    s2 = pd.Series(50.0, index=idx)
    frame = pd.DataFrame({"us10y": s1, "wti": s2})
    subset = [config.get_variable("us10y"), config.get_variable("wti")]
    results, comp = scoring.score_all(frame, subset)

    by = {r["key"]: r for r in results}
    assert by["us10y"]["final"] == 3
    assert by["wti"]["final"] == 4
    # 가중치는 config에서 읽어 계산
    w10 = config.get_variable("us10y")["weight"]
    wwti = config.get_variable("wti")["weight"]
    expected = (w10 * 3 + wwti * 4) / (w10 + wwti) * 20
    assert approx(comp, round(expected, 1)), f"{comp} != {round(expected,1)}"
    print(f"[OK] composite = {comp} (기대 {round(expected,1)})")


def test_weights_sum():
    total = sum(v["weight"] for v in config.VARIABLES)
    assert total == 100, f"가중치 합이 100이 아님: {total}"
    print(f"[OK] 가중치 합 = {total}")


if __name__ == "__main__":
    test_level_bands()
    test_trend()
    test_composite()
    test_weights_sum()
    print("\n모든 테스트 통과 [PASS]")
