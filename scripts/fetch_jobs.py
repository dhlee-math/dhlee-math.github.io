import json
import re
import socket
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin

import feedparser  # pip install feedparser

# 연구 관심 키워드(분야)
KEYWORDS = [
    "symplectic",
    "contact",
    "dynamics",
    "three-body problem",
    "hamiltonian",
    "geometry",
    "topology",
    "dynamical systems",
]

# "포닥/연구직" 류를 잡기 위한 직군 키워드(너무 많이 걸리면 이쪽을 강화)
ROLE_KEYWORDS = [
    "postdoc", "post-doctor", "postdoctoral",
    "research fellow", "fellowship",
    "research associate", "researcher", # 필요 없으면 지워
]

# ✅ Euraxess RSS
RSS_FEEDS = [
    ("Euraxess", "https://euraxess.ec.europa.eu/job-feed"),
]

# ✅ MathJobs 목록 페이지 (HTML)
MATHJOBS_LIST_URL = "https://www.mathjobs.org/jobs?joblist-0-0----d--"
MATHJOBS_BASE = "https://www.mathjobs.org"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "")


def match_any_keywords(text: str, keywords) -> list[str]:
    t = (text or "").lower()
    hits = [k for k in keywords if k.lower() in t]
    return hits


def entry_date_iso(entry) -> str:
    for key in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, key, None)
        if tp:
            dt = datetime(*tp[:6], tzinfo=timezone.utc)
            return dt.date().isoformat()
    return ""


def fetch_rss_feed(feed_name, feed_url, max_items=80, require_keyword_hit=True):
    """
    RSS를 items로 변환.
    - require_keyword_hit=True 이면 KEYWORDS가 하나도 안 걸리면 스킵
    """
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

        hits = match_any_keywords(title + " " + summary, KEYWORDS)

        if require_keyword_hit and not hits:
            # Euraxess는 잡음이 많으니 보통 True 추천.
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


def fetch_mathjobs(max_items=25, require_field_keyword=True, require_role_keyword=True):
    """
    MathJobs 목록 페이지에서 (url, title) 추출 + 키워드 필터.
    - require_field_keyword: KEYWORDS 기반 필터 적용 여부
    - require_role_keyword: ROLE_KEYWORDS 기반 필터 적용 여부
    """
    try:
        req = Request(
            MATHJOBS_LIST_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; personal jobs board)"},
        )
        html = urlopen(req, timeout=25).read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    # 링크 텍스트까지 같이 뽑기:
    # /jobs/UNIVKS, /jobs/LUH_MAPHY 같은 코드형 링크가 공고 페이지로 직행하는 경우가 많음
    pattern = re.compile(
        r'<a[^>]+href="(?P<href>/jobs/(?:[A-Za-z0-9_]+|jobs/\d+))"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    items = []
    seen = set()

    for m in pattern.finditer(html):
        href = m.group("href")
        raw_title_html = m.group("title")

        title = normalize(strip_tags(raw_title_html))
        if not title:
            continue

        url = urljoin(MATHJOBS_BASE, href)
        if url in seen:
            continue
        seen.add(url)

        # 필터링: 직군 키워드 / 분야 키워드
        role_hits = match_any_keywords(title, ROLE_KEYWORDS)
        field_hits = match_any_keywords(title, KEYWORDS)

        if require_role_keyword and not role_hits:
            continue
        if require_field_keyword and not field_hits:
            continue

        items.append(
            {
                "title": title,  # ✅ 이제 "MathJobs posting"이 아니라 실제 제목이 들어감
                "institution": "",
                "country": "",
                "region": "Other",
                "deadline": "",
                "summary": "Imported from MathJobs listing.",
                "source": "MathJobs",
                "date_posted": "",
                "tags": sorted(set(role_hits + field_hits)),
                "url": url,
            }
        )

        if len(items) >= max_items:
            break

    return items


def main():
    items = []

    # (0) 파이프라인 테스트 카드 (원하면 나중에 삭제)
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

    # (1) Euraxess RSS: 잡음이 많으면 require_keyword_hit=True 추천
    for name, url in RSS_FEEDS:
        try:
            items.extend(fetch_rss_feed(name, url, max_items=80, require_keyword_hit=True))
        except Exception:
            pass

    # (2) MathJobs: 너무 많이 나오면 max_items를 더 줄여봐 (예: 10~20)
    items.extend(fetch_mathjobs(
        max_items=20,
        require_field_keyword=True,
        require_role_keyword=True
    ))

    data = {
        "updated_at": now_iso(),
        "items": items,
    }

    with open("jobs-board/jobs.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
