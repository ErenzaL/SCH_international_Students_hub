"""Invented test documents for memory and load tests: no real person, notice or university text.

    make_pdf(9, out_dir)               -> a ~9 MB Korean PDF with small random images (PyMuPDF, a production dependency)
    make_pdf(9, out_dir, salt="run1")  -> different bytes per salt (an upload of identical bytes is refused as a duplicate)
    text_documents(12, salt="run1")    -> [(title, text)], mixed Korean/English, sizes from 3,000 to 150,000 characters
"""
from __future__ import annotations

import random
from pathlib import Path

KO = ("유학생 생활관 장학금 신청 기간 체류기간 연장 외국인등록증 수강신청 건강보험 시간제 취업 허가 서류 제출 마감 안내 학사 일정 졸업 휴학 복학 "
      "기숙사 비용 환불").split()
EN = ("students dormitory scholarship application period extension registration card course enrolment insurance part-time permit "
      "documents deadline notice calendar graduation leave return fee refund").split()
#: shaped like the real corpus: many short documents and a few very long ones (the long ones are what costs memory)
TEXT_SIZES = [150_000, 85_000, 40_000, 20_000, 12_000, 8_000, 6_000, 5_000, 4_000, 3_500, 3_000, 3_000]


def make_pdf(mb: int, out_dir: Path, salt: str = "") -> Path:
    import fitz  # pymupdf

    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"render_test_{mb}mb{'_' + salt if salt else ''}.pdf"
    if p.exists():
        return p
    rnd = random.Random(f"{mb}{salt}" if salt else mb)
    doc = fitz.open()
    page_no = 0
    while True:
        page_no += 1
        page = doc.new_page()
        text = f"제{page_no}장 안내{' (합성 시험 문서 ' + salt + ')' if salt else ''}\n" + "\n".join(
            " ".join(rnd.choice(KO) for _ in range(14)) + f" {page_no}-{i}." for i in range(38))
        page.insert_text((40, 50), text, fontname="korea", fontsize=10)
        img = bytes(rnd.getrandbits(8) for _ in range(160 * 160 * 3))
        pix = fitz.Pixmap(fitz.csRGB, 160, 160, img, False)
        page.insert_image(fitz.Rect(380, 600, 560, 780), pixmap=pix)
        if page_no % 10 == 0:
            doc.save(p, deflate=False)
            if p.stat().st_size >= mb * 1024 * 1024:
                break
    doc.close()
    return p


def text_documents(n: int = len(TEXT_SIZES), salt: str = "") -> list[tuple[str, str]]:
    rnd = random.Random(f"text{salt}")
    out = []
    for i, size in enumerate((TEXT_SIZES * (n // len(TEXT_SIZES) + 1))[:n]):
        words = KO if i % 2 == 0 else EN
        paras, total = [], 0
        while total < size:
            heading = f"## {i + 1}.{len(paras) + 1} " + " ".join(rnd.choice(words) for _ in range(4))
            body = " ".join(rnd.choice(words) for _ in range(rnd.randint(40, 120))) + "."
            paras.append(f"{heading}\n{body}")
            total += len(heading) + len(body) + 2
        out.append((f"Synthetic test document {i + 1}{' ' + salt if salt else ''}", "\n\n".join(paras)[:size]))
    return out
