import json
import re
import socket
import html as html_lib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

# =========================
# Settings
# =========================

OUT_PATH = Path("jobs-board/jobs.json")

PRIORITY_KEYWORDS = {
    1: ["symplectic", "hamiltonian"],
    2: ["geometry", "topology", "dynamics", "celestial mechanics"],
    3: ["all fields", "fellowship"],
}

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

REQUIRE_KEYWORD_HIT = False

MAX_EURAXESS_ITEMS = 80
MAX_MATHJOBS_ITEMS = 120

EURAXESS_SEARCH_PAGES = [
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions",
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions&page=1",
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions&page=2",
]
EURAXESS_BASE = "https://euraxess.ec.europa.eu"

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

socket.setdefaulttimeout(20)

# =========================
# Helpers
# =========================

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def decode_entities(s: str) -> str:
    return html_lib.unescape(s or "")

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def strip_tags(html: str) -> str:
    html = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", html)
    return decode_entities(text)

def match_keywords(text: str):
    t = (text or "").lower()
    hits = []
    for k in KEYWORDS:
        if k.lower() in t:
            hits.append(k)
    # dedupe stable
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
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; personal jobs board)",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    return urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")


def safe_load_existing_items():
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

def keyword_priority(text: str) -> tuple[int, list[str]]:
    """
    return (priority, hits)
    priority: 1(best) / 2 / 3 / 99(none)
    hits: 매칭된 키워드 리스트 (우선순위 순서 유지)
    """
    t = (text or "").lower()
    for p in (1, 2, 3):
        hits = [k for k in PRIORITY_KEYWORDS[p] if k in t]
        if hits:
            return p, hits
    return 99, []

KEEP_UP_TO_PRIORITY = 3

def parse_deadline(text: str) -> str:
    m = re.search(r"deadline\s+(\d{4}/\d{2}/\d{2})", text, flags=re.IGNORECASE)
    return m.group(1) if m else ""

def euraxess_is_math_job(detail_html: str) -> bool:
    # detail page에 Mathematics/Mathematical sciences 등이 들어가면 통과
    text = (" " + strip_tags(detail_html) + " ").lower()
    return "mathemat" in text


# =========================
# Euraxess fetch
# =========================

def fetch_euraxess_math_postdoc(require_keyword_hit=False, max_items=80):
    items = []
    seen = set()

    def is_bad_job_href(href: str) -> bool:
        bad_prefixes = [
            "/jobs/search",
            "/jobs/login",
            "/jobs/guide",
            "/jobs/content",
            "/jobs/api",
        ]
        if any(href.startswith(b) for b in bad_prefixes):
            return True
        return href.rstrip("/") == "/jobs"

    def looks_like_garbage(title: str) -> bool:
        t = (title or "").lower()
        bad_tokens = ["class=", "svg", "ecl-", "focusable", "icon-", "button", "function "]
        return (len(title) < 6) or any(x in t for x in bad_tokens)

    for page_url in EURAXESS_SEARCH_PAGES:
        try:
            html = http_get(page_url, timeout=20)
        except Exception:
            continue

        # slug/숫자 모두 허용
        anchor_pat = re.compile(
            r'<a[^>]+href="(?P<href>/jobs/[^"#?]+)"[^>]*>(?P<text>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        for m in anchor_pat.finditer(html):
            href = m.group("href").strip()
            if is_bad_job_href(href):
                continue

            url = urljoin(EURAXESS_BASE, href)
            if url in seen:
                continue
            seen.add(url)

            title = normalize(strip_tags(m.group("text")))
            if looks_like_garbage(title):
                continue
            # 먼저 상세 페이지 fetch
            try:
                detail_html = http_get(url, timeout=20)
            except Exception:
                continue
            if not euraxess_is_math_job(detail_html):
                continue

            p, hits = keyword_priority(title + " " + strip_tags(detail_html))
            if p == 99:
            # 키워드 하나도 안 걸리면 버릴지 말지는 옵션
            # 지금 네 요구는 "걸러내기"니까 일단 버리는 쪽으로:
                continue
            if p > KEEP_UP_TO_PRIORITY:
                continue

            # ✅ 상세페이지에서 수학인지 확인 (History education 등 제거)
            try:
                detail_html = http_get(url, timeout=20)
            except Exception:
                continue
            if not euraxess_is_math_job(detail_html):
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
                    "priority": p,
                }
            )

            if len(items) >= max_items:
                return items

    return items


# =========================
# MathJobs fetch
# =========================

def fetch_mathjobs_postdocs(require_keyword_hit=False, max_items=120):
    """
    - joblist 페이지에서 <h2> (기관) + 그 아래 <li> (공고 라인) 파싱
    - 메뉴/푸터 <li> 제거
    - Apply 링크 제외, /jobs/... 정보 링크만 저장
    """
    all_items = []
    seen = set()

    menu_tokens = [
        "registered employers",
        "events",
        "skip to main content",
        "view jobs",
        "minority registry",
        "job wanted",
        "delete it",
        "privacy",
    ]

    for page_url in MATHJOBS_POSTDOC_LIST_PAGES:
        try:
            html = http_get(page_url, timeout=20)
        except Exception:
            continue

        # 기관명 헤더 <h2>...</h2>
        headers = []
        for hm in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, flags=re.IGNORECASE | re.DOTALL):
            inst = normalize(strip_tags(hm.group(1)))
            if inst:
                headers.append((hm.start(), inst))

        # 공고 라인 <li>...</li>
        for m in re.finditer(r"<li[^>]*>(.*?)</li>", html, flags=re.IGNORECASE | re.DOTALL):
            li_html = m.group(1)
            li_text = normalize(strip_tags(li_html))
            # MathJobs 페이지 UI 텍스트 잘라내기 (섞여들어오는 경우)
            li_text = re.sub(r"\bJob Listings\b.*$", "", li_text, flags=re.IGNORECASE).strip()
            if not li_text or len(li_text) < 25:
                continue

            t = li_text.lower()
            if any(tok in t for tok in menu_tokens):
                continue

            # 정보 링크(Apply 말고)만
            info_link = re.search(r'href="(?P<href>/jobs/[^"]+)"', li_html, flags=re.IGNORECASE)
            if not info_link:
                continue
            href = info_link.group("href")
            if "apply" in href.lower():
                continue

            url = urljoin(MATHJOBS_BASE, href)
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

            title = re.sub(r"\(deadline.*?\)", "", li_text, flags=re.IGNORECASE).strip()
            title = re.sub(r"\bApply\b.*$", "", title, flags=re.IGNORECASE).strip()
            title = title if title else "MathJobs posting"

            p, hits = keyword_priority(title + " " + inst)
            if p == 99:
                continue
            if p > KEEP_UP_TO_PRIORITY:
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
                    "priority": p,
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

    eur = fetch_euraxess_math_postdoc(
        require_keyword_hit=REQUIRE_KEYWORD_HIT,
        max_items=MAX_EURAXESS_ITEMS,
    )
    items.extend(eur)

    mj = fetch_mathjobs_postdocs(
        require_keyword_hit=REQUIRE_KEYWORD_HIT,
        max_items=MAX_MATHJOBS_ITEMS,
    )
    items.extend(mj)

    items = dedupe_by_url(items)

    def safe_priority(it):
        return int(it.get("priority", 99) or 99)

    items.sort(key=lambda it: (safe_priority(it), (it.get("deadline") or "9999/99/99"), it.get("title","")))


    real_items = [it for it in items if it.get("source") not in ("local",)]
    if len(real_items) == 0:
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
