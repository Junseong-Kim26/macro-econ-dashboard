# -*- coding: utf-8 -*-
"""
ECOS 항목코드 확인 도구
=====================================
한국 국채 10년의 통계표/항목코드를 실제 API로 확인할 때 사용.
실행:  python discover_ecos.py  (ECOS_API_KEY 필요)

통계표 817Y002(시장금리, 일별)의 항목 목록을 출력하므로,
'국고채(10년)' 에 해당하는 ITEM_CODE 를 확인해 config.py 의
kr10y 변수 ecos.item_code 에 반영하면 된다.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("ECOS_API_KEY", "")
STAT = "817Y002"

if not KEY:
    raise SystemExit("ECOS_API_KEY 가 .env 에 없습니다.")

url = f"https://ecos.bok.or.kr/api/StatisticItemList/{KEY}/json/kr/1/200/{STAT}"
r = requests.get(url, timeout=30)
r.raise_for_status()
data = r.json()

if "StatisticItemList" not in data:
    raise SystemExit(f"응답 오류: {data}")

print(f"통계표 {STAT} 항목 목록")
print("-" * 50)
for row in data["StatisticItemList"]["row"]:
    print(f"{row.get('ITEM_CODE'):<14} {row.get('ITEM_NAME')}")
