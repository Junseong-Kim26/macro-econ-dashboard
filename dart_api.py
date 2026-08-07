# -*- coding: utf-8 -*-
"""
DART(금융감독원 전자공시) OpenAPI 클라이언트
=====================================
KRX가 주지 않는 재무항목(자본총계·당기순이익)을 받아온다.

  · corpCode.xml(zip) : 종목코드 ↔ DART 고유번호(corp_code) 매핑
  · 다중회사 주요계정  : 여러 회사의 재무상태표·손익계산서 주요계정을 한 번에

계산에 쓰는 항목
  자본총계   → PBR = 시가총액 ÷ 자본총계
  당기순이익 → ROE = 당기순이익 ÷ 자본총계 × 100
"""

import io
import os
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests

BASE = "https://opendart.fss.or.kr/api"

# (연결, 읽기) 타임아웃. 연결은 짧게 잡아 막혔을 때 빨리 알아채도록 한다.
TIMEOUT = (10, 120)

UNREACHABLE_MSG = (
    "DART 서버에 연결하지 못했습니다.\n\n"
    "**Streamlit Cloud(해외 서버)에서는 DART API 접속이 차단됩니다.** "
    "KRX는 되지만 DART만 막힙니다.\n\n"
    "➡️ **해결법**: 내 PC에서 대시보드를 실행해 `API로 불러오기` 를 누르세요. "
    "수집 결과가 Dropbox에 저장되어, 이 클라우드 화면에서도 그대로 보입니다."
)


class DartUnreachable(RuntimeError):
    """DART에 네트워크로 닿지 못했을 때(해외 IP 차단 등)."""


def _get(url, params, timeout=TIMEOUT):
    """DART 호출 공통 래퍼 — 연결 실패를 알아보기 쉬운 예외로 바꾼다."""
    try:
        return requests.get(url, params=params, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise DartUnreachable(UNREACHABLE_MSG) from e

# 보고서 코드
REPRT = {
    "사업보고서(연간)": "11011",
    "3분기보고서": "11014",
    "반기보고서": "11012",
    "1분기보고서": "11013",
}

# 계정명이 회사마다 조금씩 달라 여러 표기를 허용
EQUITY_NAMES = ["자본총계"]
PROFIT_NAMES = ["당기순이익", "당기순이익(손실)", "연결당기순이익"]


def get_key(explicit=None):
    """DART 인증키를 찾는다(최상위·섹션 안 모두 탐색 — krx_api와 동일 규칙)."""
    import krx_api

    return explicit or krx_api.find_secret("DART_API_KEY")


# ---------------------------------------------------------------------------
# 종목코드 ↔ corp_code 매핑
# ---------------------------------------------------------------------------
def load_corp_map(key=None, timeout=60):
    """corpCode.zip 을 받아 {종목코드(6자리): corp_code(8자리)} 반환."""
    key = get_key(key)
    if not key:
        raise ValueError("DART_API_KEY 가 없습니다.")

    r = _get(f"{BASE}/corpCode.xml", {"crtfc_key": key}, timeout=(10, timeout))
    r.raise_for_status()

    # 오류일 때는 zip이 아니라 JSON/XML 메시지가 온다
    if not r.content[:2] == b"PK":
        raise RuntimeError(f"DART corpCode 응답 오류: {r.content[:200]!r}")

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml_name = z.namelist()[0]
        root = ET.fromstring(z.read(xml_name).decode("utf-8"))

    mapping = {}
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        corp = (item.findtext("corp_code") or "").strip()
        if stock and corp and stock != " ":
            mapping[stock.zfill(6)] = corp
    return mapping


# ---------------------------------------------------------------------------
# 재무 주요계정
# ---------------------------------------------------------------------------
def _pick_amount(rows, account_names, prefer_fs="CFS"):
    """레코드들 중 원하는 계정의 당기금액을 뽑는다. 연결(CFS) 우선, 없으면 개별(OFS)."""
    for fs in (prefer_fs, "OFS", "CFS"):
        for row in rows:
            if row.get("fs_div") and row["fs_div"] != fs:
                continue
            nm = (row.get("account_nm") or "").replace(" ", "")
            if any(nm == a.replace(" ", "") for a in account_names):
                val = str(row.get("thstrm_amount", "")).replace(",", "").strip()
                if val and val not in ("-", ""):
                    try:
                        return float(val)
                    except ValueError:
                        continue
    return None


def fetch_financials(corp_codes, year, reprt_code, key=None,
                     batch_size=100, timeout=60, progress=None):
    """다중회사 주요계정 조회.

    corp_codes : corp_code 리스트
    반환: DataFrame(corp_code, 자본총계, 당기순이익)
    """
    key = get_key(key)
    if not key:
        raise ValueError("DART_API_KEY 가 없습니다.")

    records = {}
    total = len(corp_codes)
    for i in range(0, total, batch_size):
        batch = corp_codes[i:i + batch_size]
        params = {
            "crtfc_key": key,
            "corp_code": ",".join(batch),
            "bsns_year": str(year),
            "reprt_code": reprt_code,
        }
        r = _get(f"{BASE}/fnlttMultiAcnt.json", params, timeout=(10, timeout))
        r.raise_for_status()
        js = r.json()

        status = js.get("status")
        if status == "013":       # 조회 데이터 없음
            pass
        elif status not in ("000", None):
            raise RuntimeError(f"DART 오류 {status}: {js.get('message')}")

        for row in js.get("list", []):
            records.setdefault(row.get("corp_code"), []).append(row)

        if progress:
            progress(min(i + batch_size, total), total)

    out = []
    for corp, rows in records.items():
        eq = _pick_amount(rows, EQUITY_NAMES)
        pf = _pick_amount(rows, PROFIT_NAMES)
        out.append({"corp_code": corp, "자본총계": eq, "당기순이익": pf})

    return pd.DataFrame(out)


def annualize_profit(profit, reprt_code):
    """분기 누적 순이익을 연환산한다(ROE를 연율로 보기 위함)."""
    factor = {"11013": 4.0, "11012": 2.0, "11014": 4.0 / 3.0, "11011": 1.0}
    return profit * factor.get(reprt_code, 1.0)
