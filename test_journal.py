# -*- coding: utf-8 -*-
"""자산 운용내역 업로드 기능 검증 (파일 → 파싱 → 반영)."""
import io
import pandas as pd
import journal


def _csv(text, enc="utf-8-sig"):
    return text.encode(enc)


def t(name, cond):
    print(("통과  " if cond else "실패  ") + name)
    assert cond, name


BASE = pd.DataFrame({
    "날짜": ["2026-08-13", "2026-08-13", "2026-08-10"],
    "종목명": ["삼성전자", "미국달러", "삼성전자"],
    "금액": [1000.0, 2000.0, 900.0],
})

# 1) 정상 CSV
df, note = journal.parse_portfolio_upload(
    _csv("날짜,종목명,금액\n2026-08-18,삼성전자,1500\n2026-08-18,미국달러,2500\n"), "a.csv")
t("정상 CSV 파싱", df is not None and note is None and len(df) == 2)
t("금액 숫자 변환", df["금액"].tolist() == [1500.0, 2500.0])

# 2) 콤마 금액 · 다른 날짜형식 · cp949
df2, _ = journal.parse_portfolio_upload(
    _csv("날짜,종목명,금액\n2026/8/18,삼성전자,\"1,500\"\n", "cp949"), "b.csv")
t("cp949 + 콤마금액 + 날짜형식 자동인식",
  df2 is not None and df2["날짜"].iloc[0] == "2026-08-18" and df2["금액"].iloc[0] == 1500.0)

# 3) 열 이름 틀림 → 오류
df3, err3 = journal.parse_portfolio_upload(_csv("일자,종목,금액\n2026-08-18,삼성전자,10\n"), "c.csv")
t("열 이름 오류 안내", df3 is None and "날짜" in err3)

# 4) 빈 종목명·깨진 날짜 행은 제외하고 안내
df4, note4 = journal.parse_portfolio_upload(
    _csv("날짜,종목명,금액\n2026-08-18,삼성전자,10\n엉망,미국달러,20\n2026-08-18,,30\n"), "d.csv")
t("불량행 제외", df4 is not None and len(df4) == 1 and "제외" in note4)

# 5) 반영: 파일에 있는 날짜만 교체, 없는 날짜는 보존
up = pd.DataFrame({"날짜": ["2026-08-13"], "종목명": ["삼성전자"], "금액": [7777.0]})
merged = journal.merge_portfolio(BASE, up)
s813 = journal.snapshot(merged, "2026-08-13")
s810 = journal.snapshot(merged, "2026-08-10")
t("해당 날짜 통째 교체", len(s813) == 1 and s813["금액"].iloc[0] == 7777.0)
t("다른 날짜 보존", len(s810) == 1 and s810["금액"].iloc[0] == 900.0)

# 6) 여러 날짜 한 번에
up2 = pd.DataFrame({"날짜": ["2026-08-14", "2026-08-15"],
                    "종목명": ["삼성전자", "삼성전자"], "금액": [1.0, 2.0]})
m2 = journal.merge_portfolio(BASE, up2)
t("여러 날짜 동시 반영", len(journal.daily_totals(m2)) == 4)

# 7) 양식 = 업로드 형식과 동일 (내려받아 그대로 올릴 수 있어야 함)
tpl = journal.portfolio_template(BASE, "2026-08-18")
t("양식 열 구성 일치", list(tpl.columns) == journal.PF_COLUMNS)
t("양식은 직전 보유내역을 채움", len(tpl) == 2 and set(tpl["날짜"]) == {"2026-08-18"})
back, err7 = journal.parse_portfolio_upload(
    tpl.to_csv(index=False).encode("utf-8-sig"), "tpl.csv")
t("양식 왕복 파싱", back is not None and err7 is None and len(back) == 2)

print("\n7개 항목 모두 통과")
