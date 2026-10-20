"""🧮 공급가 계산 — 판매가·원가·수수료율로 쿠팡 공급가와 마진을 바로 계산"""
import pandas as pd
import streamlit as st

from src import config
from src import metrics as M
from src import ui

cfg = ui.setup("공급가 계산", "🧮")
d = ui.load_all(cfg)
vat = float(cfg["vat"])

st.info("💡 **쿠팡 공급가(VAT 포함) = 판매가 × (1 − 수수료율)**, 공급가(VAT 제외) = ÷ 1.1. "
        "여기에서 원가를 빼면 개당 마진입니다. 수수료율은 보통 40%로 넣으면 됩니다.")

# ------------------------------------------------------------ 시뮬레이터 (신제품 · 가격 변경 검토용)
st.subheader("🔢 바로 계산해 보기")
c = st.columns(4)
price = c[0].number_input("판매가 (원, VAT 포함)", min_value=0, value=10000, step=100, key="sim_price")
cost = c[1].number_input("원가 (원, 개당)", min_value=0, value=3500, step=100, key="sim_cost")
fee_pct = c[2].number_input("수수료율 (%)", min_value=0.0, max_value=99.0, value=40.0, step=0.5, key="sim_fee")
disc = c[3].number_input("할인 (원, 없으면 0)", min_value=0, value=0, step=100, key="sim_disc")
r = M.supply_margin(price, cost, fee_pct / 100, disc, vat)
k = st.columns(3)
ui.card(k[0], "쿠팡 공급가 (VAT 포함)", ui.won(r["공급가(VAT 포함)"]), "소비자가 × (1 − 수수료율). 쿠팡이 우리에게 주는 금액(부가세 포함)")
ui.card(k[1], "쿠팡 공급가 (VAT 제외)", ui.won(r["공급가(VAT 제외)"]), "공급가(VAT 포함) ÷ 1.1, 원 단위 반올림. 판매 데이터의 '매입원가'와 같은 값")
ui.card(k[2], "개당 마진", ui.won(r["개당 마진"]), "공급가(VAT 제외) − 원가", inverse=False)
k = st.columns(3)
ui.card(k[0], "마진율 (공급가 기준)", ui.pct(r["마진율(공급가 기준)"]), "마진 ÷ 공급가(VAT 제외). 기존 보고서의 '마진율'과 같은 기준")
ui.card(k[1], "마진율 (판매가 기준)", ui.pct(r["마진율(소비자가 기준)"]), "마진 ÷ 소비자가. 광고 전환매출(소비자가 기준)과 맞춘 기준")
be = r["손익분기 ROAS"]
ui.card(k[2], "광고 손익분기 ROAS", "-" if be is None else ui.mult(be),
        "1 ÷ 마진율(판매가 기준). 광고 ROAS가 이 값보다 낮으면 광고를 할수록 적자")
if r["개당 마진"] < 0:
    st.error("⚠️ 원가가 쿠팡 공급가보다 높아 팔수록 손해입니다.")
with st.expander("쿠팡에서 받은 공급가를 이미 알고 있다면 (수수료율 역산)"):
    sv = st.number_input("쿠팡 공급가 (VAT 포함, 원)", min_value=0, value=6000, step=10, key="sim_sup")
    fr = M.fee_rate_from_supply(price, sv, disc)
    st.write("역산한 수수료율: " + ("-" if fr is None else f"**{fr * 100:.2f}%**"))

# ------------------------------------------------------------ 상품별 표 (마스터)
st.subheader("📦 우리 상품별 공급가·마진")
master = d["master"]
if master.empty:
    st.info("상품 마스터가 비어 있습니다. 판매 데이터를 올리면 SKU가 자동으로 등록됩니다.")
    st.stop()
rows = []
for _, m in master.iterrows():
    fee = float(m["판매수수료율"]) if float(m["판매수수료율"]) > 0 else 0.40
    rows.append({"SKU ID": m["SKU ID"], "품목": m["품목"], "브랜드": m["브랜드"], "판매가": float(m["판매가"]), "할인": float(m["할인"]),
                 "원가": float(m["원가"]), "수수료율(%)": round(fee * 100, 2)})
base = pd.DataFrame(rows)


def _calc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    res = [M.supply_margin(r["판매가"], r["원가"], r["수수료율(%)"] / 100, r["할인"], vat) for _, r in out.iterrows()]
    out["공급가(VAT 포함)"] = [x["공급가(VAT 포함)"] for x in res]
    out["공급가(VAT 제외)"] = [x["공급가(VAT 제외)"] for x in res]
    out["개당 마진"] = [x["개당 마진"] for x in res]
    out["마진율(공급가 기준)"] = [x["마진율(공급가 기준)"] for x in res]
    out["마진율(판매가 기준)"] = [x["마진율(소비자가 기준)"] for x in res]
    out["손익분기 ROAS"] = [x["손익분기 ROAS"] for x in res]
    return out


editable = ["판매가", "할인", "원가", "수수료율(%)"]
st.caption("표의 **판매가·할인·원가·수수료율** 칸을 고치면 오른쪽 계산 결과가 바로 바뀝니다. "
           "수수료율이 비어 있던 상품은 기본 40%로 보여줍니다.")
ed = st.data_editor(
    _calc(base), hide_index=True, width="stretch", key="supply_editor",
    disabled=[c for c in _calc(base).columns if c not in editable],
    column_config={
        "판매가": st.column_config.NumberColumn(format="₩%d", min_value=0, step=100),
        "할인": st.column_config.NumberColumn(format="₩%d", min_value=0, step=100),
        "원가": st.column_config.NumberColumn(format="₩%d", min_value=0, step=100),
        "수수료율(%)": st.column_config.NumberColumn(format="%.2f%%", min_value=0.0, max_value=99.0, step=0.5),
        "공급가(VAT 포함)": st.column_config.NumberColumn(format="₩%d"),
        "공급가(VAT 제외)": st.column_config.NumberColumn(format="₩%d"),
        "개당 마진": st.column_config.NumberColumn(format="₩%d"),
        "마진율(공급가 기준)": st.column_config.NumberColumn(format="percent"),
        "마진율(판매가 기준)": st.column_config.NumberColumn(format="percent"),
        "손익분기 ROAS": st.column_config.NumberColumn(format="percent", help="1 ÷ 마진율(판매가 기준)"),
    })
if ui.is_admin():
    if st.button("💾 이 값을 상품 마스터에 저장", type="primary", help="판매가·할인·원가·수수료율을 마스터에 반영합니다 (다른 브랜드·다른 칸은 그대로)"):
        full = config.load_master().set_index("SKU ID")
        for _, r in ed.iterrows():
            if r["SKU ID"] in full.index:
                full.loc[r["SKU ID"], ["판매가", "할인", "원가", "판매수수료율"]] = [
                    float(r["판매가"]), float(r["할인"]), float(r["원가"]), float(r["수수료율(%)"]) / 100]
        config.save_master(full.reset_index())
        st.success("저장했습니다. 판매·재고, 통합 손익 등 다른 화면의 손익분기 ROAS도 이 값으로 계산됩니다.")
        st.rerun()
else:
    st.caption("🔐 마스터에 저장하려면 왼쪽 메뉴 아래 **관리자 로그인**이 필요합니다. (계산·확인은 로그인 없이 가능)")
