from app.services.chunking import ChunkerConfig, chunk_text, estimate_tokens, parse_segments
from app.services.ingestion.normalize import content_hash, normalize_text


def test_normalization_is_whitespace_insensitive_but_content_sensitive():
    a = "# Title\r\n\r\nHello   world ​\n\n\n\nSecond"
    b = "# Title\n\nHello world\n\nSecond"
    assert normalize_text(a) == b
    assert content_hash(a) == content_hash(b)
    assert content_hash(b) != content_hash(b + "!")
    assert len(content_hash(b)) == 64


def test_hangul_nfc_normalization():
    nfd = "한글"  # decomposed jamo
    assert content_hash(nfd) == content_hash("한글")


def test_estimate_tokens_cjk_and_latin():
    assert estimate_tokens("") == 0
    assert estimate_tokens("외국인등록증") >= 6
    assert estimate_tokens("hello world") >= 2


def test_headings_define_sections_and_every_chunk_keeps_heading():
    text = "# Guide\nIntro text.\n\n## Visa\nVisa paragraph one.\n\nVisa paragraph two.\n\n## Insurance\nInsurance text."
    chunks = chunk_text(text, ChunkerConfig(target_tokens=50, max_tokens=80, overlap_tokens=10))
    assert [c.heading for c in chunks] == ["Guide", "Visa", "Insurance"]
    assert all(c.token_count <= 80 for c in chunks)


def test_sections_never_share_a_chunk():
    chunks = chunk_text("## A\nalpha\n\n## B\nbeta")
    assert len(chunks) == 2 and "beta" not in chunks[0].content and "alpha" not in chunks[1].content


def test_long_section_splits_within_budget_with_overlap():
    paras = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(12))
    cfg = ChunkerConfig(target_tokens=150, max_tokens=200, overlap_tokens=90)
    chunks = chunk_text("## Long\n" + paras, cfg)
    assert len(chunks) > 3
    assert all(c.token_count <= cfg.max_tokens + 5 for c in chunks)
    # adjacent chunks overlap by at least one whole paragraph
    for a, b in zip(chunks, chunks[1:], strict=False):
        last_para = a.content.split("\n\n")[-1]
        assert last_para in b.content
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_numbered_procedure_stays_together():
    steps = "\n".join(f"{i}. Step {i}: do the thing carefully" for i in range(1, 8))
    chunks = chunk_text("## Procedure\n" + steps, ChunkerConfig(target_tokens=200, max_tokens=300))
    assert len(chunks) == 1 and "7. Step 7" in chunks[0].content


def test_dates_are_not_broken_inside_oversized_paragraph():
    sentence = "Applications are accepted from 2025.3.1. until 2025.3.15. at the office. "
    big = sentence * 40
    chunks = chunk_text("## Dates\n" + big, ChunkerConfig(target_tokens=60, max_tokens=90, overlap_tokens=0))
    joined = " ".join(c.content for c in chunks)
    assert "2025.3.1. until 2025.3.15." in joined
    for c in chunks:  # no chunk starts in the middle of a date such as "3.1."
        assert not c.content.startswith(("3.1.", "3.15."))


def test_page_markers_become_page_references():
    text = "# Doc\n\n[Page 1]\nFirst page text here.\n\n[Page 2]\nSecond page text here."
    chunks = chunk_text(text, ChunkerConfig(target_tokens=5, max_tokens=12, overlap_tokens=0))
    assert chunks[0].page_start == 1 and chunks[-1].page_end == 2
    assert all("[Page" not in c.content for c in chunks)


def test_cjk_text_is_chunked_without_losing_content():
    sentence = "외국인등록증은 입국 후 90일 이내에 신청해야 합니다. "
    text = "## 외국인등록\n" + sentence * 60
    chunks = chunk_text(text, ChunkerConfig(target_tokens=100, max_tokens=140, overlap_tokens=0))
    assert len(chunks) > 1
    assert sum(c.content.count("외국인등록증은") for c in chunks) == 60


def test_oversized_unbroken_string_is_hard_split():
    chunks = chunk_text("## X\n" + "가" * 2000, ChunkerConfig(target_tokens=100, max_tokens=150, overlap_tokens=0))
    assert len(chunks) >= 13 and all(c.token_count <= 150 for c in chunks)


def test_empty_text_gives_no_chunks():
    assert chunk_text("   \n\n") == []


def test_parse_segments_tracks_headings():
    segs = parse_segments("# H1\nA\n\n## H2\nB")
    assert [(s.heading, s.text) for s in segs] == [("H1", "A"), ("H2", "B")]
