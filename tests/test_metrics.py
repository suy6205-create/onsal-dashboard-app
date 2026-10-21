import pandas as pd
import pytest

from src import metrics as M

CFG = {"target_stock_days": 14, "stock_red_days": 7, "stock_yellow_days": 14, "exclude_min_cost": 5000,
       "min_clicks": 10, "bid_up_max_impressions": 1000}


def test_safe_ratios_zero_division():
    assert M.roas(100, 0) == 0 and M.ctr(1, 0) == 0 and M.cpc(100, 0) == 0 and M.cpa(100, 0) == 0
    assert M.roas(406160, 100000) == pytest.approx(4.0616)
    assert M.cvr(2, 40) == 0.05


def test_seven_day_avg_fills_missing_days_with_zero():
    s = pd.Series({"2026-09-30": 7, "2026-09-28": 7})
    assert M.seven_day_avg(s, "2026-09-30") == 2.0
    assert M.seven_day_avg(pd.Series({"2026-09-01": 100}), "2026-09-30") == 0.0


def test_days_of_stock_and_reorder():
    assert M.days_of_stock(22, 1.0) == 22
    assert M.days_of_stock(22, 0) is None
    assert M.reorder_qty(1.0, 22, 14) == 0
    assert M.reorder_qty(2.0, 10, 14) == 18
    assert M.reorder_qty(0.6, 0, 14) == 9
    assert M.reorder_qty(0, 5, 14) == 0


def test_breakeven_roas_uses_consumer_price():
    assert M.breakeven_roas(6000, 4000, 10000) == pytest.approx(10000 / 2000)
    assert M.breakeven_roas(3000, 4000, 10000) is None
    assert M.breakeven_roas(6000, 4000, 0) is None


def test_signal():
    assert M.signal(3, False, True) == "🔴"
    assert M.signal(None, True, True) == "🔴"
    assert M.signal(None, False, False) == "🔴"
    assert M.signal(10, False, True) == "🟡"
    assert M.signal(30, False, True) == "🟢"
    assert M.signal(None, False, True) == "🟢"


def test_keyword_classification():
    assert M.classify_keyword(6000, 0, 30, 500, 0, 4, CFG) == "제외 후보"
    assert M.classify_keyword(100, 0, 3, 500, 0, 4, CFG) == "데이터 부족"
    assert M.classify_keyword(3000, 2, 30, 500, 5.0, 4, CFG) == "입찰 상향 후보"
    assert M.classify_keyword(3000, 2, 30, 5000, 5.0, 4, CFG) == "효자"
    assert M.classify_keyword(3000, 1, 30, 5000, 1.0, 4, CFG) == "관찰/개선"
    assert M.quadrant(9000, 5, 4, 5000) == "핵심 유지"
    assert M.quadrant(100, 5, 4, 5000) == "확대"
    assert M.quadrant(9000, 1, 4, 5000) == "축소·제외"


def test_ad_summary_recomputes_roas_from_raw_numbers():
    ad = pd.DataFrame({"impressions": [1000, 500], "clicks": [10, 5], "cost": [1000.0, 0.0],
                       "orders": [1, 1], "qty": [1, 1], "rev": [4000.0, 500.0], "rev_d": [4000.0, 0.0],
                       "rev_i": [0.0, 500.0], "orders_d": [1, 0], "be_roas": [4.0, 4.0]})
    s = M.ad_summary(ad).iloc[0]
    assert s["roas"] == pytest.approx(4.5) and s["ctr"] == pytest.approx(0.01)
    assert s["cvr"] == pytest.approx(2 / 15)
    only_free = M.ad_summary(ad.iloc[[1]]).iloc[0]
    assert only_free["roas"] == 0


def test_supply_price_changes():
    d = pd.DataFrame({"sku_id": ["1"] * 3, "date": ["2026-09-01", "2026-09-02", "2026-09-03"],
                      "supply_cost": [6000, 6000, 6500]})
    ch = M.supply_price_changes(d)
    assert len(ch) == 1 and ch.iloc[0]["date"] == "2026-09-03"


def _master():
    return pd.DataFrame({"SKU ID": ["1"], "품목": ["세럼"], "판매가": [10000], "할인": [0], "원가": [4000],
                         "판매수수료율": [0.32], "운영중": ["Y"], "광고명키워드": ["세럼"]})


def test_sku_table_with_gaps_and_new_sku():
    daily = pd.DataFrame({
        "date": ["2026-09-29", "2026-09-30", "2026-09-30"], "sku_id": ["1", "1", "9"],
        "sku_name": ["a", "a", "신규"], "barcode": ["", "", ""], "orderable": ["발주가능"] * 3,
        "orderable_detail": [""] * 3, "inbound": [0] * 3, "outbound": [7, 7, 0], "stock": [30, 23, 5],
        "supply_cost": [6000, 6000, 1000], "soldout": [0, 0, 0]})
    t = M.sku_table(daily, _master(), "2026-09-30", CFG).set_index("sku_id")
    assert t.loc["1", "7일평균"] == 2.0 and t.loc["1", "소진예상일"] == 11.5
    assert t.loc["1", "발주권장"] == 5 and t.loc["1", "신호"] == "🟡"
    assert t.loc["9", "소진예상일"] is None or pd.isna(t.loc["9", "소진예상일"])
    assert t.loc["9", "품목"] == "신규"


def test_daily_totals_excludes_trial():
    daily = pd.DataFrame({"date": ["2026-09-15"], "sku_id": ["1"], "outbound": [12], "supply_cost": [6000]})
    trials = pd.DataFrame({"date": ["2026-09-15"], "sku_id": ["1"], "qty": [10]})
    assert M.daily_totals(daily, _master())["qty"].iloc[0] == 12
    ex = M.daily_totals(daily, _master(), trials, exclude_trial=True).iloc[0]
    assert ex["qty"] == 2 and ex["supply_rev"] == 2 * 6000 and ex["consumer_rev"] == 2 * 10000


def test_integrated_net_profit_and_dependency():
    daily = pd.DataFrame({"date": ["2026-09-21", "2026-09-22"], "sku_id": ["1", "1"], "outbound": [6, 4],
                          "supply_cost": [6000, 6000]})
    ad_p = pd.DataFrame({"exec_sku": ["1"], "conv_sku": ["1"], "cost": [10000.0], "qty": [2.0],
                         "conv_bundle": [3]})
    trials = pd.DataFrame({"date": ["2026-09-21"], "sku_id": ["1"], "qty": [1], "unit_price": [6435.0],
                           "agency_fee": [1000.0]})
    r = M.integrated_by_sku(daily, _master(), ad_p, trials, "2026-09-21", "2026-09-27").iloc[0]
    assert r["판매량"] == 10 and r["광고기여판매"] == 6 and r["오가닉추정"] == 3
    assert r["광고의존도"] == pytest.approx(0.6) and r["TACoS"] == pytest.approx(10000 / 100000)
    assert r["공헌이익"] == 2000 * 10 and r["순이익"] == 2000 * 10 - 10000 - 7435


def test_unmapped_options():
    ad = pd.DataFrame({"exec_sku": ["", "1"], "conv_sku": ["", "1"], "ad_option_id": ["A", "B"],
                       "conv_option_id": ["A", "B"], "ad_product": ["온살 X", "온살 Y"],
                       "conv_product": ["온살 X", "온살 Y"], "cost": [100.0, 50.0]})
    u = M.unmapped_options(ad, "온살")
    assert list(u["옵션ID"]) == ["A"]


def test_trial_effect():
    days = pd.date_range("2026-09-08", "2026-09-22").strftime("%Y-%m-%d")
    out = [1 if d < "2026-09-15" else 3 for d in days]
    daily = pd.DataFrame({"date": days, "sku_id": "1", "outbound": out})
    e = M.trial_effect(daily, "1", "2026-09-15", 0, 100000, 2000, "2026-09-22")
    assert e["전7일평균"] == 1 and e["후7일평균"] == 3 and e["후기간완료"]
    assert e["추가판매(7일)"] == 14 and e["회수추정액"] == 28000



def _one_day(stock, soldout_flag, outbound=2):
    return pd.DataFrame({"date": ["2026-09-30"], "sku_id": ["1"], "sku_name": ["a"], "barcode": [""],
                         "orderable": ["발주가능"], "orderable_detail": [""], "inbound": [0], "outbound": [outbound],
                         "stock": [stock], "supply_cost": [6000], "soldout": [soldout_flag]})


def test_soldout_flag_ignored_when_stock_present():
    # 쿠팡 품절여부=YES 이지만 재고가 입고되어 있으면 품절/빨간불이 아니다
    r = M.sku_table(_one_day(40, 1, outbound=7), _master(), "2026-09-30", CFG).iloc[0]
    assert not r["품절"] and r["당일품절후입고"] and r["신호"] == "🟢"


def test_zero_stock_is_soldout_even_without_flag():
    r = M.sku_table(_one_day(0, 0, outbound=0), _master(), "2026-09-30", CFG).iloc[0]
    assert r["품절"] and r["신호"] == "🔴"


def test_ad_row_brand_uses_map_then_name():
    ad = pd.DataFrame({"ad_option_id": ["A", "B", "C"], "ad_product": ["온살 세럼", "무명 상품", "루메아카이브 로션"]})
    amap = pd.DataFrame({"광고옵션ID": ["A", "B"], "SKU ID": ["1", "2"], "묶음수량": [1, 1], "광고상품명": ["", ""], "비고": ["", ""]})
    master = pd.DataFrame({"SKU ID": ["1", "2"], "브랜드": ["온살", "루메아카이브"]})
    got = M.ad_row_brand(ad, amap, master, ["온살", "루메아카이브"])
    assert list(got) == ["온살", "루메아카이브", "루메아카이브"]   # C 는 매핑이 없어 상품명으로 판별
    assert M.unmapped_options(pd.DataFrame(), ["온살"]).empty


def test_supply_margin_matches_existing_sheet_values():
    # 비타민 앰플: 판매가 10,000 · 수수료 40% · 원가 3,500 -> 기존 시트의 공급가(-VAT) 5,455 / 마진 1,955
    r = M.supply_margin(10000, 3500, 0.40)
    assert r["공급가(VAT 포함)"] == 6000 and r["공급가(VAT 제외)"] == 5455 and r["개당 마진"] == 1955
    assert r["마진율(공급가 기준)"] == pytest.approx(1955 / 5455)
    assert r["마진율(소비자가 기준)"] == pytest.approx(0.1955) and r["손익분기 ROAS"] == pytest.approx(10000 / 1955)
    # 히알루론 세럼: 판매가 9,500 · 수수료 32.26% -> 공급가(+VAT) 6,435 / (-VAT) 5,850
    h = M.supply_margin(9500, 3518, 1 - 6435 / 9500)
    assert h["공급가(VAT 포함)"] == 6435 and h["공급가(VAT 제외)"] == 5850 and h["개당 마진"] == 2332


def test_supply_margin_edge_cases_and_inverse():
    assert M.supply_margin(0, 1000, 0.4)["공급가(VAT 제외)"] == 0 and M.supply_margin(0, 1000, 0.4)["손익분기 ROAS"] is None
    loss = M.supply_margin(10000, 6000, 0.4)                       # 원가가 공급가보다 높으면 적자
    assert loss["개당 마진"] < 0 and loss["손익분기 ROAS"] is None
    assert M.supply_margin(10000, 3500, 0.4, discount=1000)["소비자가"] == 9000
    assert M.fee_rate_from_supply(10000, 6000) == pytest.approx(0.4) and M.fee_rate_from_supply(0, 6000) is None


def test_tag_ad_brand_uses_mapping_then_product_name():
    ad = pd.DataFrame({"ad_option_id": ["1", "2", "3"],
                       "ad_product": ["온살 세럼,1개", "루메아카이브 로션,1개", "아무 이름"], "cost": [1.0, 2.0, 3.0]})
    amap = pd.DataFrame({"광고옵션ID": ["1"], "SKU ID": ["9"], "묶음수량": [1], "광고상품명": [""], "비고": [""]})
    master = pd.DataFrame({"SKU ID": ["9"], "브랜드": ["루메아카이브"]})        # 매핑된 SKU 의 마스터 브랜드가 이름보다 우선
    q = M.tag_ad_brand(ad, amap, master, ["온살", "루메아카이브"])
    assert list(q["brand"]) == ["루메아카이브", "루메아카이브", "기타(미분류)"]
