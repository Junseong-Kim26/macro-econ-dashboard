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


def upsert(df, date_str, summary, body):
    """같은 날짜가 있으면 덮어쓰고, 없으면 추가한 새 DataFrame 반환."""
    df = df.copy()
    mask = df["날짜"] == date_str
    if mask.any():
        df.loc[mask, "요약"] = summary
        df.loc[mask, "내용"] = body
    else:
        new = pd.DataFrame([{"날짜": date_str, "요약": summary, "내용": body}])
        df = pd.concat([df, new], ignore_index=True)
    return df.sort_values("날짜", ascending=False).reset_index(drop=True)
