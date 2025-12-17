import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin

# 너의 관심 키워드(나중에 필터링/태깅에 쓸 수 있음)
KEYWORDS = [
    "symplectic",
    "contact",
    "dynamics",
    "three-body problem",
    "hamiltonian",
]

# MathJobs: RSS가 아니라 HTML 목록 페이지
MATHJOBS_LIST_URL = "https://www.mathjobs.org/jobs?joblist-0-0----d--"
MATHJOBS_BASE = "https://www.mathjobs.org"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_mathjobs(max_items=50):
    req = Request(
        MATHJOBS_LIST_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    html = urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")

    pattern = re.compile(
    r'href="(?P<href>/jobs/[A-Z0-9_]+)"',
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

        items.append({
            "title": "MathJobs posting",
            "institution": "",
            "country": "",
            "region": "Other",
            "deadline": "",
            "summary": "Imported from MathJobs (link only).",
            "source": "MathJobs",
            "date_posted": "",
            "tags": KEYWORDS,
            "url": url,
        })

        if len(items) >= max_items:
            break

    return items



def main():
    items = []

    # (1) 파이프라인 테스트 카드: 유지해도 되고, 나중에 지워도 됨
    items.append(
        {
            "title": "Pipeline test: jobs-board is updating",
            "institution": "dhlee-math.github.io",
            "country": "",
            "region": "Other",
            "deadline": "",
            "summary": "If you see this item, GitHub Actions updated jobs.json successfully.",
            "source": "local",
            "date_posted": datetime.now().date().isoformat(),
            "tags": KEYWORDS,
            "url": "https://dhlee-math.github.io/jobs-board/",
        }
    )

    # (2) MathJobs에서 실제 공고 링크들 추가
    items.extend(fetch_mathjobs())

    data = {
        "updated_at": now_iso(),
        "items": items,
    }

    # ⭐ 여기 경로가 가장 중요: jobs-board (하이픈)
    with open("jobs-board/jobs.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
