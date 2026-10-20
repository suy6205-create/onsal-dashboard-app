"""구글 시트(링크 공유)에서 상품 정보(판매가·쿠팡 공급가·유통기한·회사 코드)를 읽어 상품 마스터와 맞춘다.

- 시트 공유가 '링크가 있는 모든 사용자(뷰어)'여야 한다. (비공개면 401 → 친절한 안내)
- 열 이름은 별칭으로 인식한다 (아래 ALIASES). 머리글 행은 위쪽 10행 안에서 자동으로 찾는다.
- 쿠팡 공급가(VAT 포함)가 있으면 수수료율을 역산해(1 − 공급가 ÷ 판매가) 마스터의 수수료율로 맞춘다.
"""
from __future__ import annotations

import io
import re
import time

import pandas as pd

ALIASES: dict[str, list[str]] = {
    "sku": ["skuid", "sku", "스큐id", "스큐아이디", "쿠팡sku", "쿠팡skuid", "상품번호", "옵션id"],
    "name": ["품목", "상품명", "sku명", "스큐이름", "스큐명", "품명", "제품", "제품명", "품목명"],
    "price": ["판매가", "판매가격", "소비자가", "쿠팡판매가", "판매가(vat포함)"],
    "supply": ["쿠팡공급가", "공급가", "쿠팡공급가(vat포함)", "공급가(vat포함)", "쿠팡공급가격", "입점공급가", "공급가(v+)", "공급가(v포함)", "쿠팡공급가(v+)"],
    "shelf": ["유통기한", "유통기간", "소비기한"],
    "code": ["회사코드", "우리회사상품코드", "우리회사코드", "상품코드", "품목코드", "자사코드", "erp코드", "회사상품코드", "(회사)상품코드"],
}
_CACHE: dict = {}
CACHE_TTL = 600


class SheetError(RuntimeError):
    """사용자에게 그대로 보여줄 시트 읽기 오류."""


def _norm(h) -> str:
    return re.sub(r"[\s_\-·/]", "", str(h)).lower()


def parse_sheet_url(url: str) -> tuple[str, str | None]:
    """구글 시트 주소(또는 ID) -> (시트ID, gid). gid 가 없으면 None(첫 번째 탭)."""
    url = (url or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    sid = m.group(1) if m else (url if re.fullmatch(r"[A-Za-z0-9_-]{20,}", url) else "")
    if not sid:
        raise SheetError("구글 시트 주소를 알아볼 수 없습니다. 브라우저 주소창의 전체 주소(https://docs.google.com/spreadsheets/d/…)를 붙여넣어 주세요.")
    g = re.search(r"[#?&]gid=(\d+)", url)
    return sid, (g.group(1) if g else None)


def csv_export_url(url: str) -> str:
    sid, gid = parse_sheet_url(url)
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv" + (f"&gid={gid}" if gid else "")


def fetch_sheet(url: str, use_cache: bool = True) -> pd.DataFrame:
    """시트를 읽어 머리글 정리 전의 원본 표(문자열)로 돌려준다. 10분 캐시."""
    import requests
    export = csv_export_url(url)
    hit = _CACHE.get(export)
    if use_cache and hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1].copy()
    try:
        r = requests.get(export, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        raise SheetError(f"구글 시트에 연결하지 못했습니다: {type(e).__name__}") from e
    if r.status_code in (401, 403) or "text/html" in r.headers.get("content-type", ""):
        raise SheetError("시트를 읽을 수 없습니다(비공개). 시트의 [공유]에서 일반 액세스를 '링크가 있는 모든 사용자 – 뷰어'로 바꿔주세요. "
                         "회사 구글 계정 정책으로 막혀 있다면 시트를 엑셀/CSV로 내려받아 업로드해야 합니다.")
    if r.status_code != 200:
        raise SheetError(f"시트를 읽지 못했습니다 (HTTP {r.status_code}). 주소와 공유 설정을 확인해 주세요.")
    df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), header=None, dtype=str, keep_default_na=False)
    _CACHE[export] = (time.time(), df)
    return df.copy()


def clear_cache() -> None:
    _CACHE.clear()


def find_header(raw: pd.DataFrame, max_rows: int = 10) -> int:
    """머리글 행 번호: 위쪽 몇 행 중 별칭(SKU ID/제품명, 판매가, 공급가, 유통기한, 코드)과 가장 많이 맞는 행.
    SKU ID 또는 제품(이름) 열이 있고 3개 이상 맞아야 한다."""
    best, best_n = -1, 0
    for i in range(min(max_rows, len(raw))):
        heads = {_norm(x) for x in raw.iloc[i]}
        n = sum(any(a in heads for a in al) for al in ALIASES.values())
        has_key = any(a in heads for a in ALIASES["sku"] + ALIASES["name"])
        if has_key and n >= 3 and n > best_n:
            best, best_n = i, n
    if best < 0:
        raise SheetError("시트에서 머리글 행을 찾지 못했습니다. 위쪽 줄에 '제품(또는 SKU ID)', 판매가, 공급가, 유통기한, 상품코드 같은 제목이 있어야 합니다.")
    return best


def read_table(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """원본 표 -> (머리글이 정리된 표, {필드: 실제 열 이름})."""
    h = find_header(raw)
    df = raw.iloc[h + 1:].copy()
    df.columns = [str(c).strip() or f"열{i}" for i, c in enumerate(raw.iloc[h])]
    mapping: dict[str, str] = {}
    for field, al in ALIASES.items():
        for col in df.columns:
            if _norm(col) in al:
                mapping[field] = col
                break
    return df.reset_index(drop=True), mapping


def _num(v) -> float | None:
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _sku(v) -> str:
    s = str(v).strip()
    return str(int(float(s))) if re.fullmatch(r"\d+(\.0+)?", s) else s


def norm_name(v) -> str:
    """제품명 비교용: 공백·괄호·구분기호를 지우고 소문자로 (띄어쓰기가 달라도 같은 제품으로 본다)."""
    return re.sub(r"[\s()\[\]·\-_/,]", "", str(v)).lower()


def match_by_name(product: str, names_by_sku: dict[str, list[str]]) -> tuple[str | None, str]:
    """시트의 제품명 -> (SKU ID, 상태). 한 제품만 포함 관계로 맞으면 연결, 여러 개면 'ambiguous', 없으면 'none'."""
    p = norm_name(product)
    if not p:
        return None, "none"
    hits = []
    for sku, names in names_by_sku.items():
        for nm in names:
            q = norm_name(nm)
            if q and (p in q or q in p):
                hits.append(sku)
                break
    if len(hits) == 1:
        return hits[0], "ok"
    return None, ("ambiguous" if hits else "none")


def to_updates(df: pd.DataFrame, mapping: dict[str, str], names_by_sku: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """시트 표 -> 마스터에 반영할 값. 열: SKU ID, 시트제품명, 품목, 판매가, 판매수수료율, 유통기한, 회사코드 (시트에 없는 칸은 None).
    SKU ID 열이 없으면 제품명을 판매 데이터의 SKU 이름(names_by_sku)과 맞춰 연결한다.
    연결하지 못한 제품은 결과의 attrs['unmatched'] 에 (제품명, 사유) 로 담는다."""
    if "sku" not in mapping and "name" not in mapping:
        raise SheetError("시트에 SKU ID 또는 제품(이름) 열이 없습니다.")
    sub = df.copy()
    name_col = mapping.get("name")
    unmatched: list[tuple[str, str]] = []
    if "sku" in mapping:
        sub["_sku"] = sub[mapping["sku"]].map(_sku)
        sub = sub[sub["_sku"].str.fullmatch(r"\d+")]
    else:
        if names_by_sku is None:
            raise SheetError("시트에 SKU ID 열이 없어 제품명으로 연결해야 합니다.")
        skus = []
        for nm in sub[name_col]:
            sku, st_ = match_by_name(nm, names_by_sku)
            skus.append(sku or "")
            if not sku and str(nm).strip():
                unmatched.append((str(nm).strip(), "이름이 비슷한 SKU가 여러 개" if st_ == "ambiguous" else "판매 데이터에 없는 제품"))
        sub["_sku"] = skus
        sub = sub[sub["_sku"] != ""]
    out = pd.DataFrame({"SKU ID": sub["_sku"]})
    out["시트제품명"] = sub[name_col].str.strip() if name_col else ""
    out["품목"] = out["시트제품명"] if name_col else None
    price = sub[mapping["price"]].map(_num) if "price" in mapping else pd.Series(None, index=sub.index, dtype=float)
    out["판매가"] = price
    if "supply" in mapping and "price" in mapping:
        sup = sub[mapping["supply"]].map(_num)
        out["판매수수료율"] = [None if (p is None or s is None or pd.isna(p) or pd.isna(s) or p <= 0) else round(1 - s / p, 4)
                          for p, s in zip(price, sup)]
    else:
        out["판매수수료율"] = None
    out["유통기한"] = sub[mapping["shelf"]].str.strip() if "shelf" in mapping else None
    out["회사코드"] = sub[mapping["code"]].str.strip() if "code" in mapping else None
    res = out.drop_duplicates("SKU ID", keep="last").reset_index(drop=True)
    res.attrs["unmatched"] = unmatched
    return res


FIELDS = ["품목", "판매가", "판매수수료율", "유통기한", "회사코드"]
DEFAULT_FIELDS = ["판매가", "판매수수료율", "유통기한", "회사코드"]       # 품목명은 기본으로 덮어쓰지 않는다 (마스터의 짧은 이름 유지)


def _show(f: str, v) -> str:
    """미리보기 표 표시용 문자열 (숫자·문자가 섞이지 않게)."""
    try:
        if f == "판매가":
            return f"{float(v):,.0f}원"
        if f == "판매수수료율":
            return f"{float(v) * 100:.2f}%"
    except (TypeError, ValueError):
        pass
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def diff_with_master(updates: pd.DataFrame, master: pd.DataFrame, fields=None) -> pd.DataFrame:
    """시트 값과 현재 마스터 값을 비교해 '바뀌는 칸'만 표로 돌려준다. 빈 시트 값은 무시(마스터 값을 지우지 않음)."""
    mi = master.set_index("SKU ID")
    rows = []
    for u in updates.to_dict("records"):
        sku = u["SKU ID"]
        if sku not in mi.index:
            continue
        cur = mi.loc[sku]
        for f in (fields or DEFAULT_FIELDS):
            new = u.get(f)
            if new is None or (isinstance(new, float) and pd.isna(new)) or str(new).strip() == "":
                continue
            old = cur[f]
            same = (abs(float(old) - float(new)) < 1e-9) if f in ("판매가", "판매수수료율") and str(old) not in ("", "nan") \
                else (str(old).strip() == str(new).strip())
            if not same:
                rows.append({"SKU ID": sku, "품목": cur["품목"], "칸": f, "현재(마스터)": _show(f, old), "시트 값": _show(f, new)})
    return pd.DataFrame(rows, columns=["SKU ID", "품목", "칸", "현재(마스터)", "시트 값"])


def apply_updates(master: pd.DataFrame, updates: pd.DataFrame, fields=None) -> tuple[pd.DataFrame, int]:
    """시트 값을 마스터에 반영(마스터에 있는 SKU 만, 비어 있지 않은 값만). (새 마스터, 바뀐 칸 수)"""
    m = master.set_index("SKU ID").copy()
    n = 0
    for u in updates.to_dict("records"):
        sku = u["SKU ID"]
        if sku not in m.index:
            continue
        for f in (fields or DEFAULT_FIELDS):
            v = u.get(f)
            if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
                continue
            if f in ("판매가", "판매수수료율"):
                if abs(float(m.at[sku, f]) - float(v)) > 1e-9:
                    m.at[sku, f] = float(v)
                    n += 1
            elif str(m.at[sku, f]).strip() != str(v).strip():
                m.at[sku, f] = str(v).strip()
                n += 1
    return m.reset_index(), n
