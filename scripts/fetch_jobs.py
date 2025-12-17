import json
import re
import socket
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin

import feedparser  # pip install feedparser


# =========================
# Settings
# =========================

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

# ✅ Euraxess: 수학(298) + postdoc 검색 결과 HTML 페이지들
EURAXESS_PAGES = [
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions",
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions&page=1",
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_research_field%3A298&f%5B1%5D=positions%3Apostdoc_positions&page=2",
]

# (옵션) Euraxess 전체 RSS도 유지하고 싶으면 켤 수 있음 (기본은 사용 안 함)
RSS_FEEDS = [
    ("Euraxess-RSS", "https://euraxess.ec.europa.eu/job-feed"),
]

# ✅ MathJobs: "Postdoc" 리스트 (네가 준 링크로 제한)
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

OUT_PATH = "jobs-board/jobs.json"

# 소스별 최대 수집량 (너무 많아지는 것 방지)
MAX_EURAXESS_ITEMS = 200
MAX_MATHJOBS_ITEMS = 250


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


def entry_date_iso(entry):
    for key in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, key, None)
        if tp:
            dt = datetime(*tp[:6], tzinfo=timezone.utc)
            return dt.date().isoformat()
    return ""


def http_get(url: str, timeout=20) -> str:
    req = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; personal jobs board)"},
    )
    return urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")


def parse_deadline(text: str) -> str:
    m = re.search(r"deadline\s+(\d{4}/\d{2}/\d{2})", text, flags=re.IGNORECASE)
    return m.group(1) if m else ""


# =========================
# (Optional) RSS fetch
# =========================

def fetch_rss_feed(feed_name, feed_url, max_items=120, require_keyword_hit=True):
    socket.setdefaulttimeout(20)
    d = feedparser.parse(feed_url)
    if getattr(d, "bozo", 0):
        return []

    items = []
    seen = set()

    for e in d.entries[:max_items]:
        title = normalize(getattr(e, "title", ""))
        link = normalize(getattr(e, "link", ""))
        summary = normalize(getattr(e, "summary", getattr(e, "description", "")))

        if not title or not link:
            continue
        if link in seen:
            continue
        seen.add(link)

        hits = match_keywords(title + " " + summary)
        if require_keyword_hit and not hits:
            continue

        items.append(
            {
                "title": title,
                "institution": "",
                "country": "",
                "region": "Other",
                "deadline": "",
                "summary": (summary[:500] if summary else f"Imported from {feed_name}."),
                "source": feed_name,
                "date_posted": entry_date_iso(e),
                "tags": hits,
                "url": link,
            }
        )

    return items


# =========================
# Euraxess HTML fetch (Math + Postdoc pages)
# =========================

def fetch_euraxess_math_postdoc(require_keyword_hit=True, max_items=200):
    """
    Euraxess: 수학(298)+postdoc 검색결과 HTML 페이지를 긁어서 공고를 items로 만든다.
    키워드는 title+summary에서 매칭.
    """
    items = []
    seen = set()

    for page_url in EURAXESS_PAGES:
        try:
            html = http_get(page_url, timeout=20)
        except Exception:
            continue

        for m in re.finditer(
            r"<article[^>]*>(.*?)</article>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            block = m.group(1)

            title_m = re.search(
                r"<h2[^>]*>.*?<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not title_m:
                continue

            href = title_m.group(1)
            url = urljoin("https://euraxess.ec.europa.eu", href)
            title = normalize(strip_tags(title_m.group(2)))

            if not title or url in seen:
                continue
            seen.add(url)

            # 요약: job-description 클래스를 느슨하게 탐색
            summary_m = re.search(
                r"<div[^>]*class=\"[^\"]*job-description[^\"]*\"[^>]*>(.*?)</div>",
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            summary = normalize(strip_tags(summary_m.group(1))) if summary_m else ""

            hits = match_keywords(title + " " + summary)
            if require_keyword_hit and not hits:
                continue

            items.append(
                {
                    "title": title,
                    "institution": "",
                    "country": "",
                    "region": "Europe",
                    "deadline": "",
                    "summary": summary[:500] if summary else "Imported from Euraxess search.",
                    "source": "Euraxess",
                    "date_posted": "",
                    "tags": hits,
                    "url": url,
                }
            )

            if len(items) >= max_items:
                return items

    return items


# =========================
# MathJobs HTML fetch (Postdoc pages)
# =========================

def fetch_mathjobs_postdocs(require_keyword_hit=True, max_items=250):
    """
    MathJobs Postdoc 리스트 페이지(여러 장)를 긁어서,
    - 기관명(가능하면)
    - 제목(리스트 라인 텍스트 기반)
    - 정보 페이지 링크(/jobs/XXXX or /jobs/jobs/12345)만 사용
      (✅ /apply 링크는 절대 사용하지 않음)
    """
    all_items = []
    seen = set()

    for page_url in MATHJOBS_POSTDOC_LIST_PAGES:
        try:
            html = http_get(page_url, timeout=20)
        except Exception:
            continue

        # (1) 기관명 헤더 후보: <h2>...</h2>
        headers = []
        for hm in re.finditer(
            r"<h2[^>]*>(.*?)</h2>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            inst = normalize(strip_tags(hm.group(1)))
            if inst:
                headers.append((hm.start(), inst))

        # (2) 각 <li> ... </li>에서 공고 라인 추출
        for lm in re.finditer(
            r"<li[^>]*>(.*?)</li>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            li_html = lm.group(1)
            li_text = normalize(strip_tags(li_html))
            if not li_text:
                continue

            # ✅ 정보 페이지 링크만 허용 (apply 링크 무시)
            info = re.search(
                r'href="(/jobs/(?:jobs/\d+|[A-Za-z0-9_]+))"',
                li_html,
                flags=re.IGNORECASE,
            )
            if not info:
                continue

            link = urljoin(MATHJOBS_BASE, info.group(1))
            if "/apply" in link.lower():
                continue

            if link in seen:
                continue
            seen.add(link)

            # 이 li가 속한 기관명 추정: 가장 가까운 이전 h2
            inst = ""
            if headers:
                prev = [h for (pos, h) in headers if pos < lm.start()]
                if prev:
                    inst = prev[-1]

            deadline = parse_deadline(li_text)

            # 제목: Apply 이후 텍스트 제거 + 괄호로 달린 deadline 문구는 남겨도 되지만 보기 싫으면 제거
            title = re.sub(r"\bApply\b.*$", "", li_text, flags=re.IGNORECASE).strip()
            title = title if title else "MathJobs posting"

            # 키워드 필터: 제목 + 기관명 기준
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
                    "url": link,
                }
            )

            if len(all_items) >= max_items:
                return all_items

    return all_items


# =========================
# Main
# =========================

def main():
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

    # (1) Euraxess: 수학+postdoc 검색결과 HTML
    try:
        items.extend(fetch_euraxess_math_postdoc(require_keyword_hit=True, max_items=MAX_EURAXESS_ITEMS))
    except Exception:
        pass

    # (옵션) Euraxess 전체 RSS도 참고로 넣고 싶으면 주석 해제
    # for name, url in RSS_FEEDS:
    #     try:
    #         items.extend(fetch_rss_feed(name, url, require_keyword_hit=True))
    #     except Exception:
    #         pass

    # (2) MathJobs Postdoc (HTML 여러 장) — ✅ 정보 링크만
    try:
        items.extend(fetch_mathjobs_postdocs(require_keyword_hit=True, max_items=MAX_MATHJOBS_ITEMS))
    except Exception:
        pass

    # (3) dedupe by url (최종 안전장치)
    uniq = []
    seen = set()
    for it in items:
        u = it.get("url", "")
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(it)

    data = {"updated_at": now_iso(), "items": uniq}

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
