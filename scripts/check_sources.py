"""Test access + extraction for each candidate official source individually (no database needed).

    cd backend && .venv/bin/python ../scripts/check_sources.py            # all six candidates
    cd backend && .venv/bin/python ../scripts/check_sources.py URL [URL]  # specific URLs

Respects robots.txt, the domain allowlist and SSRF rules (same code path as the API). Failures are
reported with their error code; nothing is bypassed and nothing is stored.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.config import Settings  # noqa: E402
from app.services.ingestion.errors import IngestionError  # noqa: E402
from app.services.ingestion.extractors_files import extract_pdf  # noqa: E402
from app.services.ingestion.extractors_html import extract_html  # noqa: E402
from app.services.ingestion.fetcher import GuardedFetcher  # noqa: E402

CANDIDATES = [
    "https://sgee.sch.ac.kr/notice/notice01.php?page=1&make=&search=&type=&table_name=noti_fore&loc_mnu=3",
    "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do",
    "https://www.hikorea.go.kr",
    "https://www.topik.go.kr",
    "https://www.nhis.or.kr",
    "https://www.moel.go.kr",
]


def main(urls: list[str]) -> int:
    settings = Settings(_env_file=None)
    fetcher = GuardedFetcher(settings)
    failures = 0
    for url in urls:
        print(f"\n== {url}")
        try:
            res = fetcher.fetch(url)
            doc = extract_pdf(res.content, "x.pdf") if res.content_type == "application/pdf" else extract_html(
                res.content, res.url, res.encoding, settings.min_extracted_chars)
            print(f"   OK  http={res.status_code} type={res.content_type} bytes={len(res.content)} "
                  f"redirects={len(res.redirects)} extractor={doc.metadata.get('extractor')}")
            print(f"   title: {doc.title[:100]!r}  chars: {len(doc.text)}  links: {len(doc.links)}")
            print("   preview: " + " ".join(doc.text.split())[:240])
        except IngestionError as exc:
            failures += 1
            print(f"   FAILED [{exc.code}] {exc.message}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"   ERROR {type(exc).__name__}: {exc}")
    print(f"\n{len(urls) - failures}/{len(urls)} sources accessible and extractable")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or CANDIDATES))
