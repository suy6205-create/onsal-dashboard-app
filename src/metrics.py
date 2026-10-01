"""지표 계산. 화면(Streamlit)과 분리된 순수 함수 모음 — tests/ 에서 검증한다.

단위 주의
- 공급가(매입원가, VAT 제외)  : 쿠팡이 우리에게 지급하는 금액. 로켓 '공급가매출' 기준.
- 소비자가(판매가-할인)       : 고객이 결제하는 금액. 광고 전환매출액과 같은 기준.
광고 지표와 판매 지표를 섞을 때는 반드시 소비자가 기준으로 맞춘다.
"""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- 기본 비율
def safe_div(a, b, default=0.0):
    try:
        if b is None or b == 0 or (isinstance(b, float) and math.isnan(b)):
            return default
        return a / b
    except (TypeError, ZeroDivisionError):
        return default


def ctr(clicks, impressions):
    return safe_div(clicks, impressions)


def cpc(cost, clicks):
    return safe_div(cost, clicks)


def cvr(orders, clicks):
    return safe_div(orders, clicks)


def roas(revenue, cost):
    """ROAS = 전환매출액 / 광고비 (배수, 4.06 = 406%). 광고비 0이면 0."""
    return safe_div(revenue, cost)


def cpa(cost, orders):
    return safe_div(cost, orders)


def pct_change(cur, prev):
    """증감률(소수). 비교값이 0/없음이면 None."""
    if prev is None or cur is None or prev == 0 or (isinstance(prev, float) and math.isnan(prev)):
        return None
    return (cur - prev) / abs(prev)


# ---------------------------------------------------------------- 판매·재고
def seven_day_avg(qty_by_date: pd.Series, asof, days: int = 7) -> float:
    """asof 포함 최근 days일 출고합 / days. 데이터 없는 날은 0으로 간주."""
    asof = pd.Timestamp(asof)
    idx = pd.date_range(asof - timedelta(days=days - 1), asof)
    s = qty_by_date.copy()
    s.index = pd.to_datetime(s.index)
    return float(s.reindex(idx).fillna(0).sum()) / days


def days_of_stock(stock, avg7):
    """재고소진 예상일 = 현재재고 / 7일 평균 판매량. 판매 0이면 None('판매없음')."""
    if not avg7 or avg7 <= 0:
        return None
    return stock / avg7


def reorder_qty(avg7, stock, target_days: int = 14) -> int:
    """발주 권장수량 = max(0, 7일평균 × 목표재고일수 − 현재재고), 올림."""
    return int(max(0, math.ceil(round(avg7 * target_days - stock, 6))))


def stock_value(stock, unit_cost):
    return stock * unit_cost


def soldout_days(soldout_flags: pd.Series) -> int:
    return int((soldout_flags.astype(int) > 0).sum())


def consumer_price(price, discount=0):
    return (price or 0) - (discount or 0)


def contribution_per_unit(supply_cost, unit_cost):
    """개당 공헌이익 = 매입원가(공급가) − 원가."""
    return supply_cost - unit_cost


def breakeven_roas(supply_cost, unit_cost, price, discount=0):
    """손익분기 ROAS = 1 / 마진율. 마진율 = 개당 공헌이익 / 소비자가 (광고 전환매출과 같은 기준).
    마진이 0 이하이거나 가격이 없으면 None."""
    cp = consumer_price(price, discount)
    if cp <= 0:
        return None
    margin = contribution_per_unit(supply_cost, unit_cost) / cp
    return None if margin <= 0 else 1 / margin


def signal(days_left, soldout: bool, orderable_ok: bool, red=7, yellow=14) -> str:
    if soldout or not orderable_ok:
        return "🔴"
    if days_left is None:
        return "🟢"
    if days_left <= red:
        return "🔴"
    if days_left <= yellow:
        return "🟡"
    return "🟢"


def trial_qty_by_date_sku(trials: pd.DataFrame) -> pd.DataFrame:
    if trials is None or trials.empty:
        return pd.DataFrame(columns=["date", "sku_id", "trial_qty"])
    return (trials.groupby(["date", "sku_id"], as_index=False)["qty"].sum()
            .rename(columns={"qty": "trial_qty"}))


def daily_totals(daily: pd.DataFrame, master: pd.DataFrame, trials: pd.DataFrame | None = None,
                 exclude_trial: bool = False) -> pd.DataFrame:
    """날짜별 판매량/공급가매출/소비자가매출. exclude_trial=True면 체험단 수량을 뺀 '순수 판매'."""
    cols = ["date", "qty", "supply_rev", "consumer_rev"]
    if daily.empty:
        return pd.DataFrame(columns=cols)
    d = daily[["date", "sku_id", "outbound", "supply_cost"]].copy()
    if exclude_trial:
        t = trial_qty_by_date_sku(trials)
        d = d.merge(t, on=["date", "sku_id"], how="left")
        d["trial_qty"] = d["trial_qty"].fillna(0)
        d["outbound"] = (d["outbound"] - d["trial_qty"]).clip(lower=0)
    price = master.set_index("SKU ID").apply(lambda r: consumer_price(r["판매가"], r["할인"]), axis=1)
    d["consumer_price"] = d["sku_id"].map(price).fillna(0)
    d["supply_rev"] = d["outbound"] * d["supply_cost"]
    d["consumer_rev"] = d["outbound"] * d["consumer_price"]
    g = d.groupby("date", as_index=False).agg(qty=("outbound", "sum"), supply_rev=("supply_rev", "sum"),
                                                consumer_rev=("consumer_rev", "sum"))
    return g[cols]


def sku_table(daily: pd.DataFrame, master: pd.DataFrame, asof, cfg: dict) -> pd.DataFrame:
    """SKU별 현황(기존 '판매현황' 시트 대체). asof 이전 데이터만 사용."""
    asof = pd.Timestamp(asof)
    d = daily[pd.to_datetime(daily["date"]) <= asof]
    ids = list(dict.fromkeys(list(master["SKU ID"]) + list(d["sku_id"].unique())))
    mi = master.set_index("SKU ID")
    rows = []
    for sku in ids:
        s = d[d["sku_id"] == sku].sort_values("date")
        qty = s.set_index("date")["outbound"] if len(s) else pd.Series(dtype=float)
        last = s.iloc[-1] if len(s) else None
        avg7 = seven_day_avg(qty, asof, 7) if len(s) else 0.0
        prev7 = seven_day_avg(qty, asof - timedelta(days=7), 7) if len(s) else 0.0
        stock = int(last["stock"]) if last is not None else 0
        dl = days_of_stock(stock, avg7)
        name = mi["품목"].get(sku, "") if sku in mi.index else ""
        ok = last is None or str(last["orderable"]).strip() in ("발주가능", "", "nan", "None")
        sold = bool(last["soldout"]) if last is not None else False
        sup = int(last["supply_cost"]) if last is not None else 0
        unit_cost = float(mi["원가"].get(sku, 0)) if sku in mi.index else 0.0
        rows.append({
            "sku_id": sku,
            "품목": name or (last["sku_name"] if last is not None else sku),
            "sku_name": last["sku_name"] if last is not None else "",
            "현재재고": stock,
            "전일판매": seven_day_avg(qty, asof, 1) if len(s) else 0,
            "7일판매": int(round(avg7 * 7)),
            "30일판매": int(round(seven_day_avg(qty, asof, 30) * 30)) if len(s) else 0,
            "7일평균": avg7,
            "직전7일평균": prev7,
            "7일평균_증감": pct_change(avg7, prev7),
            "소진예상일": dl,
            "발주권장": reorder_qty(avg7, stock, cfg["target_stock_days"]),
            "품절": sold,
            "발주가능": ok,
            "발주가능상태": str(last["orderable"]) if last is not None else "",
            "재고금액": stock_value(stock, unit_cost),
            "공급가": sup,
            "최근데이터일": last["date"] if last is not None else None,
            "운영중": (mi["운영중"].get(sku, "Y") == "Y") if sku in mi.index else True,
            "신호": signal(dl, sold, ok, cfg["stock_red_days"], cfg["stock_yellow_days"]),
        })
    return pd.DataFrame(rows)


def supply_price_changes(daily: pd.DataFrame) -> pd.DataFrame:
    """매입원가(공급가) 변경 이력: SKU별로 값이 바뀐 첫 날짜."""
    if daily.empty:
        return pd.DataFrame(columns=["sku_id", "date", "supply_cost", "prev"])
    d = daily.sort_values(["sku_id", "date"])[["sku_id", "date", "supply_cost"]].copy()
    d["prev"] = d.groupby("sku_id")["supply_cost"].shift()
    return d[d["prev"].notna() & (d["prev"] != d["supply_cost"])].reset_index(drop=True)


# ---------------------------------------------------------------- 광고
def prep_ad(ad: pd.DataFrame, window: int, ad_map: pd.DataFrame, master: pd.DataFrame,
            default_be: float = 4.0, supply_by_sku: dict | None = None,
            wing_target: float | None = None) -> pd.DataFrame:
    """기준 어트리뷰션(1/14일) 컬럼을 표준 이름으로 만들고, 옵션→SKU/묶음수량/손익분기 ROAS 를 붙인다."""
    df = ad.copy()
    w = int(window)
    df["orders"] = df[f"orders_t_{w}"]
    df["qty"] = df[f"qty_t_{w}"]
    df["rev"] = df[f"rev_t_{w}"]
    df["orders_d"] = df[f"orders_d_{w}"]
    df["rev_d"] = df[f"rev_d_{w}"]
    df["rev_i"] = df[f"rev_i_{w}"]
    m = ad_map.drop_duplicates("광고옵션ID").set_index("광고옵션ID") if len(ad_map) else pd.DataFrame(
        columns=["SKU ID", "묶음수량"])
    sku = m["SKU ID"].to_dict() if len(m) else {}
    bun = m["묶음수량"].to_dict() if len(m) else {}
    df["exec_sku"] = df["ad_option_id"].map(sku).fillna("").replace({"nan": ""})
    df["exec_bundle"] = df["ad_option_id"].map(bun).fillna(1).astype(int)
    df["conv_sku"] = df["conv_option_id"].map(sku).fillna("").replace({"nan": ""})
    df["conv_bundle"] = df["conv_option_id"].map(bun).fillna(1).astype(int)
    df["is_halo"] = df["ad_option_id"] != df["conv_option_id"]
    be = sku_breakeven(master, supply_by_sku or {})
    df["be_roas"] = df["exec_sku"].map(be).fillna(default_be)
    if wing_target:   # 쿠팡윙(3P)은 마진 정보가 없어 손익분기 대신 목표 ROAS 를 기준선으로 쓴다
        df.loc[df["sale_type"] == "3P", "be_roas"] = wing_target
    df["kw_group"] = np.where(df["keyword"].isin(["-", ""]), "(비검색)", df["keyword"])
    return df


def sku_breakeven(master: pd.DataFrame, supply_by_sku: dict) -> dict:
    out = {}
    for _, r in master.iterrows():
        sup = supply_by_sku.get(str(r["SKU ID"]))
        if sup:
            b = breakeven_roas(sup, r["원가"], r["판매가"], r["할인"])
            if b:
                out[str(r["SKU ID"])] = b
    return out


def ad_summary(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """준비된(prep_ad) 광고 행을 by 기준으로 합산하고 CTR/CPC/CVR/ROAS/CPA 를 원천 숫자로 재계산."""
    if df.empty:
        cols = (by or []) + ["impressions", "clicks", "cost", "orders", "qty", "rev", "rev_d",
                             "rev_i", "ctr", "cpc", "cvr", "roas", "cpa", "be_roas"]
        return pd.DataFrame(columns=cols)
    d = df.copy()
    d["_be_cost"] = d["be_roas"] * d["cost"]
    key = by or ["_all"]
    if not by:
        d["_all"] = 1
    g = d.groupby(key, as_index=False).agg(
        impressions=("impressions", "sum"), clicks=("clicks", "sum"), cost=("cost", "sum"),
        orders=("orders", "sum"), qty=("qty", "sum"), rev=("rev", "sum"),
        rev_d=("rev_d", "sum"), rev_i=("rev_i", "sum"), orders_d=("orders_d", "sum"),
        _be_cost=("_be_cost", "sum"), be_mean=("be_roas", "mean"))
    g["ctr"] = [ctr(c, i) for c, i in zip(g["clicks"], g["impressions"])]
    g["cpc"] = [cpc(c, k) for c, k in zip(g["cost"], g["clicks"])]
    g["cvr"] = [cvr(o, k) for o, k in zip(g["orders"], g["clicks"])]
    g["roas"] = [roas(r, c) for r, c in zip(g["rev"], g["cost"])]
    g["cpa"] = [cpa(c, o) for c, o in zip(g["cost"], g["orders"])]
    g["be_roas"] = [safe_div(b, c, m) for b, c, m in zip(g["_be_cost"], g["cost"], g["be_mean"])]
    g = g.drop(columns=["_be_cost", "be_mean"])
    return g.drop(columns=["_all"], errors="ignore")


def direct_share(rev_d, rev_total) -> float:
    return safe_div(rev_d, rev_total)


def classify_keyword(cost, orders, clicks, impressions, roas_v, be, cfg: dict) -> str:
    if cost >= cfg["exclude_min_cost"] and orders == 0:
        return "제외 후보"
    if clicks < cfg["min_clicks"]:
        return "데이터 부족"
    if roas_v >= be:
        return "입찰 상향 후보" if impressions <= cfg["bid_up_max_impressions"] else "효자"
    return "관찰/개선"


def classify_keywords(kw: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    kw = kw.copy()
    kw["분류"] = [classify_keyword(r.cost, r.orders, r.clicks, r.impressions, r.roas, r.be_roas, cfg)
                for r in kw.itertuples()]
    return kw


def quadrant(cost, roas_v, be, cost_split) -> str:
    hi_cost, hi_roas = cost >= cost_split, roas_v >= be
    if hi_cost and hi_roas:
        return "핵심 유지"
    if not hi_cost and hi_roas:
        return "확대"
    if hi_cost and not hi_roas:
        return "축소·제외"
    return "관찰"


def keyword_group_tags(keyword: str, groups: dict, brand: str) -> dict:
    """키워드 그룹핑: 브랜드/일반, 영문/한글, 상품군(settings.keyword_groups 규칙)."""
    k = str(keyword).lower()
    has_hangul = any("가" <= ch <= "힣" for ch in k)
    prod = "기타"
    for name, words in (groups or {}).items():
        if any(str(w).lower() in k for w in words):
            prod = name
            break
    return {"브랜드": "브랜드" if brand.lower() in k else "일반",
            "언어": "한글" if has_hangul else "영문", "상품군": prod}


# ---------------------------------------------------------------- 통합 (판매 × 광고)
def integrated_by_sku(daily: pd.DataFrame, master: pd.DataFrame, ad_p: pd.DataFrame,
                      trials: pd.DataFrame, start, end, exclude_trial: bool = False) -> pd.DataFrame:
    """기간 [start,end] 의 SKU별 통합 손익.

    ad_p : prep_ad 를 거친 Retail 광고 행 (이미 같은 기간으로 필터됨)
    - 광고 기여 판매수량 = 전환 상품(conv)이 매핑된 SKU 의 광고 총 판매수량 × 묶음수량
    - 오가닉(추정)       = 전체 출고 − 광고 기여 − 체험단 수량 (0 미만은 0)
    - TACoS              = 광고비 / 소비자가매출
    - 순이익             = 공헌이익 × 판매량 − 광고비 − 체험단 비용
    """
    s, e = str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date())
    d = daily[(daily["date"] >= s) & (daily["date"] <= e)]
    t = trials[(trials["date"] >= s) & (trials["date"] <= e)] if trials is not None and len(trials) else pd.DataFrame(
        columns=["sku_id", "qty", "unit_price", "agency_fee"])
    mi = master.set_index("SKU ID")
    ids = list(dict.fromkeys(list(master["SKU ID"]) + list(d["sku_id"].unique())))
    rows = []
    for sku in ids:
        ds = d[d["sku_id"] == sku]
        qty = int(ds["outbound"].sum())
        supply_rev = float((ds["outbound"] * ds["supply_cost"]).sum())
        last_supply = int(ds["supply_cost"].iloc[-1]) if len(ds) else 0
        m = mi.loc[sku] if sku in mi.index else None
        price = consumer_price(m["판매가"], m["할인"]) if m is not None else 0
        unit_cost = float(m["원가"]) if m is not None else 0.0
        ts = t[t["sku_id"] == sku]
        t_qty = int(ts["qty"].sum()) if len(ts) else 0
        t_cost = float((ts["qty"] * (ts["unit_price"] + ts["agency_fee"])).sum()) if len(ts) else 0.0
        ad_cost = float(ad_p.loc[ad_p["exec_sku"] == sku, "cost"].sum()) if len(ad_p) else 0.0
        conv = ad_p[ad_p["conv_sku"] == sku] if len(ad_p) else ad_p
        ad_qty = float((conv["qty"] * conv["conv_bundle"]).sum()) if len(conv) else 0.0
        base_qty = max(0, qty - t_qty) if exclude_trial else qty
        organic = max(0.0, qty - ad_qty - t_qty)
        consumer_rev = base_qty * price
        contrib = supply_rev - unit_cost * qty
        rows.append({
            "sku_id": sku, "품목": (m["품목"] if m is not None else sku), "판매량": base_qty,
            "광고기여판매": ad_qty, "오가닉추정": organic, "체험단수량": t_qty,
            "공급가매출": supply_rev, "소비자가매출": consumer_rev,
            "원가합계": unit_cost * qty, "광고비": ad_cost, "체험단비": t_cost,
            "공헌이익": contrib, "순이익": contrib - ad_cost - t_cost,
            "TACoS": safe_div(ad_cost, consumer_rev, None),
            "광고의존도": safe_div(ad_qty, base_qty, None),
            "손익분기ROAS": breakeven_roas(last_supply, unit_cost, m["판매가"], m["할인"]) if m is not None and last_supply else None,
        })
    return pd.DataFrame(rows)


def unmapped_options(ad_p: pd.DataFrame, brand: str) -> pd.DataFrame:
    """브랜드 상품인데 매핑표에 없는(SKU 미확정) 광고/전환 옵션."""
    if ad_p.empty:
        return pd.DataFrame(columns=["옵션ID", "상품명", "광고비"])
    a = ad_p[(ad_p["exec_sku"] == "") & ad_p["ad_product"].str.contains(brand, regex=False)][
        ["ad_option_id", "ad_product", "cost"]].rename(
        columns={"ad_option_id": "옵션ID", "ad_product": "상품명", "cost": "광고비"})
    b = ad_p[(ad_p["conv_sku"] == "") & ad_p["conv_product"].str.contains(brand, regex=False)][
        ["conv_option_id", "conv_product"]].rename(columns={"conv_option_id": "옵션ID", "conv_product": "상품명"})
    b["광고비"] = 0.0
    return pd.concat([a, b]).groupby(["옵션ID", "상품명"], as_index=False)["광고비"].sum()


def trial_effect(daily: pd.DataFrame, sku_id: str, date, qty: int, trial_cost: float,
                 unit_contribution: float, last_data_date) -> dict:
    """체험단 전 7일 평균 vs 후 7일 평균(체험단 수량 제외) 과 투자 대비 회수 추정."""
    d0 = pd.Timestamp(date)
    s = daily[daily["sku_id"] == sku_id].copy()
    s.index = pd.to_datetime(s["date"])
    q = s["outbound"]
    before_idx = pd.date_range(d0 - timedelta(days=7), d0 - timedelta(days=1))
    after_idx = pd.date_range(d0, d0 + timedelta(days=6))
    before = float(q.reindex(before_idx).fillna(0).sum()) / 7
    after_sum = max(0.0, float(q.reindex(after_idx).fillna(0).sum()) - qty)
    after = after_sum / 7
    complete = pd.Timestamp(last_data_date) >= after_idx[-1]
    uplift_units = max(0.0, (after - before) * 7)
    recovered = uplift_units * unit_contribution
    return {"전7일평균": before, "후7일평균": after, "증감": pct_change(after, before),
            "추가판매(7일)": uplift_units, "회수추정액": recovered,
            "회수율": safe_div(recovered, trial_cost, None), "후기간완료": bool(complete)}
