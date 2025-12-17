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
    # 네가 예시로 든 것처럼, MathJobs에서 자주 걸러내고 싶은 단어도 추가 가능
    "geometry",
]

# Euraxess RSS
RSS_FEEDS = [
    ("Euraxess", "https://euraxess.ec.europa.eu/job-feed"),
]

# MathJobs: "Postdoc" 리스트 (네가 준 링크로 제한)
# 페이지네이션을 직접 여러 장 긁어서 합침.
MATHJOBS_BASE = "https://www.mathjobs.org"
MATHJOBS_POSTDOC_LIST_PAGES = [
    "https://www.mathjobs.org/jobs?joblist-0-3---0-t--",
    "https://www.mathjobs.org/jobs?joblist-0-3---40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--40-40-dt--",
    "https://www.mathjobs.org/jobs?joblist-0-3--80-40-dt--",
    # 필요하면 더 추가:
    # "https://www.mathjobs.org/jobs?joblist-0-3--120-40-dt--",
]

OUT_PATH = "jobs-board/jobs.json"


# =========================
# Helpers
# =========================

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def match_keywords(text: str):
    t = (text or "").lower()
    hits = []
    for k in KEYWORDS:
        if k.lower() in t:
            hits.append(k)
    # 중복 제거 (순서 유지)
    seen = set()
    uniq = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def entry_date_iso(entry):
    # feedparser: published_parsed / updated_parsed
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


# =========================
# RSS fetch
# =========================

def fetch_rss_feed(feed_name, feed_url, max_items=120, require_keyword_hit=True):
    """
    RSS를 items로 변환.
    require_keyword_hit=True 이면 KEYWORDS가 하나도 안 걸리면 스킵.
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
# MathJobs HTML fetch
# =========================

def strip_tags(html: str) -> str:
    # 아주 가벼운 태그 제거
    html = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)
    return re.sub(r"<[^>]+>", "", html)


def parse_deadline(text: str) -> str:
    """
    (deadline 2025/11/14 11:59PM) 같은 문자열에서 2025/11/14 부분만 뽑아 ISO로 바꾸진 않고 원문 유지.
    """
    m = re.search(r"deadline\s+(\d{4}/\d{2}/\d{2})", text, flags=re.IGNORECASE)
    return m.group(1) if m else ""


def fetch_mathjobs_postdocs(require_keyword_hit=True, per_page_limit=200):
    """
    MathJobs Postdoc 리스트 페이지(여러 장)를 긁어서,
    기관명 + 포지션 타이틀 + Apply 링크(가능하면) 추출.
    """
    all_items = []
    seen = set()

    for page_url in MATHJOBS_POSTDOC_LIST_PAGES:
        try:
            html = http_get(page_url, timeout=20)
        except Exception:
            # MathJobs는 종종 타임아웃/차단이 걸릴 수 있으니 죽지 않게
            continue

        # (1) 기관명 헤더(파란 글씨) 후보: <h2>...</h2> 형태가 많음
        # 페이지 구조가 바뀔 수 있으니 "느슨하게" 잡는다.
        headers = []
        for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, flags=re.IGNORECASE | re.DOTALL):
            inst = normalize(strip_tags(m.group(1)))
            if inst:
                headers.append((m.start(), inst))

        # (2) 각 <li> ... </li>를 훑어서 공고 라인 추출
        for m in re.finditer(r"<li[^>]*>(.*?)</li>", html, flags=re.IGNORECASE | re.DOTALL):
            li_html = m.group(1)
            li_text = normalize(strip_tags(li_html))

            # postdoc 라인만 대충 거르기: [PD] / [POSTDOC] 같은 태그가 자주 있음
            # (너무 빡세게 걸면 놓칠 수 있으니 완전히 필수로 하진 않음)
            if not li_text:
                continue

            # Apply 링크 찾기 (있으면 그걸 url로)
            apply = re.search(r'href="([^"]+/apply[^"]*)"', li_html, flags=re.IGNORECASE)
            link = ""
            if apply:
                link = urljoin(MATHJOBS_BASE, apply.group(1))
            else:
                # apply 링크가 없으면, 기관 페이지라도 연결
                inst_link = re.search(r'href="(/jobs/[A-Za-z0-9_]+)"', li_html, flags=re.IGNORECASE)
                if inst_link:
                    link = urljoin(MATHJOBS_BASE, inst_link.group(1))

            if not link:
                continue

            if link in seen:
                continue
            seen.add(link)

            # 이 li가 속한 기관명 추정: 가장 가까운 이전 h2
            inst = ""
            if headers:
                prev = [h for (pos, h) in headers if pos < m.start()]
                if prev:
                    inst = prev[-1]

            deadline = parse_deadline(li_text)

            # 제목: 보통 "[XXX] ..." 형태이므로 그대로 쓰되, "Apply" 같은 꼬리는 제거
            title = li_text
            title = re.sub(r"\bApply\b.*$", "", title, flags=re.IGNORECASE).strip()
            title = title if title else "MathJobs posting"

            # 키워드 필터 (제목+기관 기준)
            hits = match_keywords((title + " " + inst))
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

            if len(all_items) >= per_page_limit:
                break

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

    # (1) Euraxess RSS
    for name, url in RSS_FEEDS:
        try:
            items.extend(fetch_rss_feed(name, url, require_keyword_hit=True))
        except Exception:
            pass

    # (2) MathJobs Postdoc (HTML 여러 장)
    try:
        items.extend(fetch_mathjobs_postdocs(require_keyword_hit=True))
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
