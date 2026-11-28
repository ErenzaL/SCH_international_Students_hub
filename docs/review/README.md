# Checking machine translations: guide for reviewers

You are checking **drafts made by a computer**. Students rely on them for visas, money and deadlines, and they only see a
translation after **you** approve it. If you are not sure, do not approve.

You need: the Korean original, the draft, and good command of Korean and of your own language. Do not review a language you do not
speak natively without a second person.

## Part 1: the terms (once per language, about 30 minutes)

Open `glossary-<your language>.csv` (it opens in Excel or Google Sheets). Nobody has confirmed these terms yet.

| Column | What to write |
|---|---|
| decision | `ok`, `change` or `remove` |
| correction | the right term, if you chose `change` |
| reviewer, date | your name or initials, today's date |
| note | anything unclear, e.g. "the office uses another name" |

Please check in particular:
- **Names** (first rows): is there an official name in your language? Ask the international office about offices, buildings and
  centers. Do not invent one.
- **Legal words:** 외국인등록증, 출입국, 체류기간, 시간제취업, 불법취업, 범칙금, 강제퇴거. Use the words that students find on official
  (HiKorea) pages.
- **Study words:** 휴학, 복학, 전과, 계절학기, 학점교류. In some languages two very different things sound alike, such as "leave of
  absence" and "dropping out".
- **Missing words** you would expect: add a row at the end.

Two people per language should agree. The project team then puts your corrections into the program.

## Part 2: every draft

Read the original **line by line** next to the draft. Tick every box or reject the draft.

**Facts**
- [ ] Every date is the same day, month and year, also in the title
- [ ] Every weekday is right (this was wrong most often in Vietnamese)
- [ ] Every time is right; no time was added that the original does not have
- [ ] Every amount is right (300만원 = 3,000,000 won)
- [ ] Links, e-mail addresses and phone numbers are identical
- [ ] Deadlines: "until" and "from" are not mixed up

**Completeness**
- [ ] Nothing is missing: every list item, every ※ note, every table row
- [ ] Nothing was added: no advice, no explanation, no instruction that is not in the original

**Meaning**
- [ ] **Who** it is about is the same (new students, current students, exchange students, residents)
- [ ] **Exceptions** mean the same ("except", "only if", "not required")
- [ ] Must / may / must not are not mixed up
- [ ] Consequences (fines, penalty points, losing the dormitory place) are complete and equally strong
- [ ] Offices and authorities are the right ones (immigration is not police)

**Language**
- [ ] Only your language, except official names; no Chinese, Korean or other words left inside sentences
- [ ] Offices, buildings and terms as in the confirmed term list
- [ ] The title is translated and natural
- [ ] A student would understand it without the Korean original

**Result:** approve · correct it yourself and submit · reject with a short reason

Extra rule for **visa, immigration, work, money, insurance and legal** notices: two reviewers, and one of them also reads the
official page the notice refers to.

## Part 3: pilot record (one line per draft)

| Draft (title, language) | Minutes | Wrong facts | Missing / added | Wrong meaning | Wrong terms | Language | Decision | Reviewer |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

A language is ready for regular use when at least **10** drafts were reviewed by two people, **none** had a wrong fact, a missing
part or a wrong meaning that the reviewer could have overlooked, and correcting a draft took clearly less time than translating.
(These limits are a proposal; the project owner decides.)

## Examples of real mistakes found so far

| Language | Original | Draft |
|---|---|---|
| Vietnamese | 9. 9.(수) (Wednesday) | 9/9 (Friday) |
| Vietnamese | 생활관 (dormitory) | khách sạn (hotel) |
| Indonesian | 출입국 (immigration) | Polda (police) |
| Indonesian | 18:00까지 | 23:59 |
| Indonesian | 휴학생 (on leave) | mahasiswa yang berhenti studi (who quit) |
| English | who is exempt from the health check | another group is exempt |
| Chinese | list of 14 items | 7 items as a list |
| several | the section about fines | missing |

## Part 4: search questions in English about Korean notices (`crosslang_en_ko_v1_review.csv`, about 1 hour)

Each row is a question a student might ask and the Korean notice that should answer it (open the link). Fill in:

| Column | What to write |
|---|---|
| natural_wording | `yes` if a student would ask it like this; `no` otherwise |
| notice_answers_it | `yes`, `partly` or `no` |
| other_pages_that_answer | links of other official pages that answer it just as well, if you know any |
| better_question | optional: how a student would really ask |
| reviewer | your name or initials |

Do not search the Hub to check: the point is to decide what the right answer is before anyone sees what the search finds.
