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
