"""Shared enumerations and reference data (mirrors supabase/migrations CHECK constraints)."""
from __future__ import annotations

LANGUAGES = ("ko", "en", "id", "vi", "zh-CN")
SOURCE_TYPES = ("website", "sch_board", "pdf", "docx", "text_file", "screenshot", "manual_text", "kakao_message")
FETCHABLE_SOURCE_TYPES = ("website", "sch_board")       # fetched from the network (may sync daily/weekly)
FILE_SOURCE_TYPES = ("pdf", "docx", "text_file", "screenshot")  # originals kept in private storage
TEXT_SOURCE_TYPES = ("manual_text", "kakao_message")
AUTHORITY_TYPES = ("official_university", "official_government", "staff_communication", "supporter_submitted", "other")
OFFICIAL_AUTHORITIES = ("official_government", "official_university")
SCOPES = ("university", "national")
SYNC_FREQUENCIES = ("manual", "daily", "weekly")
ROLES = ("super_admin", "admin", "supporter", "student")
ADMIN_ROLES = ("super_admin", "admin")
STAFF_ROLES = ("super_admin", "admin", "supporter")

# slug, English name, description, sort order
CATEGORIES: tuple[tuple[str, str, str, int], ...] = (
    ("visa-immigration", "Visa & Immigration", "Residence status, alien registration and immigration procedures", 10),
    ("part-time-employment", "Part-Time Employment", "Working while studying and labor rules", 20),
    ("academic-life", "Academic Life", "Courses, registration, grades and academic regulations", 30),
    ("scholarships", "Scholarships", "Financial support and scholarship programs", 40),
    ("dormitory-housing", "Dormitory & Housing", "On-campus dormitories and off-campus housing", 50),
    ("health-insurance", "Health & Insurance", "National health insurance and medical care", 60),
    ("topik-korean", "TOPIK & Korean Language", "TOPIK exams and Korean language learning", 70),
    ("employment-internships", "Employment & Internships", "Jobs, internships and career support", 80),
    ("banking-taxes", "Banking & Taxes", "Bank accounts, remittance and tax matters", 90),
    ("daily-living", "Daily Living", "Transport, phones, shopping and everyday life", 100),
    ("university-announcements", "University Announcements", "Official notices from the university", 110),
)
CATEGORY_SLUGS = tuple(c[0] for c in CATEGORIES)

# Document / version lifecycle
VERSION_DRAFT = "draft"
VERSION_PENDING = "pending_review"
VERSION_APPROVED = "approved"
VERSION_REJECTED = "rejected"
VERSION_SUPERSEDED = "superseded"

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100

# Days after verification when guidance is flagged as possibly outdated (per category; source may override).
STALE_AFTER_DAYS_DEFAULT = 180
STALE_AFTER_DAYS = {
    "visa-immigration": 90, "part-time-employment": 120, "scholarships": 60, "dormitory-housing": 90,
    "health-insurance": 180, "topik-korean": 60, "university-announcements": 45, "academic-life": 120,
}
# Suggested sync policy when an admin registers a source (configurable per source).
DEFAULT_SYNC_BY_CATEGORY = {
    "university-announcements": "daily", "topik-korean": "daily", "visa-immigration": "weekly",
    "health-insurance": "weekly",
}
