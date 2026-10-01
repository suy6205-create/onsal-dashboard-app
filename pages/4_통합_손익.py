"""💰 통합 손익 (판매 × 광고)"""
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import metrics as M
from src import ui

cfg = ui.setup("통합 손익", "💰")
d = ui.load_all(cfg)
ui.no_data_stop(d, need_ad=True)
exclude = st.sidebar.toggle("체험단 제외 기준(순수 판매)", value=False,
                            help="판매량·소비자가매출에서 체험단 수량을 뺍니다. 오가닉 추정은 항상 체험단을 제외합니다.")
f = ui.ad_filters(d, cfg, "int", force_retail=True)
if f is None:
    st.stop()
st.info("⚖️ **단위 주의**: 광고 전환매출은 *소비자가* 기준, 로켓 매출은 *공급가*(쿠팡 지급액) 기준입니다. "
        "이 화면은 TACoS·광고 기여 판매를 모두 소비자가로 맞춰 계산하고, 순이익은 공급가 기준으로 계산합니다.")
s, e = f["start"], f["end"]
p = f["df"]
daily = d["daily"]
span_days = (pd.Timestamp(e) - pd.Timestamp(s)).days + 1
have = daily[(daily["date"] >= s) & (daily["date"] <= e)]["date"].nunique()
if have < span_days:
    st.warning(f"선택 기간({ui.period_label(s, e)}, {span_days}일) 중 판매 데이터가 {have}일치만 있습니다. 합계가 실제보다 작을 수 있어요.")

df = M.integrated_by_sku(daily, d["master"], p, d["trials"], s, e, exclude)
df = df[(df["판매량"] > 0) | (df["광고비"] > 0)]
if df.empty:
    st.info("선택 기간에 판매·광고 데이터가 없습니다.")
    st.stop()
tot = df.sum(numeric_only=True)

# 한 줄 요약
lines = [f"{ui.period_label(s, e)} 순이익 {ui.won(tot['순이익'])} — 공헌이익 {ui.won(tot['공헌이익'])}에서 "
         f"광고비 {ui.won(tot['광고비'])}, 체험단 {ui.won(tot['체험단비'])} 차감"]
dep = M.safe_div(tot["광고기여판매"], tot["판매량"], None)
if dep is not None:
    lines.append(f"전체 판매의 {dep*100:.0f}%가 광고 기여, 오가닉(추정) {M.safe_div(tot['오가닉추정'], tot['판매량'])*100:.0f}%")
ui.headline(lines)

k = st.columns(5)
ui.card(k[0], "순이익", ui.won(tot["순이익"]), "공헌이익 − 광고비 − 체험단 비용 (공급가 기준)", inverse=False)
ui.card(k[1], "공급가매출", ui.won(tot["공급가매출"]), "Σ출고수량 × 매입원가")
ui.card(k[2], "광고비", ui.won(tot["광고비"]), "Retail 광고비 합계", inverse=True)
ui.card(k[3], "TACoS", ui.pct(M.safe_div(tot["광고비"], tot["소비자가매출"], None)),
        "광고비 ÷ 소비자가매출. 전체 매출 대비 광고비 비중", inverse=True)
ui.card(k[4], "광고 의존도", ui.pct(dep), "광고 기여 판매수량 ÷ 전체 판매수량. 광고 기여 = 광고 총 판매수량 × 묶음수량")

un = M.unmapped_options(p, cfg["brand"])
if len(un):
    st.warning(f"SKU에 매핑되지 않은 광고 옵션 {len(un)}개 (광고비 ₩{un['광고비'].sum():,.0f}) — 광고 기여 판매·광고비가 SKU에 배분되지 않았습니다. "
               "'⚙️ 데이터 업로드·설정' → 광고 매핑표에서 확정하세요.")
    with st.expander("미매핑 옵션 보기"):
        st.dataframe(un, hide_index=True, width="stretch")
other = p[(p["conv_sku"] == "") & ~p["conv_product"].str.contains(cfg["brand"], regex=False)]
if len(other):
    st.caption(f"ℹ️ 타 브랜드 상품으로 전환된 광고 행 {len(other)}개(전환매출 ₩{other['rev'].sum():,.0f})는 광고 기여 판매에서 제외했습니다.")

show = pd.DataFrame({
    "품목": df["품목"], "판매량": df["판매량"], "광고 기여": df["광고기여판매"].round(1), "오가닉(추정)": df["오가닉추정"].round(1),
    "체험단수량": df["체험단수량"], "공급가매출": df["공급가매출"], "원가": df["원가합계"], "광고비": df["광고비"],
    "체험단비": df["체험단비"], "순이익": df["순이익"], "TACoS": df["TACoS"], "광고 의존도": df["광고의존도"],
    "손익분기 ROAS": df["손익분기ROAS"]})
money = {c: st.column_config.NumberColumn(format="₩%d") for c in ["공급가매출", "원가", "광고비", "체험단비", "순이익"]}
st.dataframe(show, hide_index=True, width="stretch", column_config={
    **money, "TACoS": st.column_config.NumberColumn(format="percent", help="광고비 ÷ 소비자가매출"),
    "광고 의존도": st.column_config.NumberColumn(format="percent", help="광고 기여 판매 ÷ 전체 판매"),
    "손익분기 ROAS": st.column_config.NumberColumn(format="percent", help="1 ÷ 마진율. 마진율 = (매입원가−원가) ÷ 소비자가"),
    "오가닉(추정)": st.column_config.NumberColumn(help="전체 출고 − 광고 기여 − 체험단 수량 (0 미만은 0)")})

st.subheader("워터폴: 공급가매출 → 순이익")
opt = ["전체"] + list(df["품목"])
pick = st.selectbox("대상", opt)
r = tot if pick == "전체" else df[df["품목"] == pick].iloc[0]
vals = [r["공급가매출"], -r["원가합계"], -r["광고비"], -r["체험단비"]]
fig = go.Figure(go.Waterfall(
    x=["공급가매출", "− 원가", "− 광고비", "− 체험단", "순이익"], measure=["absolute", "relative", "relative", "relative", "total"],
    y=vals + [0], text=[ui.won(v) for v in vals + [r["순이익"]]], textposition="outside",
    increasing=dict(marker_color="#54A24B"), decreasing=dict(marker_color="#E45756"), totals=dict(marker_color="#4C78A8"),
    hovertemplate="%{x}<br>₩%{y:,.0f}<extra></extra>"))
fig.update_layout(yaxis_title="₩", showlegend=False)
ui.show(fig, 380)

st.subheader("광고 의존도 vs 판매 성장률")
ln = span_days
prev_s, prev_e = str((pd.Timestamp(s) - timedelta(days=ln)).date()), str((pd.Timestamp(s) - timedelta(days=1)).date())
rows = []
for _, r in df.iterrows():
    cur = daily[(daily["sku_id"] == r["sku_id"]) & (daily["date"] >= s) & (daily["date"] <= e)]["outbound"].sum()
    prv = daily[(daily["sku_id"] == r["sku_id"]) & (daily["date"] >= prev_s) & (daily["date"] <= prev_e)]["outbound"].sum()
    g = M.pct_change(cur, prv)
    if g is not None and r["광고의존도"] is not None and not pd.isna(r["광고의존도"]):
        rows.append({"품목": r["품목"], "dep": r["광고의존도"] * 100, "growth": g * 100, "qty": cur})
if rows:
    sc = pd.DataFrame(rows)
    fig = go.Figure(go.Scatter(x=sc["dep"], y=sc["growth"], mode="markers+text", text=sc["품목"], textposition="top center",
                               marker=dict(size=(sc["qty"].clip(lower=1) ** 0.5 * 8).clip(12, 60), color="#4C78A8", opacity=.7),
                               hovertemplate="<b>%{text}</b><br>광고 의존도 %{x:.0f}%<br>판매 성장률 %{y:+.0f}%<extra></extra>"))
    fig.add_hline(y=0, line_dash="dot", line_color="#999")
    fig.update_layout(xaxis_title="광고 의존도(%)", yaxis_title=f"직전 {ln}일 대비 판매 성장률(%)")
    ui.show(fig, 360)
    st.caption("우상(의존도 높고 성장)=광고가 성장을 견인 · 좌상(의존도 낮고 성장)=오가닉 성장 · 우하=광고를 끊으면 위험. 직전 동일 기간 판매 데이터가 있을 때만 표시됩니다.")
else:
    st.info("직전 동일 기간의 판매 데이터가 없어 성장률 산점도를 만들 수 없습니다.")
