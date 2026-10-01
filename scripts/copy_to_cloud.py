"""로컬 데이터(data/onsal.db) 전체를 온라인 DB(Neon Postgres 등)로 복사한다. 최초 1회.

사용법 (PowerShell):
    $env:DATABASE_URL = "postgresql://사용자:비밀번호@호스트/dbname?sslmode=require"
    python scripts/copy_to_cloud.py
이미 데이터가 들어 있는 DB 에는 덮어쓰지 않고 중단한다. 일부러 덮어쓰려면 --replace 를 붙인다.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from src import db  # noqa: E402

TABLES = ["sales_center", "sales_daily", "ad_rows", "trials", "uploads", "app_config"]
DROP_ID = {"trials", "uploads"}   # 자동 증가 id 는 대상 DB 가 새로 부여


def main() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or (url.startswith("sqlite") and "--test" not in sys.argv):
        sys.exit("DATABASE_URL 환경변수에 온라인 DB 주소를 먼저 설정하세요. (README/DEPLOY.md 참고)")
    url = db.normalize_url(url)
    if not db.DB_PATH.exists():
        sys.exit(f"로컬 DB 가 없습니다: {db.DB_PATH}")

    src = create_engine(f"sqlite:///{db.DB_PATH.as_posix()}")
    dst = create_engine(url, pool_pre_ping=True)
    db._create_schema(dst)

    with dst.connect() as c:
        have = {t: c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in TABLES}
    if any(have.values()) and "--replace" not in sys.argv:
        sys.exit(f"대상 DB 에 이미 데이터가 있어 중단합니다: {have}\n덮어쓰려면 --replace 를 붙이세요.")

    with src.connect() as s, dst.begin() as d:
        for t in TABLES:
            df = pd.read_sql(text(f"SELECT * FROM {t}"), s)
            if t == "uploads" and "rows" in df.columns:
                df = df.rename(columns={"rows": "n_rows"})
            if t in DROP_ID and "id" in df.columns:
                df = df.drop(columns=["id"])
            d.execute(text(f"DELETE FROM {t}"))
            if len(df):
                db._chunked_insert(df, t, d)
            print(f"{t}: {len(df):,}행 복사")
    print("완료. 온라인 DB 에 로컬 데이터가 옮겨졌습니다.")


if __name__ == "__main__":
    main()
