# silentfail: detector precision and recall

Scripted API traces for all 15 tasks (reference solution plus a read-back after each write), 20 seeds, injection rate 0.5 per eligible call. No model calls.

| Detector | Injected | Caught (same call) | Caught (later call) | Missed | False positives | Precision | Recall |
|---|---|---|---|---|---|---|---|
| Tier 1: invariants | 407 | 179 | 59 | 169 | 1 of 593 clean | 99.6% | 58.5% |
| Tier 1 + 2: cross-checks | 407 | 407 | 0 | 0 | 0 of 593 clean | 100.0% | 100.0% |

Recall by fault type:

| Fault | Injected | Tier 1 | Tier 1 + 2 |
|---|---|---|---|
| `count_mismatch` | 55 | 100.0% | 100.0% |
| `field_corrupt` | 119 | 47.1% | 100.0% |
| `phantom_write` | 124 | 34.7% | 100.0% |
| `stale_read` | 16 | 100.0% | 100.0% |
| `truncated_list` | 15 | 33.3% | 100.0% |
| `wrong_record` | 78 | 80.8% | 100.0% |

Clean traces (no injection): 50 calls, 0 flagged by tier 1, 0 by tier 1 + 2.
Cross-check cost: 860 extra API calls for 1000 agent calls (0.86 per call).
