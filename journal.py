# -*- coding: utf-8 -*-
"""
매매일지 모듈
=====================================
- 일자별로 글을 쓰고, 목록에서 '핵심내용 한 줄'로 훑어볼 수 있게 한다.
- 저장은 Dropbox CSV (Streamlit Cloud는 파일이 영구 저장되지 않으므로).
  연결 정보는 코드가 아니라 secrets 의 [dropbox] 섹션에서 읽는다.
  (학습일지 앱과 동일한 refresh_token 방식 — 만료되지 않음)
- 공개 앱이므로 비밀번호를 아는 사람만 열람/작성할 수 있다.

CSV 컬럼: 날짜, 요약, 내용
  요약 = 목록에 한 줄로 보여줄 핵심내용 (비우면 본문 첫 줄을 자동 사용)
"""

import io

import pandas as pd
import streamlit as st

COLUMNS = ["날짜", "요약", "내용"]
DEFAULT_PATH = "/apps/macro_dashboard/trade_journal.csv"
SUMMARY_MAX = 60  # 자동 요약 시 자를 길이

# 자산 운용내역: 날짜별 종목 평가액(천원)
PF_COLUMNS = ["날짜", "종목명", "금액"]
DEFAULT_PF_PATH = "/apps/macro_dashboard/portfolio.csv"


# ---------------------------------------------------------------------------
# 설정 / 연결
# ---------------------------------------------------------------------------
def _cfg():
    """secrets 의 [dropbox] 섹션을 안전하게 읽는다."""
    try:
        return dict(st.secrets["dropbox"])
    except Exception:
        return {}


# 매매일지를 쓰는 사람. 사람마다 파일이 따로 저장된다(내용 구성은 동일).
PEOPLE = ["김준성", "윤송희"]


def _with_person(path, person):
    """/apps/.../trade_journal.csv + 김준성 → /apps/.../trade_journal_김준성.csv"""
    if not person:
        return path
    base, dot, ext = path.rpartition(".")
    return f"{base}_{person}{dot}{ext}" if dot else f"{path}_{person}"


def journal_path(person=None):
    return _with_person(_cfg().get("journal_path", DEFAULT_PATH), person)


def portfolio_path(person=None):
    return _with_person(_cfg().get("portfolio_path", DEFAULT_PF_PATH), person)


def get_client():
    """Dropbox 클라이언트. 설정이 없으면 None."""
    cfg = _cfg()
    try:
        import dropbox
    except ImportError:
        return None
    if cfg.get("refresh_token"):
        return dropbox.Dropbox(
            oauth2_refresh_token=cfg["refresh_token"],
            app_key=cfg.get("app_key"),
            app_secret=cfg.get("app_secret"),
        )
    if cfg.get("access_token"):
        return dropbox.Dropbox(cfg["access_token"])
    return None


def get_password():
    """매매일지 열람용 비밀번호. 없으면 None(=잠금 없음)."""
    try:
        return st.secrets["journal"]["password"]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 불러오기 / 저장
# ---------------------------------------------------------------------------
def empty_df():
    return pd.DataFrame(columns=COLUMNS)


def load(person=None, dbx=None):
    """Dropbox에서 매매일지를 읽어 DataFrame으로 반환."""
    dbx = dbx or get_client()
    if dbx is None:
        return empty_df()
    try:
        _, res = dbx.files_download(journal_path(person))
        df = pd.read_csv(io.BytesIO(res.content))
    except Exception:
        # 파일이 아직 없거나 접근 실패 → 빈 일지로 시작
        return empty_df()

    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["날짜"] = df["날짜"].astype(str)
    df["요약"] = df["요약"].fillna("").astype(str).replace("nan", "")
    df["내용"] = df["내용"].fillna("").astype(str).replace("nan", "")
    return df[COLUMNS].sort_values("날짜", ascending=False).reset_index(drop=True)


def save(df, person=None, dbx=None):
    """DataFrame을 Dropbox CSV로 저장. 성공 여부 반환."""
    dbx = dbx or get_client()
    if dbx is None:
        return False, "Dropbox 연결 정보가 없습니다. secrets 의 [dropbox] 설정을 확인하세요."
    try:
        import dropbox as _dbx_mod

        data = df[COLUMNS].to_csv(index=False).encode("utf-8")
        dbx.files_upload(data, journal_path(person),
                         mode=_dbx_mod.files.WriteMode.overwrite)
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"저장 중 오류가 발생했습니다: {e}"


# ---------------------------------------------------------------------------
# 한 줄 요약
# ---------------------------------------------------------------------------
def one_line(summary, body):
    """목록에 표시할 '핵심내용 한 줄'.
    요약을 적었으면 그대로, 안 적었으면 본문 첫 줄을 잘라서 사용.
    """
    s = (summary or "").strip()
    if s:
        return s
    first = ""
    for line in (body or "").splitlines():
        if line.strip():
            first = line.strip()
            break
    if len(first) > SUMMARY_MAX:
        first = first[:SUMMARY_MAX] + "…"
    return first or "(내용 없음)"


# ---------------------------------------------------------------------------
# 자산 운용내역 (날짜 · 종목명 · 금액[천원])
# ---------------------------------------------------------------------------
def empty_pf():
    return pd.DataFrame(columns=PF_COLUMNS)


def load_portfolio(person=None, dbx=None):
    """Dropbox에서 자산 운용내역을 읽어 DataFrame으로 반환."""
    dbx = dbx or get_client()
    if dbx is None:
        return empty_pf()
    try:
        _, res = dbx.files_download(portfolio_path(person))
        df = pd.read_csv(io.BytesIO(res.content))
    except Exception:
        return empty_pf()

    for col in PF_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col != "금액" else 0
    df["날짜"] = df["날짜"].astype(str)
    df["종목명"] = df["종목명"].fillna("").astype(str).replace("nan", "")
    df["금액"] = pd.to_numeric(df["금액"], errors="coerce").fillna(0.0)
    df = df[df["종목명"].str.strip() != ""]
    return df[PF_COLUMNS].reset_index(drop=True)


def save_portfolio(df, person=None, dbx=None):
    """자산 운용내역을 Dropbox CSV로 저장."""
    dbx = dbx or get_client()
    if dbx is None:
        return False, "Dropbox 연결 정보가 없습니다."
    try:
        import dropbox as _dbx_mod

        data = df[PF_COLUMNS].to_csv(index=False).encode("utf-8")
        dbx.files_upload(data, portfolio_path(person),
                         mode=_dbx_mod.files.WriteMode.overwrite)
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"자산 내역 저장 중 오류가 발생했습니다: {e}"


def upsert_portfolio(pdf, date_str, rows):
    """해당 날짜의 보유내역을 rows(종목명·금액)로 통째 교체한 새 DataFrame 반환."""
    pdf = pdf.copy()
    kept = pdf[pdf["날짜"] != date_str]

    rows = rows.copy()
    if "종목명" not in rows.columns:
        rows["종목명"] = ""
    rows["종목명"] = rows["종목명"].fillna("").astype(str).str.strip()
    rows["금액"] = pd.to_numeric(rows.get("금액"), errors="coerce").fillna(0.0)
    rows = rows[rows["종목명"] != ""]
    rows["날짜"] = date_str

    parts = [p for p in (kept, rows[PF_COLUMNS]) if not p.empty]
    out = pd.concat(parts, ignore_index=True) if parts else empty_pf()
    return out.sort_values(["날짜", "종목명"], ascending=[False, True]).reset_index(drop=True)


def portfolio_template(pdf, date_str):
    """업로드용 양식(날짜·종목명·금액). 직전 보유내역을 날짜만 바꿔 채워 준다.

    빈 칸에서 시작하는 것보다 직전 내역을 고쳐 쓰는 편이 훨씬 빠르기 때문이다.
    """
    base = effective_snapshot(pdf, date_str)[0]
    if base is None or base.empty:
        base = pd.DataFrame({"종목명": ["예) 삼성전자", "예) 미국달러"],
                             "금액": [0.0, 0.0]})
    out = base.copy()
    out.insert(0, "날짜", date_str)
    return out[PF_COLUMNS].reset_index(drop=True)


def parse_portfolio_upload(data, filename=""):
    """업로드한 자산내역 파일을 검증해 (DataFrame, 오류메시지) 로 돌려준다.

    필요한 컬럼은 내려받은 파일과 같다: 날짜 · 종목명 · 금액(천원)
    성공하면 오류메시지가 None 이고, 실패하면 DataFrame 이 None 이다.
    """
    name = (filename or "").lower()
    raw = data.read() if hasattr(data, "read") else data

    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw))
        else:
            df = None
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    df = pd.read_csv(io.BytesIO(raw), encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
            if df is None:
                return None, ("파일 글자코드를 읽지 못했습니다. "
                              "CSV는 UTF-8로 저장하거나 엑셀(.xlsx)로 올려 주세요.")
    except Exception as e:  # noqa: BLE001
        return None, f"파일을 읽지 못했습니다: {e}"

    df = df.rename(columns=lambda c: str(c).strip())
    missing = [c for c in PF_COLUMNS if c not in df.columns]
    if missing:
        return None, (f"필요한 열이 없습니다: {', '.join(missing)}  "
                      f"(열 이름은 {' · '.join(PF_COLUMNS)} 이어야 합니다)")

    df = df[PF_COLUMNS].copy()

    # 날짜: 2026-08-18 · 2026/8/18 · 엑셀 날짜셀 모두 허용 → YYYY-MM-DD 로 통일
    parsed = pd.to_datetime(df["날짜"], errors="coerce")
    bad_date = int(parsed.isna().sum())
    df["날짜"] = parsed.dt.strftime("%Y-%m-%d")

    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    # 금액에 콤마가 섞여 있어도 읽히도록
    df["금액"] = pd.to_numeric(
        df["금액"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce")
    bad_amt = int(df["금액"].isna().sum())
    df["금액"] = df["금액"].fillna(0.0)

    df = df[(df["날짜"].notna()) & (df["종목명"] != "")].reset_index(drop=True)
    if df.empty:
        return None, "쓸 수 있는 행이 없습니다. 날짜와 종목명이 채워져 있는지 확인해 주세요."

    notes = []
    if bad_date:
        notes.append(f"날짜를 읽지 못한 {bad_date}행은 제외했습니다")
    if bad_amt:
        notes.append(f"금액이 숫자가 아닌 {bad_amt}행은 0으로 처리했습니다")
    return df, ("· ".join(notes) if notes else None)


def merge_portfolio(pdf, updf):
    """업로드 자료를 기존 자산내역에 반영. **파일에 있는 날짜만** 통째로 교체한다.

    파일에 없는 날짜의 기존 기록은 건드리지 않는다(실수로 과거 기록이 날아가는 것 방지).
    """
    out = pdf.copy()
    for d in sorted(updf["날짜"].unique()):
        rows = updf[updf["날짜"] == d][["종목명", "금액"]]
        out = upsert_portfolio(out, d, rows)
    return out


def snapshot(pdf, date_str):
    """특정 날짜의 보유내역(종목명·금액)."""
    rows = pdf[pdf["날짜"] == date_str]
    return rows[["종목명", "금액"]].reset_index(drop=True)


def last_date_before(pdf, date_str):
    """해당 날짜 이전에 자산내역이 저장된 가장 최근 날짜. 없으면 None."""
    if pdf.empty:
        return None
    past = pdf[pdf["날짜"] < date_str]
    return None if past.empty else past["날짜"].max()


def latest_snapshot_before(pdf, date_str):
    """해당 날짜 이전의 가장 최근 보유내역. 새 날짜 입력 시 기본값으로 쓴다."""
    last_date = last_date_before(pdf, date_str)
    if last_date is None:
        return pd.DataFrame(columns=["종목명", "금액"])
    return snapshot(pdf, last_date)


def effective_snapshot(pdf, date_str):
    """그날 저장된 내역이 있으면 그것, 없으면 직전 내역(그대로 유지된 것으로 간주)."""
    own = snapshot(pdf, date_str)
    if not own.empty:
        return own, True
    return latest_snapshot_before(pdf, date_str), False


# ---------------------------------------------------------------------------
# 범용 표 보관 (ROE·PBR 업로드 자료 등) — 업로드 한 번 하면 계속 남는다
# ---------------------------------------------------------------------------
def save_table(df, name, dbx=None):
    """DataFrame을 Dropbox에 CSV로 보관. name 예: 'roe_pbr_stocks'."""
    dbx = dbx or get_client()
    if dbx is None:
        return False, "Dropbox 연결 정보가 없습니다."
    try:
        import dropbox as _dbx_mod

        path = f"/apps/macro_dashboard/{name}.csv"
        dbx.files_upload(df.to_csv(index=False).encode("utf-8"), path,
                         mode=_dbx_mod.files.WriteMode.overwrite)
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"보관 중 오류: {e}"


def load_table(name, dbx=None):
    """save_table 로 보관한 표를 다시 읽는다. 없으면 None."""
    dbx = dbx or get_client()
    if dbx is None:
        return None
    try:
        _, res = dbx.files_download(f"/apps/macro_dashboard/{name}.csv")
        return pd.read_csv(io.BytesIO(res.content))
    except Exception:
        return None


def by_ticker(pdf):
    """날짜(행) × 종목명(열) 금액 표. 그날 목록에 없는 종목은 0(미보유)으로 본다."""
    if pdf.empty:
        return pd.DataFrame()
    p = pdf.pivot_table(index="날짜", columns="종목명", values="금액",
                        aggfunc="sum").fillna(0.0)
    return p.sort_index()


def daily_totals(pdf):
    """날짜별 총자산(천원) 합계."""
    if pdf.empty:
        return pd.DataFrame(columns=["날짜", "총자산"])
    g = pdf.groupby("날짜", as_index=False)["금액"].sum()
    g.columns = ["날짜", "총자산"]
    return g.sort_values("날짜", ascending=False).reset_index(drop=True)


def upsert(df, date_str, summary, body):
    """같은 날짜가 있으면 덮어쓰고, 없으면 추가한 새 DataFrame 반환."""
    df = df.copy()
    mask = df["날짜"] == date_str
    if mask.any():
        df.loc[mask, "요약"] = summary
        df.loc[mask, "내용"] = body
    else:
        new = pd.DataFrame([{"날짜": date_str, "요약": summary, "내용": body}])
        df = pd.concat([df, new], ignore_index=True) if not df.empty else new
    return df.sort_values("날짜", ascending=False).reset_index(drop=True)
