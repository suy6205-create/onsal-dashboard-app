"""Streamlit 공통 UI: 페이지 초기화, 포맷, KPI 카드, 광고 필터."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import config, db
from . import metrics as M

PLOT_CFG = {"displaylogo": False}


# ---------------------------------------------------------------- 포맷
def won(x) -> str:
    return "-" if x is None or pd.isna(x) else f"₩{x:,.0f}"


def pct(x, digits=1) -> str:
    return "-" if x is None or pd.isna(x) else f"{x*100:.{digits}f}%"


def num(x) -> str:
    return "-" if x is None or pd.isna(x) else f"{x:,.0f}"


def mult(x) -> str:
    """ROAS 배수 표기: 4.06 -> '406.0% (4.06배)' 대신 간단히 퍼센트."""
    return "-" if x is None or pd.isna(x) else f"{x*100:,.1f}%"


def delta_txt(cur, prev) -> str | None:
    c = M.pct_change(cur, prev)
    return None if c is None else f"{c*100:+.1f}%"


def kpi(col, label: str, value: str, cur=None, prev=None, prev_week=None, help: str = "",
        inverse: bool = False, cap: str = "전주 동요일 대비") -> None:
    """KPI 카드: 값 + 전일 대비(▲▼) + 전주 동요일 대비 캡션 + ⓘ 계산 근거 툴팁."""
    with col:
        st.metric(label, value, delta_txt(cur, prev), delta_color="inverse" if inverse else "normal",
                  help=help or None)
        wk = delta_txt(cur, prev_week)
        st.caption(f"{cap} {wk}" if wk else f"{cap} -")


def card(col, label: str, value: str, help: str = "", delta: str | None = None, inverse: bool = False):
    with col:
        st.metric(label, value, delta, delta_color="inverse" if inverse else "normal", help=help or None)


def headline(lines: list[str]) -> None:
    for ln in lines:
        st.info("💡 " + ln)


# ---------------------------------------------------------------- 초기화 / 데이터
_CSS = """
<style>
div[data-testid="stMetricValue"] {font-size: 1.5rem;}
@media (max-width: 640px) {div[data-testid="stMetricValue"] {font-size: 1.25rem;}}
.block-container {padding-top: 2.2rem;}
</style>
"""


def _admin_password() -> str:
    """관리자 비밀번호: ADMIN_PASSWORD (없으면 APP_PASSWORD) — 환경변수 또는 Streamlit secrets. 없으면 빈 문자열."""
    import os
    for key in ("ADMIN_PASSWORD", "APP_PASSWORD"):
        pw = os.environ.get(key, "")
        if not pw:
            try:
                pw = str(st.secrets[key])
            except Exception:  # noqa: BLE001
                pw = ""
        if pw:
            return pw
    return ""


def is_admin() -> bool:
    """보기는 누구나, 업로드·설정·등록·수정은 관리자만. 비밀번호가 설정되지 않은 환경(로컬)은 항상 True."""
    return (not _admin_password()) or bool(st.session_state.get("_admin"))


def require_admin(what: str = "이 화면") -> None:
    """관리자가 아니면 안내 후 페이지 실행을 멈춘다."""
    if is_admin():
        return
    st.warning(f"🔐 {what}은(는) 관리자만 사용할 수 있습니다. 왼쪽 메뉴 아래 **관리자 로그인**에 비밀번호를 입력하세요. "
               "(다른 화면은 로그인 없이 볼 수 있습니다)")
    st.stop()


def _admin_sidebar() -> None:
    import hmac
    pw = _admin_password()
    if not pw:
        return
    with st.sidebar:
        if st.session_state.get("_admin"):
            st.caption("🔓 관리자 모드")
            if st.button("관리자 로그아웃", key="_admin_logout"):
                st.session_state["_admin"] = False
                st.rerun()
            return
        with st.expander("🔐 관리자 로그인 (업로드·등록·설정)"):
            typed = st.text_input("비밀번호", type="password", key="_admin_pw_input")
            if typed:
                if hmac.compare_digest(typed.encode(), pw.encode()):
                    st.session_state["_admin"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 맞지 않습니다.")


def _storage_badge() -> None:
    """어떤 저장소를 쓰는지 사이드바에 표시. 온라인 서버가 임시 저장소를 쓰면 경고."""
    try:
        if db.is_remote():
            st.sidebar.caption("💾 저장소: 온라인 DB (데이터 유지됨)")
        elif str(db.ROOT).startswith("/mount"):
            st.sidebar.error("⚠️ 온라인 DB에 연결되지 않았습니다. 지금 임시 저장소를 쓰는 중이라 업로드한 데이터가 "
                             "서버 재시작 시 사라집니다. Streamlit 앱 설정 → Secrets 의 DATABASE_URL 을 확인하세요.")
        else:
            st.sidebar.caption("💾 저장소: 이 PC의 로컬 파일")
    except Exception:  # noqa: BLE001
        pass


def setup(title: str, icon: str = "📊") -> dict:
    st.set_page_config(page_title=f"온살 · {title}", page_icon=icon, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)
    _admin_sidebar()
    _storage_badge()
    db.init_db()
    cfg = config.load_settings()
    st.title(f"{icon} {title}")
    return cfg


def load_all(cfg: dict) -> dict:
    return {
        "master": config.load_master(), "map": config.load_map(),
        "daily": db.read_sales_daily(), "ad": db.read_ad(), "trials": db.read_trials(),
    }


def no_data_stop(d: dict, need_ad: bool = False) -> None:
    if d["daily"].empty:
        st.warning("저장된 판매 데이터가 없습니다. '⚙️ 데이터 업로드·설정' 에서 로켓 판매 CSV를 올리거나 "
                   "`python scripts/migrate_legacy.py` 로 기존 보고서를 이관하세요.")
        st.stop()
    if need_ad and d["ad"].empty:
        st.warning("저장된 광고 데이터가 없습니다. '⚙️ 데이터 업로드·설정' 에서 광고 XLSX를 올려주세요.")
        st.stop()


def supply_by_sku(daily: pd.DataFrame) -> dict:
    if daily.empty:
        return {}
    last = daily.sort_values("date").groupby("sku_id").tail(1)
    return dict(zip(last["sku_id"], last["supply_cost"]))


def period_label(s: str, e: str) -> str:
    return s[5:].replace("-", "/") if s == e else f"{s[5:].replace('-', '/')}~{e[5:].replace('-', '/')}"


# ---------------------------------------------------------------- 광고 필터
STYPE = {"로켓배송": "Retail", "쿠팡윙": "3P"}
STYPE_LABEL = {v: k for k, v in STYPE.items()}


def ref_label(stype: str) -> str:
    """ROAS 기준선 이름. 로켓=손익분기(마진 기반), 윙=목표 ROAS(마진 정보 없음)."""
    return {"로켓배송": "손익분기 ROAS", "쿠팡윙": "목표 ROAS"}.get(stype, "기준 ROAS(로켓=손익분기·윙=목표)")


def _drop_nested(spans: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """다른 기간에 완전히 포함되는 기간(예: 월간 파일 안의 주간·일자 파일)은 이중 집계되므로 제외."""
    keep, dropped = [], []
    for sp in spans:
        if any(o != sp and o[0] <= sp[0] and o[1] >= sp[1] for o in spans):
            dropped.append(sp)
        else:
            keep.append(sp)
    return keep, dropped


def type_cfg(cfg: dict, code: str) -> dict:
    """판매방식별 기준값. 로켓(Retail)은 기본 키, 윙(3P)은 wing_ 접두 키로 덮어쓴다."""
    c = dict(cfg)
    if code == "3P":
        for k in ("exclude_min_cost", "min_clicks", "bid_up_max_impressions"):
            if cfg.get(f"wing_{k}") is not None:
                c[k] = cfg[f"wing_{k}"]
    return c


def _set_range(rkey: str, s: str, e: str) -> None:
    st.session_state[rkey] = (pd.Timestamp(s).date(), pd.Timestamp(e).date())


def _quick_cb(key: str, optmap: dict) -> None:
    sel = st.session_state.get(f"{key}_quick")
    if sel in optmap:
        _set_range(f"{key}_rng", *optmap[sel])
    st.session_state[f"{key}_quick"] = "직접 입력"          # 다시 같은 항목을 고를 수 있게 되돌림


def period_kind(s: str, e: str) -> str:
    n = (pd.Timestamp(e) - pd.Timestamp(s)).days + 1
    return "월간" if n >= 28 else "주간" if n == 7 else "일자" if n == 1 else "기간"


def ad_filters(d: dict, cfg: dict, key: str, allow_sale_type: bool = True,
               force_retail: bool = False, default_stype: str = "로켓배송",
               fixed_stype: str | None = None) -> dict | None:
    """기간(날짜 범위)/판매방식(로켓·윙)/전환 기준(1·14일) 선택 UI.
    반환: {df(prep_ad 결과), start, end, window, stype(라벨), kept}."""
    ad = d["ad"]
    if ad.empty:
        st.warning("저장된 광고 데이터가 없습니다. '📤 파일 업로드·설정' 에서 광고 XLSX를 올려주세요.")
        return None
    periods = ad[["period_start", "period_end"]].drop_duplicates().sort_values("period_start")
    lo, hi = periods["period_start"].min(), periods["period_end"].max()
    lo_d, hi_d = pd.Timestamp(lo).date(), pd.Timestamp(hi).date()
    allp = [(r.period_start, r.period_end) for r in periods.itertuples()]
    rkey = f"{key}_rng"
    cur = st.session_state.get(rkey)
    if not (isinstance(cur, (tuple, list)) and 1 <= len(cur) <= 2 and all(lo_d <= x <= hi_d for x in cur)):
        st.session_state[rkey] = (lo_d, hi_d)                   # 처음이거나 데이터 범위를 벗어났으면 전체 기간
    quick = {"전체 기간": (lo, hi)}
    for sp in allp:
        if sp[0] != sp[1]:
            quick[f"{period_label(*sp)} · {period_kind(*sp)}({(pd.Timestamp(sp[1]) - pd.Timestamp(sp[0])).days + 1}일)"] = sp
    cq, c1, c2, c3 = st.columns([2.2, 2.2, 1.8, 1.2])
    cq.selectbox("빠른 선택 (저장된 기간)", ["직접 입력"] + list(quick), key=f"{key}_quick",
                 on_change=_quick_cb, args=(key, quick),
                 help="업로드한 주간·월간 파일의 기간을 한 번에 선택합니다. 고르면 옆의 날짜가 자동으로 바뀝니다.")
    rng = c1.date_input("기간 (시작일 ~ 종료일)", min_value=lo_d, max_value=hi_d, key=rkey,
                        help="일자 파일은 날짜별로 걸러지지만, 주간·월간 파일은 일자별로 나눌 수 없어 "
                             "선택한 기간 안에 파일 전체가 들어올 때만 포함됩니다.")
    s0, e0 = (rng[0], rng[-1]) if isinstance(rng, (tuple, list)) and len(rng) else (rng, rng)
    s_sel, e_sel = str(s0), str(e0)
    if fixed_stype:
        stype = fixed_stype
        c2.markdown(f"판매방식: **{fixed_stype}**")
    elif force_retail or not allow_sale_type:
        stype = "로켓배송"
        c2.markdown("판매방식: **로켓배송(Retail)**")
    else:
        opts = ["로켓배송", "쿠팡윙", "전체"]
        stype = c2.radio("판매방식", opts, index=opts.index(default_stype), horizontal=True, key=f"{key}_st",
                         help="로켓배송=Retail(로켓 판매 상품 광고), 쿠팡윙=3P(판매자배송 광고)")
    default_w = 14 if int(cfg["attribution_days"]) == 14 else 1
    window = c3.radio("전환 기준", [14, 1], index=0 if default_w == 14 else 1, horizontal=True,
                      format_func=lambda x: f"{x}일", key=f"{key}_w",
                      help="광고 클릭/노출 후 N일 이내 발생한 주문을 광고 성과로 인정")
    inside = [sp for sp in allp if sp[0] >= s_sel and sp[1] <= e_sel]
    partial = [sp for sp in allp if sp not in inside and sp[0] <= e_sel and sp[1] >= s_sel]
    kept, dropped = _drop_nested(inside)
    if partial:
        st.warning("선택 기간과 일부만 겹쳐 **제외된 파일**: " + ", ".join(period_label(*sp) for sp in partial)
                   + " — 주간·월간 파일은 일자별로 나눌 수 없습니다. 아래 버튼으로 파일 전체 기간을 바로 볼 수 있어요. "
                     "하루 단위로 보려면 일자별 광고 파일(시작일=종료일)을 올려야 합니다.")
        bc = st.columns(min(len(partial), 4))
        for i, sp in enumerate(partial[:4]):
            bc[i].button(f"👉 {period_label(*sp)} {period_kind(*sp)} 전체 보기", key=f"{key}_pb{i}",
                         on_click=_set_range, args=(rkey, sp[0], sp[1]))
    if dropped:
        st.caption("ℹ️ 더 큰 기간 파일에 포함되어 이중 집계를 막으려고 뺀 파일: "
                   + ", ".join(period_label(*sp) for sp in dropped))
    if not kept:
        st.info("선택한 기간에 포함되는 광고 데이터가 없습니다. 기간을 조정하세요.")
        return None
    idx = pd.MultiIndex.from_frame(ad[["period_start", "period_end"]])
    df = ad[idx.isin(kept)]
    if stype != "전체":
        df = df[df["sale_type"] == STYPE[stype]]
    spans = sorted(kept)
    for a, b in zip(spans, spans[1:]):
        if b[0] <= a[1]:
            st.warning("포함된 광고 기간이 서로 겹칩니다. 합계가 이중 집계될 수 있어요.")
            break
    p = M.prep_ad(df, window, d["map"], d["master"], cfg["default_breakeven_roas"], supply_by_sku(d["daily"]),
                   cfg.get("wing_target_roas"))
    return {"df": p, "start": min(sp[0] for sp in kept), "end": max(sp[1] for sp in kept),
            "window": window, "stype": stype, "kept": kept}


def apply_extra_filters(p: pd.DataFrame, key: str, campaign=True, group=True, placement=True,
                        keyword=False) -> pd.DataFrame:
    """키워드 검색 + 캠페인/광고그룹/노출지면 추가 필터."""
    if keyword:
        q = st.text_input("🔎 키워드 검색 (쉼표로 여러 개, 예: 비타민, 히알루론)", key=f"{key}_kwq",
                          help="검색 영역 키워드에 해당 글자가 포함된 행만 보여줍니다. 비워두면 전체.")
        terms = [t.strip().lower() for t in q.split(",") if t.strip()]
        if terms:
            kwl = p["keyword"].str.lower()
            p = p[kwl.apply(lambda k: any(t in k for t in terms))]
    cols = st.columns(3)
    if campaign and len(p):
        v = cols[0].multiselect("캠페인", sorted(p["campaign"].unique()), key=f"{key}_camp")
        if v:
            p = p[p["campaign"].isin(v)]
    if group and len(p):
        v = cols[1].multiselect("광고그룹", sorted(p["ad_group"].unique()), key=f"{key}_grp")
        if v:
            p = p[p["ad_group"].isin(v)]
    if placement and len(p):
        v = cols[2].multiselect("노출 지면", sorted(p["placement_group"].unique()), key=f"{key}_pl")
        if v:
            p = p[p["placement_group"].isin(v)]
    return p


# ---------------------------------------------------------------- 차트
def style(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(template="plotly_white", height=height, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=-0.2), hovermode="closest")
    return fig


def show(fig: go.Figure, height: int = 380) -> None:
    st.plotly_chart(style(fig, height), width="stretch", config=PLOT_CFG)


def signal_color(sig: str) -> str:
    return {"🔴": "#fde2e2", "🟡": "#fff4cc", "🟢": "#e1f5e5"}.get(sig, "")
