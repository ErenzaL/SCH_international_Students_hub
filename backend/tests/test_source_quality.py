"""Source-quality checks: missing metadata is 'unknown' (never valid/official); no source is modified."""
from __future__ import annotations

import copy
from datetime import UTC, datetime

from app.services.source_quality import SourceQualityConfig, assess_document, assess_documents

NOW = datetime(2026, 11, 23, tzinfo=UTC)
CFG = SourceQualityConfig(official_domains=["hikorea.go.kr", "sch.ac.kr"])


def test_missing_metadata_is_unknown_not_valid():
    r = assess_document(dict(id="x", title="Notice"), CFG, NOW)
    assert r["authority"] == r["validity"] == r["published"] == r["version_status"] == r["domain"] == "unknown"
    assert "no_source_url" in r["flags"] and "authority_unknown" in r["flags"]


def test_official_identity_validity_age_and_version():
    r = assess_document(dict(id="a", authority_type="official_government", source_url="https://www.hikorea.go.kr/x",
                             valid_until="2026-01-01T00:00:00+00:00", source_published_at="2021-03-01",
                             verification_status="approved", is_current=True), CFG, NOW)
    assert r["authority"] == "official" and r["domain"] == "listed" and r["validity"] == "expired"
    assert "old_publication" in r["flags"] and r["version_status"] == "current_approved"
    s = assess_document(dict(id="b", authority_type="supporter_submitted", source_url="https://blog.example.com/p",
                             valid_from="2027-01-01", verification_status="superseded"), CFG, NOW)
    assert s["authority"] == "supporter_submitted" and s["domain"] == "unlisted" and s["validity"] == "not_yet_valid"
    assert "version_superseded" in s["flags"]


def test_declared_edition_is_reported_as_text_evidence():
    r = assess_document(dict(id="g", title="가이드북", text="# 외국인 유학생 가이드북\n# 2021 개정판"), CFG, NOW)
    assert r["declared_edition_year"] == 2021 and "old_declared_edition" in r["flags"]
    assert r["published"] == "unknown"          # the edition year is not taken as the publication date


def test_overlapping_documents_are_detected_and_inputs_untouched():
    base = " ".join(f"part time work permit rule number {i} applies to students" for i in range(40))
    docs = [dict(id="guide", text=base + " " + " ".join(f"other chapter {i} text" for i in range(200))),
            dict(id="excerpt", text=base), dict(id="unrelated", text="dormitory refrigerator inspection notice " * 30)]
    before = copy.deepcopy(docs)
    rep = assess_documents(docs, CFG, NOW)
    assert any(o["document"] == "excerpt" and o["contained_in"] == "guide" for o in rep["overlaps"])
    assert not any(o["document"] == "unrelated" for o in rep["overlaps"])
    assert docs == before
    assert rep["unknown_counts"]["validity"] == 3
