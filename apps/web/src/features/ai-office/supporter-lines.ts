/**
 * What each language supporter says in THEIR language (independent of the site language): a short greeting, the
 * welcome line of their conversation and three example questions. The examples are suggestions the student can
 * click; they are sent as the student's own message (no hidden instructions).
 */
import type { LanguageCode } from "@/types/api";

export interface SupporterLines {
  greeting: string;
  welcome: string;
  examples: [string, string, string];
}

export const SUPPORTER_LINES: Record<LanguageCode, SupporterLines> = {
  ko: {
    greeting: "안녕하세요! 한국어로 도와드릴게요.",
    welcome: "안녕하세요, 한국어 지원 담당 민지예요. 비자, 학사, 생활에 관해 승인된 공식 자료를 바탕으로 한국어로 답해 드려요.",
    examples: ["외국인등록증은 언제까지 신청해야 하나요?", "시간제 취업 허가는 어떻게 받나요?", "D-2 비자 연장에 필요한 서류는 무엇인가요?"],
  },
  en: {
    greeting: "Hi! I can help you in English.",
    welcome: "Hello, I'm Alex from English support. I answer in English, based on approved official sources about visas, studies and daily life.",
    examples: ["When do I need to apply for my residence card?", "How do I get permission for part-time work?", "What documents do I need to extend my D-2 visa?"],
  },
  id: {
    greeting: "Halo! Saya bisa membantu dalam bahasa Indonesia.",
    welcome: "Halo, saya Sari dari layanan bahasa Indonesia. Saya menjawab dalam bahasa Indonesia berdasarkan sumber resmi yang sudah disetujui tentang visa, studi, dan kehidupan sehari-hari.",
    examples: ["Kapan saya harus mendaftar kartu izin tinggal (ARC)?", "Bagaimana cara mendapatkan izin kerja paruh waktu?", "Dokumen apa yang diperlukan untuk memperpanjang visa D-2?"],
  },
  vi: {
    greeting: "Xin chào! Mình có thể hỗ trợ bạn bằng tiếng Việt.",
    welcome: "Xin chào, mình là Minh, hỗ trợ bằng tiếng Việt. Mình trả lời bằng tiếng Việt dựa trên các nguồn chính thức đã được duyệt về visa, học tập và cuộc sống.",
    examples: ["Khi nào tôi phải đăng ký thẻ cư trú?", "Làm thế nào để xin phép làm thêm?", "Cần những giấy tờ gì để gia hạn visa D-2?"],
  },
  "zh-CN": {
    greeting: "你好！我可以用中文为你提供帮助。",
    welcome: "你好，我是中文支持的 Mei。我会根据已审核的官方资料，用中文回答关于签证、学业和生活的问题。",
    examples: ["外国人登录证需要在什么时候之前办理？", "如何申请校外打工许可？", "延长 D-2 签证需要哪些材料？"],
  },
};
