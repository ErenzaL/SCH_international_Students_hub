"""Terms the local model must not invent. DRAFT: written by an AI assistant, to be confirmed by native speakers and the
international office before it is relied on. Only terms that occur in the text are given to the model."""
from __future__ import annotations

import re

# Korean (regular expression) -> en, id, vi, zh-CN
TERMS: list[tuple[str, str, str, str, str]] = [
    ("순천향대학교|순천향대", "Soonchunhyang University", "Universitas Soonchunhyang", "Đại học Soonchunhyang", "顺天乡大学"),
    ("생활관|기숙사", "dormitory", "asrama", "ký túc xá", "宿舍"),
    ("생활관비", "dormitory fee", "biaya asrama", "phí ký túc xá", "宿舍费"),
    ("입사생|사생(?!활)", "dormitory resident", "penghuni asrama", "sinh viên ở ký túc xá", "住宿生"),
    ("입사(?!자)", "move-in", "masuk asrama", "vào ở ký túc xá", "入住"),
    ("퇴사", "move-out", "keluar dari asrama", "trả phòng ký túc xá", "退宿"),
    ("글로벌빌리지", "Global Village", "Global Village", "Global Village", "Global Village"),
    ("학성사", "Hakseongsa", "Hakseongsa", "Hakseongsa", "学成舍（Hakseongsa）"),
    ("향설", "Hyangseol", "Hyangseol", "Hyangseol", "香雪（Hyangseol）"),
    ("신창역", "Sinchang Station", "Stasiun Sinchang", "ga Sinchang", "新昌站（Sinchang）"),
    ("국제교육교류처", "Office of International Education and Exchange", "Kantor Pendidikan dan Pertukaran Internasional",
     "Phòng Giáo dục và Giao lưu Quốc tế", "国际教育交流处"),
    ("유학생지원센터", "International Student Support Center", "Pusat Dukungan Mahasiswa Internasional",
     "Trung tâm Hỗ trợ Sinh viên Quốc tế", "留学生支援中心"),
    ("유학생", "international student", "mahasiswa internasional", "sinh viên quốc tế", "留学生"),
    ("외국인등록증", "residence card (ARC)", "kartu registrasi orang asing (ARC)", "thẻ đăng ký người nước ngoài (ARC)",
     "外国人登录证（ARC）"),
    ("출입국", "immigration", "imigrasi", "xuất nhập cảnh", "出入境"),
    ("체류기간", "period of stay", "masa tinggal", "thời gian lưu trú", "停留期限"),
    ("시간제\\s*취업", "part-time work (permit)", "kerja paruh waktu", "làm thêm bán thời gian", "时间制就业（兼职）"),
    ("불법\\s*취업", "illegal employment", "bekerja secara ilegal", "làm việc bất hợp pháp", "非法就业"),
    ("범칙금", "administrative fine", "denda administratif", "tiền phạt hành chính", "罚款"),
    ("강제퇴거", "deportation", "deportasi", "trục xuất", "强制驱逐出境"),
    ("벌점", "penalty points", "poin pelanggaran", "điểm phạt", "罚分"),
    ("보증금", "deposit", "uang jaminan", "tiền đặt cọc", "保证金"),
    ("가상계좌", "virtual account", "rekening virtual", "tài khoản ảo", "虚拟账户"),
    ("수강\\s*신청", "course registration", "pendaftaran mata kuliah", "đăng ký môn học", "选课"),
    ("계절학기", "seasonal semester", "semester pendek", "học kỳ phụ", "季节学期"),
    ("전과", "change of major", "pindah jurusan", "chuyển ngành", "转专业"),
    ("휴학생", "student on leave of absence", "mahasiswa yang sedang cuti", "sinh viên đang bảo lưu", "休学生"),
    ("휴학(?!생)", "leave of absence", "cuti kuliah", "bảo lưu", "休学"),
    ("복학", "return from leave of absence", "kembali aktif kuliah", "quay lại học", "复学"),
    ("기말평가|기말고사", "final exam", "ujian akhir semester", "thi cuối kỳ", "期末考试"),
    ("중간평가|중간고사", "midterm exam", "ujian tengah semester", "thi giữa kỳ", "期中考试"),
    ("수업평가|강의평가", "course evaluation", "evaluasi perkuliahan", "đánh giá môn học", "课程评价"),
    ("학점교류", "credit exchange", "pertukaran kredit (SKS)", "trao đổi tín chỉ", "学分交流"),
    ("장학금", "scholarship", "beasiswa", "học bổng", "奖学金"),
    ("학자금", "student financial aid", "bantuan biaya pendidikan", "hỗ trợ học phí", "学资金"),
    ("등록금", "tuition", "uang kuliah", "học phí", "学费"),
    ("건강검진", "health checkup", "pemeriksaan kesehatan", "khám sức khỏe", "健康检查"),
    ("결핵", "tuberculosis", "tuberkulosis", "bệnh lao", "结核病"),
    ("광복절", "Liberation Day of Korea", "Hari Kemerdekaan Korea", "Ngày Giải phóng Hàn Quốc", "光复节"),
    ("대체휴무|대체공휴일", "substitute holiday", "libur pengganti", "nghỉ bù", "补休"),
    ("종합정보시스템", "integrated information system", "sistem informasi terpadu", "hệ thống thông tin tổng hợp", "综合信息系统"),
    ("선착순", "first come, first served", "siapa cepat dia dapat", "ai đăng ký trước được trước", "先到先得"),
    ("국기원", "Kukkiwon", "Kukkiwon", "Kukkiwon", "国技院"),
    ("한국장학재단", "Korea Student Aid Foundation (KOSAF)", "Korea Student Aid Foundation (KOSAF)",
     "Quỹ Học bổng Hàn Quốc (KOSAF)", "韩国奖学财团（KOSAF）"),
]
_COL = {"en": 1, "id": 2, "vi": 3, "zh-CN": 4}


def terms_in(text: str, lang: str, limit: int = 25) -> list[tuple[str, str]]:
    if lang not in _COL:
        return []
    out = []
    for row in TERMS:
        m = re.search(row[0], text)
        if m:
            out.append((m[0], row[_COL[lang]]))
    return out[:limit]
