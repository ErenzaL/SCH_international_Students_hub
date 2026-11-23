**Draft abstract (preliminary - evaluation questions and labels are AI-drafted and not yet human-reviewed).**

International students need accurate answers about immigration, residence and university procedures in their own
language, while the authoritative sources are written mostly in Korean and English. We describe and evaluate a
retrieval-augmented assistant for international students at Soonchunhyang University built on
25 approved documents (766 chunks; intfloat/multilingual-e5-small,
384-dimensional embeddings in PostgreSQL/pgvector). On a held-out set of 100 synthetic questions
(20 scenarios in Korean, English, Indonesian, Vietnamese and Chinese) evaluated against the deployed system, the improved
hybrid retriever reached MRR 0.700 versus 0.647 for vector-only retrieval and
0.600 for equal-weight hybrid fusion (paired differences +5.3 pp (95% CI -0.4 to +11.8) and +10.0 pp (95% CI +3.0 to +18.1)). In the local
evaluation, the Recall@1 gain over vector-only retrieval on the development set used for tuning (+5.0 pp (95% CI -7.0 to +17.0)) was larger
than on the held-out set (+6.0 pp (95% CI -4.0 to +16.0)), illustrating the optimism of tuning-set evaluation. Answer quality (correctness, relevance, faithfulness) was not evaluated: no human-reviewed scores exist. We release the evaluation framework, a review workflow for
independent labels and the statistics of the knowledge base.
