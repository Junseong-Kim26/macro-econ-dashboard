# -*- coding: utf-8 -*-
"""
AI크레딧 위험지수 로직 검증 (API 키·Dropbox 없이 실행 가능)
=====================================
방향이 기존 scoring.py 와 반대(높을수록 위험)이므로 그 부분을 집중 검증한다.
실행:  python test_aicredit.py
"""

import pandas as pd

import aicredit
import config


def _ind(key):
    for i in config.AI_CREDIT_INDICATORS:
        if i["key"] == key:
            return i
    raise KeyError(key)


def test_level_risk_u_shape():
    """신용스프레드는 U자형 — 너무 좁아도, 너무 벌어져도 위험."""
    hy = _ind("hy_oas")["risk_bands"]
    assert aicredit.level_risk(2.71, hy) == 5   # 역사적 최저권 = 위험 미가격
    assert aicredit.level_risk(3.5, hy) == 4
    assert aicredit.level_risk(4.5, hy) == 1    # 정상적인 위험 보상
    assert aicredit.level_risk(6.5, hy) == 3
    assert aicredit.level_risk(12.0, hy) == 5   # 위기
    # 구간을 벗어나지 않는지 (경계값)
    assert aicredit.level_risk(3.0, hy) == 4    # 하한 포함
    assert aicredit.level_risk(3.8, hy) == 1
    print("[OK] level_risk U자형 (좁아도 벌어져도 위험)")


def test_trend_direction():
    """trend_dir 에 따라 위험 방향이 뒤집히는지."""
    # 스프레드: 오르면 위험(up). 0.8%p 확대 → 크게 위험 → 5
    assert aicredit.trend_risk(4.0, 3.2, "spread", "up") == 5
    # 0.3%p 확대 → 소폭 위험 → 4
    assert aicredit.trend_risk(3.5, 3.2, "spread", "up") == 4
    # 보합
    assert aicredit.trend_risk(3.25, 3.2, "spread", "up") == 3
    # 축소 → 위험 낮아짐 → 1
    assert aicredit.trend_risk(2.4, 3.2, "spread", "up") == 1

    # 수익률: 내리면 위험(down). 같은 -15%p 변화가 위험 5가 되어야 한다
    assert aicredit.trend_risk(-5.0, 10.0, "ret", "down") == 5
    # 오르면 위험 낮아짐
    assert aicredit.trend_risk(25.0, 10.0, "ret", "down") == 1
    print("[OK] trend_risk 방향 뒤집기 (up / down)")


def test_score_indicator():
    """수준·추세 결합. 값이 변하지 않으면 추세는 항상 보합(3)."""
    idx = pd.date_range("2025-01-01", periods=400, freq="D")
    s = pd.Series(2.71, index=idx)          # 하이일드 OAS 극단 압축 유지
    r = aicredit.score_indicator(s, _ind("hy_oas"))
    assert r["level"] == 5 and r["trend"] == 3
    assert r["final"] == 4                  # round(0.5*5 + 0.5*3)
    assert r["current"] == 2.71
    print(f"[OK] score_indicator 결합 (수준5·추세3 → 최종 {r['final']})")


def test_empty_series():
    """데이터를 못 받아온 지표가 있어도 죽지 않아야 한다."""
    empty = pd.Series(dtype="float64", index=pd.DatetimeIndex([]))
    r = aicredit.score_indicator(empty, _ind("hy_oas"))
    assert r["current"] is None and r["final"] is None
    # 전부 비어 있으면 자동점수는 None
    results, auto = aicredit.score_auto({})
    assert auto is None, f"빈 입력인데 점수가 나옴: {auto}"
    print("[OK] 빈 시리즈 처리 (앱이 죽지 않음)")


def test_partial_data():
    """일부 지표만 들어와도 남은 가중치로 계산되어야 한다."""
    idx = pd.date_range("2025-01-01", periods=400, freq="D")
    smap = {"hy_oas": pd.Series(2.71, index=idx)}   # 1개만
    results, auto = aicredit.score_auto(smap)
    assert auto == 80.0, f"단일 지표 점수 오류: {auto}"  # final 4 → 4*20
    print(f"[OK] 일부 지표만 있어도 계산됨 (자동점수 {auto})")


def test_checklist_points():
    df = aicredit.empty_checklist()
    assert aicredit.checklist_points(df)[0] == 0

    df.loc[df["항목"] == "resecuritization", "확인"] = True
    pts, hits = aicredit.checklist_points(df)
    assert pts == 25 and len(hits) == 1

    df.loc[df["항목"] == "cds_index", "확인"] = True
    pts, _ = aicredit.checklist_points(df)
    assert pts == 45
    print(f"[OK] 체크리스트 가점 (최대 {aicredit.checklist_max_points()})")


def test_total_index_cap():
    """체크리스트는 더하기만 하고, 100을 넘지 않는다."""
    assert aicredit.total_index(60.0, 0) == 60.0
    assert aicredit.total_index(60.0, 25) == 85.0
    assert aicredit.total_index(95.0, 50) == 100.0   # 상한
    assert aicredit.total_index(None, 25) is None    # 자동점수 없으면 계산 불가
    print("[OK] 최종지수 상한 100 · 가점은 더하기만")


def test_interpret_bands():
    """해석구간이 0~100을 빈틈없이 덮는지."""
    for v, expect in [(0, "낮음"), (24.9, "낮음"), (25, "보통"), (44.9, "보통"),
                      (45, "경계"), (64.9, "경계"), (65, "높음"), (84.9, "높음"),
                      (85, "매우 높음"), (100, "매우 높음")]:
        label = aicredit.interpret(v)[0]
        assert label == expect, f"{v} → {label} (기대 {expect})"
    assert aicredit.interpret(None)[0] == "데이터 없음"
    print("[OK] 해석구간 경계 (0~100 빈틈 없음)")


def test_weights_and_bands():
    total = sum(i["weight"] for i in config.AI_CREDIT_INDICATORS)
    assert total == 100, f"가중치 합이 100이 아님: {total}"

    # 모든 지표의 risk_bands 가 실수 전 구간을 덮는지 (구멍 = 점수 None)
    for ind in config.AI_CREDIT_INDICATORS:
        bands = ind["risk_bands"]
        assert bands[0][0] == float("-inf"), f"{ind['key']}: 하단이 -inf 아님"
        assert bands[-1][1] == float("inf"), f"{ind['key']}: 상단이 inf 아님"
        for (_, hi), (lo, _) in zip([(b[0], b[1]) for b in bands[:-1]],
                                    [(b[0], b[1]) for b in bands[1:]]):
            assert hi == lo, f"{ind['key']}: 구간이 이어지지 않음 ({hi} vs {lo})"
        for _, _, score in bands:
            assert 1 <= score <= 5, f"{ind['key']}: 위험점수 범위 밖 {score}"
    print(f"[OK] 가중치 합 = {total} · 모든 구간 연속 · 점수 1~5")


def test_trend_types_exist():
    """config 오타로 KeyError 나는 것을 미리 잡는다."""
    for ind in config.AI_CREDIT_INDICATORS:
        assert ind["trend_type"] in config.AI_TREND_THRESHOLDS, \
            f"{ind['key']}: 없는 trend_type {ind['trend_type']}"
        assert ind["trend_dir"] in ("up", "down"), \
            f"{ind['key']}: 잘못된 trend_dir {ind['trend_dir']}"
    print("[OK] trend_type · trend_dir 정의 확인")


if __name__ == "__main__":
    test_level_risk_u_shape()
    test_trend_direction()
    test_score_indicator()
    test_empty_series()
    test_partial_data()
    test_checklist_points()
    test_total_index_cap()
    test_interpret_bands()
    test_weights_and_bands()
    test_trend_types_exist()
    print("\n모든 테스트 통과 [PASS]")
