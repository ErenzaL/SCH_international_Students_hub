"""Response quality (system_v2): one final answer per turn - no automatic disclaimers, no supporter offers on
ordinary answered questions, no duplicated endings, no citation clutter - in all five languages. The supporter offer
is a structured action (metadata), rendered once by the client, never text in the answer."""
from __future__ import annotations

import pytest

from app.repositories.base import Query
from app.services.assistant.prompts import PROMPTS_DIR, load_system_prompt
from app.services.assistant.texts import t
from tests.test_assistant import _events, conv, say
from tests.test_assistant_m2 import Bot, bot, setup_kb
from tests.test_retrieval import make_doc

LEGACY = ("offer", "individual", "conflicting")


@pytest.fixture
def kb(env):  # type: ignore[no-untyped-def]
    out = setup_kb(env)
    out["sch"] = make_doc(env, "외국인 유학생 성적우수 장학금 안내",
                          "# 성적우수 장학금\n\n직전 학기 평점 3.5 이상인 외국인 유학생에게 수업료의 30%를 감면합니다.",
                          category="scholarships", language="ko", scope="university",
                          authority="official_university")["document_id"]
    return out


def noisy(core: str, lang: str) -> str:
    """The worst case seen in production: a correct answer followed by every kind of redundant ending."""
    return (f"{core}\n\n{core}\n\n{t('individual', lang)}\n\n{t('offer', lang)}\n\n{t('offer', lang)}\n\n"
            "Sources:\n- [1] D-2 Visa Extension\n- [1] D-2 Visa Extension\n\nLet me know if you have any other questions!")


CASES = [
    ("en", "What documents do I need to extend my D-2 visa?", "d2",
     "To extend your D-2 visa, you'll generally need:\n\n1. Passport and residence card [1]\n"
     "2. Certificate of enrollment [1]\n3. Proof of residence [1]\n\nApply before your permitted stay expires [1]."),
    ("ko", "유학생 아르바이트 조건이 뭐예요?", "pt",
     "시간제 취업 허가를 받은 후에 아르바이트를 할 수 있고, 학기 중에는 주당 25시간까지 가능합니다 [1]."),
    ("vi", "Tôi bị mất thẻ cư trú, phải làm lại như thế nào?", "arc",
     "Nếu bị mất thẻ cư trú, bạn cần xin cấp lại tại cơ quan xuất nhập cảnh trong vòng 14 ngày [1]."),
    ("id", "Apa syarat beasiswa prestasi untuk mahasiswa internasional?", "sch",
     "Beasiswa prestasi diberikan kepada mahasiswa internasional dengan IPK semester sebelumnya minimal 3.5, "
     "berupa potongan 30% biaya kuliah [1]."),
    ("zh-CN", "寒假怎么申请住宿舍？", "dorm",
     "寒假住宿需在门户网站申请，申请时间为2026年12月1日至12月11日，宿舍费每天10,000韩元 [1]。"),
]


@pytest.mark.parametrize("lang,question,doc,core", CASES)
def test_one_clean_answer_per_turn_in_every_language(kb, lang, question, doc, core):
    env = kb["env"]
    rewrite = {"standalone": question, "en": question, "ko": {"pt": "유학생 시간제 취업", "arc": "외국인등록증 분실 재발급",
                                                           "sch": "외국인 유학생 장학금", "dorm": "동계방학 생활관 입사 신청",
                                                           "d2": "D-2 체류기간 연장 서류"}[doc]}
    bot(env, Bot(noisy(core, lang), rewrite=rewrite,
                 meta={"evidence": "sufficient", "needs_human": "case_specific"}))   # model over-cautious
    msg = say(env, conv(env, language=lang), question)
    c, md = msg["content"], msg["metadata"]
    expected = core.replace(" [1]", "")
    assert c == expected, c                                              # exactly the answer, once
    for key in LEGACY:
        for any_lang in ("ko", "en", "id", "vi", "zh-CN"):
            assert t(key, any_lang) not in c                             # no template endings in any language
    assert "Sources:" not in c and "[1]" not in c and "Let me know" not in c
    assert md["offer_handoff"] is False and md["handoff_reasons"] == []  # answered: no supporter offer
    cited = [x for x in msg["citations"] if x["cited"]]
    assert [x["document_id"] for x in cited] == [kb[doc]]                # one relevant source, listed once
    assert len({x["document_id"] for x in msg["citations"]}) == len(msg["citations"])
    assert md["prompt_version"] == "system_v2" and md["answer_generation"] == "llm"


def test_explicit_request_is_answered_first_then_offered_once(kb):
    env = kb["env"]
    bot(env, Bot(f"Apply before your stay expires [1].\n\n{t('offer', 'en')}", meta={"needs_human": "explicit_request"}))
    msg = say(env, conv(env), "Can I talk to a real person about my D-2 extension?")
    assert msg["content"] == "Apply before your stay expires."          # the answer, without offer text
    assert msg["metadata"]["handoff_reasons"] == ["asked_for_human"] and msg["metadata"]["offer_handoff"] is True
    assert env.store.select("support_tickets", Query())[0] == []


def test_administrative_action_only_when_staff_must_act(kb):
    env = kb["env"]
    bot(env, Bot("Submit a certificate of enrollment with your D-2 extension application [1].",
                 meta={"needs_human": "administrative_action"}))
    informational = say(env, conv(env), "What documents do I need to extend my D-2 visa?")
    assert informational["metadata"]["offer_handoff"] is False            # how-to question: answered, no offer
    action = say(env, conv(env), "Please issue my certificate of enrollment for the D-2 extension")
    assert action["metadata"]["handoff_reasons"] == ["administrative_action"]


def test_the_model_never_learns_endings_from_earlier_turns(kb):
    env = kb["env"]
    cid = conv(env)
    # an assistant message stored by an older version, with the appended template endings
    old = say(env, cid, "What documents do I need to extend my D-2 visa?")
    env.store.update("ai_messages", {"content": f"Passport [1].\n\n{t('individual', 'en')}\n\n{t('offer', 'en')}"},
                     {"id": old["id"]})
    b = bot(env, Bot("The fee is 60,000 won [1]."))
    say(env, cid, "How much does it cost?")
    convo = b.answers()[-1][1].split("<conversation>")[1].split("</conversation>")[0]
    assert t("offer", "en") not in convo and t("individual", "en") not in convo and "[1]" not in convo
    assert "Passport." in convo


def test_streaming_delivers_one_final_message_without_markers(kb):
    env = kb["env"]
    bot(env, Bot(noisy("Bring your passport [1] and certificate of enrollment [1][2].", "en")))
    cid = conv(env)
    evs = _events(env.client.post(f"/api/v1/conversations/{cid}/messages/stream", headers=env.auth("student"),
                                  json={"content": "What documents do I need to extend my D-2 visa?"}).text)
    kinds = [e for e, _ in evs]
    assert kinds.count("done") == 1 and kinds[-1] == "done"
    streamed = "".join(d["text"] for e, d in evs if e == "delta")
    assert "[1]" not in streamed and "[2]" not in streamed
    final = evs[-1][1]["assistant_message"]["content"]
    assert final == "Bring your passport and certificate of enrollment."
    assert final.count("passport") == 1
    msgs = env.client.get(f"/api/v1/conversations/{cid}", headers=env.auth("student")).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["content"] == final


def test_genuinely_case_specific_question_without_evidence_is_offered_once(kb):
    env = kb["env"]
    bot(env, Bot("I couldn't verify in the available documents whether an overstay can be excused.",
                 meta={"evidence": "none", "needs_human": "case_specific", "in_scope": True}))
    msg = say(env, conv(env), "I overstayed by three days because I was in hospital. What happens in my case?")
    assert msg["metadata"]["handoff_reasons"] == ["individual_decision"]
    assert msg["content"].count("Global Supporter") == 0


def test_system_v2_keeps_v1_and_adds_the_focus_rules():
    v1 = (PROMPTS_DIR / "system_v1.txt").read_text(encoding="utf-8")
    v2 = (PROMPTS_DIR / "system_v2.txt").read_text(encoding="utf-8")
    for heading in [ln for ln in v1.splitlines() if ln.startswith("## ")]:
        assert heading in v2                                              # all 10 sections preserved
    changed = {"When escalation is appropriate, explain naturally that a Global Supporter may be able to help."}
    for line in v1.splitlines():
        if line.strip() and line not in changed:
            assert line in v2, line                                       # every other v1 line kept verbatim
    for rule in (
        "Answer only what the student asks. Do not add generic case-specific disclaimers, unnecessary warnings, or "
        "Global Supporter offers to ordinary informational answers.",
        "Do not automatically end responses with questions or suggestions.",
        "Keep responses concise and natural while preserving relevant factual requirements, deadlines, and safety "
        "information.",
        "Do not duplicate citations, source lists, or response endings.",
        "Escalation decisions are controlled by backend policy, not by the LLM independently inserting supporter "
        "offers."):
        assert rule in v2
    assert "## 11. Focus, length and endings" in v2
    assert load_system_prompt().version == "system_v2" and load_system_prompt("system_v1").version == "system_v1"
    assert load_system_prompt("system_v2").contract_version == "response_contract_v2"
