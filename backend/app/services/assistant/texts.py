"""Fixed assistant texts in the five site languages (used without an LLM and for safety framing)."""
from __future__ import annotations

NATIVE_NAMES = {"ko": "한국어", "en": "English", "id": "Bahasa Indonesia", "vi": "Tiếng Việt", "zh-CN": "中文"}

TEXT: dict[str, dict[str, str]] = {
    "found": {
        "en": "Here is what the approved official sources say (general guidance, not a decision about your case):",
        "ko": "승인된 공식 자료의 내용입니다(일반 안내이며 개인 사안에 대한 결정이 아닙니다):",
        "id": "Berikut informasi dari sumber resmi yang telah disetujui (panduan umum, bukan keputusan atas kasus Anda):",
        "vi": "Đây là thông tin từ các nguồn chính thức đã được duyệt (hướng dẫn chung, không phải quyết định cho trường hợp của bạn):",
        "zh-CN": "以下是已审核官方资料中的内容（一般性指导，并非针对您个人情况的决定）：",
    },
    "none": {
        "en": "I couldn't find this in the approved SCH and Korean government sources, so I can't answer it reliably. "
              "You could try rephrasing, or check with the responsible office.",
        "ko": "승인된 순천향대학교 및 한국 정부 자료에서 관련 내용을 찾지 못해 신뢰할 수 있는 답변을 드리기 어렵습니다. "
              "질문을 바꿔 보시거나 담당 부서에 확인해 주세요.",
        "id": "Saya tidak menemukan informasi ini di sumber resmi SCH dan pemerintah Korea yang disetujui, jadi saya tidak "
              "dapat menjawab dengan andal. Coba ubah pertanyaan Anda atau tanyakan ke kantor yang berwenang.",
        "vi": "Tôi không tìm thấy thông tin này trong các nguồn chính thức đã duyệt của SCH và chính phủ Hàn Quốc nên không "
              "thể trả lời chính xác. Bạn có thể hỏi lại theo cách khác hoặc liên hệ văn phòng phụ trách.",
        "zh-CN": "我在已审核的顺天乡大学和韩国政府资料中没有找到相关内容，因此无法给出可靠的回答。您可以换一种问法，或向负责部门确认。",
    },
    "individual": {
        "en": "Whether this applies to you depends on your personal situation — only the responsible office can decide that.",
        "ko": "본인에게 해당되는지는 개인 상황에 따라 다르며, 담당 부서만 결정할 수 있습니다.",
        "id": "Apakah ini berlaku untuk Anda tergantung situasi pribadi Anda — hanya kantor yang berwenang yang dapat memutuskannya.",
        "vi": "Điều này có áp dụng cho bạn hay không tùy vào hoàn cảnh cá nhân — chỉ văn phòng phụ trách mới quyết định được.",
        "zh-CN": "这是否适用于您取决于您的个人情况——只有负责部门才能决定。",
    },
    "offer": {
        "en": "Would you like me to prepare a request for a Global Supporter? Nothing is sent unless you confirm.",
        "ko": "글로벌 서포터에게 보낼 요청을 준비해 드릴까요? 확인하시기 전에는 아무것도 전송되지 않습니다.",
        "id": "Mau saya siapkan permintaan untuk Global Supporter? Tidak ada yang dikirim sebelum Anda konfirmasi.",
        "vi": "Bạn có muốn tôi chuẩn bị yêu cầu gửi Global Supporter không? Không có gì được gửi đi khi bạn chưa xác nhận.",
        "zh-CN": "需要我为您准备一份发给全球支持者的请求吗？在您确认之前不会发送任何内容。",
    },
    "conflicting": {
        "en": "The official sources I found are not fully consistent, so please confirm the details with the responsible office.",
        "ko": "찾은 공식 자료의 내용이 서로 완전히 일치하지 않으므로 담당 부서에 세부 사항을 확인해 주세요.",
        "id": "Sumber resmi yang saya temukan tidak sepenuhnya konsisten, jadi mohon konfirmasi detailnya ke kantor yang berwenang.",
        "vi": "Các nguồn chính thức tôi tìm được không hoàn toàn thống nhất, vui lòng xác nhận chi tiết với văn phòng phụ trách.",
        "zh-CN": "我找到的官方资料并不完全一致，请向负责部门确认具体信息。",
    },
    "greeting": {
        "en": "Hi! I can help with questions about studying at SCH and living in Korea — visas, dormitories, scholarships, "
              "insurance and more. What would you like to know?",
        "ko": "안녕하세요! 순천향대 유학 생활과 한국 생활에 관한 질문(비자, 기숙사, 장학금, 보험 등)을 도와드릴게요. 무엇이 궁금하신가요?",
        "id": "Halo! Saya bisa membantu pertanyaan seputar kuliah di SCH dan tinggal di Korea — visa, asrama, beasiswa, asuransi, "
              "dan lainnya. Apa yang ingin Anda ketahui?",
        "vi": "Xin chào! Tôi có thể giúp bạn về việc học tại SCH và cuộc sống ở Hàn Quốc — visa, ký túc xá, học bổng, bảo hiểm "
              "và nhiều hơn nữa. Bạn muốn hỏi gì?",
        "zh-CN": "你好！我可以帮你解答在顺天乡大学学习和在韩国生活的问题——签证、宿舍、奖学金、保险等。你想了解什么？",
    },
    "handoff_created": {
        "en": "Done — your request #{number} was sent to the {team}. A Global Supporter will reply in “My requests”, and "
              "you'll get a notification. Meanwhile, feel free to keep asking me.",
        "ko": "요청 #{number}을(를) {team}에 보냈습니다. 글로벌 서포터가 ‘내 요청’에서 답변하면 알림을 받으실 수 있어요. "
              "그동안 계속 질문하셔도 됩니다.",
        "id": "Selesai — permintaan #{number} sudah dikirim ke {team}. Global Supporter akan membalas di “Permintaan saya” "
              "dan Anda akan mendapat notifikasi. Sambil menunggu, silakan terus bertanya.",
        "vi": "Xong — yêu cầu #{number} đã được gửi tới {team}. Global Supporter sẽ trả lời trong “Yêu cầu của tôi” và bạn sẽ "
              "nhận được thông báo. Trong lúc chờ, bạn cứ tiếp tục hỏi tôi nhé.",
        "zh-CN": "已完成——您的请求 #{number} 已发送给{team}。全球支持者会在“我的请求”中回复，您也会收到通知。在此期间，您可以继续向我提问。",
    },
    "team": {
        "en": "{language} support team", "ko": "{language} 지원팀", "id": "tim dukungan {language}",
        "vi": "nhóm hỗ trợ {language}", "zh-CN": "{language}支持团队",
    },
    "thanks": {
        "en": "You're welcome! Ask me anytime if anything else comes up.",
        "ko": "천만에요! 다른 궁금한 점이 생기면 언제든지 물어보세요.",
        "id": "Sama-sama! Tanyakan saja kapan pun kalau ada hal lain.",
        "vi": "Không có gì! Cứ hỏi tôi bất cứ lúc nào nếu bạn cần thêm.",
        "zh-CN": "不客气！还有其他问题随时问我。",
    },
}


def t(key: str, lang: str) -> str:
    return TEXT[key].get(lang) or TEXT[key]["en"]
