**Draft abstract (Milestone 5, preliminary - AI-drafted labels, not human-reviewed).**

We study retrieval for a multilingual assistant that answers international students' questions in Korean, English,
Indonesian, Vietnamese and Chinese from 25 approved university and government
documents written mainly in English and Korean (766 chunks; multilingual-e5-small in
PostgreSQL/pgvector). An error analysis of 200 synthetic questions shows that most first-rank failures arise when a
document in the question's own script outranks the relevant document in another language, followed by keyword
ambiguity and dominance of one long multi-topic guide. On a held-out set (100 questions, 20 scenarios) we compare dense
retrieval, two hybrid retrievers and off-the-shelf multilingual cross-encoder reranking on identical candidate pools:
the improved hybrid reaches MRR 0.706 [0.610, 0.800], and reranking it with bge-reranker-v2-m3 gives 0.787 [0.696, 0.870]
(paired difference +8.0 pp [+1.7, +14.0] (supported)) at a median local cost (Apple M1, GPU reranking) of 3700 ms per question.
Answer-level effects were not evaluated. All evaluation data, scripts and notebooks are released for review.
