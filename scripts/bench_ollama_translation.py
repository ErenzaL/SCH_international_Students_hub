"""Translation benchmark for the local model: quality and latency for every pair of ko, en, id, vi, zh-CN.

    cd backend && .venv/bin/python ../scripts/bench_ollama_translation.py            # all 20 directions, 2 notices
    cd backend && .venv/bin/python ../scripts/bench_ollama_translation.py --pairs ko-en,ko-vi --out result.json

Uses SYNTHETIC notices only and the production prompts and checks (``translate_document``, ``validate_translation``,
``local_model_warnings``). No database, no .env file, no network except Ollama on this machine.

* chrF (character n-gram F-score, 0-100) against a reference translation. The references were written by an AI
  assistant and NOT checked by native speakers: use the scores to compare directions and models, not as an absolute
  measure. Different target languages are not directly comparable with each other.
* clean: no automatic check flagged the draft (a flagged draft becomes ``needs_review``).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import Settings  # noqa: E402
from app.services.llm.base import LLMError, build_llm_from_settings  # noqa: E402
from app.services.translation.quality import local_model_warnings, validate_translation  # noqa: E402
from app.services.translation_drafts import translate_document  # noqa: E402

LANGS = ("ko", "en", "id", "vi", "zh-CN")
NOTICES: dict[str, dict[str, tuple[str, str]]] = {
    "scholarship": {
        "ko": ("국제학생 장학금 신청 안내",
               "국제학생 장학금 신청을 받습니다. 신청 기간은 2026-12-01부터 2026-12-15 18:00까지입니다.\n\n"
               "- 지원 금액: 500,000원\n- 제출 서류: 신청서, 성적증명서, 여권 사본\n\n"
               "신청서는 https://example.ac.kr/apply 에서 제출하세요. 마감 이후에는 신청할 수 없습니다.\n\n"
               "문의: intl@example.ac.kr, 041-000-1234"),
        "en": ("International Student Scholarship Application Guide",
               "We are accepting applications for the international student scholarship. The application period is from "
               "2026-12-01 to 2026-12-15 18:00.\n\n"
               "- Amount: 500,000 won\n- Required documents: application form, academic transcript, copy of passport\n\n"
               "Submit the application form at https://example.ac.kr/apply. You cannot apply after the deadline.\n\n"
               "Contact: intl@example.ac.kr, 041-000-1234"),
        "id": ("Panduan Pendaftaran Beasiswa Mahasiswa Internasional",
               "Kami menerima pendaftaran beasiswa mahasiswa internasional. Periode pendaftaran adalah dari 2026-12-01 "
               "sampai 2026-12-15 18:00.\n\n"
               "- Jumlah bantuan: 500,000 won\n- Dokumen yang diperlukan: formulir pendaftaran, transkrip nilai, "
               "salinan paspor\n\n"
               "Kirimkan formulir pendaftaran di https://example.ac.kr/apply. Anda tidak dapat mendaftar setelah batas "
               "waktu.\n\nKontak: intl@example.ac.kr, 041-000-1234"),
        "vi": ("Hướng dẫn đăng ký học bổng cho sinh viên quốc tế",
               "Chúng tôi nhận đơn đăng ký học bổng dành cho sinh viên quốc tế. Thời gian đăng ký là từ 2026-12-01 đến "
               "2026-12-15 18:00.\n\n"
               "- Số tiền hỗ trợ: 500,000 won\n- Giấy tờ cần nộp: đơn đăng ký, bảng điểm, bản sao hộ chiếu\n\n"
               "Nộp đơn đăng ký tại https://example.ac.kr/apply. Bạn không thể đăng ký sau khi hết hạn.\n\n"
               "Liên hệ: intl@example.ac.kr, 041-000-1234"),
        "zh-CN": ("国际学生奖学金申请指南",
                  "现接受国际学生奖学金申请。申请时间为 2026-12-01 至 2026-12-15 18:00。\n\n"
                  "- 资助金额：500,000韩元\n- 提交材料：申请表、成绩单、护照复印件\n\n"
                  "请在 https://example.ac.kr/apply 提交申请表。截止后无法申请。\n\n"
                  "咨询：intl@example.ac.kr, 041-000-1234"),
    },
    "visa": {
        "ko": ("D-2 체류기간 연장 안내",
               "D-2 체류자격 학생은 체류기간이 만료되기 전에 연장을 신청해야 합니다.\n\n"
               "- 준비 서류: 여권, 외국인등록증, 재학증명서\n- 수수료: 60,000원\n\n"
               "만료일이 지나면 과태료가 부과될 수 있습니다. 학교에서 대신 신청하지 않으며 본인이 직접 신청해야 합니다."),
        "en": ("D-2 Extension of Stay Guide",
               "Students with D-2 status must apply for an extension before their period of stay expires.\n\n"
               "- Documents to prepare: passport, residence card, certificate of enrollment\n- Fee: 60,000 won\n\n"
               "A fine may be imposed after the expiry date. The university does not apply on your behalf; you must "
               "apply yourself."),
        "id": ("Panduan Perpanjangan Masa Tinggal D-2",
               "Mahasiswa dengan status D-2 harus mengajukan perpanjangan sebelum masa tinggalnya berakhir.\n\n"
               "- Dokumen yang disiapkan: paspor, kartu registrasi orang asing, surat keterangan mahasiswa aktif\n"
               "- Biaya: 60,000 won\n\n"
               "Denda dapat dikenakan setelah tanggal berakhir. Universitas tidak mengajukan atas nama Anda; Anda harus "
               "mengajukan sendiri."),
        "vi": ("Hướng dẫn gia hạn thời gian lưu trú D-2",
               "Sinh viên có tư cách lưu trú D-2 phải nộp đơn gia hạn trước khi thời gian lưu trú hết hạn.\n\n"
               "- Giấy tờ cần chuẩn bị: hộ chiếu, thẻ đăng ký người nước ngoài, giấy chứng nhận đang theo học\n"
               "- Lệ phí: 60,000 won\n\n"
               "Bạn có thể bị phạt tiền sau ngày hết hạn. Trường không nộp đơn thay bạn; bạn phải tự mình nộp đơn."),
        "zh-CN": ("D-2 停留期限延长指南",
                  "持 D-2 停留资格的学生必须在停留期限到期之前申请延长。\n\n"
                  "- 准备材料：护照、外国人登录证、在学证明\n- 手续费：60,000韩元\n\n"
                  "到期之后可能会被处以罚款。学校不代为申请，必须由本人亲自申请。"),
    },
}


def chrf(hypothesis: str, reference: str, order: int = 6, beta: float = 2.0) -> float:
    """chrF2 (Popovic 2015): mean character n-gram precision and recall, whitespace removed."""
    h, r = "".join(hypothesis.split()), "".join(reference.split())
    ps, rs = [], []
    for n in range(1, order + 1):
        a = Counter(h[i:i + n] for i in range(len(h) - n + 1))
        b = Counter(r[i:i + n] for i in range(len(r) - n + 1))
        if not a or not b:
            continue
        same = sum((a & b).values())
        ps.append(same / sum(a.values()))
        rs.append(same / sum(b.values()))
    if not ps:
        return 0.0
    p, q = sum(ps) / len(ps), sum(rs) / len(rs)
    return 100 * (1 + beta**2) * p * q / (beta**2 * p + q) if p + q else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="")
    ap.add_argument("--pairs", default="", help="e.g. ko-en,ko-zh-CN (default: all 20)")
    ap.add_argument("--out", default="", help="write the full result (with the synthetic outputs) as JSON")
    args = ap.parse_args()
    pairs = [(s, t) for s in LANGS for t in LANGS if s != t]
    if args.pairs:
        wanted = args.pairs.split(",")
        pairs = [(s, t) for s, t in pairs if f"{s}-{t}" in wanted]
    settings = Settings(_env_file=None, llm_provider="ollama", **({"ollama_model": args.model} if args.model else {}))
    llm = build_llm_from_settings(settings)
    try:
        llm.complete("Reply OK.", "OK?", max_tokens=16)       # load the model, so it is not part of the timings
    except LLMError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    rows = []
    print(f"{'pair':12} {'notice':12} {'chrF':>6} {'sec':>6} {'tok/s':>6}  checks")
    for s, t in pairs:
        for name, texts in NOTICES.items():
            (title, body), (rt, rb) = texts[s], texts[t]
            t0 = time.perf_counter()
            row: dict = dict(source=s, target=t, notice=name)
            try:
                out = translate_document(llm, title=title, body=body, source_lang=s, target_lang=t, chunk_chars=3000)
            except LLMError as exc:
                rows.append(row | dict(error=exc.code))
                print(f"{s + '-' + t:12} {name:12} FAILED {exc.code}")
                continue
            sec = time.perf_counter() - t0
            src, hyp, ref = f"{title}\n{body}", f"{out['title']}\n{out['body']}", f"{rt}\n{rb}"
            warn = validate_translation(src, hyp, s, t) + local_model_warnings(src, hyp, s, t)
            row |= dict(chrf=round(chrf(hyp, ref), 1), seconds=round(sec, 2), input_tokens=out["input_tokens"],
                        output_tokens=out["output_tokens"], tokens_per_s=round(out["output_tokens"] / sec, 1),
                        warnings=warn, output=hyp)
            rows.append(row)
            print(f"{s + '-' + t:12} {name:12} {row['chrf']:6.1f} {sec:6.2f} {row['tokens_per_s']:6.1f}  "
                  + (", ".join(f"{w['type']}={w['value']}" for w in warn) or "clean"))
    good = [r for r in rows if "error" not in r]
    summary = {}
    print(f"\n{'target':8} {'n':>3} {'chrF':>6} {'median s':>9} {'max s':>6} {'clean':>7}")
    for t in LANGS:
        g = [r for r in good if r["target"] == t]
        if g:
            summary[t] = dict(n=len(g), chrf=round(statistics.mean(r["chrf"] for r in g), 1),
                              median_s=round(statistics.median(r["seconds"] for r in g), 2),
                              max_s=max(r["seconds"] for r in g), clean=sum(not r["warnings"] for r in g))
            x = summary[t]
            print(f"{t:8} {x['n']:>3} {x['chrf']:6.1f} {x['median_s']:9.2f} {x['max_s']:6.2f} {x['clean']:>3}/{x['n']}")
    print(f"errors: {len(rows) - len(good)}")
    if args.out:
        Path(args.out).write_text(json.dumps(dict(
            model=llm.model, at=datetime.now(UTC).isoformat(), num_ctx=settings.ollama_num_ctx,
            temperature=settings.ollama_temperature, by_target=summary, rows=rows), ensure_ascii=False, indent=1) + "\n")
        print(f"written: {args.out}")
    llm.close()  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
