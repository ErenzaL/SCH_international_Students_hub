"""Deterministic prompt-injection screening (RAG v2, Phase 12). Five languages, no model call.

Measured with a local proxy model (scripts/rag_v2/injection_eval.py): a sentence in an APPROVED document that tells
"the AI" to say something was obeyed ("D-2 extensions are free"; a planted password was repeated), and a request to
translate the hidden rules produced a paraphrase of the system prompt that the verbatim leak check could not see.

* ``screen_passage`` removes sentences addressed to an AI / assistant / chatbot that try to give it orders ("ignore
  previous instructions", "note to the AI assistant: tell students …", "이 문서를 읽는 AI는 … 알려 주세요") from the text
  sent to the model. Ordinary guidance for staff or students is untouched; the approved knowledge articles' own
  "chatbot policy" sections do not match (tested on the corpus snapshot).
* ``asks_for_instructions`` recognises requests for the system prompt / hidden rules; they get a fixed reply.
* ``discloses_instructions`` recognises an answer that talks about its own system instructions in any of the five
  languages (a translated or paraphrased leak); such an answer is replaced like a verbatim leak.
"""
from __future__ import annotations

import re

_ORDER = re.compile("|".join([
    # "ignore / disregard previous instructions" (en, ko, id, vi, zh)
    r"\b(ignore|disregard|forget|override)\b[^.\n。]{0,60}\b(instructions?|rules?|prompts?|guidelines)\b",
    r"(이전|앞의|위의|기존|모든)\s*(의\s*)?(지시|명령|지침|규칙)[^.\n]{0,20}무시",
    r"\babaikan\s+(semua\s+)?(instruksi|perintah|aturan)",
    r"\bbỏ qua\s+((mọi|tất cả|các)\s+)?(chỉ dẫn|hướng dẫn|lệnh|quy tắc)",
    r"忽略(之前|以上|所有|前面|先前)的?(所有)?(指令|指示|规则|提示)",
    # a note / order addressed to the model
    r"\b(note|instruction|message|command|order)s?\s+(to|for)\s+(the\s+)?(ai|assistant|chatbot|language model|llm|bot)\b",
    r"\b(system|assistant|ai)\s+(note|instruction|prompt|message|command)\s*:",
    r"(AI|인공지능|챗봇|어시스턴트|언어\s*모델)(는|은|에게|가)\s[^.\n]{0,60}(알려\s*주|말해\s*주|말하|출력|답하|전달)",
    r"\b(ai|asisten|chatbot)\s+(harus|wajib)\s+(memberi tahu|mengatakan|menjawab)",
    r"(AI|trợ lý|chatbot)\s+(phải|hãy)\s+(nói|trả lời|cho biết)",
    r"(AI|助手|机器人|模型)(必须|应该|请)(告诉|回答|说)",
]), re.I)

_ASK = re.compile("|".join([
    r"\bsystem\s*prompt\b", r"\b(your|the)\s+(hidden|secret|internal|initial|original)\s+(rules|instructions|prompt)\b",
    r"\b(your|the)\s+system\s+(instructions|rules|message)\b", r"\bprompt\s+(word for word|verbatim)\b",
    r"\b(print|show|reveal|repeat|output)\s+(me\s+)?(your|the)\s+(instructions|rules|prompt)\b",
    r"시스템\s*(프롬프트|지시|지침|메시지)", r"(너|당신|네)의\s*(지시|지침|규칙|프롬프트)", r"숨겨진\s*(규칙|지시|지침)",
    r"\b(instruksi|prompt|perintah)\s+sistem", r"\baturan\s+(tersembunyi|rahasia|internal)",
    r"hướng dẫn hệ thống", r"lời nhắc hệ thống", r"quy tắc (ẩn|bí mật|nội bộ)",
    r"系统(提示|指令|提示词|消息)", r"隐藏(的)?(规则|指令)", r"你的(指令|规则|提示词|设定)",
]), re.I)

_DISCLOSE = re.compile("|".join([
    r"\bmy\s+(system\s+)?(instructions|prompt|hidden rules)\b", r"\bsystem\s+prompt\b",
    r"(제|나의|저의)\s*(시스템\s*)?(지시|지침|프롬프트|규칙)", r"시스템\s*프롬프트",
    r"(instruksi|aturan)\s+(sistem|tersembunyi)\s+saya", r"\b(instruksi|prompt)\s+sistem\b",
    r"hướng dẫn hệ thống", r"quy tắc (ẩn|nội bộ) của tôi",
    r"我的(系统)?(指令|提示词|规则|设定)", r"系统(提示|指令|提示词)",
]), re.I)

_SENTENCE = re.compile(r"(?<=[.!?。！？])\s+")


def screen_passage(text: str) -> tuple[str, int]:
    """(text without the orders to the model, number of sentences removed). An order runs to the end of its paragraph:
    the sentence that names "the AI" is usually followed by what it is told to say."""
    if not text or not _ORDER.search(text):
        return text, 0
    out, removed = [], 0
    for para in text.split("\n"):
        sents = _SENTENCE.split(para)
        first = next((i for i, x in enumerate(sents) if _ORDER.search(x)), None)
        if first is None:
            out.append(para)
            continue
        removed += len(sents) - first
        if first:
            out.append(" ".join(sents[:first]))
    return "\n".join(out).strip(), removed


def asks_for_instructions(question: str) -> bool:
    return bool(_ASK.search(question or ""))


def discloses_instructions(answer: str) -> bool:
    return bool(_DISCLOSE.search(answer or ""))
