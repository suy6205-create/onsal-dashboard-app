"""설정·마스터·매핑 입출력.

저장 위치는 DB(app_config 테이블)다 → 온라인 배포에서도 수정 내용이 유지된다.
처음 읽을 때 DB 에 값이 없으면 저장소의 config/ 파일(settings.yaml, product_master.csv, ad_sku_map.csv)을
기본값으로 복사해 시작한다.
"""
from io import StringIO
from pathlib import Path

import pandas as pd
import yaml

from . import db

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
MASTER_PATH = CONFIG_DIR / "product_master.csv"
MAP_PATH = CONFIG_DIR / "ad_sku_map.csv"

MASTER_COLS = ["SKU ID", "품목", "판매가", "할인", "원가", "판매수수료율", "운영중", "광고명키워드"]
MAP_COLS = ["광고옵션ID", "광고상품명", "SKU ID", "묶음수량", "비고"]

DEFAULTS = {
    "brand": "온살", "attribution_days": 14, "target_stock_days": 14,
    "stock_red_days": 7, "stock_yellow_days": 14, "exclude_min_cost": 5000,
    "min_clicks": 10, "drop_pct": 30, "bid_up_max_impressions": 1000,
    "wing_target_roas": 3.0,
    "wing_exclude_min_cost": 1500, "wing_min_clicks": 10, "wing_bid_up_max_impressions": 1000,
    "trial_fee_per_unit": 0, "vat": 1.1, "default_breakeven_roas": 4.0,
    "keyword_groups": {},
}


def _load_text(name: str, seed: Path) -> str:
    """DB 에서 읽고, 없으면 config/ 파일로 시드(없으면 빈 문자열)."""
    txt = db.kv_get(name)
    if txt is None:
        txt = seed.read_text(encoding="utf-8-sig") if seed.exists() else ""
        db.kv_set(name, txt)
    return txt


# ---------------------------------------------------------------- settings
def load_settings() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(yaml.safe_load(_load_text("settings", SETTINGS_PATH)) or {})
    return cfg


def save_settings(cfg: dict) -> None:
    db.kv_set("settings", yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))


# ---------------------------------------------------------------- master
def _csv(txt: str, dtype: dict) -> pd.DataFrame:
    return pd.read_csv(StringIO(txt), dtype=dtype) if txt.strip() else pd.DataFrame()


def load_master() -> pd.DataFrame:
    df = _csv(_load_text("product_master", MASTER_PATH), {"SKU ID": str})
    for c in MASTER_COLS:
        if c not in df.columns:
            df[c] = "" if c in ("SKU ID", "품목", "운영중", "광고명키워드") else 0
    for c in ["판매가", "할인", "원가", "판매수수료율"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["운영중"] = df["운영중"].fillna("Y")
    df["광고명키워드"] = df["광고명키워드"].fillna("")
    return df[MASTER_COLS]


def save_master(df: pd.DataFrame) -> None:
    db.kv_set("product_master", df[MASTER_COLS].to_csv(index=False))


# ---------------------------------------------------------------- ad map
def load_map() -> pd.DataFrame:
    df = _csv(_load_text("ad_sku_map", MAP_PATH), {"광고옵션ID": str, "SKU ID": str})
    for c in MAP_COLS:
        if c not in df.columns:
            df[c] = ""
    df["묶음수량"] = pd.to_numeric(df["묶음수량"], errors="coerce").fillna(1).astype(int)
    for c in ("광고옵션ID", "SKU ID", "광고상품명", "비고"):
        df[c] = df[c].fillna("").astype(str)
    return df[MAP_COLS]


def save_map(df: pd.DataFrame) -> None:
    db.kv_set("ad_sku_map", df[MAP_COLS].to_csv(index=False))
