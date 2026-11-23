# Answer-quality rubric v1 (fixed; do not edit - create v2 instead)

Applies to one assistant answer to one question, judged against the approved source documents (and the human
reference answer, where one exists). Score each dimension independently. Record the reviewer (human) or the judge
model + prompt version (LLM-as-judge) for every score; keep human and model judgments in separate columns.

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| **Correctness** | States something wrong about a rule, requirement, deadline, fee or procedure | Correct but incomplete: misses a material condition | Correct and complete for what the sources support |
| **Relevance** | Does not answer the question asked | Answers it, with unrelated or excessive material | Answers exactly the question asked |
| **Faithfulness** | Contains a claim not supported by the cited/approved sources | Supported, but over-generalises or drops a qualifier | Every claim is supported by the sources |
| **Citation accuracy** | A cited source does not support the claim it is attached to | Sources are relevant but at least one is unnecessary or one supporting source is missing | Every cited source supports the answer and no relevant source is missing |

Additional counts / flags per answer:
- **Unsupported claims**: number of factual statements (requirements, numbers, dates, offices, URLs) not supported by
  any approved source. Unsupported claim rate = answers with >= 1 unsupported claim / answers judged.
- **Language consistency**: the whole answer is in the requested language (Korean official terms in parentheses are
  allowed).
- **Appropriate abstention** (questions without evidence): says it could not verify the information; no invented
  facts.
- **High-stakes items** (immigration status, work permission, deadlines): correctness and faithfulness must be judged
  by a human against the reference answer; LLM-as-judge scores are reported separately and never replace them.

Aggregation: report means with 95% bootstrap intervals and n; report failed/unavailable generations as their own
category (never drop them).
