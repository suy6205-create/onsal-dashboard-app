"""📦 판매·재고"""
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import metrics as M
from src import ui
from src.export import to_excel_bytes

cfg = ui.setup("판매·재고", "📦")
d = ui.load_all(cfg)
ui.no_data_stop(d)
daily, master, trials = d["daily"], d["master"], d["trials"]
dates = sorted(daily["date"].unique())
asof_s = st.sidebar.selectbox("기준일", dates[::-1])
asof = pd.Timestamp(asof_s)
exclude = st.sidebar.toggle("체험단 제외 기준", value=False)
sku = M.sku_table(daily, master, asof, cfg)
op = sku[sku["운영중"]]

# 한 줄 요약
low = op[op["소진예상일"].notna()].sort_values("소진예상일")
if len(low) and low.iloc[0]["소진예상일"] <= cfg["stock_yellow_days"]:
    r = low.iloc[0]
    ui.headline([f"{r['품목']} 재고 소진까지 {r['소진예상일']:.0f}일 — 발주 필요 (권장 {r['발주권장']:,}개)"])
else:
    ui.headline(["모든 운영중 SKU의 재고가 안전 범위입니다."])

t_status, t_heat, t_month, t_order = st.tabs(["SKU 현황 · 상세", "일자별 판매 히트맵", "월별 매출 분석", "발주 요청 리스트"])

# ------------------------------------------------------------ SKU 현황
with t_status:
    show = pd.DataFrame({
        "신호": sku["신호"], "품목": sku["품목"], "현재재고": sku["현재재고"], "전일판매": sku["전일판매"].astype(int),
        "7일판매": sku["7일판매"], "30일판매": sku["30일판매"], "7일평균": sku["7일평균"].round(2),
        "소진예상일": sku["소진예상일"].apply(lambda v: "판매없음" if v is None or pd.isna(v) else f"{v:.1f}일"),
        "발주권장": sku["발주권장"], "품절": sku["품절"].map({True: "품절", False: ""}),
        "재고금액": sku["재고금액"].apply(ui.won),
    })
    st.caption("🔴 위험 · 🟡 주의 · 🟢 양호 — 기준: 재고소진 예상일 "
               f"{cfg['stock_red_days']}일 이하=🔴, {cfg['stock_yellow_days']}일 이하=🟡 (설정에서 변경). "
               "행을 클릭하면 아래에 SKU 상세가 표시됩니다.")
    ev = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun",
                      selection_mode="single-row", column_config={
                          "7일평균": st.column_config.NumberColumn(help="최근 7일 출고합 ÷ 7 (데이터 없는 날은 0)"),
                          "소진예상일": st.column_config.TextColumn(help="현재재고 ÷ 7일 평균 판매량"),
                          "발주권장": st.column_config.NumberColumn(
                              help=f"max(0, 7일평균 × 목표재고일수({cfg['target_stock_days']}일) − 현재재고)"),
                          "재고금액": st.column_config.TextColumn(help="현재재고 × 원가(상품 마스터)")})
    sel = ev.selection.rows
    pick = sku.iloc[sel[0]] if sel else sku.iloc[0]
    st.subheader(f"🔎 {pick['품목']} 상세")
    s = daily[daily["sku_id"] == pick["sku_id"]].copy()
    if s.empty:
        st.info("이 SKU의 판매 데이터가 없습니다.")
    else:
        s["dt"] = pd.to_datetime(s["date"])
        fig = go.Figure()
        fig.add_bar(x=s["dt"], y=s["outbound"], name="판매(출고)", marker_color="#4C78A8",
                    hovertemplate="%{x|%m/%d} 판매 %{y:,}개<extra></extra>")
        fig.add_scatter(x=s["dt"], y=s["stock"], name="현재재고", yaxis="y2", mode="lines",
                        line=dict(color="#54A24B"), hovertemplate="%{x|%m/%d} 재고 %{y:,}개<extra></extra>")
        inb = s[s["inbound"] > 0]
        if len(inb):
            fig.add_scatter(x=inb["dt"], y=inb["stock"], yaxis="y2", mode="markers", name="입고 이벤트",
                            marker=dict(symbol="triangle-up", size=13, color="#F58518"), text=inb["inbound"],
                            hovertemplate="%{x|%m/%d} 입고 %{text:,}개<extra></extra>")
        fig.update_layout(yaxis=dict(title="판매(개)"), yaxis2=dict(title="재고(개)", overlaying="y", side="right", showgrid=False))
        ui.show(fig, 360)
        full = pd.date_range(s["dt"].min(), s["dt"].max())
        byday = s.set_index("dt")["outbound"].reindex(full).fillna(0)
        wd = byday.groupby(byday.index.dayofweek).mean().reindex(range(7)).fillna(0)
        fig2 = go.Figure(go.Bar(x=list("월화수목금토일"), y=wd.values, marker_color="#72B7B2",
                                hovertemplate="%{x}요일 평균 %{y:.2f}개/일<extra></extra>"))
        fig2.update_layout(title="요일별 평균 판매 (데이터 없는 날은 0)", yaxis_title="개/일")
        ui.show(fig2, 280)
        ch = M.supply_price_changes(s)
        if len(ch):
            st.caption("매입원가(공급가) 변경 이력: " + " · ".join(
                f"{r.date} {int(r.prev):,}→{int(r.supply_cost):,}원" for r in ch.itertuples()))

# ------------------------------------------------------------ 히트맵
with t_heat:
    months = sorted({x[:7] for x in dates}, reverse=True)
    mon = st.selectbox("월 선택", months)
    sub = daily[daily["date"].str.startswith(mon)]
    names = dict(zip(master["SKU ID"], master["품목"]))
    sub = sub.assign(품목=sub["sku_id"].map(names).fillna(sub["sku_name"]))
    days = pd.date_range(f"{mon}-01", periods=pd.Period(mon).days_in_month)
    pv = sub.pivot_table(index="품목", columns="date", values="outbound", aggfunc="sum")
    pv = pv.reindex(columns=days.strftime("%Y-%m-%d"))
    z = pv.values
    fig = go.Figure(go.Heatmap(
        z=z, x=[x[8:] for x in pv.columns], y=list(pv.index), colorscale="Blues", xgap=2, ygap=2,
        text=[[("" if pd.isna(v) else f"{v:.0f}") for v in row] for row in z], texttemplate="%{text}",
        hovertemplate="%{y}<br>" + mon + "-%{x}<br>출고 %{z:,}개<extra></extra>", colorbar=dict(title="출고")))
    if len(trials):
        for tr in trials[trials["date"].str.startswith(mon)].itertuples():
            if names.get(tr.sku_id) in list(pv.index):
                xi, yi = int(tr.date[8:]) - 1, list(pv.index).index(names[tr.sku_id])
                fig.add_shape(type="rect", x0=xi - .5, x1=xi + .5, y0=yi - .5, y1=yi + .5,
                              line=dict(color="#F58518", width=3))
    fig.update_layout(xaxis=dict(title="일", dtick=1), yaxis=dict(autorange="reversed"))
    ui.show(fig, max(220, 90 * len(pv) + 120))
    st.caption("주황 테두리 = 체험단 진행일. 빈 칸 = 해당일 데이터 없음(판매 0으로 계산).")

# ------------------------------------------------------------ 월별 매출
with t_month:
    dd = daily.copy()
    dd["월"] = dd["date"].str[:7]
    price = master.set_index("SKU ID").apply(lambda r: M.consumer_price(r["판매가"], r["할인"]), axis=1)
    dd["소비자가"] = dd["sku_id"].map(price).fillna(0)
    if exclude:
        tq = M.trial_qty_by_date_sku(trials)
        dd = dd.merge(tq, on=["date", "sku_id"], how="left").fillna({"trial_qty": 0})
        dd["outbound"] = (dd["outbound"] - dd["trial_qty"]).clip(lower=0)
    dd["공급가매출"] = dd["outbound"] * dd["supply_cost"]
    dd["소비자가매출"] = dd["outbound"] * dd["소비자가"]
    names = dict(zip(master["SKU ID"], master["품목"]))
    dd["품목"] = dd["sku_id"].map(names).fillna(dd["sku_name"])
    g = dd.groupby(["월", "품목"], as_index=False).agg(판매수량=("outbound", "sum"), 공급가매출=("공급가매출", "sum"),
                                                     소비자가매출=("소비자가매출", "sum"))
    tot = g.groupby("월", as_index=False)[["판매수량", "공급가매출", "소비자가매출"]].sum().assign(품목="전체")
    g = pd.concat([g, tot]).sort_values(["품목", "월"])
    g["전월대비"] = g.groupby("품목")["판매수량"].pct_change()
    # 월 내 데이터 일수 (부분 월 경고)
    nd = dd.groupby("월")["date"].nunique()
    g["데이터일수"] = g["월"].map(nd)
    out = g.sort_values(["월", "품목"], ascending=[False, True]).copy()
    out["공급가매출"] = out["공급가매출"].apply(ui.won)
    out["소비자가매출"] = out["소비자가매출"].apply(ui.won)
    out["전월대비"] = out["전월대비"].apply(lambda v: "-" if pd.isna(v) or v in (float("inf"),) else f"{v*100:+.1f}%")
    st.dataframe(out[["월", "품목", "판매수량", "공급가매출", "소비자가매출", "전월대비", "데이터일수"]],
                 hide_index=True, width="stretch",
                 column_config={"공급가매출": st.column_config.TextColumn(help="판매량 × 매입원가(쿠팡이 지급하는 공급가, VAT 제외)"),
                                "소비자가매출": st.column_config.TextColumn(help="판매량 × (판매가−할인). 광고 전환매출과 같은 기준"),
                                "전월대비": st.column_config.TextColumn(help="판매수량 기준. 데이터일수가 적은 달은 비교에 주의")})
    st.caption("※ 데이터 일수가 달 일수보다 적으면 전월 대비가 왜곡될 수 있습니다.")

# ------------------------------------------------------------ 발주 요청
with t_order:
    need = op[op["발주권장"] > 0].sort_values("소진예상일")
    if need.empty:
        st.success("현재 발주가 필요한 SKU가 없습니다.")
    else:
        lst = pd.DataFrame({
            "SKU ID": need["sku_id"], "품목": need["품목"], "SKU 명": need["sku_name"], "현재재고": need["현재재고"],
            "7일평균 판매": need["7일평균"].round(2),
            "소진예상(일)": need["소진예상일"].apply(lambda v: None if pd.isna(v) else round(v, 1)),
            "발주 권장수량": need["발주권장"]})
        st.dataframe(lst, hide_index=True, width="stretch")
        st.download_button("⬇️ 발주 요청 리스트 엑셀 다운로드", to_excel_bytes({"발주요청": lst}),
                           file_name=f"발주요청_{asof_s}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption(f"발주 권장수량 = max(0, 7일평균 × 목표재고일수 {cfg['target_stock_days']}일 − 현재재고), 올림")
