"""전체 데이터를 엑셀 1개 + DB 파일 사본으로 backups/ 폴더에 저장한다.  python scripts/backup.py
- backups/온살_백업_YYYY-MM-DD.xlsx  (판매·광고·체험단·마스터·매핑 전체)
- backups/onsal_YYYY-MM-DD.db        (DB 통째 사본, 복원할 때 data/onsal.db 로 덮어쓰기)
최근 30개만 남기고 오래된 백업은 지운다."""
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml  # noqa: E402

from src import config, db  # noqa: E402
from src.export import to_excel_bytes  # noqa: E402

KEEP = 30


def main() -> None:
    db.init_db()
    out = ROOT / "backups"
    out.mkdir(exist_ok=True)
    today = date.today().isoformat()
    sheets = {"판매_일자합산": db.read_sales_daily(), "판매_센터별": db.read_sales_center(), "광고": db.read_ad(),
              "체험단": db.read_trials(), "상품마스터": config.load_master(), "광고매핑": config.load_map()}
    xlsx = out / f"온살_백업_{today}.xlsx"
    xlsx.write_bytes(to_excel_bytes(sheets))
    if not db.is_remote():   # 로컬 SQLite 일 때만 DB 파일 사본 (온라인 DB 는 엑셀 백업으로 충분)
        shutil.copy2(db.DB_PATH, out / f"onsal_{today}.db")
    (out / f"settings_{today}.yaml").write_text(yaml.safe_dump(config.load_settings(), allow_unicode=True, sort_keys=False),
                                                encoding="utf-8")
    for pattern in ("온살_백업_*.xlsx", "onsal_*.db", "settings_*.yaml"):
        for old in sorted(out.glob(pattern))[:-KEEP]:
            old.unlink()
    print(f"백업 완료: {xlsx}")
    print({k: f"{len(v):,}행" for k, v in sheets.items()})


if __name__ == "__main__":
    main()
