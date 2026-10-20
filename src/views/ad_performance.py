"""광고 성과 화면 (로켓배송 광고, 일 단위 / 주 단위)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src import metrics as M
from src import ui


def _detail(cfg: dict, d: dict) -> None:
    f = ui.ad_filters(d, cfg, "adp")
    if f is None:
        return
    p = ui.apply_extra_filters(f["df"], "adp", keyword=True)
    w = f["window"]
    if p.empty:
        st.info("선택한 조건에 해당하는 광고 데이터가 없습니다.")
        return

    tot = M.ad_summary(p).iloc[0]
    st.caption(f"{f['label']} · 전환 {w}일 기준. "
               "비율 지표는 파일의 값이 아니라 원천 숫자(노출·클릭·광고비·주문·전환매출)로 다시 계산합니다.")

    # ---- 한 줄 요약
    lines = []
    if p["cost"].sum() > 0:
        pl = M.ad_summary(p, ["placement_group"]).set_index("placement_group")
        pl = pl[pl["cost"] > 0].assign(gap=lambda x: x["cost"] / x["cost"].sum() - x["rev"] / max(x["rev"].sum(), 1))
        worst = pl.sort_values("gap", ascending=False)
        if len(worst) and worst["gap"].iloc[0] > 0.1:
            n = worst.index[0]
            lines.append(f"'{n}' 지면이 광고비의 {worst.loc[n, 'cost'] / pl['cost'].sum() * 100:.0f}%를 쓰지만 "
                         f"전환매출은 {worst.loc[n, 'rev'] / max(pl['rev'].sum(), 1) * 100:.0f}%뿐입니다")
        lines.append(f"ROAS {ui.mult(tot['roas'])} — 손익분기 약 {ui.mult(tot['be_roas'])} "
                     + ("이상으로 이익 구간" if tot["roas"] >= tot["be_roas"] else "에 못 미쳐 현재 적자 구조"))
    ui.headline(lines or ["광고비가 없는 데이터입니다."])

    # ---- KPI
    k = st.columns(5)
    ui.card(k[0], "노출수", ui.num(tot["impressions"]))
    ui.card(k[1], "클릭수", ui.num(tot["clicks"]))
    ui.card(k[2], "CTR", ui.pct(tot["ctr"], 2), "클릭수 ÷ 노출수")
    ui.card(k[3], "CPC", ui.won(tot["cpc"]), "광고비 ÷ 클릭수")
    ui.card(k[4], "광고비", ui.won(tot["cost"]))
    k = st.columns(5)
    ui.card(k[0], "주문수", ui.num(tot["orders"]), f"총 주문수({w}일)")
    ui.card(k[1], "CVR", ui.pct(tot["cvr"], 2), "주문수 ÷ 클릭수")
    ui.card(k[2], "전환매출", ui.won(tot["rev"]), f"총 전환매출액({w}일) — 소비자가 기준")
    ui.card(k[3], "ROAS", ui.mult(tot["roas"]), "전환매출액 ÷ 광고비. 광고비 0이면 0으로 표시")
    ui.card(k[4], "직접 전환 비중", ui.pct(M.direct_share(tot["rev_d"], tot["rev"])),
            "직접 전환매출 ÷ 총 전환매출. 나머지는 광고 노출 후 다른 경로로 구매한 간접 전환")

    FMT = {"광고비": st.column_config.NumberColumn(format="₩%d"), "전환매출": st.column_config.NumberColumn(format="₩%d"),
           "CPC": st.column_config.NumberColumn(format="₩%d"), "CTR": st.column_config.NumberColumn(format="percent"),
           "CVR": st.column_config.NumberColumn(format="percent"), "ROAS": st.column_config.NumberColumn(format="percent")}
    RENAME = {"impressions": "노출", "clicks": "클릭", "cost": "광고비", "orders": "주문", "rev": "전환매출",
              "ctr": "CTR", "cpc": "CPC", "cvr": "CVR", "roas": "ROAS", "keyword": "키워드"}

    t_kw, t_pl, t_prod, t_halo, t_day = st.tabs(["키워드별 상세", "노출 지면별",
                                                 "상품(옵션)별 · 묶음수량",
                                                 "헤일로 전환", "일별 추이"])

    with t_kw:
        sk = p[p["placement_group"] == "검색"]
        kt = M.ad_summary(sk, ["keyword"]).sort_values("cost", ascending=False)
        st.caption(f"검색 영역 키워드 {len(kt):,}개 (광고비 높은 순). 위의 '키워드 검색'에 단어를 넣으면 해당 키워드만 남고, "
                   "위 KPI도 그 키워드 기준으로 바뀝니다. 컬럼 제목을 누르면 정렬됩니다.")
        st.dataframe(kt[["keyword", "impressions", "clicks", "ctr", "cpc", "cost", "orders", "cvr", "rev", "roas"]]
                     .rename(columns=RENAME), hide_index=True, width="stretch", column_config=FMT)


    with t_pl:
        pl = M.ad_summary(p, ["placement_group"])
        fig = go.Figure()
        fig.add_bar(x=pl["placement_group"], y=[M.safe_div(c, pl["cost"].sum()) * 100 for c in pl["cost"]],
                    name="광고비 비중", marker_color="#E45756", customdata=pl["cost"],
                    hovertemplate="%{x}<br>광고비 비중 %{y:.1f}% (₩%{customdata:,.0f})<extra></extra>")
        fig.add_bar(x=pl["placement_group"], y=[M.safe_div(r, pl["rev"].sum()) * 100 for r in pl["rev"]],
                    name="전환매출 비중", marker_color="#4C78A8", customdata=pl["rev"],
                    hovertemplate="%{x}<br>전환매출 비중 %{y:.1f}% (₩%{customdata:,.0f})<extra></extra>")
        fig.update_layout(barmode="group", yaxis_title="비중(%)")
        ui.show(fig, 340)
        st.dataframe(pl[["placement_group", "impressions", "clicks", "cost", "orders", "rev", "ctr", "cpc", "cvr", "roas"]]
                     .rename(columns={"placement_group": "지면", "impressions": "노출", "clicks": "클릭", "cost": "광고비",
                                      "orders": "주문", "rev": "전환매출", "ctr": "CTR", "cpc": "CPC", "cvr": "CVR", "roas": "ROAS"}),
                     hide_index=True, width="stretch", column_config={
                         "광고비": st.column_config.NumberColumn(format="₩%d"), "전환매출": st.column_config.NumberColumn(format="₩%d"),
                         "CPC": st.column_config.NumberColumn(format="₩%d"), "CTR": st.column_config.NumberColumn(format="percent"),
                         "CVR": st.column_config.NumberColumn(format="percent"), "ROAS": st.column_config.NumberColumn(format="percent")})
        st.caption("광고비 비중 > 전환매출 비중인 지면 = 돈은 쓰는데 매출이 따라오지 않는 지면입니다.")

    with t_prod:
        pr = M.ad_summary(p, ["ad_product", "exec_sku", "exec_bundle"]).sort_values("cost", ascending=False)
        pcols = ["ad_product", "impressions", "clicks", "cost", "orders", "rev", "ctr", "cpc", "cvr", "roas"]
        pcols.insert(1, "exec_bundle")
        REF = "손익분기 ROAS"
        pr[REF] = pr["be_roas"]
        st.dataframe(pr[pcols + [REF]]
                     .rename(columns={"ad_product": "광고집행 상품", "exec_bundle": "묶음", "impressions": "노출", "clicks": "클릭",
                                      "cost": "광고비", "orders": "주문", "rev": "전환매출", "ctr": "CTR", "cpc": "CPC",
                                      "cvr": "CVR", "roas": "ROAS"}),
                     hide_index=True, width="stretch", column_config={
                         "광고비": st.column_config.NumberColumn(format="₩%d"), "전환매출": st.column_config.NumberColumn(format="₩%d"),
                         "CPC": st.column_config.NumberColumn(format="₩%d"), "CTR": st.column_config.NumberColumn(format="percent"),
                         "CVR": st.column_config.NumberColumn(format="percent"), "ROAS": st.column_config.NumberColumn(format="percent"),
                         REF: st.column_config.NumberColumn(format="percent")})
        bd = M.ad_summary(p, ["exec_sku", "exec_bundle"])
        bd = bd[bd["cost"] > 0]
        if len(bd):
            names = dict(zip(d["master"]["SKU ID"], d["master"]["품목"]))
            bd["품목"] = bd["exec_sku"].map(names).fillna("미매핑")
            fig = go.Figure()
            for nm, g in bd.groupby("품목"):
                g = g.sort_values("exec_bundle")
                fig.add_bar(x=[f"{b}개" for b in g["exec_bundle"]], y=g["roas"] * 100, name=nm,
                            customdata=g[["cost", "orders", "clicks"]].values,
                            hovertemplate=nm + " %{x}<br>ROAS %{y:.0f}%<br>광고비 ₩%{customdata[0]:,.0f} · 주문 %{customdata[1]:.0f}건 · 클릭 %{customdata[2]:.0f}<extra></extra>")
            fig.update_layout(barmode="group", title="묶음수량별 ROAS (어느 구성이 효율 좋은가)", yaxis_title="ROAS(%)")
            ui.show(fig, 340)
            st.caption("클릭·주문이 적은 구성은 우연에 크게 흔들립니다. 광고비·주문 수를 같이 보세요.")
        if (p["exec_sku"] == "").any():
            st.warning("SKU에 매핑되지 않은 광고 옵션이 있어 '미매핑'으로 표시됩니다. '⚙️ 데이터 업로드·설정' → 광고 매핑표에서 확정하세요.")

    with t_halo:
        h = p[p["is_halo"] & (p["rev"] > 0)]
        if h.empty:
            st.info("다른 상품으로 넘어간 전환(헤일로)이 없습니다.")
        else:
            flow = h.groupby(["ad_product", "conv_product"], as_index=False).agg(
                전환매출=("rev", "sum"), 판매수량=("qty", "sum"), 주문수=("orders", "sum"), 광고비=("cost", "sum"))
            flow = flow.sort_values("전환매출", ascending=False)
            st.caption(f"광고한 상품과 실제로 팔린 상품이 다른 전환 {len(flow)}건, 전환매출 ₩{flow['전환매출'].sum():,.0f} "
                       f"({flow['전환매출'].sum() / max(tot['rev'], 1) * 100:.0f}%)")
            top = flow.head(15)
            left = list(dict.fromkeys(top["ad_product"]))
            right = list(dict.fromkeys(top["conv_product"]))
            labels = [x.split(",")[0] + " " + (x.split(",")[1] if "," in x else "") for x in left] + \
                     [x.split(",")[0] + " " + (x.split(",")[1] if "," in x else "") + " " for x in right]
            fig = go.Figure(go.Sankey(
                node=dict(label=labels, pad=15, color=["#4C78A8"] * len(left) + ["#F58518"] * len(right)),
                link=dict(source=[left.index(a) for a in top["ad_product"]],
                          target=[len(left) + right.index(c) for c in top["conv_product"]],
                          value=top["전환매출"], hovertemplate="%{source.label} → %{target.label}<br>전환매출 ₩%{value:,.0f}<extra></extra>")))
            ui.show(fig, 420)
            st.dataframe(flow.rename(columns={"ad_product": "광고한 상품", "conv_product": "실제 팔린 상품"}),
                         hide_index=True, width="stretch",
                         column_config={"전환매출": st.column_config.NumberColumn(format="₩%d"),
                                        "광고비": st.column_config.NumberColumn(format="₩%d")})

    with t_day:
        dd = p[p["period_start"] == p["period_end"]]
        if dd["period_start"].nunique() < 2:
            st.info("일별 추이는 일자 데이터가 2일 이상 쌓이면 표시됩니다. (주간·월간 기간 파일은 일자 차트에 섞지 않습니다)")
        else:
            g = M.ad_summary(dd, ["period_start"]).sort_values("period_start")
            fig = go.Figure()
            fig.add_bar(x=g["period_start"], y=g["cost"], name="광고비", marker_color="#E45756",
                        hovertemplate="%{x}<br>광고비 ₩%{y:,.0f}<extra></extra>")
            fig.add_scatter(x=g["period_start"], y=g["roas"] * 100, name="ROAS(%)", yaxis="y2", mode="lines+markers",
                            line=dict(color="#4C78A8"), hovertemplate="%{x}<br>ROAS %{y:.0f}%<extra></extra>")
            fig.update_layout(yaxis=dict(title="광고비(₩)"), yaxis2=dict(title="ROAS(%)", overlaying="y", side="right", showgrid=False))
            ui.show(fig, 380)


# ------------------------------------------------------------------ 기간별 비교
def _weekly_trend(cfg: dict, d: dict) -> None:
    ad = d["ad"]
    if ad.empty:
        st.info("저장된 광고 데이터가 없습니다.")
        return
    w = st.radio("전환 기준", [14, 1], index=0 if int(cfg["attribution_days"]) == 14 else 1, horizontal=True,
                 format_func=lambda x: f"{x}일", key="wt_w")
    p = M.prep_ad(ad, w, d["map"], d["master"], cfg["default_breakeven_roas"], ui.supply_by_sku(d["daily"]))
    wf = M.ad_weekly_frame(M.tag_ad_periods(p))
    if wf.empty:
        st.info("주 단위(월~일) 또는 일 단위 광고 파일이 아직 없습니다.")
        return
    g = M.ad_summary(wf, ["week"]).sort_values("week").reset_index(drop=True)
    days = wf.groupby("week")["n_days"].max()
    g["일수"] = g["week"].map(days).astype(int)
    g["기간"] = [M.week_label(x) for x in g["week"]]
    g["비고"] = ["" if n >= 7 else f"진행 중 · 일 {n}/7" for n in g["일수"]]
    g["일평균 광고비"] = g["cost"] / g["일수"]
    g["일평균 전환매출"] = g["rev"] / g["일수"]
    prev_cost, prev_roas = g["일평균 광고비"].shift(), g["roas"].shift()
    g["전주 대비 광고비"] = [None if pd.isna(b) or b == 0 else (a - b) / b for a, b in zip(g["일평균 광고비"], prev_cost)]
    g["전주 대비 ROAS"] = [None if pd.isna(b) or b == 0 else (a - b) / b for a, b in zip(g["roas"], prev_roas)]
    g["판정"] = ["-" if c <= 0 else ("✅ 양호" if r >= b else "⚠️ 기준 미달") for c, r, b in zip(g["cost"], g["roas"], g["be_roas"])]
    g["기준"] = g["be_roas"]
    show = g[["기간", "일수", "cost", "일평균 광고비", "clicks", "orders", "rev", "cvr", "cpc", "roas", "기준", "판정",
              "전주 대비 광고비", "전주 대비 ROAS", "비고"]].iloc[::-1]
    st.caption("주(월~일)마다 한 번씩만 센 합계입니다. 진행 중인 주는 일수가 적으니 **일평균**과 전주 대비로 비교하세요.")
    st.dataframe(show.rename(columns={"cost": "광고비", "clicks": "클릭", "orders": "주문", "rev": "전환매출", "cvr": "CVR",
                                      "cpc": "CPC", "roas": "ROAS", "기준": "손익분기 ROAS"}),
                 hide_index=True, width="stretch", column_config={
                     "광고비": st.column_config.NumberColumn(format="₩%d"), "일평균 광고비": st.column_config.NumberColumn(format="₩%d"),
                     "전환매출": st.column_config.NumberColumn(format="₩%d"), "CPC": st.column_config.NumberColumn(format="₩%d"),
                     "CVR": st.column_config.NumberColumn(format="percent"), "ROAS": st.column_config.NumberColumn(format="percent"),
                     "손익분기 ROAS": st.column_config.NumberColumn(format="percent"),
                     "전주 대비 광고비": st.column_config.NumberColumn(format="percent"),
                     "전주 대비 ROAS": st.column_config.NumberColumn(format="percent")})
    fig = go.Figure()
    fig.add_bar(x=g["기간"], y=g["일평균 광고비"], name="일평균 광고비", marker_color="#E45756",
                hovertemplate="%{x}<br>일평균 광고비 ₩%{y:,.0f}<extra></extra>")
    fig.add_bar(x=g["기간"], y=g["일평균 전환매출"], name="일평균 전환매출", marker_color="#4C78A8",
                hovertemplate="%{x}<br>일평균 전환매출 ₩%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=g["기간"], y=g["roas"] * 100, name="ROAS(%)", yaxis="y2", mode="lines+markers",
                    line=dict(color="#54A24B"), hovertemplate="%{x}<br>ROAS %{y:.0f}%<extra></extra>")
    fig.update_layout(barmode="group", yaxis=dict(title="일평균(₩)"),
                      yaxis2=dict(title="ROAS(%)", overlaying="y", side="right", showgrid=False))
    ui.show(fig, 380)


def render() -> None:
    cfg = ui.setup("광고 성과", "📢")
    d = ui.load_all(cfg)
    t_detail, t_period = st.tabs(["📊 상세 분석", "🗓️ 주별 추이"])
    with t_detail:
        _detail(cfg, d)
    with t_period:
        _weekly_trend(cfg, d)
