"""⚙️ 데이터 업로드·설정"""
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import config, db, service
from src import loaders as L
from src.export import to_excel_bytes
from src import ui

cfg = ui.setup("파일 업로드·설정", "📤")
ui.require_admin("파일 업로드·설정 화면")
t_up, t_hist, t_master, t_map, t_cfg, t_exp = st.tabs(
    ["파일 업로드", "업로드 이력 · 누락 캘린더", "상품 마스터", "광고 매핑표", "기준값", "내보내기"])


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ------------------------------------------------------------ 업로드
with t_up:
    st.markdown("**① 판매 CSV(`basic_operation_rocket_*.csv`) ② 광고 XLSX(`*_pa_total_campaign_*.xlsx`)** 를 "
                "여러 개 한꺼번에 올려도 됩니다. 확인 후 [저장]을 누르세요. 같은 날짜/기간은 덮어씁니다.")
    files = st.file_uploader("파일 선택 (드래그앤드롭)", type=["csv", "xlsx"], accept_multiple_files=True)
    master, amap = config.load_master(), config.load_map()
    existing_periods = db.ad_periods()
    saves = []   # (kind, name, payload...)
    for i, fl in enumerate(files or []):
        name = fl.name
        raw = fl.getvalue()
        with st.container(border=True):
            st.markdown(f"**📄 {name}**")
            try:
                if name.lower().endswith(".csv"):
                    ps = L.parse_sales_csv(BytesIO(raw), cfg["brand"])
                    if ps.brand_rows == 0:
                        st.error(f"'{cfg['brand']}' 브랜드 행이 없습니다. (전체 {ps.total_rows}행) 브랜드명은 설정에서 바꿀 수 있어요.")
                        continue
                    fn = L.parse_sales_filename(name)
                    ns = service.new_skus(ps.daily)
                    have = set(db.read_sales_daily()["date"]) & set(ps.dates)
                    c = st.columns(4)
                    c[0].metric("인식된 날짜", f"{ps.dates[0]}" + (f" ~ {ps.dates[-1]}" if len(ps.dates) > 1 else ""))
                    c[1].metric(f"{cfg['brand']} 행 수", f"{ps.brand_rows} / {ps.total_rows}")
                    c[2].metric("센터 합산 후", f"{len(ps.daily)}건")
                    c[3].metric("신규 SKU", f"{len(ns)}개")
                    if fn and (fn[0], fn[1]) != (ps.dates[0], ps.dates[-1]):
                        st.warning(f"파일명 날짜({fn[0]}~{fn[1]})와 데이터 내 날짜({ps.dates[0]}~{ps.dates[-1]})가 다릅니다. 데이터 내 날짜를 사용합니다.")
                    if have:
                        st.info(f"이미 저장된 날짜 {len(have)}일은 덮어씁니다.")
                    if ns:
                        st.warning("신규 SKU는 상품 마스터에 자동 추가되며 '가격 미입력' 상태입니다: " + ", ".join(ns))
                    st.dataframe(ps.daily.head(20), hide_index=True, width="stretch")
                    saves.append(("sales", name, ps))
                else:
                    ad = L.parse_ad_xlsx(BytesIO(raw))
                    fn = L.parse_ad_filename(name)
                    c = st.columns(2)
                    s0 = c[0].date_input("기간 시작", value=_d(fn[0]) if fn else date.today(), key=f"s{i}",
                                         help="리포트 파일 안에는 날짜가 없어 파일명에서 읽었습니다. 틀리면 수정하세요.")
                    e0 = c[1].date_input("기간 종료", value=_d(fn[1]) if fn else date.today(), key=f"e{i}")
                    if not fn:
                        st.warning("파일명에서 기간을 읽지 못했습니다. 기간을 직접 지정해 주세요.")
                    s, e = str(s0), str(e0)
                    if s > e:
                        st.error("시작일이 종료일보다 늦습니다.")
                        continue
                    kind = "일자 데이터" if s == e else "기간 데이터(일자 차트에는 섞지 않음)"
                    draft = L.draft_ad_map(ad, master, cfg["brand"], amap)
                    unmapped = int((draft["SKU ID"] == "").sum())
                    cc = st.columns(4)
                    cc[0].metric("행 수", len(ad))
                    cc[1].metric("Retail / 3P", f"{(ad['sale_type'] == 'Retail').sum()} / {(ad['sale_type'] == '3P').sum()}")
                    cc[2].metric("광고비(전체)", ui.won(ad["cost"].sum()))
                    cc[3].metric("신규 매핑 후보 옵션", f"{len(draft)}개")
                    st.caption(f"저장 형태: {kind}")
                    if len(existing_periods):
                        ov = existing_periods[(existing_periods.period_start <= e) & (existing_periods.period_end >= s) &
                                              ~((existing_periods.period_start == s) & (existing_periods.period_end == e))]
                        if len(ov):
                            st.warning("이미 저장된 다른 기간과 겹칩니다 → 합산하면 광고비가 이중 집계될 수 있어요: "
                                       + ", ".join(f"{a}~{b}" for a, b in zip(ov.period_start, ov.period_end)))
                        if ((existing_periods.period_start == s) & (existing_periods.period_end == e)).any():
                            st.info("같은 기간이 이미 있어 덮어씁니다.")
                    if len(draft):
                        st.warning(f"매핑표에 없는 옵션 {len(draft)}개 → 이름으로 SKU·묶음수량을 추정해 초안으로 추가합니다"
                                   + (f" (그중 SKU 미확정 {unmapped}개)" if unmapped else "") + ". 광고 매핑표 탭에서 확정하세요.")
                    st.dataframe(ad.head(20), hide_index=True, width="stretch")
                    saves.append(("ad", name, ad, s, e))
            except L.FileFormatError as ex:
                st.error(str(ex))
            except Exception as ex:  # noqa: BLE001
                st.error(f"파일을 처리하는 중 오류가 났습니다: {ex}")
    if saves and st.button(f"💾 {len(saves)}개 파일 저장", type="primary"):
        for sv in saves:
            if sv[0] == "sales":
                new = service.ingest_sales(sv[2], sv[1])
                st.success(f"{sv[1]} 저장 완료" + (f" · 신규 SKU {len(new)}개 마스터 추가" if new else ""))
            else:
                n = service.ingest_ad(sv[2], sv[3], sv[4], sv[1], cfg["brand"])
                st.success(f"{sv[1]} 저장 완료 ({sv[3]}~{sv[4]})" + (f" · 매핑 초안 {n}개 추가" if n else ""))
        pend = service.pending_price_skus()
        if len(pend):
            st.warning("가격 미입력 SKU: " + ", ".join(pend["품목"]) + " — 상품 마스터 탭에서 입력하세요.")
    elif not files:
        st.info("파일을 올려주세요.")

# ------------------------------------------------------------ 이력·누락
with t_hist:
    up = db.read_uploads()
    st.subheader("업로드 이력")
    st.dataframe(up.rename(columns={"filename": "파일명", "kind": "구분", "period_start": "시작", "period_end": "종료",
                                    "n_rows": "행 수", "uploaded_at": "업로드 시각"}).drop(columns=["id"]),
                 hide_index=True, width="stretch")
    sd = db.read_sales_daily()
    if sd.empty:
        st.info("판매 데이터가 없습니다.")
    else:
        have = set(sd["date"])
        lo, hi = min(have), max(have)
        rng = pd.date_range(lo, hi)
        miss = [x.strftime("%Y-%m-%d") for x in rng if x.strftime("%Y-%m-%d") not in have]
        st.subheader("판매 데이터 누락 캘린더")
        st.caption(f"{lo} ~ {hi}: 누락 {len(miss)}일" + (" — " + ", ".join(m[5:] for m in miss[:20]) + (" …" if len(miss) > 20 else "") if miss else " (모두 있음)"))
        ad = db.read_ad()
        cover = set()
        if len(ad):
            for r in db.ad_periods().itertuples():
                cover |= {x.strftime("%Y-%m-%d") for x in pd.date_range(r.period_start, r.period_end)}
        for title, ok in (("판매", have), ("광고(일자·기간 파일이 덮는 날)", cover)):
            first = pd.Timestamp(lo) - pd.Timedelta(days=pd.Timestamp(lo).weekday())
            days = pd.date_range(first, pd.Timestamp(hi))
            wk = [(x - first).days // 7 for x in days]
            z = [[None] * 7 for _ in range(max(wk) + 1)]
            tx = [[""] * 7 for _ in range(max(wk) + 1)]
            for x, w in zip(days, wk):
                key = x.strftime("%Y-%m-%d")
                z[w][x.weekday()] = (1 if key in ok else 0) if key >= lo else None
                tx[w][x.weekday()] = x.strftime("%m/%d")
            fig = go.Figure(go.Heatmap(z=z, x=list("월화수목금토일"), y=[f"{(first + pd.Timedelta(days=7*i)).strftime('%m/%d')}주" for i in range(len(z))],
                                       text=tx, texttemplate="%{text}", xgap=3, ygap=3, showscale=False,
                                       colorscale=[[0, "#f4b6b6"], [1, "#b7e1c1"]], zmin=0, zmax=1,
                                       hovertemplate="%{text}<extra></extra>"))
            fig.update_layout(title=f"{title} (초록=있음, 빨강=없음)", yaxis=dict(autorange="reversed"))
            ui.show(fig, 120 + 38 * len(z))

# ------------------------------------------------------------ 마스터
with t_master:
    st.caption("가격·원가는 MD가 직접 입력합니다. 공급가(매입원가)는 판매 데이터에서 자동으로 가져오며, 변경되면 이력이 남습니다. "
               "판매수수료율은 참고용입니다(매입원가에 이미 반영).")
    m = config.load_master()
    ed = st.data_editor(m, num_rows="dynamic", width="stretch", hide_index=True, key="master_ed", column_config={
        "SKU ID": st.column_config.TextColumn(required=True), "운영중": st.column_config.SelectboxColumn(options=["Y", "N"]),
        "광고명키워드": st.column_config.TextColumn(help="광고 상품명에 이 단어가 있으면 이 SKU로 자동 매핑 (예: 비타민)")})
    if st.button("💾 마스터 저장"):
        e = ed.dropna(subset=["SKU ID"]).copy()
        e["SKU ID"] = e["SKU ID"].astype(str).str.strip()
        if e["SKU ID"].duplicated().any():
            st.error("SKU ID가 중복됩니다.")
        else:
            e = e.fillna({"판매가": 0, "할인": 0, "원가": 0, "판매수수료율": 0, "운영중": "Y", "품목": "", "광고명키워드": ""})
            config.save_master(e)
            st.success("저장했습니다.")
    chg = db.read_sales_daily()
    if len(chg):
        from src import metrics as M
        ch = M.supply_price_changes(chg)
        if len(ch):
            st.subheader("매입원가(공급가) 변경 이력")
            st.dataframe(ch.rename(columns={"sku_id": "SKU ID", "date": "변경일", "prev": "이전", "supply_cost": "변경 후"}),
                         hide_index=True, width="stretch")

# ------------------------------------------------------------ 매핑표
with t_map:
    st.caption("광고 리포트의 옵션ID와 로켓 SKU ID는 서로 다른 체계라 이 표로 연결합니다. 묶음수량(1개/2개/…6개)도 여기서 관리합니다. "
               "'자동추정' 항목은 이름 규칙으로 만든 초안이니 확인 후 비고를 지워 확정하세요.")
    mp = config.load_map()
    master = config.load_master()
    ed = st.data_editor(mp, num_rows="dynamic", width="stretch", hide_index=True, key="map_ed", column_config={
        "광고옵션ID": st.column_config.TextColumn(required=True),
        "SKU ID": st.column_config.SelectboxColumn(options=[""] + list(master["SKU ID"])),
        "묶음수량": st.column_config.NumberColumn(min_value=1, step=1)})
    c = st.columns([1, 1, 3])
    if c[0].button("💾 매핑표 저장"):
        e = ed.dropna(subset=["광고옵션ID"]).copy()
        e["광고옵션ID"] = e["광고옵션ID"].astype(str).str.strip()
        e["묶음수량"] = e["묶음수량"].fillna(1).astype(int)
        e = e.fillna("")
        config.save_map(e.drop_duplicates("광고옵션ID", keep="last"))
        st.success("저장했습니다.")
    if c[1].button("🔄 초안 다시 생성"):
        ad = db.read_ad()
        if ad.empty:
            st.info("광고 데이터가 없습니다.")
        else:
            dr = L.draft_ad_map(ad, master, cfg["brand"], mp)
            if len(dr):
                config.save_map(pd.concat([mp, dr], ignore_index=True))
                st.success(f"{len(dr)}개 추가")
                st.rerun()
            else:
                st.info("새로 추가할 옵션이 없습니다.")
    n_un = int((mp["SKU ID"].astype(str).str.strip() == "").sum())
    if n_un:
        st.warning(f"SKU가 비어 있는(미매핑) 옵션 {n_un}개 — 통합 분석에서 '미매핑'으로 집계됩니다.")

# ------------------------------------------------------------ 기준값
with t_cfg:
    c = st.columns(3)
    new = dict(cfg)
    new["brand"] = c[0].text_input("판매 데이터 필터 브랜드", cfg["brand"])
    new["attribution_days"] = c[1].radio("광고 전환 기준(기본)", [14, 1], index=0 if cfg["attribution_days"] == 14 else 1, horizontal=True)
    new["target_stock_days"] = c[2].number_input("목표 재고일수 (발주 권장 기준)", 1, 90, int(cfg["target_stock_days"]))
    c = st.columns(3)
    new["stock_red_days"] = c[0].number_input("🔴 재고소진 예상일 이하", 1, 60, int(cfg["stock_red_days"]))
    new["stock_yellow_days"] = c[1].number_input("🟡 재고소진 예상일 이하", 1, 90, int(cfg["stock_yellow_days"]))
    new["drop_pct"] = c[2].number_input("판매 급감 기준(%)", 1, 100, int(cfg["drop_pct"]), help="7일평균이 직전 7일 대비 이 % 이상 줄면 경고")
    c = st.columns(3)
    new["exclude_min_cost"] = c[0].number_input("🚀 로켓: 제외 키워드 기준 광고비(₩)", 0, 1000000, int(cfg["exclude_min_cost"]), step=1000)
    new["min_clicks"] = c[1].number_input("🚀 로켓: 최소 클릭 수(미만=데이터 부족)", 0, 1000, int(cfg["min_clicks"]))
    new["bid_up_max_impressions"] = c[2].number_input("🚀 로켓: 입찰 상향 후보 노출 상한", 0, 10_000_000, int(cfg["bid_up_max_impressions"]), step=100)
    c = st.columns(3)
    new["wing_exclude_min_cost"] = c[0].number_input("🪽 윙: 제외 키워드 기준 광고비(₩)", 0, 1000000, int(cfg.get("wing_exclude_min_cost", 1500)), step=100,
                                                      help="윙은 키워드 수가 많고 개당 광고비가 작아 로켓보다 낮게 둡니다")
    new["wing_min_clicks"] = c[1].number_input("🪽 윙: 최소 클릭 수(미만=데이터 부족)", 0, 1000, int(cfg.get("wing_min_clicks", 10)))
    new["wing_bid_up_max_impressions"] = c[2].number_input("🪽 윙: 입찰 상향 후보 노출 상한", 0, 10_000_000, int(cfg.get("wing_bid_up_max_impressions", 1000)), step=100)
    c = st.columns(3)
    new["trial_fee_per_unit"] = c[0].number_input("체험단 대행비 기본값(개당, VAT 별도, 0=매번 직접 입력)", 0, 1_000_000, int(cfg["trial_fee_per_unit"]), step=1000)
    new["vat"] = c[1].number_input("VAT 배수", 1.0, 2.0, float(cfg["vat"]), step=0.05)
    new["wing_target_roas"] = c[1].number_input("쿠팡윙 목표 ROAS(배, 3.0=300%)", 0.5, 20.0, float(cfg.get("wing_target_roas", 3.0)), step=0.1,
                                                 help="윙 광고는 마진 정보가 없어 손익분기 대신 이 값을 기준선으로 씁니다")
    new["default_breakeven_roas"] = c[2].number_input("임시 손익분기 ROAS(배)", 0.5, 20.0, float(cfg["default_breakeven_roas"]), step=0.1,
                                                       help="상품 마스터에 가격·원가가 없을 때만 사용")
    kg = pd.DataFrame([{"그룹": k, "포함 단어(쉼표 구분)": ", ".join(v)} for k, v in (cfg.get("keyword_groups") or {}).items()])
    st.markdown("**키워드 상품군 규칙**")
    kge = st.data_editor(kg if len(kg) else pd.DataFrame({"그룹": [""], "포함 단어(쉼표 구분)": [""]}), num_rows="dynamic",
                         width="stretch", hide_index=True, key="kg_ed")
    if st.button("💾 기준값 저장", type="primary"):
        new["keyword_groups"] = {r["그룹"]: [w.strip() for w in str(r["포함 단어(쉼표 구분)"]).split(",") if w.strip()]
                                 for _, r in kge.iterrows() if str(r["그룹"]).strip()}
        config.save_settings(new)
        st.success("저장했습니다. 다른 화면에서 바로 반영됩니다.")

# ------------------------------------------------------------ 내보내기
with t_exp:
    st.caption("누적된 전체 데이터를 엑셀 한 파일로 내려받습니다.")
    sheets = {"판매_일자합산": db.read_sales_daily(), "판매_센터별": db.read_sales_center(), "광고": db.read_ad(),
              "체험단": db.read_trials(), "상품마스터": config.load_master(), "광고매핑": config.load_map()}
    st.write({k: f"{len(v):,}행" for k, v in sheets.items()})
    if st.button("엑셀 파일 만들기"):
        st.session_state["export_bytes"] = to_excel_bytes(sheets)
    if "export_bytes" in st.session_state:
        st.download_button("⬇️ 전체 데이터 엑셀 다운로드", st.session_state["export_bytes"],
                           file_name=f"온살_전체데이터_{date.today()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
