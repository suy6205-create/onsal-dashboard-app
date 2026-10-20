"""📋 발주 관리 — 발주에 필요한 정보를 한눈에 보고, 체크·수량 입력으로 발주서를 만든다"""
from datetime import date

import pandas as pd
import streamlit as st

from src import config, db, gsheet
from src import metrics as M
from src import ui
try:
    from src.purchase_order import build_po_xlsx, po_filename
    PO_IMPORT_ERROR = None
except Exception as _e:   # noqa: BLE001  (서버가 오류 내용을 가리므로 화면에 직접 보여준다)
    build_po_xlsx = po_filename = None
    PO_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

cfg = ui.setup("발주 관리", "📋")
d = ui.load_all(cfg)
ui.no_data_stop(d)
daily, master = d["daily"], d["master"]
dates = sorted(daily["date"].unique())
asof_s = st.sidebar.selectbox("기준일", dates[::-1])
asof = pd.Timestamp(asof_s)
sku = M.sku_table(daily, master, asof, cfg)
op = sku[sku["운영중"]]
mi = master.set_index("SKU ID") if len(master) else master
actual = ui.supply_by_sku(daily)             # 판매 데이터의 매입원가 = 쿠팡 지급 공급가(VAT 제외)

t_over, t_po, t_sheet = st.tabs(["📊 발주 정보 한눈에", "📝 발주서 만들기", "🔄 구글 시트에서 가져오기"])

# ------------------------------------------------------------ 한눈에 보기
with t_over:
    def _m(s_, col):
        return str(mi[col].get(s_, "")) if len(mi) and s_ in mi.index else ""
    ov = pd.DataFrame({
        "신호": op["신호"], "브랜드": op["브랜드"], "품목": op["품목"], "SKU ID": op["sku_id"],
        "회사 코드": [_m(s_, "회사코드") for s_ in op["sku_id"]], "유통기한": [_m(s_, "유통기한") for s_ in op["sku_id"]],
        "현재재고": op["현재재고"], "7일평균": op["7일평균"].round(2),
        "소진예상일": op["소진예상일"].apply(lambda v: "판매없음" if v is None or pd.isna(v) else f"{v:.1f}일"),
        "발주권장": op["발주권장"],
        "쿠팡 공급가(VAT 포함)": [round(actual[s_] * cfg["vat"]) if s_ in actual else None for s_ in op["sku_id"]],
    })
    ov["발주 정보"] = ["✅" if (a and b) else "⚠️ 빠짐" for a, b in zip(ov["회사 코드"], ov["유통기한"])]
    need = op[op["발주권장"] > 0]
    ui.headline([f"발주 권장 상품 {len(need)}개" + (f": {', '.join(need['품목'].head(3))}" if len(need) else " — 없음")])
    miss = ov[ov["발주 정보"] != "✅"]
    if len(miss):
        st.warning(f"회사 코드 또는 유통기한이 비어 있는 상품 {len(miss)}개: {', '.join(miss['품목'].head(5))}. "
                   "'구글 시트에서 가져오기' 탭이나 파일 업로드·설정 → 상품 마스터에서 채우세요.")
    st.dataframe(ov, hide_index=True, width="stretch", column_config={
        "쿠팡 공급가(VAT 포함)": st.column_config.NumberColumn(format="₩%d", help="최근 판매 데이터의 매입원가(VAT 제외) × 1.1"),
        "발주권장": st.column_config.NumberColumn(help=f"max(0, 7일평균 × 목표재고일수({cfg['target_stock_days']}일) − 현재재고)")})

# ------------------------------------------------------------ 발주서 만들기
with t_po:
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
    vid, vname, center = cfg["po_vendor_id"], cfg["po_vendor_name"], cfg["po_center"]   # 고정값 (기준값 탭에서 변경 가능)
    if len(ok_idx) == 0:
        st.info("위 표에서 발주할 상품의 '발주'를 체크하고 '발주수량'을 입력하면 발주서를 내려받을 수 있습니다.")
    else:
        extra = st.checkbox("추가 발주 (파일명 끝에 _추가)", value=False)
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


# ------------------------------------------------------------ 구글 시트 연동
with t_sheet:
    st.caption("판매가·쿠팡 공급가·유통기한·회사 코드를 정리해 둔 구글 시트를 읽어 상품 마스터에 맞춥니다. "
               "시트 공유는 '링크가 있는 모든 사용자(뷰어)'여야 합니다. 쿠팡 공급가(VAT 포함)가 있으면 수수료율을 자동으로 역산합니다.")
    url = st.text_input("구글 시트 주소", cfg.get("sheet_url", ""), key="sheet_url_in",
                        placeholder="https://docs.google.com/spreadsheets/d/…")
    if ui.is_admin():
        if url.strip() != cfg.get("sheet_url", "") and st.button("💾 이 주소를 기억하기"):
            config.save_settings({**cfg, "sheet_url": url.strip()})
            st.rerun()
    if not url.strip():
        st.info("시트 주소를 붙여넣으면 내용을 읽어 옵니다.")
    else:
        if st.button("🔄 시트 다시 읽기"):
            gsheet.clear_cache()
        try:
            raw = gsheet.fetch_sheet(url)
            tbl, mp = gsheet.read_table(raw)
        except gsheet.SheetError as ex:
            st.error(str(ex))
            st.stop()
        names = {"sku": "SKU ID", "name": "품목", "price": "판매가", "supply": "쿠팡 공급가", "cost": "원가", "shelf": "유통기한", "code": "회사 코드"}
        st.success("읽은 열: " + " · ".join(f"{names[k]}→「{v}」" for k, v in mp.items()))
        lack = [names[k] for k in names if k not in mp and not (k == "sku" and "name" in mp)]
        if "sku" not in mp and "name" in mp:
            st.caption("ℹ️ 시트에 SKU ID 열이 없어서 제품명을 판매 데이터의 SKU 이름과 맞춰 연결합니다 (띄어쓰기가 달라도 인식).")
        if lack:
            st.warning("시트에서 찾지 못한 열: " + ", ".join(lack) + " (있는 열만 반영합니다)")
        full = config.load_master()
        names_by_sku: dict = {}                          # 시트에 SKU ID 열이 없으면 판매 데이터의 SKU 이름과 제품명을 맞춘다
        for r_ in db.read_sales_daily().sort_values("date").drop_duplicates("sku_id", keep="last").itertuples():
            names_by_sku.setdefault(r_.sku_id, []).append(r_.sku_name)
        for _, r_ in full.iterrows():
            names_by_sku.setdefault(r_["SKU ID"], []).append(r_["품목"])
        try:
            ups = gsheet.to_updates(tbl, mp, names_by_sku)
        except gsheet.SheetError as ex:
            st.error(str(ex))
            st.stop()
        with_name = st.checkbox("품목 이름도 시트 값으로 바꾸기", value=False, key="sheet_with_name",
                                help="기본은 꺼짐: 마스터의 짧은 품목명을 그대로 둡니다")
        fields = gsheet.FIELDS if with_name else gsheet.DEFAULT_FIELDS
        diff = gsheet.diff_with_master(ups, full, fields)
        st.markdown(f"시트의 제품 중 **{len(ups)}개**가 우리 상품(SKU)과 연결됐고, 바뀌는 칸은 **{len(diff)}개**입니다.")
        snap = gsheet.sheet_products(tbl, mp)           # 시트의 모든 제품 (판매 전 제품 포함)
        unm = ups.attrs.get("unmatched", [])
        if unm:
            with st.expander(f"아직 판매 데이터에 없는 시트 제품 {len(unm)}개 — 판매가 시작되면 아래 정보가 자동으로 채워집니다"):
                det = snap[snap["시트제품명"].isin([n for n, _ in unm])].rename(columns={"판매수수료율": "수수료율"})
                st.dataframe(det, hide_index=True, width="stretch", column_config={
                    "판매가": st.column_config.NumberColumn(format="₩%d"), "원가": st.column_config.NumberColumn(format="₩%d"),
                    "수수료율": st.column_config.NumberColumn(format="percent")})
                st.caption("판매 CSV에 이 제품이 처음 나오는 날 상품 마스터에 자동 등록되면서, 시트의 판매가·원가·수수료율·유통기한·회사 코드가 함께 들어갑니다. "
                           "(아래 '시트 정보 저장'을 눌러 두어야 합니다)")
        if "code" in mp:
            codes = tbl[mp["code"]].astype(str).str.strip()
            dup = sorted(set(codes[codes.duplicated(keep=False) & (codes != "")]))
            if dup:
                st.warning("시트에서 같은 회사 코드가 여러 제품에 쓰였습니다: " + ", ".join(dup) + " — 오타일 수 있어요. 확인해 주세요.")
        if diff.empty:
            st.info("마스터와 시트의 값이 같습니다. 바뀔 내용이 없습니다.")
            if ui.is_admin() and st.button("📌 시트 정보 저장 (판매 전 제품 자동 채우기용)"):
                config.save_sheet_products(snap)
                st.success(f"시트 제품 {len(snap)}개의 정보를 저장했습니다.")
        else:
            st.dataframe(diff, hide_index=True, width="stretch")
            if ui.is_admin():
                if st.button("✅ 마스터에 반영", type="primary"):
                    new, n = gsheet.apply_updates(full, ups, fields)
                    config.save_master(new)
                    config.save_sheet_products(snap)         # 판매 전 제품도 나중에 자동으로 채우도록 시트 정보를 함께 저장
                    st.success(f"{n}개 칸을 마스터에 반영하고, 시트 제품 {len(snap)}개의 정보를 저장했습니다.")
                    st.rerun()
            else:
                st.caption("🔐 반영하려면 왼쪽 메뉴 아래 **관리자 로그인**이 필요합니다. (미리보기는 로그인 없이 볼 수 있어요)")
