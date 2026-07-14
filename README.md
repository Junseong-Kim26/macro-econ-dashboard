# 거시경제 대시보드

주식 투자 판단을 위해 미국·한국의 핵심 거시변수를 한 화면에서 **그래프 · 일별 테이블 · 점수화**로 보여줍니다.

## 무엇을 보여주나요?

| 변수 | 소스 |
|---|---|
| 미국채 10년 / 30년 금리 | FRED |
| 한국 국채 10년 금리 | 한국은행 ECOS |
| WTI 유가 | FRED |
| 미국 CPI / PPI (전년동월대비) | FRED |
| 미국 신용카드 연체율 | FRED |

- **종합점수(0~100)**: 각 변수를 `절대수준 점수` + `최근 3개월 추세 점수`로 1~5점 매긴 뒤 가중평균 → 0~100 환산. 높을수록 주식에 우호적.
- **그래프**: 변수별 시계열 (1년/3년/5년/전체)
- **일별 테이블**: 전 변수 통합표 + CSV/Excel 다운로드

## 처음 1회 준비 (API 키 발급 — 둘 다 무료)

### 1) FRED 키 (필수)
1. https://fred.stlouisfed.org 접속 → 우측 상단 **My Account** 로 회원가입/로그인
2. 로그인 후 **API Keys** 메뉴 → **Request API Key**
3. 발급된 32자리 키를 복사

### 2) 한국은행 ECOS 키 (한국 금리를 보려면 필요)
1. https://ecos.bok.or.kr 접속 → **인증키 신청/관리**
2. 이메일로 인증키 발급받기

### 3) 키 입력
이 폴더의 **`.env`** 파일을 메모장으로 열어 아래처럼 붙여넣고 저장:
```
FRED_API_KEY=여기에_FRED_키
ECOS_API_KEY=여기에_ECOS_키
```
> `.env` 는 git/공유에 올라가지 않습니다(.gitignore 처리됨).

## 실행 방법

- **간편**: `거시경제대시보드_실행하기.bat` 더블클릭
- **직접**:
  ```
  "C:\Users\junse\anaconda3\python.exe" -m streamlit run app.py
  ```
- 브라우저에서 http://localhost:8501 자동 열림. 종료는 검은 창에서 `Ctrl+C`.

## 변수 추가/수정하는 법

`config.py` 의 `VARIABLES` 리스트에 딕셔너리 하나만 추가하면 됩니다.
점수구간·가중치·추세 임계값도 모두 이 파일의 숫자만 바꾸면 반영됩니다.
(FRED 시리즈 코드는 https://fred.stlouisfed.org 에서 검색 → URL의 코드 사용)

## 참고 도구

- `discover_ecos.py` : 한국 국채 10년의 ECOS 항목코드를 실제로 확인
  (`python discover_ecos.py`, ECOS 키 필요). 결과의 국고채(10년) 코드를
  `config.py` 의 `kr10y → ecos.item_code` 에 반영.
- `test_scoring.py` : 점수 로직 검증 (키 없이 실행 가능)

## 파일 구조

```
config.py    변수·가중치·점수구간 (여기만 고치면 됨)
data.py      FRED/ECOS 수집 + 일별 정렬(forward-fill) + 캐시
scoring.py   수준·추세·종합점수 계산
app.py       화면
cache/       받은 데이터 저장(자동)
```
