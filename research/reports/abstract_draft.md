**Draft abstract (preliminary - evaluation questions and labels are AI-drafted and not yet human-reviewed).**

International students need accurate answers about immigration, residence and university procedures in their own
language, while the authoritative sources are written mostly in Korean and English. We describe and evaluate a
retrieval-augmented assistant for international students at Soonchunhyang University built on
23 approved documents (457 chunks; intfloat/multilingual-e5-small,
384-dimensional embeddings in PostgreSQL/pgvector). On a held-out set of 100 synthetic questions
(20 scenarios in Korean, English, Indonesian, Vietnamese and Chinese) evaluated against the deployed system, the improved
hybrid retriever reached MRR 0.693 versus 0.669 for vector-only retrieval and
0.551 for equal-weight hybrid fusion (paired differences +2.3 pp (95% CI -2.3 to +7.4) and +14.2 pp (95% CI +7.0 to +21.7)). In the local
evaluation, the Recall@1 gain over vector-only retrieval on the development set used for tuning (+12.0 pp (95% CI +3.0 to +21.0)) was larger
than on the held-out set (+3.0 pp (95% CI -6.0 to +13.0)), illustrating the optimism of tuning-set evaluation. Answer quality (correctness, relevance, faithfulness) was not evaluated: no human-reviewed scores exist. In 27 recorded production cases, 85% produced a generated answer (served by gemini-3.5-flash-lite). We release the evaluation framework, a review workflow for
independent labels and the statistics of the knowledge base.
