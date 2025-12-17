import json
import re
import socket
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin

import feedparser  # pip install feedparser

KEYWORDS = [
    "symplectic",
    "contact",
    "dynamics",
    "three-body problem",
    "hamiltonian",
]

# ✅ Euraxess RSS
RSS_FEEDS = [
    ("Euraxess", "https://euraxess.ec.europa.eu/job-feed"),
]

# (옵션) MathJobs HTML 목록도 계속 쓸 거면 유지
MATHJOBS_LIST_URL = "https://www.mathjobs.org/jobs?joblist-0-0----d--"
MATHJOBS_BASE = "https://www.mathjobs.org"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def match_keywords(text: str):
    t = (text or "").lower()
    hits = [k for k in KEYWORDS if k.lower() in t]
    return hits


def entry_date_iso(entry):
    # feedparser는 published_parsed / updated_parsed를 줄 때가 많음
    for key in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, key, None)
        if tp:
            dt = datetime(*tp[:6], tzinfo=timezone.utc)
            return dt.date().isoformat()
    return ""


def fetch_rss_feed(feed_name, feed_url, max_items=80, require_keyword_hit=True):
    """
    RSS를 items로 변환.
    - require_keyword_hit=True 이면 KEYWORDS가 하나도 안 걸리면 스킵(잡음 줄이기)
    """
    socket.setdefaulttimeout(20)  # 네트워크 타임아웃 (Actions에서 멈춤 방지)

    d = feedparser.parse(feed_url)
    if getattr(d, "bozo", 0):
        # 깨진 RSS거나 일시적 오류일 수 있음. 실패해도 파이프라인 전체는 살려둠.
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
                "summary": summary[:500] if summary else f"Imported from {feed_name}.",
                "source": feed_name,
                "date_posted": entry_date_iso(e),
                "tags": hits if hits else [],
                "url": link,
            }
        )

    return items


def fetch_mathjobs(max_items=50):
    """
    MathJobs 목록 페이지에서 링크를 뽑는 간단 파서.
    (MathJobs는 종종 타임아웃/차단이 걸릴 수 있어서 try/except로 죽지 않게)
    """
    try:
        req = Request(
            MATHJOBS_LIST_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; personal jobs board)"},
        )
        html = urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    # /jobs/UNIVKS 같은 “짧은 코드” 링크도 있고, /jobs/jobs/12345 형태도 있음
    pattern = re.compile(
        r'href="(?P<href>/jobs/(?:jobs/\d+|[A-Za-z0-9_]+))"',
        re.IGNORECASE,
    )

    items = []
    seen = set()

    for m in pattern.finditer(html):
        href = m.group("href")
        url = urljoin(MATHJOBS_BASE, href)
        if url in seen:
            continue
        seen.add(url)

        items.append(
            {
                "title": "MathJobs posting",
                "institution": "",
                "country": "",
                "region": "Other",
                "deadline": "",
                "summary": "Imported from MathJobs listing.",
                "source": "MathJobs",
                "date_posted": "",
                "tags": [],
                "url": url,
            }
        )
        if len(items) >= max_items:
            break

    return items


def main():
    items = []

    # (0) 파이프라인 테스트 카드: 원하면 지워도 됨
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

    # (1) Euraxess RSS 추가
    for name, url in RSS_FEEDS:
        try:
            items.extend(fetch_rss_feed(name, url))
        except Exception:
            # RSS 하나가 죽어도 전체 워크플로우는 안 죽게
            pass

    # (2) (옵션) MathJobs도 계속 시도하고 싶으면 켜두기
    # items.extend(fetch_mathjobs())

    data = {
        "updated_at": now_iso(),
        "items": items,
    }

    # ✅ 네 폴더명이 jobs-board 라고 했으니 이걸로 고정
    with open("jobs-board/jobs.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
