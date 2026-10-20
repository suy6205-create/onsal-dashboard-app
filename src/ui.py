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
    try:
        db.init_db()
        cfg = config.load_settings()
    except Exception as e:  # noqa: BLE001  (서버는 오류 내용을 가리므로 직접 안내)
        st.title(f"{icon} {title}")
        st.error("데이터베이스에 연결하지 못했습니다. 무료 DB 가 잠들었다 깨어나는 중이면 잠시 후 다시 열립니다.")
        st.caption(f"원인: {type(e).__name__}: {str(e).strip().splitlines()[0][:600] if str(e).strip() else ''}")
        if st.button("🔄 다시 시도", type="primary"):
            st.rerun()
        st.stop()
    st.title(f"{icon} {title}")
    return cfg


def load_all(cfg: dict) -> dict:
    """데이터를 읽고, 사이드바에서 고른 브랜드(전체/브랜드별)로 판매·마스터·체험단·광고를 걸러서 돌려준다."""
    d = {
        "master": config.load_master(), "map": config.load_map(),
        "daily": db.read_sales_daily(), "ad": db.read_ad(), "trials": db.read_trials(),
    }
    brands = config.brand_list(cfg)
    d["brands"] = brands
    if len(brands) <= 1:
        d["brand_sel"] = "전체"
        return d
    sel = st.sidebar.selectbox("🏷️ 브랜드", ["전체"] + brands, key="brand_sel",
                               help="판매·재고·광고·체험단 화면을 브랜드별로 나눠서 봅니다. '전체'는 모든 브랜드 합산.")
    d["brand_sel"] = sel
    if sel == "전체":
        return d
    master_all = d["master"]
    d["ad"] = d["ad"][M.ad_row_brand(d["ad"], d["map"], master_all, brands).eq(sel).to_numpy()] if len(d["ad"]) else d["ad"]
    d["master"] = master_all[master_all["브랜드"] == sel].reset_index(drop=True)
    skus = set(d["master"]["SKU ID"])
    d["daily"] = d["daily"][d["daily"]["brand"] == sel].reset_index(drop=True)
    d["trials"] = d["trials"][d["trials"]["sku_id"].isin(skus)].reset_index(drop=True)
    return d


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


# ---------------------------------------------------------------- 광고 필터 (주 단위 / 일 단위)
def ad_filters(d: dict, cfg: dict, key: str) -> dict | None:
    """보기 단위(주/일) · 기간 · 전환 기준(1/14일) 선택.
    저장 규칙: 광고 데이터는 '일 단위(하루)'와 '주 단위(월~일)' 파일만 저장된다. 주 파일이 있는 주는 그 파일을,
    없는 주(진행 중)는 일 데이터를 합쳐서 한 번씩만 센다.
    반환: {df(prep_ad 결과), start, end, window, label, unit, kept}"""
    ad = d["ad"]
    if ad.empty:
        st.warning("저장된 광고 데이터가 없습니다. '📤 파일 업로드·설정' 에서 광고 XLSX(하루 또는 월~일 한 주)를 올려주세요.")
        return None
    c1, c2 = st.columns([1.6, 1.2])
    unit = c1.radio("보기 단위", ["주 단위", "일 단위"], horizontal=True, key=f"{key}_unit",
                    help="주 단위=월~일 한 주 합계(진행 중인 주는 지금까지 올린 일 데이터 합), 일 단위=하루 단위 파일이 있는 날짜")
    default_w = 14 if int(cfg["attribution_days"]) == 14 else 1
    window = c2.radio("전환 기준", [14, 1], index=0 if default_w == 14 else 1, horizontal=True,
                      format_func=lambda x: f"{x}일", key=f"{key}_w",
                      help="광고 클릭 후 N일 안에 생긴 주문을 광고 성과로 인정합니다. 쿠팡 광고 리포트는 1일·14일 두 가지만 제공해요(7일 기준은 없음). 14일은 최근 주에는 아직 덜 쌓여 있을 수 있습니다.")
    p_all = M.prep_ad(ad, window, d["map"], d["master"], cfg["default_breakeven_roas"], supply_by_sku(d["daily"]))
    t = M.tag_ad_periods(p_all)
    n_legacy = len(set(zip(p_all["period_start"], p_all["period_end"]))) - len(set(zip(t["period_start"], t["period_end"])))
    if n_legacy > 0:
        st.caption(f"ℹ️ 일·주 단위가 아닌 예전 기간 데이터 {n_legacy}건은 계산에서 제외했습니다 "
                   "(파일 업로드·설정 → 광고 데이터 관리에서 지울 수 있어요).")
    with st.expander("📅 광고 데이터 수집 현황 (최근 8주)"):
        cov = M.ad_coverage(t)
        st.dataframe(cov[["주", "주 단위 파일", "일 단위 파일"]], hide_index=True, width="stretch")
        st.caption("주 단위 파일이 있으면 그 주는 주 파일로 계산합니다. 아직 끝나지 않은 주는 하루씩 올린 일 파일을 합칩니다.")
    if t.empty:
        st.info("일·주 단위 광고 데이터가 아직 없습니다. 하루 또는 월~일 한 주 단위로 내려받아 올려주세요.")
        return None

    if unit == "주 단위":
        wf = M.ad_weekly_frame(t)
        wk = wf.groupby("week").agg(n_days=("n_days", "max"), weekly=("kind", lambda k: (k == "주").any())).reset_index().sort_values("week")
        labels = {r.week: f"{M.week_label(r.week)} · " + ("주 파일" if r.weekly else f"진행 중 · 일 {int(r.n_days)}/7") for r in wk.itertuples()}
        opts = list(labels.values())
        kskey = f"{key}_wk"
        default = opts[-4:]
        st.session_state[kskey] = [x for x in st.session_state.get(kskey, default) if x in opts] or default
        sel = st.multiselect("주 선택 (여러 주 선택 가능)", opts, key=kskey)
        if not sel:
            st.info("보고 싶은 주를 선택하세요.")
            return None
        weeks = [w for w, lab in labels.items() if lab in sel]
        df = wf[wf["week"].isin(weeks)]
        label = f"주 단위 {len(weeks)}주 ({M.week_label(min(weeks))[:5]} ~ {M.week_label(max(weeks))[-5:]})" if len(weeks) > 1 else f"주 단위 {M.week_label(weeks[0])}"
    else:
        dd = t[t["kind"] == "일"]
        if dd.empty:
            st.info("일 단위(하루) 파일이 없습니다. 주 단위 파일은 하루씩 나눌 수 없어서 '주 단위'로 보세요.")
            return None
        lo_d, hi_d = pd.Timestamp(dd["period_start"].min()).date(), pd.Timestamp(dd["period_start"].max()).date()
        rkey = f"{key}_dr"
        cur = st.session_state.get(rkey)
        if not (isinstance(cur, (tuple, list)) and 1 <= len(cur) <= 2 and all(lo_d <= x <= hi_d for x in cur)):
            st.session_state[rkey] = (max(lo_d, hi_d - pd.Timedelta(days=6)), hi_d)
        rng = st.date_input("날짜 범위", min_value=lo_d, max_value=hi_d, key=rkey,
                            help="하루 단위 파일이 있는 날짜만 계산됩니다.")
        s0, e0 = (rng[0], rng[-1]) if isinstance(rng, (tuple, list)) and len(rng) else (rng, rng)
        df = dd[(dd["period_start"] >= str(s0)) & (dd["period_start"] <= str(e0))]
        if df.empty:
            st.info("선택한 날짜에 일 단위 광고 파일이 없습니다.")
            return None
        n_days = df["period_start"].nunique()
        label = f"일 단위 {period_label(str(s0), str(e0))} (파일 있는 날 {n_days}일)"
    kept = sorted(set(zip(df["period_start"], df["period_end"])))
    return {"df": df, "start": min(sp[0] for sp in kept), "end": max(sp[1] for sp in kept),
            "window": window, "label": label, "unit": unit, "kept": kept, "stype": "로켓배송"}


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
