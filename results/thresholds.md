# Threshold tuning (Fix 6)

Re-ranker scores for all 186 E2 pairs (skill vs the first 1,000 characters the app scores). Split by skill (seed 621): tune = 7 skills / 82 pairs (79 unanimous, used to fit), test = 8 skills / 104 pairs (95 unanimous).
Irrelevant (N) pairs: 7 in the tuning set, 9 in the unanimous test set. Small: read counts, not just %.

| Threshold | placeholder | tuned |
|---|---|---|
| RERANK_GOOD | 0.0 | -2.0 |
| WEAK_MATCH | 5.0 | -2.0 |
| STRONG_MATCH | 8.0 | -2.0 |

## Held-out test half: does the tuned value beat the placeholder?

| Threshold | value | rows | relevant kept | irrelevant caught | precision above | balanced acc |
|---|---|---|---|---|---|---|
| RERANK_GOOD (placeholder) | 0.0 | unanimous 95 | 97% (83/86) | 67% (6/9) | 97% | 82% |
| RERANK_GOOD (placeholder) | 0.0 | all 104 | 94% (85/90) | 50% (7/14) | 92% | 72% |
| RERANK_GOOD (tuned) | -2.0 | unanimous 95 | 99% (85/86) | 44% (4/9) | 94% | 72% |
| RERANK_GOOD (tuned) | -2.0 | all 104 | 98% (88/90) | 36% (5/14) | 91% | 67% |
| WEAK_MATCH (placeholder) | 5.0 | unanimous 95 | 74% (64/86) | 78% (7/9) | 97% | 76% |
| WEAK_MATCH (placeholder) | 5.0 | all 104 | 72% (65/90) | 79% (11/14) | 96% | 75% |
| WEAK_MATCH (tuned) | -2.0 | unanimous 95 | 99% (85/86) | 44% (4/9) | 94% | 72% |
| WEAK_MATCH (tuned) | -2.0 | all 104 | 98% (88/90) | 36% (5/14) | 91% | 67% |
| STRONG_MATCH (placeholder) | 8.0 | unanimous 95 | 24% (21/86) | 100% (9/9) | 100% | 62% |
| STRONG_MATCH (placeholder) | 8.0 | all 104 | 23% (21/90) | 100% (14/14) | 100% | 62% |
| STRONG_MATCH (tuned) | -2.0 | unanimous 95 | 99% (85/86) | 44% (4/9) | 94% | 72% |
| STRONG_MATCH (tuned) | -2.0 | all 104 | 98% (88/90) | 36% (5/14) | 91% | 67% |

What each column means for the user:
- RERANK_GOOD: *relevant kept* = good courses still shown; *irrelevant caught* = bad ones hidden.
- WEAK_MATCH: *irrelevant caught* = bad picks that get the 'weak match - check it' warning.
- STRONG_MATCH: *precision above* = how often a course allowed to win on price is really relevant.

CLOSE_MARGIN is not tuned: relevance labels cannot say which of two relevant courses is better.
