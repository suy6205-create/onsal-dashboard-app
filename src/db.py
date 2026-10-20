"""저장소: 일자별 판매/광고 누적, 체험단, 업로드 이력, 설정·마스터.

기본은 로컬 SQLite 파일(data/onsal.db). 환경변수/Streamlit secrets 의 DATABASE_URL 이 있으면
그 DB(예: Neon Postgres)를 쓴다 → 온라인 배포 시 서버 재시작에도 데이터가 유지된다.
SQL 은 SQLite/Postgres 양쪽에서 동작하는 표준 문법만 쓴다.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, event, inspect, text

from .loaders import AD_NUM_COLS, AD_TEXT_COLS, DAILY_COLS

DEFAULT_BRAND = "온살"   # brand 칸이 없던 예전 데이터의 기본 브랜드
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


def retrying(fn, tries: int = 4, base_delay: float = 1.5, sleep=time.sleep):
    """일시적 연결 실패(무료 DB 가 잠들었다 깨어나는 순간 등)에 대비해 몇 번 다시 시도한다."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                sleep(base_delay * (i + 1))
    raise last


def engine():
    global _engine
    if _engine is None:
        url = get_url()
        kwargs = {"connect_args": {"connect_timeout": 15}} if not url.startswith("sqlite") else {}
        eng = create_engine(url, pool_pre_ping=True, pool_recycle=300, future=True, **kwargs)
        if not url.startswith("sqlite"):
            @event.listens_for(eng, "do_connect")
            def _connect_with_retry(dialect, conn_rec, cargs, cparams):   # noqa: ANN001
                return retrying(lambda: dialect.loaded_dbapi.connect(*cargs, **cparams))
        _create_schema(eng)      # 연결 단계에서 이미 재시도하므로 여기서는 한 번만
        _engine = eng          # 스키마 준비까지 성공했을 때만 보관 (실패하면 다음 접속에서 다시 시도)
    return _engine


def reset_engine() -> None:
    """테스트용: 엔진을 다시 만든다 (DATABASE_URL 이 바뀐 뒤 호출)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _CACHE.clear()


def _ddl(dialect: str) -> list[str]:
    id_col = "INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite" else "SERIAL PRIMARY KEY"
    ad_cols = ",\n  ".join([f"{c} TEXT" for c in AD_TEXT_COLS] + [f"{c} DOUBLE PRECISION" for c in AD_NUM_COLS])
    return [
        """CREATE TABLE IF NOT EXISTS sales_center (
  date TEXT, sku_id TEXT, center TEXT, sku_name TEXT, brand TEXT, barcode TEXT, orderable TEXT,
  orderable_detail TEXT, inbound INTEGER, outbound INTEGER, stock INTEGER, supply_cost INTEGER, soldout INTEGER,
  PRIMARY KEY (date, sku_id, center))""",
        """CREATE TABLE IF NOT EXISTS sales_daily (
  date TEXT, sku_id TEXT, sku_name TEXT, brand TEXT, barcode TEXT, orderable TEXT, orderable_detail TEXT,
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
    # 브랜드가 하나였던 예전 DB: brand 컬럼을 추가하고 기존 데이터는 기본 브랜드로 채운다
    insp = inspect(eng)
    for table in ("sales_center", "sales_daily"):
        if "brand" not in [col["name"] for col in insp.get_columns(table)]:
            with eng.begin() as c:
                c.execute(text(f"ALTER TABLE {table} ADD COLUMN brand TEXT"))
                c.execute(text(f"UPDATE {table} SET brand = :b WHERE brand IS NULL"), {"b": DEFAULT_BRAND})
    if eng.dialect.name == "sqlite":   # 예전 로컬 DB: uploads.rows -> n_rows (rows 는 일부 DB 에서 예약어 취급)
        with eng.begin() as c:
            cols = [r[1] for r in c.execute(text("PRAGMA table_info(uploads)"))]
            if "rows" in cols and "n_rows" not in cols:
                c.execute(text("ALTER TABLE uploads RENAME COLUMN rows TO n_rows"))


def init_db() -> None:
    engine()


@contextmanager
def conn():
    """트랜잭션 연결 (정상 종료 시 commit, 예외 시 rollback). 쓰기가 끝나면 읽기 캐시를 비운다."""
    try:
        with engine().begin() as c:
            yield c
    finally:
        _CACHE.clear()


# 화면을 누를 때마다 DB 에서 같은 데이터를 다시 받지 않도록 읽기 결과를 (30분) 보관한다.
# (무료 DB 는 데이터 전송량·가동 시간 한도가 있어 반복 조회가 한도를 빨리 소진시킨다)
_CACHE: dict = {}
CACHE_TTL = 1800


def _read(sql: str, params: dict | None = None) -> pd.DataFrame:
    key = (get_url(), sql, tuple(sorted((params or {}).items())))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1].copy()
    with engine().connect() as c:
        df = pd.read_sql(text(sql), c, params=params)
    _CACHE[key] = (time.time(), df)
    return df.copy()


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
    brands = sorted(daily["brand"].unique())    # 같은 날짜라도 이 파일에 들어 있는 브랜드의 행만 교체
    with conn() as c:
        for t in ("sales_center", "sales_daily"):
            c.execute(text(f"DELETE FROM {t} WHERE date IN :dates AND brand IN :brands").bindparams(
                bindparam("dates", expanding=True), bindparam("brands", expanding=True)),
                {"dates": dates, "brands": brands})
        _chunked_insert(center[["date", "sku_id", "center", "sku_name", "brand", "barcode", "orderable", "orderable_detail",
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


def delete_ad_periods(spans) -> None:
    """(시작, 종료) 목록에 해당하는 광고 데이터를 삭제."""
    with conn() as c:
        for s, e in spans:
            c.execute(text("DELETE FROM ad_rows WHERE period_start=:s AND period_end=:e"), {"s": s, "e": e})


def delete_all_ad() -> None:
    with conn() as c:
        c.execute(text("DELETE FROM ad_rows"))


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
