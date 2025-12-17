import json
from datetime import datetime, timezone

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def main():
    data = {
        "updated_at": now_iso(),
        "items": [
            {
                "title": "Pipeline test: jobs-board is updating",
                "institution": "dhlee-math.github.io",
                "country": "",
                "region": "Other",
                "deadline": "",
                "summary": "If you see this item, GitHub Actions updated jobs.json successfully.",
                "source": "local",
                "date_posted": datetime.now().date().isoformat(),
                "tags": ["symplectic","contact","dynamics","three-body problem","hamiltonian"],
                "url": "https://dhlee-math.github.io/jobs-board/"
            }
        ]
    }

    with open("jobs_board/jobs.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
