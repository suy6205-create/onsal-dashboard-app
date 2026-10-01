"""기존 보고서(쿠팡_로켓_판매재고_관리.xlsx)의 일일데이터·체험단 시트를 DB에 최초 1회 적재.

사용법:  python scripts/migrate_legacy.py "sample_data/쿠팡_로켓_판매재고_관리.xlsx"
- '일자(자동)' 수식 컬럼은 무시한다.
- 같은 날짜는 덮어쓰기(upsert)이므로 여러 번 실행해도 중복되지 않는다.
- 체험단 대행비는 기존 시트에 없으므로 0으로 두고, 체험단 화면에서 직접 입력한다.
"""
from __future__ import annotations

import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, db, service  # noqa: E402
from src.loaders import read_legacy_workbook  # noqa: E402


def main(path: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load_settings()
    db.init_db()
    parsed, trials = read_legacy_workbook(path, cfg["brand"])
    new = service.ingest_sales(parsed, Path(path).name)
    print(f"판매 일일데이터: {parsed.brand_rows}행 / {len(parsed.dates)}일 "
          f"({parsed.dates[0]} ~ {parsed.dates[-1]}) -> 날짜+SKU {len(parsed.daily)}건 저장")
    if new:
        print(f"신규 SKU 마스터 추가(가격 미입력): {new}")
    n = db.import_trials(trials)
    print(f"체험단: {len(trials)}건 중 {n}건 신규 저장 (대행비는 비어 있음 — 체험단 화면에서 직접 입력)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/migrate_legacy.py <쿠팡_로켓_판매재고_관리.xlsx 경로>")
    main(sys.argv[1])
