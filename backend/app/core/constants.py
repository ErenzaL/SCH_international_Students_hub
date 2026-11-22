"""Shared enumerations and reference data (mirrors supabase/migrations CHECK constraints)."""
from __future__ import annotations

LANGUAGES = ("ko", "en", "id", "vi", "zh-CN")
SOURCE_TYPES = ("website", "pdf", "docx", "manual_text", "kakao_message")
AUTHORITY_TYPES = ("official_university", "official_government", "supporter_submitted", "other")
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
