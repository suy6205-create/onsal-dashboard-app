"""sample_data/ 의 판매 CSV·광고 XLSX 를 DB에 적재 (업로드 화면과 동일 로직). 데모/검증용."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from src import config, db, loaders as L, service  # noqa: E402

cfg = config.load_settings()
db.init_db()
for f in sorted((ROOT / "sample_data").glob("basic_operation_rocket_*.csv")):
    ps = L.parse_sales_csv(str(f), cfg["brand"])
    new = service.ingest_sales(ps, f.name)
    print(f"판매 {f.name}: {ps.brand_rows}행, 날짜 {ps.dates}, 신규 SKU {new}")
for f in sorted((ROOT / "sample_data").glob("A*_pa_total_campaign_*.xlsx")):
    s, e = L.parse_ad_filename(f.name)
    n = service.ingest_ad(L.parse_ad_xlsx(str(f)), s, e, f.name, cfg["brand"])
    print(f"광고 {f.name}: {s}~{e}, 매핑 초안 {n}개")
