"""비공개 저장소의 최신 코드를 '공개 배포용 저장소'(onsal-dashboard-app)로 동기화한다.

- config/product_master.csv, config/ad_sku_map.csv 는 헤더만 있는 빈 양식으로 바꿔서 올린다 (가격·원가 비공개).
- 커밋 작성자는 GitHub noreply 주소를 쓴다.
사용: python scripts/publish_public.py  ["커밋 메시지"]     (gh 로그인 필요)
Streamlit Community Cloud 는 이 공개 저장소를 보고 자동으로 다시 배포한다.
"""
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER, REPO, BRANCH = "suy6205-create", "onsal-dashboard-app", "main"
NOREPLY = f"{OWNER}@users.noreply.github.com"
BLANKS = {
    "config/product_master.csv": "SKU ID,품목,판매가,할인,원가,판매수수료율,운영중,광고명키워드\n",
    "config/ad_sku_map.csv": "광고옵션ID,광고상품명,SKU ID,묶음수량,비고\n",
}
FORBIDDEN = ["npg" + "_", "neondb" + "_owner", "gho" + "_", "ep-green" + "-"]   # 쪼개 적어 이 파일 자신은 걸리지 않게 함


def run(*cmd, cwd=None, check=True, capture=True):
    r = subprocess.run(cmd, cwd=cwd, check=check, capture_output=capture, text=True, encoding="utf-8")
    return (r.stdout or "").strip()


def main() -> None:
    msg = sys.argv[1] if len(sys.argv) > 1 else "Sync from private repo"
    token = run("gh", "auth", "token")
    url = f"https://x-access-token:{token}@github.com/{OWNER}/{REPO}.git"
    tmp = Path(tempfile.mkdtemp(prefix="pub_"))
    try:
        run("git", "clone", "-q", "-b", BRANCH, url, str(tmp / "pub"))
        pub = tmp / "pub"
        for item in pub.iterdir():                      # .git 만 남기고 비운 뒤 최신 코드로 채움
            if item.name != ".git":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        archive = tmp / "src.tar"
        run("git", "archive", "-o", str(archive), "HEAD", cwd=ROOT)
        with tarfile.open(archive) as tf:
            tf.extractall(pub)
        for rel, content in BLANKS.items():
            (pub / rel).write_text(content, encoding="utf-8")
        for f in pub.rglob("*"):                        # 비밀값이 섞였는지 마지막 점검
            if f.is_file() and ".git" not in f.parts:
                try:
                    txt = f.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                bad = [w for w in FORBIDDEN if w in txt]
                if bad:
                    sys.exit(f"중단: {f.relative_to(pub)} 에 민감한 문자열 {bad} 가 있습니다.")
        run("git", "add", "-A", cwd=pub)
        if not run("git", "status", "--porcelain", cwd=pub):
            print("변경 사항이 없습니다. (공개 저장소가 이미 최신)")
            return
        run("git", "-c", f"user.name={OWNER}", "-c", f"user.email={NOREPLY}", "commit", "-q", "-m", msg, cwd=pub)
        run("git", "push", "-q", "origin", BRANCH, cwd=pub)
        print(f"공개 저장소 갱신 완료: https://github.com/{OWNER}/{REPO}  ({msg})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
