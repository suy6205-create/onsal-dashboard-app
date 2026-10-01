"""저장소: 일자별 판매/광고 누적, 체험단, 업로드 이력, 설정·마스터.

기본은 로컬 SQLite 파일(data/onsal.db). 환경변수/Streamlit secrets 의 DATABASE_URL 이 있으면
그 DB(예: Neon Postgres)를 쓴다 → 온라인 배포 시 서버 재시작에도 데이터가 유지된다.
SQL 은 SQLite/Postgres 양쪽에서 동작하는 표준 문법만 쓴다.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, text

from .loaders import AD_NUM_COLS, AD_TEXT_COLS, DAILY_COLS

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "onsal.db"

_engine = None


def normalize_url(url: str) -> str:
    """Neon/Heroku 식 주소(postgres://, postgresql://)를 SQLAlchemy+psycopg2 형식으로 맞춘다."""
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def get_url() -> str:
    """DATABASE_URL(환경변수 → Streamlit secrets) → 없으면 로컬 SQLite."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        try:
            import streamlit as st
            url = str(st.secrets["DATABASE_URL"]).strip()
        except Exception:  # noqa: BLE001  (secrets 없음/키 없음)
            url = ""
    if not url:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{DB_PATH.as_posix()}"
    return normalize_url(url)


def is_remote() -> bool:
    return not get_url().startswith("sqlite")


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_url(), pool_pre_ping=True, pool_recycle=300, future=True)
        _create_schema(_engine)
    return _engine


def reset_engine() -> None:
    """테스트용: 엔진을 다시 만든다 (DATABASE_URL 이 바뀐 뒤 호출)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def _ddl(dialect: str) -> list[str]:
    id_col = "INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite" else "SERIAL PRIMARY KEY"
    ad_cols = ",\n  ".join([f"{c} TEXT" for c in AD_TEXT_COLS] + [f"{c} DOUBLE PRECISION" for c in AD_NUM_COLS])
    return [
        """CREATE TABLE IF NOT EXISTS sales_center (
  date TEXT, sku_id TEXT, center TEXT, sku_name TEXT, barcode TEXT, orderable TEXT,
  orderable_detail TEXT, inbound INTEGER, outbound INTEGER, stock INTEGER, supply_cost INTEGER, soldout INTEGER,
  PRIMARY KEY (date, sku_id, center))""",
        """CREATE TABLE IF NOT EXISTS sales_daily (
  date TEXT, sku_id TEXT, sku_name TEXT, barcode TEXT, orderable TEXT, orderable_detail TEXT,
  inbound INTEGER, outbound INTEGER, stock INTEGER, supply_cost INTEGER, soldout INTEGER,
  PRIMARY KEY (date, sku_id))""",
        f"""CREATE TABLE IF NOT EXISTS ad_rows (
  period_start TEXT, period_end TEXT, is_daily INTEGER, source_file TEXT, row_no INTEGER,
  {ad_cols},
  PRIMARY KEY (period_start, period_end, row_no))""",
        f"""CREATE TABLE IF NOT EXISTS trials (
  id {id_col}, date TEXT, sku_id TEXT, qty INTEGER,
  unit_price DOUBLE PRECISION, agency_fee DOUBLE PRECISION, memo TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS uploads (
  id {id_col}, filename TEXT, kind TEXT, period_start TEXT,
  period_end TEXT, n_rows INTEGER, uploaded_at TEXT)""",
        "CREATE TABLE IF NOT EXISTS app_config (name TEXT PRIMARY KEY, content TEXT)",
    ]


def _create_schema(eng) -> None:
    with eng.begin() as c:
        for stmt in _ddl(eng.dialect.name):
            c.execute(text(stmt))
    if eng.dialect.name == "sqlite":   # 예전 로컬 DB: uploads.rows -> n_rows (rows 는 일부 DB 에서 예약어 취급)
        with eng.begin() as c:
            cols = [r[1] for r in c.execute(text("PRAGMA table_info(uploads)"))]
            if "rows" in cols and "n_rows" not in cols:
                c.execute(text("ALTER TABLE uploads RENAME COLUMN rows TO n_rows"))


def init_db() -> None:
    engine()


@contextmanager
def conn():
    """트랜잭션 연결 (정상 종료 시 commit, 예외 시 rollback)."""
    with engine().begin() as c:
        yield c


def _read(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine().connect() as c:
        return pd.read_sql(text(sql), c, params=params)


def _chunked_insert(df: pd.DataFrame, table: str, c) -> None:
    # Postgres 는 쿼리당 바인드 변수 65535개 제한 → 컬럼 수에 맞춰 묶음 크기를 줄인다
    size = max(1, 30000 // max(1, len(df.columns)))
    df.to_sql(table, c, if_exists="append", index=False, method="multi", chunksize=size)


def _log(c, filename, kind, start, end, rows):
    c.execute(text("INSERT INTO uploads(filename,kind,period_start,period_end,n_rows,uploaded_at) "
                   "VALUES (:f,:k,:s,:e,:n,:t)"),
              dict(f=filename, k=kind, s=start, e=end, n=int(rows), t=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


# ---------------------------------------------------------------- 설정/마스터 (key-value)
def kv_get(name: str) -> str | None:
    df = _read("SELECT content FROM app_config WHERE name = :n", {"n": name})
    return None if df.empty else df.iloc[0]["content"]


def kv_set(name: str, content: str) -> None:
    with conn() as c:
        c.execute(text("DELETE FROM app_config WHERE name = :n"), {"n": name})
        c.execute(text("INSERT INTO app_config(name, content) VALUES (:n, :v)"), {"n": name, "v": content})


# ---------------------------------------------------------------- 판매
def upsert_sales(center: pd.DataFrame, daily: pd.DataFrame, filename: str = "") -> None:
    """같은 날짜 데이터는 통째로 교체(덮어쓰기) -> 중복 누적 없음."""
    if daily.empty:
        return
    dates = sorted(daily["date"].unique())
    dq = bindparam("dates", expanding=True)
    with conn() as c:
        c.execute(text("DELETE FROM sales_center WHERE date IN :dates").bindparams(dq), {"dates": dates})
        c.execute(text("DELETE FROM sales_daily WHERE date IN :dates").bindparams(bindparam("dates", expanding=True)),
                  {"dates": dates})
        _chunked_insert(center[["date", "sku_id", "center", "sku_name", "barcode", "orderable", "orderable_detail",
                                "inbound", "outbound", "stock", "supply_cost", "soldout"]], "sales_center", c)
        _chunked_insert(daily[DAILY_COLS], "sales_daily", c)
        _log(c, filename, "판매", dates[0], dates[-1], len(center))


def read_sales_daily() -> pd.DataFrame:
    return _read("SELECT * FROM sales_daily ORDER BY date, sku_id")


def read_sales_center() -> pd.DataFrame:
    return _read("SELECT * FROM sales_center ORDER BY date, sku_id, center")


# ---------------------------------------------------------------- 광고
def upsert_ad(ad: pd.DataFrame, start: str, end: str, filename: str = "") -> None:
    """같은 기간(시작~종료)의 광고 데이터는 교체."""
    df = ad.copy()
    df.insert(0, "row_no", range(len(df)))
    df.insert(0, "source_file", filename)
    df.insert(0, "is_daily", int(start == end))
    df.insert(0, "period_end", end)
    df.insert(0, "period_start", start)
    with conn() as c:
        c.execute(text("DELETE FROM ad_rows WHERE period_start=:s AND period_end=:e"), {"s": start, "e": end})
        _chunked_insert(df, "ad_rows", c)
        _log(c, filename, "광고", start, end, len(df))


def read_ad() -> pd.DataFrame:
    return _read("SELECT * FROM ad_rows")


def ad_periods() -> pd.DataFrame:
    return _read("SELECT period_start, period_end, is_daily, COUNT(*) AS n_rows, MAX(source_file) AS source_file "
                 "FROM ad_rows GROUP BY period_start, period_end, is_daily ORDER BY period_start")


# ---------------------------------------------------------------- 체험단
def read_trials() -> pd.DataFrame:
    return _read("SELECT * FROM trials ORDER BY date, id")


def add_trial(date: str, sku_id: str, qty: int, unit_price: float, agency_fee: float, memo: str) -> None:
    with conn() as c:
        c.execute(text("INSERT INTO trials(date,sku_id,qty,unit_price,agency_fee,memo) "
                       "VALUES (:d,:s,:q,:u,:a,:m)"),
                  dict(d=date, s=sku_id, q=int(qty), u=float(unit_price), a=float(agency_fee), m=memo))


def replace_trials(df: pd.DataFrame) -> None:
    """data_editor 결과로 전체 교체 (수정/삭제 반영)."""
    d = df[["date", "sku_id", "qty", "unit_price", "agency_fee", "memo"]].copy()
    d["qty"] = d["qty"].astype(int)
    with conn() as c:
        c.execute(text("DELETE FROM trials"))
        if len(d):
            _chunked_insert(d, "trials", c)


def import_trials(df: pd.DataFrame) -> int:
    """이관용: 같은 (날짜, SKU, 개수)가 이미 있으면 건너뜀."""
    cur = read_trials()
    n = 0
    for r in df.itertuples():
        dup = len(cur) and ((cur["date"] == r.date) & (cur["sku_id"] == r.sku_id) & (cur["qty"] == r.qty)).any()
        if not dup:
            add_trial(r.date, r.sku_id, int(r.qty), float(r.unit_price), float(r.agency_fee), str(r.memo))
            n += 1
    return n


# ---------------------------------------------------------------- 이력
def read_uploads() -> pd.DataFrame:
    return _read("SELECT * FROM uploads ORDER BY id DESC")
