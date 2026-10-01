"""적재 로직 (업로드 화면·이관 스크립트 공용): DB 저장 + 마스터/매핑표 자동 갱신."""
from __future__ import annotations

import pandas as pd

from . import config, db
from .loaders import ParsedSales, draft_ad_map


def add_new_skus_to_master(daily: pd.DataFrame) -> list[str]:
    """판매데이터에 처음 나온 SKU 를 마스터에 자동 추가(가격 0 = '가격 미입력' 경고 대상)."""
    master = config.load_master()
    known = set(master["SKU ID"])
    new = []
    rows = []
    for sku, name in daily[["sku_id", "sku_name"]].drop_duplicates("sku_id").itertuples(index=False):
        if sku not in known:
            new.append(sku)
            rows.append({"SKU ID": sku, "품목": name, "판매가": 0, "할인": 0, "원가": 0,
                         "판매수수료율": 0, "운영중": "Y", "광고명키워드": ""})
    if rows:
        config.save_master(pd.concat([master, pd.DataFrame(rows)], ignore_index=True))
    return new


def new_skus(daily: pd.DataFrame) -> list[str]:
    known = set(config.load_master()["SKU ID"])
    return [s for s in daily["sku_id"].unique() if s not in known]


def ingest_sales(parsed: ParsedSales, filename: str = "") -> list[str]:
    db.upsert_sales(parsed.center, parsed.daily, filename)
    return add_new_skus_to_master(parsed.daily)


def ingest_ad(ad: pd.DataFrame, start: str, end: str, filename: str = "", brand: str = "온살") -> int:
    """광고 저장 + 매핑표 초안 자동 생성(기존 매핑은 보존). 새로 추가된 초안 수를 반환."""
    db.upsert_ad(ad, start, end, filename)
    existing = config.load_map()
    draft = draft_ad_map(ad, config.load_master(), brand, existing)
    if len(draft):
        config.save_map(pd.concat([existing, draft], ignore_index=True))
    return len(draft)


def pending_price_skus() -> pd.DataFrame:
    """판매가/원가가 비어 있는 SKU ('가격 미입력' 경고)."""
    m = config.load_master()
    return m[(m["판매가"] <= 0) | (m["원가"] <= 0)]
