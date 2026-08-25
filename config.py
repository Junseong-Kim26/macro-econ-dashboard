# -*- coding: utf-8 -*-
"""
거시경제 대시보드 - 설정 파일
=====================================
★ 새로운 변수를 추가하려면 아래 VARIABLES 리스트에 딕셔너리 하나만 추가하면 됩니다.
   (코드 수정 불필요 — data.py / scoring.py / app.py 는 그대로 둡니다.)

각 변수 딕셔너리 항목 설명
--------------------------------------------------
key         : 내부 식별용 고유 이름(영문, 겹치면 안 됨)
name        : 화면에 표시할 한글 이름
source      : 'fred'  = 미국 세인트루이스 연준
              'ecos'  = 한국은행 경제통계시스템
series_id   : FRED 시리즈 코드 (source='fred'일 때)
ecos        : ECOS 조회 정보 dict (source='ecos'일 때)
unit        : 표시 단위 ('%', '$' 등)
decimals    : 표시 소수 자릿수
transform   : None      = 원값 그대로 사용
              'yoy'     = 전년동월대비 상승률(%)로 변환 (CPI, PPI용)
weight      : 종합점수 가중치 (전체 합이 100이 되도록)
trend_type  : 추세 점수 임계값 세트 이름 (아래 TREND_THRESHOLDS 키)
level_bands : (하한, 상한, 점수) 목록. 하한 <= 값 < 상한 이면 해당 점수.
              점수가 높을수록 '주식에 우호적'.
"""

INF = float("inf")

# 데이터 조회 시작일 (충분히 길게 잡고, 화면에서 기간 선택)
DATA_START = "2010-01-01"

# 추세(최근 3개월 변화) 점수용 임계값
#   mode 'abs' = 절대 변화(%p),  'pct' = 비율 변화(%)
#   flat  = 이 이하 변화면 '보합'
#   small = 이 이하 변화면 '소폭', 초과하면 '큰폭'
TREND_THRESHOLDS = {
    "rate":        {"mode": "abs", "flat": 0.1, "small": 0.5},   # 금리류
    "inflation":   {"mode": "abs", "flat": 0.2, "small": 1.0},   # 물가 YoY
    "wti":         {"mode": "pct", "flat": 0.03, "small": 0.15},  # 유가(비율)
    "delinquency": {"mode": "abs", "flat": 0.1, "small": 0.3},   # 연체율
    "vix":         {"mode": "abs", "flat": 2.0, "small": 6.0},   # 변동성지수
    "dollar":      {"mode": "abs", "flat": 1.0, "small": 3.0},   # 달러인덱스
    "unemp":       {"mode": "abs", "flat": 0.1, "small": 0.4},   # 실업률(%p)
}

# 추세 점수 계산 시 "최근 3개월"의 개월 수
TREND_MONTHS = 3

# 종합점수 해석 구간 (하한, 상한, 라벨, 색상, 설명)
SCORE_INTERPRETATION = [
    (80, 101, "매우 우호 (강세 환경)", "#1a9850",
     "금리·물가·변동성이 대부분 낮거나 하락세. 위험자산(주식)에 매우 우호적인 국면으로, 적극적 비중 확대를 고려할 수 있는 환경."),
    (60, 80,  "우호", "#66bd63",
     "다수 지표가 우호적. 순풍이 부는 국면으로, 주식 비중을 유지·확대하기 좋은 환경. 일부 지표는 아직 부담일 수 있어 점검 필요."),
    (40, 60,  "중립", "#fee08b",
     "우호·비우호 요인이 섞여 방향성이 뚜렷하지 않음. 추세 전환을 확인하며 균형 잡힌 비중과 분할 대응이 적절한 국면."),
    (20, 40,  "비우호", "#f46d43",
     "금리·물가·변동성 등 다수 지표가 부담. 역풍이 부는 국면으로, 위험 관리와 방어적 자산 비중 확대를 고려."),
    (0,  20,  "매우 비우호 (위험 회피)", "#d73027",
     "대부분 지표가 악화. 위험 회피가 우선되는 국면으로, 현금·안전자산 비중을 높이고 신규 진입에 신중할 필요."),
]

# ---------------------------------------------------------------------------
# 변수 정의
# ---------------------------------------------------------------------------
VARIABLES = [
    {
        "key": "us10y",
        "name": "미국채 10년",
        "source": "fred",
        "series_id": "DGS10",
        "unit": "%",
        "decimals": 2,
        "transform": None,
        "weight": 15,
        "trend_type": "rate",
        "level_bands": [
            (-INF, 2.0, 5),
            (2.0, 3.0, 4),
            (3.0, 4.0, 3),
            (4.0, 5.0, 2),
            (5.0, INF, 1),
        ],
    },
    {
        "key": "us30y",
        "name": "미국채 30년",
        "source": "fred",
        "series_id": "DGS30",
        "unit": "%",
        "decimals": 2,
        "transform": None,
        "weight": 8,
        "trend_type": "rate",
        "level_bands": [
            (-INF, 2.5, 5),
            (2.5, 3.5, 4),
            (3.5, 4.5, 3),
            (4.5, 5.5, 2),
            (5.5, INF, 1),
        ],
    },
    {
        "key": "kr10y",
        "name": "한국 국채 10년",
        "source": "ecos",
        # ECOS 통계표 817Y002(시장금리, 일별), 항목 국고채(10년).
        # 항목코드는 discover_ecos.py 로 확인 후 필요시 교체.
        "ecos": {"stat_code": "817Y002", "item_code": "010210000", "cycle": "D"},
        "unit": "%",
        "decimals": 2,
        "transform": None,
        "weight": 6,
        "trend_type": "rate",
        "level_bands": [
            (-INF, 2.5, 5),
            (2.5, 3.0, 4),
            (3.0, 3.5, 3),
            (3.5, 4.0, 2),
            (4.0, INF, 1),
        ],
    },
    {
        "key": "wti",
        "name": "WTI 유가",
        "source": "fred",
        "series_id": "DCOILWTICO",
        "unit": "$",
        "decimals": 2,
        "transform": None,
        "weight": 10,
        "trend_type": "wti",
        # U자형: 완만한 중간대(40~60$)가 최고점, 너무 낮으면(<40$) 수요둔화로 3점
        "level_bands": [
            (-INF, 40, 3),
            (40, 60, 5),
            (60, 80, 4),
            (80, 100, 2),
            (100, INF, 1),
        ],
    },
    {
        "key": "cpi",
        "name": "미국 CPI (YoY)",
        "source": "fred",
        "series_id": "CPIAUCSL",
        "unit": "%",
        "decimals": 2,
        "transform": "yoy",
        "weight": 12,
        "trend_type": "inflation",
        "level_bands": [
            (-INF, 2.0, 5),
            (2.0, 3.0, 4),
            (3.0, 4.0, 3),
            (4.0, 5.0, 2),
            (5.0, INF, 1),
        ],
    },
    {
        "key": "ppi",
        "name": "미국 PPI (YoY)",
        "source": "fred",
        # PPIFIS = 최종수요 PPI(헤드라인). PPIACO(전체상품)는 변동이 극심해 부적합.
        "series_id": "PPIFIS",
        "unit": "%",
        "decimals": 2,
        "transform": "yoy",
        "weight": 8,
        "trend_type": "inflation",
        "level_bands": [
            (-INF, 1.0, 5),
            (1.0, 3.0, 4),
            (3.0, 5.0, 3),
            (5.0, 7.0, 2),
            (7.0, INF, 1),
        ],
    },
    {
        "key": "cc_delinq",
        "name": "미국 카드 연체율",
        "source": "fred",
        "series_id": "DRCCLACBS",
        "unit": "%",
        "decimals": 2,
        "transform": None,
        "weight": 12,
        "trend_type": "delinquency",
        "level_bands": [
            (-INF, 2.0, 5),
            (2.0, 2.5, 4),
            (2.5, 3.0, 3),
            (3.0, 3.5, 2),
            (3.5, INF, 1),
        ],
    },
    {
        "key": "vix",
        "name": "나스닥/S&P 변동성 VIX",
        "source": "fred",
        "series_id": "VIXCLS",
        "unit": "",
        "decimals": 2,
        "transform": None,
        "weight": 12,
        "trend_type": "vix",
        # 낮을수록(안정) 우호. 20 넘으면 불안, 35 넘으면 공포.
        "level_bands": [
            (-INF, 15, 5),
            (15, 20, 4),
            (20, 25, 3),
            (25, 35, 2),
            (35, INF, 1),
        ],
    },
    {
        "key": "usd",
        "name": "달러인덱스(광의)",
        "source": "fred",
        # DTWEXBGS = 광의 명목 달러지수(2006.1=100). 강달러는 위험자산에 역풍으로 간주.
        "series_id": "DTWEXBGS",
        "unit": "",
        "decimals": 2,
        "transform": None,
        "weight": 7,
        "trend_type": "dollar",
        "level_bands": [
            (-INF, 100, 5),
            (100, 110, 4),
            (110, 120, 3),
            (120, 127, 2),
            (127, INF, 1),
        ],
    },
    {
        "key": "unemp",
        "name": "미국 실업률",
        "source": "fred",
        "series_id": "UNRATE",
        "unit": "%",
        "decimals": 2,
        "transform": None,
        "weight": 10,
        "trend_type": "unemp",
        # 낮을수록/내려갈수록 우호(경기 견조). 상승은 침체 위험 신호.
        "level_bands": [
            (-INF, 4.0, 5),
            (4.0, 4.5, 4),
            (4.5, 5.0, 3),
            (5.0, 6.0, 2),
            (6.0, INF, 1),
        ],
    },
]


def get_variable(key):
    """key로 변수 정의를 찾는다."""
    for v in VARIABLES:
        if v["key"] == key:
            return v
    raise KeyError(f"알 수 없는 변수 key: {key}")


# ---------------------------------------------------------------------------
# 콤보 차트 정의 (점수화하지 않고 '그래프'만 표시하는 시장지표)
# ---------------------------------------------------------------------------
# 각 series 항목:
#   label  : 범례에 표시할 이름
#   source : 'fred' | 'yfinance' | 'stooq'
#   id     : 시리즈/티커 코드
#   kind   : 'line' | 'bar'  (콤보: 서로 다른 종류를 섞음)
#   axis   : 'left' | 'right' (스케일이 다르면 오른쪽 보조축)
#   color  : 선/막대 색
COMBO_CHARTS = [
    {
        "key": "market_combo",
        "title": "미국 증시지수 & IPO ETF (콤보)",
        "left_title": "지수 (나스닥·다우)",
        "right_title": "IPO ETF ($)",
        "series": [
            {"label": "나스닥 종합", "source": "fred", "id": "NASDAQCOM",
             "kind": "line", "axis": "left", "color": "#1f77b4"},
            {"label": "다우존스", "source": "fred", "id": "DJIA",
             "kind": "line", "axis": "left", "color": "#ff7f0e"},
            {"label": "IPO ETF", "source": "yfinance", "id": "IPO",
             "kind": "line", "axis": "right", "color": "#2ca02c"},
        ],
    },
    {
        "key": "usdkrw",
        "title": "원/달러 환율",
        "left_title": "원/달러 (₩)",
        "series": [
            {"label": "원/달러", "source": "fred", "id": "DEXKOUS",
             "kind": "line", "axis": "left", "color": "#d62728"},
        ],
    },
    {
        "key": "jgb",
        "title": "일본 국채 금리 (10년 · 30년)",
        "left_title": "금리 (%)",
        # 자료: 일본 재무성(財務省) 국채금리정보, 매영업일 공표. 인증키 불필요.
        # FRED 의 일본 국채는 월별·2개월 지연이고 30년물이 없어서 직접 받아온다.
        "series": [
            {"label": "일본 10년", "source": "mof", "id": "JGB10Y",
             "mof": {"col": "10年"},
             "kind": "line", "axis": "left", "color": "#8c564b"},
            {"label": "일본 30년", "source": "mof", "id": "JGB30Y",
             "mof": {"col": "30年"},
             "kind": "line", "axis": "left", "color": "#e377c2"},
        ],
    },
    {
        "key": "usdjpy",
        "title": "엔/달러 환율",
        "left_title": "엔/달러 (¥)",
        "series": [
            {"label": "엔/달러", "source": "fred", "id": "DEXJPUS",
             "kind": "line", "axis": "left", "color": "#17becf"},
        ],
    },
    {
        "key": "yield_spread",
        "title": "미국 장단기 금리차 (10년 - 2년)",
        "left_title": "금리차 (%p)",
        "zero_line": True,  # 0선(수익률곡선 역전 기준) 표시
        "series": [
            {"label": "10Y-2Y 금리차", "source": "fred", "id": "T10Y2Y",
             "kind": "line", "axis": "left", "color": "#9467bd"},
        ],
    },
]


# ===========================================================================
# AI · 데이터센터 크레딧 모니터
# ===========================================================================
# 배경: SEC가 2026-07-29 해석서한에서 특정 구조의 데이터센터 유동화증권을
#       증권거래법 §3(a)(79) 상 'asset-backed security'가 아니라고 판단 →
#       Reg AB 자산단위 공시, 신용위험보유 5%, Rule 15Ga-1/2, 127B 가 면제됐다.
#       구조는 ABS인데 보호장치만 벗겨진 상태이므로 별도 감시가 필요하다.
#
# ★ 방향이 기존 VARIABLES 와 정반대다.
#   기존 10종 = "낮을수록 우호" 로 통일된 '주식 환경 점수'.
#   여기 지표 = "높을수록 위험" 인 '위험지수'이고, 신용스프레드는
#   좁을수록 위험(위험이 가격에 안 들어감)이라 U자형이다.
#   그래서 같은 점수엔진(scoring.py)에 섞지 않고 aicredit.py 로 분리했다.
#
# risk_bands  : (하한, 상한, 위험점수 1~5). 5 = 가장 위험.
# trend_dir   : 'up'   = 값이 오르면 위험 증가
#               'down' = 값이 내리면 위험 증가
# transform   : None | 'yoy' | 'ret6m'(6개월 수익률 %) | 'diff'(파생: 두 시리즈 차)
# ---------------------------------------------------------------------------

# 위험 추세 임계값 (mode: 'abs' = 절대변화, 'pct' = 비율변화)
AI_TREND_THRESHOLDS = {
    "spread":  {"mode": "abs", "flat": 0.15, "small": 0.50},  # 신용스프레드(%p)
    "gap":     {"mode": "abs", "flat": 0.50, "small": 1.50},  # CCC-BBB 격차(%p)
    "ret":     {"mode": "abs", "flat": 3.0,  "small": 10.0},  # 수익률(%p)
    "macro":   {"mode": "abs", "flat": 0.3,  "small": 1.0},   # 산업생산 YoY 등
    "nfci":    {"mode": "abs", "flat": 0.10, "small": 0.30},  # 금융환경지수
}

AI_TREND_MONTHS = 3

AI_CREDIT_INDICATORS = [
    {
        "key": "hy_oas",
        "name": "미국 하이일드 OAS",
        "source": "fred", "series_id": "BAMLH0A0HYM2",
        "unit": "%p", "decimals": 2, "transform": None,
        "weight": 18, "trend_type": "spread", "trend_dir": "up",
        "why": "위험한 회사에 돈을 빌려줄 때 요구하는 추가 이자입니다. "
               "너무 좁으면 시장이 위험을 값에 안 넣고 있다는 뜻이라 오히려 경고입니다.",
        # U자형: 극단적으로 좁아도(안일) 위험, 크게 벌어져도(스트레스 현실화) 위험
        "risk_bands": [
            (-INF, 3.0, 5),   # 역사적 최저권 — 위험 미가격
            (3.0, 3.8, 4),
            (3.8, 5.5, 1),    # 정상적인 위험 보상
            (5.5, 8.0, 3),    # 스트레스 진입
            (8.0, INF, 5),    # 위기
        ],
    },
    {
        "key": "bbb_oas",
        "name": "BBB 회사채 OAS",
        "source": "fred", "series_id": "BAMLC0A4CBBB",
        "unit": "%p", "decimals": 2, "transform": None,
        "weight": 15, "trend_type": "spread", "trend_dir": "up",
        "why": "데이터센터 채권이 실제로 매겨지는 등급대(A~BBB)의 가산금리입니다. "
               "여기가 좁을수록 발행이 쉬워지고 물량이 늘어납니다.",
        "risk_bands": [
            (-INF, 1.05, 5),
            (1.05, 1.25, 4),
            (1.25, 1.90, 1),
            (1.90, 3.00, 3),
            (3.00, INF, 5),
        ],
    },
    {
        "key": "ccc_bbb_gap",
        "name": "신용질 분화 (CCC이하 − BBB)",
        "source": "derived", "transform": "diff",
        "minuend": {"source": "fred", "id": "BAMLH0A3HYC"},
        "subtrahend": {"source": "fred", "id": "BAMLC0A4CBBB"},
        "unit": "%p", "decimals": 2,
        "weight": 17, "trend_type": "gap", "trend_dir": "up",
        "why": "우량과 불량의 금리 차이입니다. 전체 스프레드는 좁은데 이 격차만 "
               "벌어지면, 겉은 멀쩡한데 밑바닥부터 무너지는 후기 국면 신호입니다.",
        "risk_bands": [
            (-INF, 6.0, 1),
            (6.0, 8.0, 2),
            (8.0, 10.0, 3),
            (10.0, 13.0, 4),
            (13.0, INF, 5),
        ],
    },
    {
        "key": "dtcr_ret",
        "name": "데이터센터 REIT (6개월 수익률)",
        "source": "yfinance", "series_id": "DTCR",
        "unit": "%", "decimals": 1, "transform": "ret6m",
        "weight": 15, "trend_type": "ret", "trend_dir": "down",
        "why": "데이터센터 자산 자체의 시장가격입니다. 담보가치가 먼저 흔들리면 "
               "채권 상환재원도 흔들립니다.",
        "risk_bands": [
            (-INF, -20, 5),
            (-20, -10, 4),
            (-10, 0, 3),
            (0, 15, 1),
            (15, INF, 2),   # 과열 급등도 가벼운 경계 신호
        ],
    },
    {
        "key": "owl_ret",
        "name": "사모신용 운용사 Blue Owl (6개월 수익률)",
        "source": "yfinance", "series_id": "OWL",
        "unit": "%", "decimals": 1, "transform": "ret6m",
        "weight": 10, "trend_type": "ret", "trend_dir": "down",
        "why": "실제 대형 데이터센터 딜을 주관하는 운용사입니다. 2007년에도 "
               "서브프라임 대출기관 주가가 채권지수보다 먼저 무너졌습니다.",
        "risk_bands": [
            (-INF, -25, 5),
            (-25, -12, 4),
            (-12, 0, 3),
            (0, INF, 1),
        ],
    },
    {
        "key": "bizd_ret",
        "name": "BDC(사모대출) ETF (6개월 수익률)",
        "source": "yfinance", "series_id": "BIZD",
        "unit": "%", "decimals": 1, "transform": "ret6m",
        "weight": 8, "trend_type": "ret", "trend_dir": "down",
        "why": "사모대출 시장 전반의 체온계입니다. 이쪽이 식으면 데이터센터 "
               "리파이낸싱(만기 재조달)도 같이 막힙니다.",
        "risk_bands": [
            (-INF, -15, 5),
            (-15, -7, 4),
            (-7, 0, 3),
            (0, INF, 1),
        ],
    },
    {
        "key": "power_yoy",
        "name": "미국 전력생산 (YoY)",
        "source": "fred", "series_id": "IPG2211S",
        "unit": "%", "decimals": 2, "transform": "yoy",
        "weight": 9, "trend_type": "macro", "trend_dir": "down",
        "why": "데이터센터가 실제로 돌아가면 전력 생산이 늘어납니다. 계약은 "
               "있는데 전력 수요가 안 늘면 수요가 말뿐이라는 뜻입니다.",
        "risk_bands": [
            (-INF, 0.0, 5),
            (0.0, 1.5, 4),
            (1.5, 3.0, 2),
            (3.0, INF, 1),
        ],
    },
    {
        "key": "nfci_lev",
        "name": "시카고연준 레버리지 지수",
        "source": "fred", "series_id": "NFCILEVERAGE",
        "unit": "", "decimals": 3, "transform": None,
        "weight": 8, "trend_type": "nfci", "trend_dir": "up",
        "why": "금융시스템 전체의 빚 사용 정도입니다. 0이 평균이고, "
               "마이너스로 깊어질수록 빚이 느슨하게 풀린 상태(위험 축적)입니다.",
        "risk_bands": [
            (-INF, -0.50, 5),   # 레버리지 매우 느슨 — 위험 축적
            (-0.50, -0.20, 4),
            (-0.20, 0.20, 2),
            (0.20, 0.60, 3),
            (0.60, INF, 5),     # 급격한 긴축 — 스트레스 현실화
        ],
    },
]

# 정성 체크리스트 — 숫자로 잡히지 않는 구조적 사건.
# 하나라도 켜지면 위험지수에 가점(points)이 더해진다. 켜져 있어야만 더해지고,
# 꺼져 있다고 빼지는 않는다(구조적 사건은 위험을 더할 뿐이다).
AI_CREDIT_CHECKLIST = [
    {
        "key": "resecuritization",
        "label": "여러 딜의 메자닌 트랜치를 묶은 재유동화 상품 출현",
        "points": 25,
        "why": "2008년 증폭의 진짜 엔진이었던 CDO of ABS 구조입니다. "
               "이게 등장하면 손실이 한 딜에 머물지 않고 복제됩니다. 가장 중요한 항목.",
    },
    {
        "key": "cds_index",
        "label": "데이터센터·AI인프라 전용 CDS 지수 조성",
        "points": 20,
        "why": "합성 노출이 실제 채권 잔액을 넘어설 수 있게 되는 시점입니다. "
               "2007년 ABX 지수가 그 역할을 했습니다.",
    },
    {
        "key": "tenant_spread",
        "label": "임차인이 하이퍼스케일러 → 중소 AI기업으로 확산",
        "points": 15,
        "why": "지금 이 구조를 지탱하는 유일한 버팀목이 임차인 신용입니다. "
               "그게 내려가면 담보의 특수성 문제가 그대로 드러납니다.",
    },
    {
        "key": "insurer_naic",
        "label": "보험사 일반계정 편입 급증 또는 NAIC 자본charge 논의 착수",
        "points": 10,
        "why": "손실이 장기 부채를 진 기관으로 옮겨간 상태를 뜻합니다. "
               "규제당국이 자본charge를 논의한다는 건 이미 규모가 커졌다는 신호입니다.",
    },
    {
        "key": "sec_reversal",
        "label": "SEC 해석서한 번복 또는 관련 규칙제정 착수",
        "points": 10,
        "why": "해석서한은 규칙이 아니라 실무국 의견이라 뒤집힐 수 있습니다. "
               "뒤집히면 이미 발행된 물량이 조건 재조정 압력을 받습니다.",
    },
    {
        "key": "gpu_freeride",
        "label": "GPU 유동화·리스전용 구조가 이번 면제에 무임승차 시도",
        "points": 10,
        "why": "서한은 '실물을 소유하고 직접 운영하는' 구조에만 한정됩니다. "
               "GPU 유동화는 명시적으로 범위 밖인데도 확대 적용되면 규제공백이 넓어집니다.",
    },
]

# 위험지수 해석 구간 (하한, 상한, 라벨, 색상, 설명) — 높을수록 위험
AI_RISK_INTERPRETATION = [
    (0, 25, "낮음", "#1a9850",
     "위험 보상이 정상 범위이고 구조적 경고 신호도 없습니다. 평소대로 관찰만 하면 됩니다."),
    (25, 45, "보통", "#66bd63",
     "일부 지표가 느슨하지만 아직 특이 신호는 아닙니다. 분기 단위 점검으로 충분합니다."),
    (45, 65, "경계", "#fee08b",
     "위험 대비 보상이 얇아졌거나 신용질 분화가 진행 중입니다. "
     "AI·데이터센터 관련 종목 비중과 만기 구조를 점검할 시점입니다."),
    (65, 85, "높음", "#f46d43",
     "여러 축이 동시에 악화됐거나 구조적 사건이 확인됐습니다. "
     "관련 익스포저 축소와 헤지를 구체적으로 검토할 국면입니다."),
    (85, 101, "매우 높음", "#d73027",
     "취약성이 광범위하게 쌓였고 전파 경로도 열렸습니다. "
     "AI 인프라 크레딧 관련 노출을 적극적으로 줄여야 하는 국면입니다."),
]

# 위험지수 탭에서 보여줄 그래프 (점수화와 별개, 눈으로 확인하는 용도)
#   rebase=True 면 구간 첫날을 100으로 환산해 서로 다른 가격을 겹쳐 본다.
AI_CREDIT_CHARTS = [
    {
        "key": "spreads",
        "title": "신용스프레드 — 좁을수록 위험이 값에 안 들어간 상태",
        "left_title": "OAS (%p)",
        "right_title": "CCC이하 OAS (%p)",
        "series": [
            {"label": "하이일드 OAS", "source": "fred", "id": "BAMLH0A0HYM2",
             "axis": "left", "color": "#d62728"},
            {"label": "BBB OAS", "source": "fred", "id": "BAMLC0A4CBBB",
             "axis": "left", "color": "#1f77b4"},
            {"label": "CCC이하 OAS", "source": "fred", "id": "BAMLH0A3HYC",
             "axis": "right", "color": "#7f7f7f"},
        ],
    },
    {
        "key": "dc_assets",
        "title": "데이터센터 자산가격 — 담보가치가 먼저 흔들리는지",
        "left_title": "구간 시작 = 100",
        "rebase": True,
        "series": [
            {"label": "데이터센터 REIT ETF (DTCR)", "source": "yfinance", "id": "DTCR",
             "axis": "left", "color": "#2ca02c"},
            {"label": "데이터인프라 REIT ETF (SRVR)", "source": "yfinance", "id": "SRVR",
             "axis": "left", "color": "#98df8a"},
            {"label": "에퀴닉스 (EQIX)", "source": "yfinance", "id": "EQIX",
             "axis": "left", "color": "#1f77b4"},
            {"label": "디지털리얼티 (DLR)", "source": "yfinance", "id": "DLR",
             "axis": "left", "color": "#aec7e8"},
        ],
    },
    {
        "key": "private_credit",
        "title": "사모신용 — 딜을 주관하는 쪽이 먼저 신호를 준다",
        "left_title": "구간 시작 = 100",
        "rebase": True,
        "series": [
            {"label": "Blue Owl (OWL)", "source": "yfinance", "id": "OWL",
             "axis": "left", "color": "#ff7f0e"},
            {"label": "Ares Management (ARES)", "source": "yfinance", "id": "ARES",
             "axis": "left", "color": "#ffbb78"},
            {"label": "BDC ETF (BIZD)", "source": "yfinance", "id": "BIZD",
             "axis": "left", "color": "#9467bd"},
            {"label": "하이일드 채권 ETF (HYG)", "source": "yfinance", "id": "HYG",
             "axis": "left", "color": "#c5b0d5"},
        ],
    },
    {
        "key": "power_demand",
        "title": "전력 — AI 수요가 말이 아니라 실물로 나타나는지",
        "left_title": "전력생산 지수 (2017=100)",
        "right_title": "전기요금 CPI",
        "series": [
            {"label": "전력생산 산업생산지수", "source": "fred", "id": "IPG2211S",
             "axis": "left", "color": "#8c564b"},
            {"label": "전기요금 CPI", "source": "fred", "id": "CUSR0000SEHF01",
             "axis": "right", "color": "#c49c94"},
        ],
    },
]
