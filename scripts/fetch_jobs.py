import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

# =========================
# Settings
# =========================

OUT_PATH = Path("jobs-board/jobs.json")

KEYWORDS = [
    "symplectic",
    "contact",
    "dynamics",
    "three-body problem",
    "three body problem",
    "hamiltonian",
    "geometry",
    "topology",
    "dynamical systems",
]

# ✅ “키워드가 하나도 안 걸리면 버릴래?” (권장: False)
REQUIRE_KEYWORD_HIT = False

# ✅ 소스별 최대 수집 개수(너무 많아지는 거 방지)
MAX_EURAXESS_ITEMS = 80
MAX_MATHJOBS_ITEMS = 120

# ✅ Euraxess: 네가 준 “수학 + postdoc” 검색 페이지들 (page=0,1,2)
EURAXESS_SEARCH_PAGES = [
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions",
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions&page=1",
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions&page=2",
]
EURAXESS_BASE = "https://euraxess.ec.europa.eu"

# ✅ MathJobs: Postdoc 리스트 페이지들 (네가 준 포맷)
MATHJOBS_BASE = "https://www.mathjobs.org"
MATHJOBS_POSTDOC_LIST_PAGES = [
    "https://www.mathjobs.org/jobs?joblist-0-3---0-t--",
    "https://www.mathjobs.org/jobs?joblist-0-3---40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--40-40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--80-40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--120-40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--160-40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--200-40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--240-40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--280-40-dt--",
]

# 네트워크 타임아웃 (Actions에서 멈추는 것 방지)
socket.setdefaulttimeout(20)


# =========================
# Helpers
# =========================

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def strip_tags(html: str) -> str:
    html = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)
    return re.sub(r"<[^>]+>", "", html)


def match_keywords(text: str):
    t = (text or "").lower()
    hits = []
    for k in KEYWORDS:
        if k.lower() in t:
            hits.append(k)
    # 중복 제거(순서 유지)
    seen = set()
    uniq = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def http_get(url: str, timeout=20) -> str:
    req = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; personal jobs board)"},
    )
    return urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")


def safe_load_existing_items():
    """파싱이 망했을 때 덮어쓰지 않기 위해 기존 파일을 읽어둔다."""
    try:
        if OUT_PATH.exists():
            data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            items = data.get("items", [])
            if isinstance(items, list):
                return items
    except Exception:
        pass
    return []


def dedupe_by_url(items):
    uniq = []
    seen = set()
    for it in items:
        u = (it.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(it)
    return uniq


def parse_deadline(text: str) -> str:
    """
    (deadline 2025/11/14 11:59PM) 같은 문자열에서 2025/11/14만 뽑기.
    """
    m = re.search(r"deadline\s+(\d{4}/\d{2}/\d{2})", text, flags=re.IGNORECASE)
    return m.group(1) if m else ""


# =========================
# Euraxess HTML fetch
# =========================

def fetch_euraxess_math_postdoc(require_keyword_hit=False, max_items=80):
    items = []
    seen = set()

    # /jobs/search 같은 비-공고 링크 제거용
    def is_bad_job_href(href: str) -> bool:
        bad = [
            "/jobs/search",
            "/jobs/login",
            "/jobs/guide",
            "/jobs/",
        ]
        return any(href.startswith(b) for b in bad)

    # title 품질 체크 (메뉴/아이콘 찌꺼기 방지)
    def looks_like_garbage(title: str) -> bool:
        t = (title or "").lower()
        bad_tokens = ["class=", "svg", "ecl-", "focusable", "icon-", "button"]
        return (len(title) < 5) or any(x in t for x in bad_tokens)

    for page_url in EURAXESS_SEARCH_PAGES:
        try:
            html = http_get(page_url, timeout=20)
        except Exception:
            continue

        # ✅ "전체 <a ...>...</a>"를 잡아 anchor text만 title로 사용
        # Euraxess 공고 URL은 보통 /jobs/123456 형태가 많아서 우선 숫자형을 1순위로
        anchor_pat = re.compile(
            r'<a[^>]+href="(?P<href>/jobs/\d+[^"]*)"[^>]*>(?P<text>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        for m in anchor_pat.finditer(html):
            href = m.group("href")
            if is_bad_job_href(href):
                continue

            url = urljoin(EURAXESS_BASE, href)
            if url in seen:
                continue
            seen.add(url)

            raw_text = m.group("text")
            title = normalize(strip_tags(raw_text))

            # 가끔 anchor text가 비거나 이상하면 버리기
            if looks_like_garbage(title):
                continue

            # 키워드 필터 옵션(기본 False 유지 가능)
            hits = match_keywords(title)
            if require_keyword_hit and not hits:
                continue

            items.append(
                {
                    "title": title,
                    "institution": "",
                    "country": "",
                    "region": "Europe",
                    "deadline": "",
                    "summary": "Imported from Euraxess search.",
                    "source": "Euraxess(search)",
                    "date_posted": "",
                    "tags": hits,
                    "url": url,
                }
            )

            if len(items) >= max_items:
                return items

    return items



# =========================
# MathJobs HTML fetch (info link only)
# =========================

def fetch_mathjobs_postdocs(require_keyword_hit=False, max_items=120):
    """
    MathJobs Postdoc 리스트 페이지를 여러 장 긁어서:
    - 기관명(h2)
    - 공고 라인(li)
    - ✅ url은 Apply가 아니라 '정보 링크'(/jobs/UCIM or /jobs/jobs/1234 등)만 저장
    """
    all_items = []
    seen = set()

    for page_url in MATHJOBS_POSTDOC_LIST_PAGES:
        try:
            html = http_get(page_url, timeout=20)
        except Exception:
            continue

        # 기관명 헤더 <h2>...</h2>
        headers = []
        for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, flags=re.IGNORECASE | re.DOTALL):
            inst = normalize(strip_tags(m.group(1)))
            if inst:
                headers.append((m.start(), inst))

        # 각 공고 라인 <li>...</li>
        for m in re.finditer(r"<li[^>]*>(.*?)</li>", html, flags=re.IGNORECASE | re.DOTALL):
            li_html = m.group(1)
            li_text = normalize(strip_tags(li_html))
            if not li_text:
                continue

            # ✅ Apply 링크는 무시. 대신 "정보 링크"만 찾는다.
            # 예: /jobs/UCIM, /jobs/LUH_MAPHY, /jobs/jobs/12345
            info_link = re.search(
                r'href="(?P<href>/jobs/(?:jobs/\d+|[A-Za-z0-9_]+))"',
                li_html,
                flags=re.IGNORECASE,
            )
            if not info_link:
                continue

            url = urljoin(MATHJOBS_BASE, info_link.group("href"))
            if url in seen:
                continue
            seen.add(url)

            # 이 li가 속한 기관명 추정: 가장 가까운 이전 h2
            inst = ""
            if headers:
                prev = [h for (pos, h) in headers if pos < m.start()]
                if prev:
                    inst = prev[-1]

            deadline = parse_deadline(li_text)

            # 제목: [PD] Postdoc ... (deadline ...) 같은 줄에서 deadline 이후 제거
            title = li_text
            title = re.sub(r"\(deadline.*?\)", "", title, flags=re.IGNORECASE).strip()
            title = re.sub(r"\bApply\b.*$", "", title, flags=re.IGNORECASE).strip()
            title = title if title else "MathJobs posting"

            hits = match_keywords(title + " " + inst)
            if require_keyword_hit and not hits:
                continue

            all_items.append(
                {
                    "title": title,
                    "institution": inst,
                    "country": "",
                    "region": "Other",
                    "deadline": deadline,
                    "summary": "Imported from MathJobs postdoc listing.",
                    "source": "MathJobs",
                    "date_posted": "",
                    "tags": hits,
                    "url": url,
                }
            )

            if len(all_items) >= max_items:
                return all_items

    return all_items


# =========================
# Main
# =========================

def main():
    existing_items = safe_load_existing_items()

    items = []

    # (0) 파이프라인 테스트 카드 (원하면 나중에 지워도 됨)
    items.append(
        {
            "title": "Pipeline test: jobs-board is updating",
            "institution": "dhlee-math.github.io",
            "country": "",
            "region": "Other",
            "deadline": "",
            "summary": "If you see this item, GitHub Actions updated jobs.json successfully.",
            "source": "local",
            "date_posted": datetime.now(timezone.utc).date().isoformat(),
            "tags": KEYWORDS,
            "url": "https://dhlee-math.github.io/jobs-board/",
        }
    )

    # (1) Euraxess (search pages)
    eur = fetch_euraxess_math_postdoc(
        require_keyword_hit=REQUIRE_KEYWORD_HIT,
        max_items=MAX_EURAXESS_ITEMS,
    )
    items.extend(eur)

    # (2) MathJobs (postdoc list pages)
    mj = fetch_mathjobs_postdocs(
        require_keyword_hit=REQUIRE_KEYWORD_HIT,
        max_items=MAX_MATHJOBS_ITEMS,
    )
    items.extend(mj)

    # (3) 최종 dedupe
    items = dedupe_by_url(items)

    # ✅ “아무것도 못 뽑으면 기존 파일을 유지” (테스트 카드만 남는 참사 방지)
    real_items = [it for it in items if it.get("source") not in ("local",)]
    if len(real_items) == 0:
        # 기존에 뭐가 있었으면 그걸 유지하되, updated_at만 갱신하지 말자(혼란 방지)
        if existing_items:
            data = {"updated_at": now_iso(), "items": dedupe_by_url(existing_items)}
            OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return

    data = {"updated_at": now_iso(), "items": items}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
