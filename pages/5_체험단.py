"""🎁 체험단"""
from datetime import date

import pandas as pd
import streamlit as st

from src import db
from src import metrics as M
from src import ui

cfg = ui.setup("체험단", "🎁")
d = ui.load_all(cfg)
master, daily = d["master"], d["daily"]
names = dict(zip(master["SKU ID"], master["품목"]))
sup = ui.supply_by_sku(daily)
vat, fee_default = cfg["vat"], cfg["trial_fee_per_unit"] * cfg["vat"]

st.subheader("체험단 등록")
if master.empty:
    st.warning("상품 마스터가 비어 있습니다.")
    st.stop()
with st.form("trial_form", clear_on_submit=True):
    c = st.columns(4)
    dt = c[0].date_input("날짜", value=date.today())
    sku = c[1].selectbox("SKU", list(master["SKU ID"]), format_func=lambda x: f"{names.get(x, x)} ({x})")
    qty = c[2].number_input("체험단 개수", min_value=1, value=10, step=1)
    memo = c[3].text_input("업체 / 메모")
    c = st.columns(3)
    unit_auto = float(sup.get(sku, 0)) * vat
    unit = c[0].number_input("제품가(공급가+VAT, 개당)", min_value=0.0, value=unit_auto, step=100.0,
                             help="판매 데이터의 매입원가 × 1.1 이 자동 입력됩니다. 필요하면 수정하세요.")
    fee = c[1].number_input("체험단 대행비(개당, VAT 포함)", min_value=0.0, value=float(fee_default), step=100.0,
                            help="체험단 업체에 지급하는 개당 대행비를 직접 입력하세요 (VAT 포함 금액).")
    c[2].markdown(f"**제품금액** {ui.won(qty * unit)}  \n**총비용** {ui.won(qty * unit + qty * fee)}")
    if st.form_submit_button("➕ 등록", type="primary"):
        db.add_trial(str(dt), sku, int(qty), unit, fee, memo)
        st.success("등록했습니다.")
        st.rerun()

trials = db.read_trials()
st.subheader("기록 (수정·삭제 가능)")
if trials.empty:
    st.info("등록된 체험단 기록이 없습니다.")
    st.stop()
ed = st.data_editor(trials.drop(columns=["id"]), num_rows="dynamic", width="stretch", hide_index=True,
                    column_config={"date": st.column_config.TextColumn("날짜(YYYY-MM-DD)"),
                                   "sku_id": st.column_config.SelectboxColumn("SKU", options=list(master["SKU ID"])),
                                   "qty": st.column_config.NumberColumn("개수", min_value=1, step=1),
                                   "unit_price": st.column_config.NumberColumn("제품가(공급가+VAT)", format="₩%.1f"),
                                   "agency_fee": st.column_config.NumberColumn("대행비(개당)", format="₩%.1f"),
                                   "memo": "업체/메모"}, key="trial_editor")
if st.button("💾 변경사항 저장"):
    t = ed.dropna(subset=["date", "sku_id", "qty"]).copy()
    bad = pd.to_datetime(t["date"], errors="coerce").isna()
    if bad.any():
        st.error("날짜 형식이 잘못된 행이 있습니다 (예: 2026-09-15).")
    else:
        t["date"] = pd.to_datetime(t["date"]).dt.strftime("%Y-%m-%d")
        t[["unit_price", "agency_fee"]] = t[["unit_price", "agency_fee"]].fillna(0)
        t["memo"] = t["memo"].fillna("")
        db.replace_trials(t)
        st.success("저장했습니다.")
        st.rerun()

trials = db.read_trials()
trials["제품금액"] = trials["qty"] * trials["unit_price"]
trials["총비용"] = trials["제품금액"] + trials["qty"] * trials["agency_fee"]
st.metric("총 투자금액", ui.won(trials["총비용"].sum()), help="Σ(개수×제품가) + Σ(개수×대행비)")

st.subheader("체험단 전후 판매 비교")
st.caption("체험단 전 7일 평균 vs 체험단일 포함 후 7일 평균(체험단 수량은 제외). "
           "회수 추정 = 추가 판매량 × 개당 공헌이익(매입원가−원가) ÷ 체험단 총비용. 판매 증가가 모두 체험단 덕이라는 보장은 없으니 참고용으로 보세요.")
last = daily["date"].max()
mi = master.set_index("SKU ID")
rows = []
for r in trials.itertuples():
    uc = float(sup.get(r.sku_id, 0)) - float(mi["원가"].get(r.sku_id, 0))
    e = M.trial_effect(daily, r.sku_id, r.date, r.qty, r.총비용, uc, last)
    rows.append({"날짜": r.date, "품목": names.get(r.sku_id, r.sku_id), "개수": r.qty, "총비용": r.총비용,
                 "전 7일 평균": e["전7일평균"], "후 7일 평균": e["후7일평균"], "증감": e["증감"],
                 "추가판매(7일)": e["추가판매(7일)"], "회수추정액": e["회수추정액"], "회수율": e["회수율"],
                 "상태": "완료" if e["후기간완료"] else "후 7일 데이터 부족"})
res = pd.DataFrame(rows)
st.dataframe(res, hide_index=True, width="stretch", column_config={
    "총비용": st.column_config.NumberColumn(format="₩%d"), "회수추정액": st.column_config.NumberColumn(format="₩%d"),
    "전 7일 평균": st.column_config.NumberColumn(format="%.2f"), "후 7일 평균": st.column_config.NumberColumn(format="%.2f"),
    "증감": st.column_config.NumberColumn(format="percent"), "회수율": st.column_config.NumberColumn(format="percent"),
    "추가판매(7일)": st.column_config.NumberColumn(format="%.1f")})
