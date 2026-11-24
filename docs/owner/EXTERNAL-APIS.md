# External services and data sources

Checked on 2026-11-25 on the providers' own pages. "?" = the page does not say it: ask before use. **No service needs a payment.**

| Provider | Used by | Official page | API / key | Free | Quota | Storing / redistributing | Variable | Without it |
|---|---|---|---|---|---|---|---|---|
| **Google Gemini** | live chat, server-side translation drafts | [pricing](https://aistudio.google.com/docs/pricing), [key](https://aistudio.google.com/apikey) | API key | yes: 3.6 Flash and 3.5 Flash-Lite input and output are free on the standard tier; **free-tier content may be used to improve Google's products** | shown per key in AI Studio | model output | `LLM_API_KEY`, `LLM_PROVIDER=gemini` | chat shows excerpts of sources |
| **Supabase** | database, sign-in, files | [supabase.com](https://supabase.com) | keys | yes (500 MB, no backups) | plan | own data | `SUPABASE_*` | nothing works |
| **Render** | hosting | [render.com](https://render.com) | account | yes (750 h) | plan | – | – | – |
| **SCH boards and pages** (home.sch.ac.kr, sgee.sch.ac.kr) | Robo, Joon, Leo, Daniel, Yuna, Seo, Mia | [sgee.sch.ac.kr](https://sgee.sch.ac.kr/main/kor_main.php) | no API; public pages, robots.txt allows the paths used | yes | 1 request a second at most | quoted with a link; **ask the international office for its consent** | – | desk has no sources |
| **www.sch.ac.kr** | – | – | **robots.txt forbids automated access: not used** | | | | | |
| **Study in Korea** (NIIED) | Leo, Daniel, Yuna, Seo, Mia | [studyinkorea.go.kr](https://www.studyinkorea.go.kr) | no API; public pages | yes | 1 request a second | quoted with a link; terms of use: ? | – | fewer sources |
| **HiKorea** | Yuna | [hikorea.go.kr](https://www.hikorea.go.kr) | public notice list | yes | " | " | – | fewer sources |
| **TOPIK** | Seo | [topik.go.kr](https://www.topik.go.kr) | no API; pages need JavaScript, no text can be read | – | – | – | – | dates come from Study in Korea / SCH notices, entered by staff |
| **Public-institution jobs** (재정경제부) | Daniel | [data.go.kr/15125273](https://www.data.go.kr/data/15125273/openapi.do) | `https://apis.data.go.kr/1051000/recruitment`, service key | yes | per account: ? | **no restriction on use** | `DATA_GO_KR_SERVICE_KEY` | source stays blocked |
| **Saramin** | Daniel | [oapi.saramin.co.kr](https://oapi.saramin.co.kr/guide/job-search) | `https://oapi.saramin.co.kr/job-search`, access key after approval | yes (price not stated) | **500 calls a day** | ? read [cautions](https://oapi.saramin.co.kr/caution), ask api@saramin.co.kr | `SARAMIN_ACCESS_KEY` | source stays blocked |
| **JobKorea** | Daniel (not connected) | [API application](https://www.jobkorea.co.kr/service/api) | for **public institutions and schools**, individual approval, unique address per site, caller IP is registered | ? | up to 500 postings, new every 2 h | ? ask api@jobkorea.co.kr | – | not connected. Render has no fixed outgoing IP on the free plan: clarify first |
| **Buddies Korea** | – | no official site or API could be identified | ? | ? | ? | ? | – | not connected; tell me the address |
| **OCR.space** (optional) | screenshots | [ocr.space](https://ocr.space/ocrapi) | free key; **images are sent there** | yes | free limit | – | `OCR_PROVIDER=ocr_space`, `OCR_SPACE_API_KEY` | screenshots are typed by hand |
| **Hugging Face** | embedding model download at build time | – | none | yes | – | MIT model | – | – |

Saramin and the public-institution API were tested with recorded answer shapes, **not with a real key**. No platform is scraped.

## Get the two job keys

| | Public institutions | Saramin |
|---|---|---|
| 1 | account on data.go.kr | [apply](https://oapi.saramin.co.kr/join), wait for the approval mail |
| 2 | open the page above → 활용신청, purpose "student information" | Application → 앱 등록 → 내 앱리스트 → access-key |
| 3 | 마이페이지 → copy the **decoding** key | read the cautions; ask whether titles and links may be stored and shown |
| 4 | Render → API → Environment → `DATA_GO_KR_SERVICE_KEY` | `SARAMIN_ACCESS_KEY` |
| 5 | Admin → Agents → Sources → add the prepared source; AI Office → Daniel → Sources → Check now | the same |
| Good | status ok, candidates in Review | the same. `api_key_invalid` = wrong key |

Postings become candidates; after approval they show employer, place, deadline and a link, and leave search on their deadline. The posting page itself is never read.
