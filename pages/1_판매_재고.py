"""📦 판매·재고"""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import config, db
from src import metrics as M
from src import ui
try:
    from src.purchase_order import build_po_xlsx, po_filename
    PO_IMPORT_ERROR = None
except Exception as _e:   # noqa: BLE001  (서버가 오류 내용을 가리므로 화면에 직접 보여준다)
    build_po_xlsx = po_filename = None
    PO_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

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

t_status, t_heat, t_month = st.tabs(["SKU 현황 · 발주서", "일자별 판매 히트맵", "월별 매출 분석"])

# ------------------------------------------------------------ SKU 현황
with t_status:
    base = pd.DataFrame({
        "신호": sku["신호"], "브랜드": sku["브랜드"], "품목": sku["품목"], "현재재고": sku["현재재고"],
        "전일판매": sku["전일판매"].astype(int), "7일판매": sku["7일판매"], "30일판매": sku["30일판매"],
        "7일평균": sku["7일평균"].round(2),
        "소진예상일": sku["소진예상일"].apply(lambda v: "판매없음" if v is None or pd.isna(v) else f"{v:.1f}일"),
        "발주권장": sku["발주권장"],
        "발주": False, "발주수량": 0, "기발주량": 0,
        "품절": [("품절" if s_ else ("당일 품절→입고됨" if r_ else "")) for s_, r_ in zip(sku["품절"], sku["당일품절후입고"])],
        "재고금액": sku["재고금액"].apply(ui.won),
    })
    st.caption("🔴 위험 · 🟡 주의 · 🟢 양호 — 기준: 재고소진 예상일 "
               f"{cfg['stock_red_days']}일 이하=🔴, {cfg['stock_yellow_days']}일 이하=🟡 (설정에서 변경). "
               "**발주할 상품은 '발주' 칸을 체크하고 '발주수량'을 입력**하세요. 아래에서 발주서를 만들 수 있습니다.")
    EDITABLE = ("발주", "발주수량", "기발주량")
    edited = st.data_editor(
        base, hide_index=True, width="stretch", key=f"po_editor_{asof_s}_{d.get('brand_sel', '전체')}",
        disabled=[c for c in base.columns if c not in EDITABLE],
        column_config={
            "7일평균": st.column_config.NumberColumn(help="최근 7일 출고합 ÷ 7 (데이터 없는 날은 0)"),
            "소진예상일": st.column_config.TextColumn(help="현재재고 ÷ 7일 평균 판매량"),
            "발주권장": st.column_config.NumberColumn(
                help=f"max(0, 7일평균 × 목표재고일수({cfg['target_stock_days']}일) − 현재재고). 참고용이며 발주서에는 입력한 발주수량이 들어갑니다."),
            "발주": st.column_config.CheckboxColumn("발주", help="체크한 상품만 발주서에 들어갑니다"),
            "발주수량": st.column_config.NumberColumn("발주수량", min_value=0, step=1, format="%d", help="발주서의 '발주 요청량'"),
            "기발주량": st.column_config.NumberColumn("기발주량", min_value=0, step=1, format="%d",
                                                  help="이미 발주해 둔 수량(오늘 ~ 차주 토요일까지). 없으면 0"),
            "재고금액": st.column_config.TextColumn(help="현재재고 × 원가(상품 마스터)")})

    # ---- 발주서 만들기 (사용자가 매번 만들던 '매뉴얼 발주요청' 엑셀과 같은 서식)
    st.subheader("📝 발주서 만들기")
    if PO_IMPORT_ERROR:
        st.error(f"발주서 기능을 불러오지 못했습니다 → {PO_IMPORT_ERROR}")
        st.stop()
    qty_in = pd.to_numeric(edited["발주수량"], errors="coerce").fillna(0).astype(int)
    prior_in = pd.to_numeric(edited["기발주량"], errors="coerce").fillna(0).astype(int)
    checked = edited["발주"].fillna(False).astype(bool)
    ok_idx = edited.index[checked & (qty_in > 0)]
    zero_checked = edited.loc[checked & (qty_in <= 0), "품목"].tolist()
    unchecked_qty = edited.loc[~checked & (qty_in > 0), "품목"].tolist()
    if zero_checked:
        st.warning("체크했지만 발주수량이 0이라 빠졌습니다: " + ", ".join(zero_checked))
    if unchecked_qty:
        st.info("발주수량은 적었지만 '발주'가 체크되지 않아 빠졌습니다: " + ", ".join(unchecked_qty))
    vid, vname = cfg.get("po_vendor_id", ""), cfg.get("po_vendor_name", "")
    if not (vid and vname):
        st.warning("발주서에 들어갈 **VENDOR ID / VENDOR NAME** 이 아직 없습니다. 한 번만 입력해 두면 계속 쓰입니다.")
        if ui.is_admin():
            with st.form("po_vendor_form"):
                f1, f2 = st.columns(2)
                nv1 = f1.text_input("VENDOR ID", vid)
                nv2 = f2.text_input("VENDOR NAME", vname)
                if st.form_submit_button("💾 저장", type="primary"):
                    config.save_settings({**cfg, "po_vendor_id": nv1.strip(), "po_vendor_name": nv2.strip()})
                    st.rerun()
        else:
            st.info("왼쪽 메뉴의 '관리자 로그인' 후 이 칸이 나타납니다. (또는 파일 업로드·설정 → 기준값 탭)")
    elif len(ok_idx) == 0:
        st.info("위 표에서 발주할 상품의 '발주'를 체크하고 '발주수량'을 입력하면 발주서를 내려받을 수 있습니다.")
    else:
        centers = db.read_sales_center()
        center_opts = sorted(centers["center"].dropna().unique()) if len(centers) else ["VF107"]
        c1, c2 = st.columns([1, 1])
        center = c1.selectbox("납품센터", center_opts, index=center_opts.index("VF107") if "VF107" in center_opts else 0)
        extra = c2.checkbox("추가 발주 (파일명 끝에 _추가)", value=False)
        rows, preview = [], []
        for i in ok_idx:
            r_ = sku.loc[i]
            nm = r_["sku_name"] or r_["품목"]
            rows.append({"sku_id": r_["sku_id"], "name": nm, "qty": int(qty_in[i]), "prior": int(prior_in[i]),
                         "stock": int(r_["현재재고"]), "avg7": float(r_["7일평균"])})
            tot = int(qty_in[i]) + int(prior_in[i]) + int(r_["현재재고"])
            preview.append({"SKU ID": r_["sku_id"], "스큐 이름": nm, "발주 요청량": int(qty_in[i]), "기발주량": int(prior_in[i]),
                            "쿠팡 현재고": int(r_["현재재고"]), "일평균판매량": round(float(r_["7일평균"]), 1),
                            "재고일수": (round(tot / r_["7일평균"], 1) if r_["7일평균"] > 0 else None), "납품센터": center})
        st.dataframe(pd.DataFrame(preview), hide_index=True, width="stretch")
        fname = po_filename(vname, center, date.today(), extra)
        st.download_button(f"⬇️ 발주서 다운로드 ({len(rows)}건)", build_po_xlsx(rows, vid, vname, center), file_name=fname,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        st.caption(f"파일명: {fname} · 재고일수 = (발주 요청량 + 기발주량 + 현재고) ÷ 일평균판매량, 납품일자 = 내일 (엑셀 수식). "
                   "두 브랜드를 한 파일에 담으려면 왼쪽 메뉴 브랜드를 '전체'로 두세요.")

    # ---- SKU 상세
    pick_name = st.selectbox("🔎 상세를 볼 상품", list(sku["품목"]), index=0)
    pick = sku[sku["품목"] == pick_name].iloc[0]
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
