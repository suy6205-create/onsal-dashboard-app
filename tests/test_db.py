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
    row = {"date": "2026-09-30", "sku_id": "1", "center": "VF107", "sku_name": "a", "brand": "온살", "barcode": "8800000000001",
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


def test_old_db_without_brand_column_is_migrated(tmp_path, monkeypatch):
    import sqlalchemy as sa
    path = tmp_path / "old.db"
    eng = sa.create_engine(f"sqlite:///{path.as_posix()}")
    with eng.begin() as c:   # 브랜드 컬럼이 없던 예전 스키마
        for t in ("sales_center", "sales_daily"):
            c.execute(sa.text(f"CREATE TABLE {t} (date TEXT, sku_id TEXT, sku_name TEXT, barcode TEXT, orderable TEXT, "
                              "orderable_detail TEXT, inbound INTEGER, outbound INTEGER, stock INTEGER, supply_cost INTEGER, soldout INTEGER)"))
        c.execute(sa.text("INSERT INTO sales_daily VALUES ('2026-09-30','1','a','','발주가능','',0,1,5,100,0)"))
    eng.dispose()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    db.reset_engine()
    got = db.read_sales_daily()
    db.reset_engine()
    assert list(got["brand"]) == ["온살"]


def test_upsert_replaces_only_brands_in_file(tmpdb):
    def frame(brand, sku, out):
        row = {"date": "2026-10-15", "sku_id": sku, "center": "VF107", "sku_name": "a", "brand": brand, "barcode": "1",
               "orderable": "발주가능", "orderable_detail": "", "inbound": 0, "outbound": out, "stock": 5,
               "supply_cost": 6000, "soldout": 0}
        c = pd.DataFrame([row])
        return c, L.aggregate_centers(c)
    both = pd.concat([frame("온살", "1", 1)[0], frame("루메아카이브", "2", 2)[0]], ignore_index=True)
    db.upsert_sales(both, L.aggregate_centers(both), "all.csv")
    c, d = frame("온살", "1", 9)           # 온살만 다시 올림 -> 루메아카이브 행은 그대로
    db.upsert_sales(c, d, "onsal_only.csv")
    got = db.read_sales_daily().set_index("sku_id")
    assert got.loc["1", "outbound"] == 9 and got.loc["2", "outbound"] == 2 and len(got) == 2


def test_po_fixed_values_default_even_if_blank_saved(tmpdb):
    cfg = config.load_settings()
    assert (cfg["po_vendor_id"], cfg["po_vendor_name"], cfg["po_center"]) == ("A00065399", "오아 주식회사", "VF107")
    cfg.update(po_vendor_id="", po_vendor_name="", po_center="")      # 예전에 빈 값이 저장된 DB
    config.save_settings(cfg)
    again = config.load_settings()
    assert again["po_vendor_id"] == "A00065399" and again["po_center"] == "VF107"
    cfg.update(po_vendor_id="B1")                                      # 직접 바꾼 값은 존중
    config.save_settings(cfg)
    assert config.load_settings()["po_vendor_id"] == "B1"


def test_retrying_recovers_from_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("connection timeout")
        return "ok"
    slept = []
    assert db.retrying(flaky, tries=4, base_delay=1.0, sleep=slept.append) == "ok"
    assert calls["n"] == 3 and slept == [1.0, 2.0]


def test_retrying_gives_up_with_last_error():
    def always():
        raise RuntimeError("down")
    with pytest.raises(RuntimeError, match="down"):
        db.retrying(always, tries=2, base_delay=0, sleep=lambda s: None)
