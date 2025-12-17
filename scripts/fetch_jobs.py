import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from urllib.error import URLError

KEYWORDS = [
    "symplectic",
    "contact",
    "dynamics",
    "three-body problem",
    "hamiltonian",
]

MATHJOBS_LIST_URL = "https://www.mathjobs.org/jobs?joblist-0-0----d--"
MATHJOBS_BASE = "https://www.mathjobs.org"

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def fetch_mathjobs(max_items=50, timeout=30):
    req = Request(
        MATHJOBS_LIST_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; personal jobs board; +https://dhlee-math.github.io/)"
        },
    )
    html = urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")

    # MathJobs 공고는 /jobs/UNIVKS, /jobs/LUH_MAPHY 같은 형태도 많음
    pattern = re.compile(r'href="(?P<href>/jobs/[A-Z0-9_]+)"', re.IGNORECASE)

    items, seen = [], set()
    for m in pattern.finditer(html):
        href = m.group("href")
        url = urljoin(MATHJOBS_BASE, href)
        if url in seen:
            continue
        seen.add(url)

        items.append(
            {
                "title": href.replace("/jobs/", ""),   # 일단 ID라도 보여주기 (나중에 상세 파싱 가능)
                "institution": "",
                "country": "",
                "region": "Other",
                "deadline": "",
                "summary": "Imported from MathJobs listing.",
                "source": "MathJobs",
                "date_posted": "",
                "tags": KEYWORDS,
                "url": url,
            }
        )
        if len(items) >= max_items:
            break

    return items

def main():
    items = [
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
    ]

    # ✅ 여기서 실패해도 전체는 계속 진행
    try:
        items.extend(fetch_mathjobs())
    except (URLError, TimeoutError, Exception) as e:
        items.append(
            {
                "title": "MathJobs fetch failed (temporary)",
                "institution": "mathjobs.org",
                "country": "",
                "region": "Other",
                "deadline": "",
                "summary": f"Could not fetch MathJobs listing due to: {type(e).__name__}",
                "source": "MathJobs",
                "date_posted": datetime.now(timezone.utc).date().isoformat(),
                "tags": KEYWORDS,
                "url": MATHJOBS_LIST_URL,
            }
        )

    data = {"updated_at": now_iso(), "items": items}

    # 너 폴더명이 jobs-board 라고 했으니 그걸로 통일
    with open("jobs-board/jobs.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
