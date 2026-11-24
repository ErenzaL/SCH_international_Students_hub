# Stage 2 assessment: real-time Qwen answers for the live chatbot

**Status: assessment only. Nothing is built, exposed or deployed, and nothing may be without written approval from
university IT.** Recommendation: not now. Keep Gemini for the chatbot and use the GPU for drafts (stage 1).

## What was measured

| | Value | Source |
|---|---|---|
| Full RAG turn, local (rewrite + search + answer) | 1.2–2.6 s, about 2 s median | 15 questions × 2, three synthetic documents |
| Generation speed | about 90 tokens/s, one request at a time | RTX 4070, Q4_K_M |
| GPU memory | about 5.6 GB with a 16k context | Ollama |
| Citations and grounding accepted by the app | 30/30 after a format reminder (2/5 before) | same run |
| Known errors | wrong terms in Indonesian, occasional Chinese words, one dropped date range in translation | benchmark |

Network time is not included. Three documents are far from the production corpus, so the 30/30 is not a quality forecast.

## Options

| Option | Inbound port at school | Extra cost | Assessment |
|---|---|---|---|
| A. Worker-initiated stream (WebSocket or long poll from school to the API) | none | $0 | Only acceptable design. Keeps the API awake whenever the worker is connected |
| B. Tunnel (Cloudflare Tunnel, Tailscale) to an authenticated gateway | none, but publishes a service | $0 plans exist | Bypasses the university perimeter; needs explicit IT approval and an owner |
| C. Public reverse proxy with TLS on the school network | yes | $0 | Reject: exposes a student-run service on the university network |
| D. Existing job queue with polling | none | $0 | Reject for chat: seconds of delay before the first word |

## Why not now

1. **Privacy.** Chat messages contain personal data. Stage 1 sends only public text to the school server; chat would
   process student messages on a shared machine where other accounts and administrators exist.
2. **Availability.** One workstation without redundancy, and a free API instance that sleeps. Gemini stays necessary as
   fallback; a fallback that leaves the school also changes what students must be told about their data.
3. **Capacity.** One request at a time: ten simultaneous students wait about 20 s. Translation shares the same GPU.
4. **Quality.** Not evaluated on real content in five languages by native speakers.
5. **Free hours.** A permanent connection keeps Render awake (about 744 of 750 hours).

## Requirements if it is reconsidered (option A)

- Written approval: IT (network, account, GPU use), the data-protection contact, and the project owner.
- A separate, short-lived credential and a separate process from stage 1; mutual authentication; per-request deadline.
- Fixed request shape (messages, limits), no arbitrary Ollama API, no model management, no tools.
- Redaction before sending, no prompt or answer logging at school, memory only, retention zero, notice to students.
- Admission control: at most 1–2 running and 4 waiting, chat before translation, over the limit → Gemini.
- Circuit breaker with a health signal: first word within 3 s or Gemini answers.
- Shadow evaluation first: synthetic and consented questions, native reviewers, per-language acceptance against Gemini.
- Kill switch on the API side; penetration test of the endpoint; named owner and an incident contact at IT.

## Questions for university IT

1. Is a continuously running outbound process on this account and GPU allowed, and under which policy?
2. May student messages be processed on this machine? Who has administrative access, and what is logged?
3. Is a persistent outbound WebSocket to a commercial host allowed? Are tunnels prohibited?
4. Are there maintenance windows, GPU time limits, or other users with priority?
