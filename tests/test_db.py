import pandas as pd
import pytest

from src import config, db
from src import loaders as L


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    db.reset_engine()
    yield
    db.reset_engine()


def _sales(outbound=3):
    row = {"date": "2026-09-30", "sku_id": "1", "center": "VF107", "sku_name": "a", "barcode": "8800000000001",
           "orderable": "발주가능", "orderable_detail": "정상", "inbound": 0, "outbound": outbound, "stock": 10,
           "supply_cost": 6000, "soldout": 0}
    c = pd.DataFrame([row])
    return c, L.aggregate_centers(c)


def test_sales_upsert_overwrites_same_date(tmpdb):
    c, d = _sales(3)
    db.upsert_sales(c, d, "a.csv")
    c, d = _sales(7)
    db.upsert_sales(c, d, "a_again.csv")
    got = db.read_sales_daily()
    assert len(got) == 1 and got.iloc[0]["outbound"] == 7 and got.iloc[0]["barcode"] == "8800000000001"
    assert len(db.read_uploads()) == 2


def test_ad_upsert_replaces_same_period_only(tmpdb):
    ad = pd.DataFrame({c: ["x"] for c in L.AD_TEXT_COLS} | {c: [1.0] for c in L.AD_NUM_COLS})
    db.upsert_ad(ad, "2026-09-21", "2026-09-27", "w.xlsx")
    db.upsert_ad(ad, "2026-09-21", "2026-09-27", "w2.xlsx")
    db.upsert_ad(ad, "2026-09-30", "2026-09-30", "d.xlsx")
    per = db.ad_periods()
    assert len(per) == 2 and len(db.read_ad()) == 2
    assert list(per.sort_values("period_start")["is_daily"]) == [0, 1]


def test_trials_crud(tmpdb):
    db.add_trial("2026-09-15", "1", 10, 6435.0, 0.0, "")
    t = db.read_trials()
    assert len(t) == 1
    t.loc[0, "agency_fee"] = 72839.8
    db.replace_trials(t.drop(columns=["id"]))
    assert db.read_trials().iloc[0]["agency_fee"] == pytest.approx(72839.8)
    db.replace_trials(t.iloc[0:0].drop(columns=["id"]))
    assert db.read_trials().empty


def test_config_roundtrip_in_db(tmpdb):
    m = config.load_master()
    row = {"SKU ID": "1000001", "품목": "테스트", "판매가": 10000, "할인": 0, "원가": 4000,
           "판매수수료율": 0, "운영중": "Y", "광고명키워드": ""}
    config.save_master(pd.concat([m, pd.DataFrame([row])], ignore_index=True))
    m = config.load_master()
    assert m.iloc[-1]["SKU ID"] == "1000001"
    m.loc[m.index[-1], "판매가"] = 12345
    config.save_master(m)
    assert config.load_master().iloc[-1]["판매가"] == 12345
    cfg = config.load_settings()
    cfg["wing_target_roas"] = 2.5
    config.save_settings(cfg)
    assert config.load_settings()["wing_target_roas"] == 2.5
    config.save_map(config.load_map())
    assert list(config.load_map().columns) == config.MAP_COLS
