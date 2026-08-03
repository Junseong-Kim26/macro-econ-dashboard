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

# 자산 운용내역: 날짜별 종목 평가액(백만원)
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


def journal_path():
    return _cfg().get("journal_path", DEFAULT_PATH)


def portfolio_path():
    return _cfg().get("portfolio_path", DEFAULT_PF_PATH)


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


def load(dbx=None):
    """Dropbox에서 매매일지를 읽어 DataFrame으로 반환."""
    dbx = dbx or get_client()
    if dbx is None:
        return empty_df()
    try:
        _, res = dbx.files_download(journal_path())
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


def save(df, dbx=None):
    """DataFrame을 Dropbox CSV로 저장. 성공 여부 반환."""
    dbx = dbx or get_client()
    if dbx is None:
        return False, "Dropbox 연결 정보가 없습니다. secrets 의 [dropbox] 설정을 확인하세요."
    try:
        import dropbox as _dbx_mod

        data = df[COLUMNS].to_csv(index=False).encode("utf-8")
        dbx.files_upload(data, journal_path(), mode=_dbx_mod.files.WriteMode.overwrite)
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
# 자산 운용내역 (날짜 · 종목명 · 금액[백만원])
# ---------------------------------------------------------------------------
def empty_pf():
    return pd.DataFrame(columns=PF_COLUMNS)


def load_portfolio(dbx=None):
    """Dropbox에서 자산 운용내역을 읽어 DataFrame으로 반환."""
    dbx = dbx or get_client()
    if dbx is None:
        return empty_pf()
    try:
        _, res = dbx.files_download(portfolio_path())
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


def save_portfolio(df, dbx=None):
    """자산 운용내역을 Dropbox CSV로 저장."""
    dbx = dbx or get_client()
    if dbx is None:
        return False, "Dropbox 연결 정보가 없습니다."
    try:
        import dropbox as _dbx_mod

        data = df[PF_COLUMNS].to_csv(index=False).encode("utf-8")
        dbx.files_upload(data, portfolio_path(), mode=_dbx_mod.files.WriteMode.overwrite)
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
    """날짜별 총자산(백만원) 합계."""
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
