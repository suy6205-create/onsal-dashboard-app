"""🏠 홈 — 오늘의 요약 (MD가 매일 처음 보는 화면)"""
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import actions, ui
from src import metrics as M

cfg = ui.setup("오늘의 요약", "🏠")
d = ui.load_all(cfg)
ui.no_data_stop(d)
daily, ad, master, trials = d["daily"], d["ad"], d["master"], d["trials"]

st.page_link("pages/9_데이터_업로드_설정.py", label="매일 파일 업로드 (판매 CSV · 광고 XLSX)", icon="📤")
# ---- 기준일 · 데이터 최신성
dates = sorted(daily["date"].unique())
c1, c2 = st.columns([1, 3])
asof_s = c1.selectbox("기준일", dates[::-1], index=0, help="기본값은 가장 최근 판매 데이터 날짜")
asof = pd.Timestamp(asof_s)
exclude = st.sidebar.toggle("체험단 제외 기준(순수 판매)", value=False,
                            help="체험단 구매도 출고수량에 포함된다고 가정하고 그 수량을 뺀 판매를 봅니다.")
last_ad = ad["period_end"].max() if len(ad) else None
c2.caption(f"데이터 최신성 · 판매 {dates[-1][5:].replace('-', '/')}까지"
           + (f", 광고 {last_ad[5:].replace('-', '/')}까지 반영" if last_ad else ", 광고 데이터 없음"))
if last_ad and last_ad < dates[-1]:
    c2.caption(f"⚠️ 광고 데이터가 판매보다 {(pd.Timestamp(dates[-1]) - pd.Timestamp(last_ad)).days}일 늦습니다. "
               "광고 리포트도 최신으로 올려주세요.")

# ---- 광고 컨텍스트: 기준일 기준 최근 7일 일자 데이터가 있으면 그것, 없으면 가장 최근 기간 파일
w = int(cfg["attribution_days"])
sup = ui.supply_by_sku(daily)
ad_ctx_label, ad_ctx = "", pd.DataFrame()
if len(ad):
    rd = ad[(ad["is_daily"] == 1) & (ad["period_start"] <= asof_s) &
            (ad["period_start"] >= str((asof - timedelta(days=6)).date()))]
    if len(rd):
        ad_ctx, ad_ctx_label = rd, f"최근 7일 일자 데이터 ({ui.period_label(rd.period_start.min(), rd.period_end.max())})"
    else:
        per = ad[ad["period_end"] <= asof_s].sort_values("period_end")
        if len(per):
            last = per.iloc[-1]
            ad_ctx = per[(per["period_start"] == last["period_start"]) & (per["period_end"] == last["period_end"])]
            ad_ctx_label = f"가장 최근 광고 기간 ({ui.period_label(last['period_start'], last['period_end'])})"
ad_p = M.prep_ad(ad_ctx[ad_ctx["sale_type"] == "Retail"], w, d["map"], master,
                 cfg["default_breakeven_roas"], sup) if len(ad_ctx) else pd.DataFrame()

# ---- 한 줄 요약
sku_tbl = M.sku_table(daily, master, asof, cfg)
ui.headline(actions.build_headline(sku_tbl, ad_p, cfg))
need_price = master[(master["판매가"] <= 0) | (master["원가"] <= 0)]
if len(need_price):
    st.warning(f"가격 미입력 SKU {len(need_price)}개: {', '.join(need_price['품목'])} — 상품 마스터에서 입력하세요.")

# ---- KPI 6개
tot = M.daily_totals(daily, master, trials, exclude).set_index("date")


def at(col, days_back=0):
    k = str((asof - timedelta(days=days_back)).date())
    return float(tot[col].get(k, 0)) if len(tot) else 0.0


def ad_day(day: pd.Timestamp):
    r = ad[(ad["is_daily"] == 1) & (ad["period_start"] == str(day.date())) & (ad["sale_type"] == "Retail")]
    if r.empty:
        return None
    s = M.ad_summary(M.prep_ad(r, w, d["map"], master, cfg["default_breakeven_roas"], sup)).iloc[0]
    return s


cur_ad, prev_ad, wk_ad = ad_day(asof), ad_day(asof - timedelta(days=1)), ad_day(asof - timedelta(days=7))
k = st.columns(6)
ui.kpi(k[0], "판매량", ui.num(at("qty")) + "개", at("qty"), at("qty", 1), at("qty", 7),
       "기준일 Σ출고수량 (체험단 제외 토글 시 체험단 수량 차감)")
ui.kpi(k[1], "공급가매출", ui.won(at("supply_rev")), at("supply_rev"), at("supply_rev", 1), at("supply_rev", 7),
       "판매량 × 매입원가(쿠팡이 우리에게 지급하는 공급가, VAT 제외)")
if cur_ad is not None:
    cons = at("consumer_rev")
    ui.kpi(k[2], "광고비", ui.won(cur_ad["cost"]), cur_ad["cost"], None if prev_ad is None else prev_ad["cost"],
           None if wk_ad is None else wk_ad["cost"], "Retail 광고 기준일 광고비", inverse=True)
    ui.kpi(k[3], f"ROAS({w}일)", ui.mult(cur_ad["roas"]), cur_ad["roas"],
           None if prev_ad is None else prev_ad["roas"], None if wk_ad is None else wk_ad["roas"],
           "광고 전환매출액 ÷ 광고비 (원천 숫자로 재계산). 손익분기 ROAS 이상이어야 이익")
    ui.kpi(k[4], "TACoS", ui.pct(M.safe_div(cur_ad["cost"], cons, None)),
           M.safe_div(cur_ad["cost"], cons, None), M.safe_div(prev_ad["cost"], at("consumer_rev", 1), None) if prev_ad is not None else None,
           M.safe_div(wk_ad["cost"], at("consumer_rev", 7), None) if wk_ad is not None else None,
           "광고비 ÷ 소비자가매출 (판매량×(판매가−할인)). 전체 매출 대비 광고비 비중", inverse=True)
elif len(ad_p):
    t = M.ad_summary(ad_p).iloc[0]
    s0, e0 = ad_ctx.period_start.min(), ad_ctx.period_end.max()
    cons = float(M.daily_totals(daily[(daily["date"] >= s0) & (daily["date"] <= e0)], master, trials,
                                exclude)["consumer_rev"].sum())
    ui.card(k[2], "광고비(기간)", ui.won(t["cost"]), f"{ad_ctx_label} 합계. 기준일 일자 데이터가 없어 기간 합계를 표시합니다.")
    ui.card(k[3], f"ROAS({w}일)", ui.mult(t["roas"]), f"{ad_ctx_label}. 광고 전환매출액 ÷ 광고비")
    ui.card(k[4], "TACoS(기간)", ui.pct(M.safe_div(t["cost"], cons, None)),
            "기간 광고비 ÷ 같은 기간 소비자가매출", inverse=True)
else:
    for i, n in ((2, "광고비"), (3, "ROAS"), (4, "TACoS")):
        ui.card(k[i], n, "-", "광고 데이터가 없습니다")
red_n = int(((sku_tbl["운영중"]) & (sku_tbl["품절"] | ~sku_tbl["발주가능"] |
                                     (sku_tbl["소진예상일"] <= cfg["stock_red_days"]))).sum())
ui.card(k[5], "품절·발주필요 SKU", f"{red_n}개",
        f"품절이거나 발주불가이거나 재고소진 예상일이 {cfg['stock_red_days']}일 이내인 운영중 SKU 수", inverse=True)
if ad_ctx_label:
    st.caption(f"광고 기준 구간: {ad_ctx_label} · Retail · {w}일 전환")

# ---- 오늘의 액션 리스트
st.subheader("✅ 오늘의 액션 리스트")
acts = actions.build_actions(sku_tbl, ad_p, cfg)
if not acts:
    st.success("🟢 오늘 처리할 긴급 액션이 없습니다.")
for a in acts:
    box = {"🔴": st.error, "🟡": st.warning, "🟢": st.success}[a["level"]]
    box(f"**{a['level']} {a['title']}**  \n{a['detail']}")

# ---- 로켓 vs 윙 광고 비교
st.subheader("🚀 로켓배송 vs 🪽 쿠팡윙 광고 비교")
if len(ad_ctx):
    both = M.prep_ad(ad_ctx, w, d["map"], master, cfg["default_breakeven_roas"], sup, cfg.get("wing_target_roas"))
    cmp = M.ad_summary(both, ["sale_type"])
    if len(cmp) and cmp["cost"].sum() > 0:
        cmp["구분"] = cmp["sale_type"].map(ui.STYPE_LABEL)
        cmp["기준 ROAS"] = cmp["be_roas"]
        cmp["광고비 비중"] = cmp["cost"] / cmp["cost"].sum()
        cmp["판정"] = ["✅ 양호" if r >= b else "⚠️ 기준 미달" for r, b in zip(cmp["roas"], cmp["be_roas"])]
        st.caption(f"{ad_ctx_label} · {w}일 전환 기준. 기준 ROAS: 로켓=마진 기반 손익분기, 윙=목표 ROAS "
                   f"({ui.mult(cfg.get('wing_target_roas'))}, 설정에서 변경)")
        st.dataframe(cmp[["구분", "cost", "광고비 비중", "orders", "rev", "roas", "기준 ROAS", "판정"]]
                     .rename(columns={"cost": "광고비", "orders": "주문", "rev": "전환매출", "roas": "ROAS"}),
                     hide_index=True, width="stretch", column_config={
                         "광고비": st.column_config.NumberColumn(format="₩%d"), "전환매출": st.column_config.NumberColumn(format="₩%d"),
                         "CPC": st.column_config.NumberColumn(format="₩%d"), "CVR": st.column_config.NumberColumn(format="percent"),
                         "ROAS": st.column_config.NumberColumn(format="percent"), "기준 ROAS": st.column_config.NumberColumn(format="percent"),
                         "광고비 비중": st.column_config.NumberColumn(format="percent")})
        fig = go.Figure()
        fig.add_bar(x=cmp["구분"], y=cmp["cost"], name="광고비", marker_color="#E45756",
                    hovertemplate="%{x}<br>광고비 ₩%{y:,.0f}<extra></extra>")
        fig.add_bar(x=cmp["구분"], y=cmp["rev"], name="전환매출", marker_color="#4C78A8",
                    hovertemplate="%{x}<br>전환매출 ₩%{y:,.0f}<extra></extra>")
        fig.update_layout(barmode="group", yaxis_title="₩")
        ui.show(fig, 260)
        st.caption("윙은 판매자배송 상품이라 로켓 재고·판매와 연결되지 않으며, 위 로켓 KPI·통합 손익에는 윙 광고비가 포함되지 않습니다. "
                   "자세한 내용은 메뉴의 '로켓 광고 성과' / '윙 광고 성과'에서 보세요.")
    else:
        st.info("비교할 광고비 데이터가 없습니다.")
else:
    st.info("광고 데이터가 없어 비교할 수 없습니다.")

# ---- 최근 30일 추이
st.subheader("📈 최근 30일 판매·광고비 추이")
idx = pd.date_range(asof - timedelta(days=29), asof)
q = tot["qty"].reindex(idx.strftime("%Y-%m-%d")).fillna(0) if len(tot) else pd.Series(0, index=idx.strftime("%Y-%m-%d"))
fig = go.Figure()
fig.add_bar(x=idx, y=q.values, name="판매량", marker_color="#4C78A8",
            hovertemplate="%{x|%m/%d}<br>판매량 %{y:,}개<extra></extra>")
daily_ad = ad[(ad["is_daily"] == 1) & (ad["sale_type"] == "Retail")].groupby("period_start")["cost"].sum() if len(ad) else pd.Series(dtype=float)
if len(daily_ad):
    s = daily_ad.reindex(idx.strftime("%Y-%m-%d"))
    fig.add_scatter(x=idx, y=s.values, name="광고비(일자)", yaxis="y2", mode="lines+markers",
                    line=dict(color="#E45756"), hovertemplate="%{x|%m/%d}<br>광고비 ₩%{y:,.0f}<extra></extra>")
_spans = [(r.period_start, r.period_end) for r in ad[ad["is_daily"] == 0][["period_start", "period_end"]].drop_duplicates().itertuples()] if len(ad) else []
for r in [type("P", (), {"period_start": x, "period_end": y}) for x, y in ui._drop_nested(_spans)[0]]:
    if pd.Timestamp(r.period_end) >= idx[0] and pd.Timestamp(r.period_start) <= idx[-1]:
        c = ad[(ad.period_start == r.period_start) & (ad.period_end == r.period_end) & (ad.sale_type == "Retail")]["cost"].sum()
        fig.add_vrect(x0=pd.Timestamp(r.period_start) - timedelta(hours=12), x1=pd.Timestamp(r.period_end) + timedelta(hours=12),
                      fillcolor="#E45756", opacity=0.08, line_width=0,
                      annotation_text=f"기간 광고비 ₩{c:,.0f}", annotation_position="top left", annotation_font_size=11)
if len(trials):
    tt = trials.groupby("date")["qty"].sum()
    tt = tt[(tt.index >= str(idx[0].date())) & (tt.index <= asof_s)]
    if len(tt):
        fig.add_scatter(x=pd.to_datetime(tt.index), y=[q.get(x, 0) for x in tt.index], mode="markers",
                        name="체험단 진행일", marker=dict(symbol="star", size=14, color="#F58518"),
                        text=[f"체험단 {v}개" for v in tt.values], hovertemplate="%{x|%m/%d} %{text}<extra></extra>")
fig.update_layout(yaxis=dict(title="판매량(개)"), yaxis2=dict(title="광고비(₩)", overlaying="y", side="right", showgrid=False))
ui.show(fig, 400)
st.caption("광고비 선은 '일자 데이터'만 표시합니다. 주간·월간 기간 파일은 붉은 음영 구간에 기간 합계로 표시됩니다.")
