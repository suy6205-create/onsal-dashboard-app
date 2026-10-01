"""🏠 홈 — 오늘의 요약 (MD가 매일 처음 보는 화면). 일 / 주(최근 7일) 보기 전환 가능."""
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
# ---- 기준일 · 보기 단위 · 데이터 최신성
dates = sorted(daily["date"].unique())
c1, c3, c2 = st.columns([1, 1.3, 3])
asof_s = c1.selectbox("기준일", dates[::-1], index=0, help="기본값은 가장 최근 판매 데이터 날짜")
asof = pd.Timestamp(asof_s)
view = c3.radio("보기 단위", ["일", "주", "월"], index=1, horizontal=True, key="home_view",
                help="일 = 기준일 하루 · 주 = 기준일을 마지막 날로 하는 최근 7일 · 월 = 기준일이 속한 달의 1일~기준일(월 누계)")
week, month = view == "주", view == "월"


def _window_set() -> dict:
    """i=0 현재 구간, 1 = 직전 비교 구간, 2 = 그 이전 구간. 각 (시작일, 종료일)."""
    if view == "월":
        m0 = asof.replace(day=1)
        n = (asof - m0).days + 1                                   # 이번 달 경과 일수
        out = {0: (m0, asof)}
        cur = m0
        for i in (1, 2):
            pm_end = cur - timedelta(days=1)                       # 이전 달 말일
            pm0 = pm_end.replace(day=1)
            out[i] = (pm0, min(pm0 + timedelta(days=n - 1), pm_end))   # 같은 일수만큼 (월말 넘으면 말일까지)
            cur = pm0
        return out
    span_ = 7 if view == "주" else 1
    return {i: (asof - timedelta(days=span_ * i + span_ - 1), asof - timedelta(days=span_ * i)) for i in (0, 1, 2)}


W = _window_set()
span = (W[0][1] - W[0][0]).days + 1
UNIT = {"일": "", "주": "7일", "월": "월 누계"}[view]
CAP = {"일": "전주 동요일 대비", "주": "2주 전 대비", "월": "2개월 전 대비"}[view]
CMP = {"일": "전일", "주": "직전 7일", "월": "지난달 같은 기간"}[view]
exclude = st.sidebar.toggle("체험단 제외 기준(순수 판매)", value=False,
                            help="체험단 구매도 출고수량에 포함된다고 가정하고 그 수량을 뺀 판매를 봅니다.")
last_ad = ad["period_end"].max() if len(ad) else None
c2.caption(f"데이터 최신성 · 판매 {dates[-1][5:].replace('-', '/')}까지"
           + (f", 광고 {last_ad[5:].replace('-', '/')}까지 반영" if last_ad else ", 광고 데이터 없음"))
if last_ad and last_ad < dates[-1]:
    c2.caption(f"⚠️ 광고 데이터가 판매보다 {(pd.Timestamp(dates[-1]) - pd.Timestamp(last_ad)).days}일 늦습니다. "
               "광고 리포트도 최신으로 올려주세요.")
if view != "일":
    st.caption(f"집계 기간 {W[0][0]:%m/%d} ~ {W[0][1]:%m/%d} ({span}일) · 증감(▲▼)은 {CMP} "
               f"({W[1][0]:%m/%d} ~ {W[1][1]:%m/%d}) 대비")
if W[1][0] < pd.Timestamp(dates[0]):
    st.caption(f"⚠️ 비교 구간({W[1][0]:%m/%d}~)에는 판매 데이터가 {dates[0][5:].replace('-', '/')}부터만 있어 증감이 실제보다 크게 보일 수 있습니다.")

# ---- 광고 컨텍스트: 기준일 기준 최근 7일 일자 데이터가 있으면 그것, 없으면 가장 최근 기간 파일
w = int(cfg["attribution_days"])
sup = ui.supply_by_sku(daily)
ad_ctx_label, ad_ctx = "", pd.DataFrame()
if len(ad):
    ctx_start = asof.replace(day=1) if month else asof - timedelta(days=6)
    rd = ad[(ad["is_daily"] == 1) & (ad["period_start"] <= asof_s) &
            (ad["period_start"] >= str(ctx_start.date()))]
    if len(rd):
        ad_ctx = rd
        ad_ctx_label = f"{'이번 달' if month else '최근 7일'} 일자 데이터 ({ui.period_label(rd.period_start.min(), rd.period_end.max())})"
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

# ---- KPI 6개 (일: 기준일 하루 / 주: 최근 7일 합계)
tot = M.daily_totals(daily, master, trials, exclude).set_index("date")


def win_sum(col: str, i: int = 0) -> float:
    """구간 i(0 현재, 1 직전, 2 그 이전)의 합계."""
    keys = pd.date_range(W[i][0], W[i][1]).strftime("%Y-%m-%d")
    return float(tot[col].reindex(keys).fillna(0).sum()) if len(tot) else 0.0


def ad_win(i: int = 0):
    """같은 구간의 Retail 일자 광고 합계 (없으면 None). ndays = 광고 데이터가 있는 일수."""
    r = ad[(ad["is_daily"] == 1) & (ad["sale_type"] == "Retail") &
           (ad["period_start"] >= str(W[i][0].date())) & (ad["period_start"] <= str(W[i][1].date()))]
    if r.empty:
        return None
    s = M.ad_summary(M.prep_ad(r, w, d["map"], master, cfg["default_breakeven_roas"], sup)).iloc[0].copy()
    s["ndays"] = r["period_start"].nunique()
    return s


cur_ad, prev_ad, wk_ad = ad_win(0), ad_win(1), ad_win(2)
k = st.columns(6)
ui.kpi(k[0], f"판매량({UNIT})" if UNIT else "판매량", ui.num(win_sum("qty")) + "개", win_sum("qty"),
       win_sum("qty", 1), win_sum("qty", 2),
       f"{'집계 기간' if UNIT else '기준일'} Σ출고수량 (체험단 제외 토글 시 체험단 수량 차감)", cap=CAP)
ui.kpi(k[1], f"공급가매출({UNIT})" if UNIT else "공급가매출", ui.won(win_sum("supply_rev")), win_sum("supply_rev"),
       win_sum("supply_rev", 1), win_sum("supply_rev", 2),
       "판매량 × 매입원가(쿠팡이 우리에게 지급하는 공급가, VAT 제외)", cap=CAP)
if cur_ad is not None:
    cons = win_sum("consumer_rev")
    pc, wc = (None if prev_ad is None else prev_ad["cost"]), (None if wk_ad is None else wk_ad["cost"])
    ui.kpi(k[2], f"광고비({UNIT})" if UNIT else "광고비", ui.won(cur_ad["cost"]), cur_ad["cost"], pc, wc,
           f"Retail 광고 {'집계 기간' if UNIT else '기준일'} 광고비 (일자 데이터 기준)", inverse=True, cap=CAP)
    ui.kpi(k[3], f"ROAS({w}일)", ui.mult(cur_ad["roas"]), cur_ad["roas"],
           None if prev_ad is None else prev_ad["roas"], None if wk_ad is None else wk_ad["roas"],
           "광고 전환매출액 ÷ 광고비 (원천 숫자로 재계산). 손익분기 ROAS 이상이어야 이익", cap=CAP)
    ui.kpi(k[4], "TACoS", ui.pct(M.safe_div(cur_ad["cost"], cons, None)),
           M.safe_div(cur_ad["cost"], cons, None),
           M.safe_div(prev_ad["cost"], win_sum("consumer_rev", 1), None) if prev_ad is not None else None,
           M.safe_div(wk_ad["cost"], win_sum("consumer_rev", 2), None) if wk_ad is not None else None,
           "광고비 ÷ 소비자가매출 (판매량×(판매가−할인)). 전체 매출 대비 광고비 비중", inverse=True, cap=CAP)
    if view != "일" and cur_ad["ndays"] < span:
        st.caption(f"⚠️ 광고 일자 데이터가 {int(cur_ad['ndays'])}/{span}일만 있어 광고비·ROAS·TACoS는 부분 합계입니다. "
                   "빠진 날의 광고 파일을 올리면 정확해집니다.")
elif len(ad_p):
    t = M.ad_summary(ad_p).iloc[0]
    s0, e0 = ad_ctx.period_start.min(), ad_ctx.period_end.max()
    cons = float(M.daily_totals(daily[(daily["date"] >= s0) & (daily["date"] <= e0)], master, trials,
                                exclude)["consumer_rev"].sum())
    ui.card(k[2], "광고비(기간)", ui.won(t["cost"]), f"{ad_ctx_label} 합계. 선택 구간의 일자 데이터가 없어 기간 합계를 표시합니다.")
    ui.card(k[3], f"ROAS({w}일)", ui.mult(t["roas"]), f"{ad_ctx_label}. 광고 전환매출액 ÷ 광고비")
    ui.card(k[4], "TACoS(기간)", ui.pct(M.safe_div(t["cost"], cons, None)),
            "기간 광고비 ÷ 같은 기간 소비자가매출", inverse=True)
else:
    for i, n in ((2, "광고비"), (3, "ROAS"), (4, "TACoS")):
        ui.card(k[i], n, "-", "광고 데이터가 없습니다")
red_n = int(((sku_tbl["운영중"]) & (sku_tbl["품절"] | ~sku_tbl["발주가능"] |
                                     (sku_tbl["소진예상일"] <= cfg["stock_red_days"]))).sum())
ui.card(k[5], "품절·발주필요 SKU", f"{red_n}개",
        f"품절이거나 발주불가이거나 재고소진 예상일이 {cfg['stock_red_days']}일 이내인 운영중 SKU 수 (기준일 시점)", inverse=True)
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

# ---- 추이 차트
if view == "주":
    st.subheader("📈 최근 12주 주간 판매·광고비 추이")
    ends = [asof - timedelta(days=7 * i) for i in range(11, -1, -1)]          # 12개 구간의 마지막 날
    qs, ads = [], []
    daily_ad = ad[(ad["is_daily"] == 1) & (ad["sale_type"] == "Retail")].groupby("period_start")["cost"].sum() if len(ad) else pd.Series(dtype=float)
    for e in ends:
        keys = pd.date_range(e - timedelta(days=6), e).strftime("%Y-%m-%d")
        qs.append(float(tot["qty"].reindex(keys).fillna(0).sum()) if len(tot) else 0.0)
        ads.append(float(daily_ad.reindex(keys).fillna(0).sum()) if len(daily_ad) else None)
    labels = [f"{(e - timedelta(days=6)):%m/%d}~{e:%m/%d}" for e in ends]
    fig = go.Figure()
    fig.add_bar(x=labels, y=qs, name="판매량(7일)", marker_color="#4C78A8",
                hovertemplate="%{x}<br>판매량 %{y:,.0f}개<extra></extra>")
    if len(daily_ad):
        fig.add_scatter(x=labels, y=ads, name="광고비(일자 데이터 합)", yaxis="y2", mode="lines+markers",
                        line=dict(color="#E45756"), hovertemplate="%{x}<br>광고비 ₩%{y:,.0f}<extra></extra>")
    if len(trials):
        mark_x, mark_y, mark_t = [], [], []
        for lab, e, q_ in zip(labels, ends, qs):
            keys = set(pd.date_range(e - timedelta(days=6), e).strftime("%Y-%m-%d"))
            n = int(trials[trials["date"].isin(keys)]["qty"].sum())
            if n:
                mark_x.append(lab), mark_y.append(q_), mark_t.append(f"체험단 {n}개")
        if mark_x:
            fig.add_scatter(x=mark_x, y=mark_y, mode="markers", name="체험단 진행 주", text=mark_t,
                            marker=dict(symbol="star", size=14, color="#F58518"),
                            hovertemplate="%{x} %{text}<extra></extra>")
    fig.update_layout(yaxis=dict(title="판매량(개)"),
                      yaxis2=dict(title="광고비(₩)", overlaying="y", side="right", showgrid=False))
    ui.show(fig, 400)
    st.caption("각 막대는 기준일을 마지막 날로 7일씩 끊은 구간입니다. 광고비 선은 '일자 데이터'만 합산하므로 "
               "주간·월간 기간 파일만 있는 구간은 비어 보일 수 있습니다. 일 단위 차트는 '보기 단위'를 '일'로 바꾸세요.")
elif view == "월":
    st.subheader("📈 최근 12개월 월별 판매·광고비 추이")
    m_starts = [(asof.replace(day=1) - pd.DateOffset(months=i)).normalize() for i in range(11, -1, -1)]
    qs, labels, ads = [], [], []
    # 월별 Retail 광고비: 일자 파일 + 한 달 안에 들어가는 기간 파일 (더 큰 기간에 포함되는 것은 이중 집계 방지로 제외)
    ad_r = ad[ad["sale_type"] == "Retail"] if len(ad) else ad
    cost_by_span = ad_r.groupby(["period_start", "period_end"])["cost"].sum().to_dict() if len(ad_r) else {}
    kept_spans = ui._drop_nested(list(cost_by_span))[0]
    ad_month: dict = {}
    for ps, pe in kept_spans:
        if ps[:7] == pe[:7]:
            ad_month[ps[:7]] = ad_month.get(ps[:7], 0.0) + cost_by_span[(ps, pe)]
    for m0 in m_starts:
        m_end = min(m0 + pd.offsets.MonthEnd(0), asof)
        keys = pd.date_range(m0, m_end).strftime("%Y-%m-%d")
        qs.append(float(tot["qty"].reindex(keys).fillna(0).sum()) if len(tot) else 0.0)
        labels.append(f"{m0:%Y-%m}" + (" (누계)" if m0 == m_starts[-1] and asof < m0 + pd.offsets.MonthEnd(0) else ""))
        ads.append(ad_month.get(f"{m0:%Y-%m}"))
    fig = go.Figure()
    fig.add_bar(x=labels, y=qs, name="판매량", marker_color="#4C78A8",
                hovertemplate="%{x}<br>판매량 %{y:,.0f}개<extra></extra>")
    if any(v is not None for v in ads):
        fig.add_scatter(x=labels, y=ads, name="광고비(Retail)", yaxis="y2", mode="lines+markers",
                        line=dict(color="#E45756"), hovertemplate="%{x}<br>광고비 ₩%{y:,.0f}<extra></extra>")
    if len(trials):
        mx, my, mt = [], [], []
        for lab, m0, q_ in zip(labels, m_starts, qs):
            n = int(trials[trials["date"].str.startswith(f"{m0:%Y-%m}")]["qty"].sum())
            if n:
                mx.append(lab), my.append(q_), mt.append(f"체험단 {n}개")
        if mx:
            fig.add_scatter(x=mx, y=my, mode="markers", name="체험단 진행 월", text=mt,
                            marker=dict(symbol="star", size=14, color="#F58518"),
                            hovertemplate="%{x} %{text}<extra></extra>")
    fig.update_layout(yaxis=dict(title="판매량(개)"),
                      yaxis2=dict(title="광고비(₩)", overlaying="y", side="right", showgrid=False))
    ui.show(fig, 400)
    st.caption("판매 데이터가 있는 달만 값이 있습니다(데이터가 없는 달은 0). 광고비는 일자 파일과 '한 달 안에 들어가는' 기간 파일을 합산하며, "
               "여러 달에 걸친 기간 파일은 월별로 나눌 수 없어 제외됩니다. 마지막 막대는 이번 달 누계입니다.")
else:
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
