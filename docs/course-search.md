# How course search works

The guide searches the local SkillsFuture course catalogue for courses that teach each missing skill. The default mode is **hybrid search followed by reranking** (`hybrid_rerank`). The search implementation is in [course_search.py](../src/course_search.py). It is called by the **course agent**, [course_agent.py](../src/course_agent.py): code searches first; the AI rewrites queries only for skills with no strong match, then picks one course per skill from the candidates code found (up to 4). A rewritten query must pass the same strong-match threshold, and a pick that is not on the list is replaced by `choose_course()`. The agent is evaluated on its own in E3b (see the [evaluation guide](evaluation.md)).

## Search flow

1. Take a missing skill from the chosen career path.
2. Retrieve courses using both keyword search (BM25) and meaning search (dense embeddings).
3. Combine their rankings using Reciprocal Rank Fusion (RRF).
4. Rerank the combined candidates by how well their descriptions match the query.
5. Collapse duplicate titles and check the relevance threshold.
6. Return up to four candidate courses per skill (the agent picks one), or retry with a broader query and more candidates.

Search ranks courses by relevance. Personal funding calculations happen afterwards, when the graph adds the user's estimated fee to each returned course.

## What we search

Courses are read from `data/careers.db`. During [data preparation](../src/data_prep.py), each course's title, about text and learning outcomes are combined into `search_text`, capped at 2,000 characters.

BM25 uses that stored text. Dense embeddings and reranking each use its first 1,000 characters. Content beyond these limits cannot contribute to those models' decisions. Fees, ratings and provider reputation are not ranking signals.

## BM25 and dense retrieval

| Method | How it works | Why we use it |
|---|---|---|
| BM25 | Matches query words against course text, accounting for term frequency, term rarity and document length. | Finds exact terminology such as Python or SQL. |
| Dense | Represents the query and course text as embedding vectors, then ranks courses by vector similarity. | Finds similar meanings even when wording differs, such as visualization and dashboarding. |

BM25 uses `BM25Okapi`. Text is lowercased, split into letter/number tokens and filtered with the stopword list in the code. Only courses with a positive BM25 score are returned.

Dense search defaults to `BAAI/bge-small-en-v1.5`. Course vectors are computed in advance and stored in `data/index/course_vectors.npy`, with corresponding course IDs in `course_vector_ids.json`. At search time, the query is prefixed with `Represent this sentence for searching relevant passages: ` and encoded. Both course and query vectors are normalized, so their dot product gives cosine similarity.

## Hybrid: combining the rankings

Hybrid uses **equal-weight Reciprocal Rank Fusion**. It combines ranking positions rather than adding the raw BM25 and dense similarity scores, which have different scales.

For each course:

```text
hybrid score = BM25 contribution + dense contribution
contribution = 1 / (60 + rank)
```

Ranks start at **0** in this implementation: first position has rank 0, fifth has rank 4. A course receives a contribution only from a list in which it appears.

For example:

| Course | BM25 position | Dense position | Calculation | Hybrid score |
|---|---|---|---|---|
| A | 1st | 20th | 1/60 + 1/79 | 0.02932 |
| B | 5th | 5th | 1/64 + 1/64 | 0.03125 |

Course B ranks above A because its combined contribution is higher. This is how the system resolves different rankings: neither retriever has an overriding vote. If fusion scores tie, Python's stable sort preserves insertion order; BM25 results are inserted first.

The constant **60** smooths the contributions so one top position does not dominate as strongly. A smaller constant gives more emphasis to top positions; a larger constant makes contributions more similar. It is fixed in the code, rather than learned or tuned by the evaluation. There is no configurable 70/30 or other percentage split.

By default, each retriever supplies up to 30 candidates. Fusion combines their union and keeps the top 30 candidates. These scores determine ordering; they are not relevance probabilities.

## Reranking and duplicate removal

In `hybrid_rerank` mode, the default cross-encoder is `cross-encoder/ms-marco-MiniLM-L-6-v2`. It reads each query–course-text pair together and assigns a relevance score. Candidates are then ordered by that score; the RRF score is not added to it.

After ranking, courses with the same normalized title are collapsed, keeping the first occurrence. Normalization removes parenthesized text and applies the tokenizer, so different runs or formats of a course may count as one result. The low-level `search()` method returns up to five distinct courses by default; the career guide requests up to two per missing skill.

The returned `score` is the reranker score in `hybrid_rerank` mode. In the other modes it is `None`. A reranker score is not a percentage or probability of relevance.

## Relevance threshold and fallbacks

The guide's `find_courses_for_skill()` wrapper tries these steps in order:

| Attempt | Query | Candidate pool |
|---|---|---|
| `title` | Skill name | 30 |
| `broadened` | Skill name plus framework skill description | 30 |
| `widened` | Skill name plus framework skill description | 90 |

In hybrid modes, the pool size applies both to each retriever's input list and to the fused shortlist. The wrapper stops at the first attempt with at least one qualifying course; it does not continue merely to fill both result slots. If no skill description is available, the broadened and widened attempts are skipped.

For `hybrid_rerank`, a returned course qualifies when its reranker score is at least `CAREER_RERANK_GOOD`. The source-code default is **0.0**, marked as a placeholder; an environment setting can override it. The wrapper checks this threshold after `search()` returns its requested number of distinct courses. In modes without a reranker, returned courses qualify without a score threshold.

If every attempt fails, the wrapper returns `no_strong_match`, an empty course list and a message directing the user to search MySkillsFuture. It does not perform a web search. Retrieval, reranking and retries run through code and local models, without additional chat-model calls.

## Modes and configuration

| Mode | Retrieval and ordering |
|---|---|
| `bm25` | Keyword ranking only |
| `dense` | Embedding similarity only |
| `hybrid` | BM25 and dense rankings combined with RRF |
| `hybrid_rerank` | Hybrid candidates reordered by the cross-encoder (default) |

| Environment variable | Source-code default |
|---|---|
| `CAREER_SEARCH_MODE` | `hybrid_rerank` |
| `CAREER_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` |
| `CAREER_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| `CAREER_RERANK_GOOD` | `0.0` |

Build the embedding index once after preparing the database:

```bash
python src/course_search.py --build
```

Rebuild it when course search text or the embedding model changes. The loader checks that saved course IDs match the database, but does not detect text-only or model changes.

Try a query from the project root:

```bash
python src/course_search.py "Data Governance"
```

The CLI runs the low-level search and prints up to five courses. It does not run the guide's threshold-and-fallback wrapper. Set environment variables in the shell when using this CLI; it does not load `.env` itself.
