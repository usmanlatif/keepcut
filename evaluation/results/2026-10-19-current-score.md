# M2 triage evaluation: current

Date: 2026-10-19
Git commit: `f9ee8be977da4b0dd51ed0b3e1815685327383f4`

dirty: no

Dirty status covers only uncommitted changes under `app/`.

Model: `course-chat`

| Working-tree file | SHA-256 |
| --- | --- |
| `app/prompts/triage.md` | `15b946e8a3195f3dd4543e6c748c9ec200a5308663d63e7b3a87d5495e953231` |
| `app/data/labels.md` | `3e0f45e9a9784466460158d4f7de86ff1bb456a019b9a989aaa3bda38cf287f5` |
| `app/data/business_profile.md` | `e10ee53b4b66d98ce1adadf4adda14b89dd9cb9f22985267ab68f2221f39a9f7` |
| `app/core/triage.py` | `64ac2cb2475109103306800f691a586151ac4d577207a512858a43302566ab92` |
| `app/core/context.py` | `daff77a28788853601021459decb0161966a5383ccbaac6075f5b1ebda5bb7aa` |
| `app/core/llm.py` | `6a55dfd713c436a6cf1bbae55359f2eb262fdd95cf668bca79696e780929a545` |
| `evaluation/score.py` | `1b3e567f3044d99c43cfc9d053088061589a14f2090404473bbd48173c148e5f` |
| `evaluation/golden_set.csv` | `90378c38b8d0275be6527ee3bc78205832d8aaa3847927e096b932031c20f848` |

Evaluates the current working tree with the app's triage function and current prompt. The version name is a results label, not a prompt selector.

Campaign: Plover Generic Search. Profile: `app/data/business_profile.md`.

Errors count as wrong decisions and remain in recall and share denominators. Precision is n/a when a class is never predicted. Macro scores average all three classes; if any component is undefined, the macro is n/a. A three-run mean/range is n/a if any run is undefined. Consistency requires the same valid decision (target, block, or monitor) in all three runs; any error breaks consistency. pass^3 requires three correct decisions.

## Run 1

Golden labels in rows; predicted decisions in columns.

| Golden label | target | block | monitor | error |
| --- | ---: | ---: | ---: | ---: |
| target | 9 | 0 | 4 | 0 |
| block | 0 | 14 | 9 | 0 |
| monitor | 0 | 0 | 4 | 0 |

| Metric | Score |
| --- | ---: |
| target precision | 100.00% |
| target recall | 69.23% |
| block precision | 100.00% |
| block recall | 60.87% |
| monitor precision | 23.53% |
| monitor recall | 100.00% |
| macro precision | 74.51% |
| macro recall | 76.70% |
| monitor share | 42.50% |
| whole-term triggers | 18.00 |
| intent transactional share | 62.50% |
| intent commercial share | 25.00% |
| intent informational share | 5.00% |
| intent navigational share | 7.50% |
| intent missing share | 0.00% |
| prompt tokens | 3950.00 |
| completion tokens | 1525.00 |
| total tokens | 5475.00 |
| calls | 2.00 |
| seconds | 63.02 |
| errors | 0.00 |
| validation/call diagnostics | 0.00 |

## Run 2

Golden labels in rows; predicted decisions in columns.

| Golden label | target | block | monitor | error |
| --- | ---: | ---: | ---: | ---: |
| target | 7 | 0 | 6 | 0 |
| block | 0 | 16 | 7 | 0 |
| monitor | 0 | 0 | 4 | 0 |

| Metric | Score |
| --- | ---: |
| target precision | 100.00% |
| target recall | 53.85% |
| block precision | 100.00% |
| block recall | 69.57% |
| monitor precision | 23.53% |
| monitor recall | 100.00% |
| macro precision | 74.51% |
| macro recall | 74.47% |
| monitor share | 42.50% |
| whole-term triggers | 22.00 |
| intent transactional share | 62.50% |
| intent commercial share | 22.50% |
| intent informational share | 10.00% |
| intent navigational share | 5.00% |
| intent missing share | 0.00% |
| prompt tokens | 3950.00 |
| completion tokens | 1574.00 |
| total tokens | 5524.00 |
| calls | 2.00 |
| seconds | 7.88 |
| errors | 0.00 |
| validation/call diagnostics | 0.00 |

## Run 3

Golden labels in rows; predicted decisions in columns.

| Golden label | target | block | monitor | error |
| --- | ---: | ---: | ---: | ---: |
| target | 7 | 2 | 4 | 0 |
| block | 0 | 17 | 6 | 0 |
| monitor | 0 | 0 | 4 | 0 |

| Metric | Score |
| --- | ---: |
| target precision | 100.00% |
| target recall | 53.85% |
| block precision | 89.47% |
| block recall | 73.91% |
| monitor precision | 28.57% |
| monitor recall | 100.00% |
| macro precision | 72.68% |
| macro recall | 75.92% |
| monitor share | 35.00% |
| whole-term triggers | 20.00 |
| intent transactional share | 60.00% |
| intent commercial share | 22.50% |
| intent informational share | 12.50% |
| intent navigational share | 5.00% |
| intent missing share | 0.00% |
| prompt tokens | 3950.00 |
| completion tokens | 1556.00 |
| total tokens | 5506.00 |
| calls | 2.00 |
| seconds | 11.64 |
| errors | 0.00 |
| validation/call diagnostics | 0.00 |

## Across three runs

| Metric | Mean | Min | Max |
| --- | ---: | ---: | ---: |
| target precision | 100.00% | 100.00% | 100.00% |
| target recall | 58.97% | 53.85% | 69.23% |
| block precision | 96.49% | 89.47% | 100.00% |
| block recall | 68.12% | 60.87% | 73.91% |
| monitor precision | 25.21% | 23.53% | 28.57% |
| monitor recall | 100.00% | 100.00% | 100.00% |
| macro precision | 73.90% | 72.68% | 74.51% |
| macro recall | 75.70% | 74.47% | 76.70% |
| monitor share | 40.00% | 35.00% | 42.50% |
| whole-term triggers | 20.00 | 18.00 | 22.00 |
| intent transactional share | 61.67% | 60.00% | 62.50% |
| intent commercial share | 23.33% | 22.50% | 25.00% |
| intent informational share | 9.17% | 5.00% | 12.50% |
| intent navigational share | 5.83% | 5.00% | 7.50% |
| intent missing share | 0.00% | 0.00% | 0.00% |
| prompt tokens | 3950.00 | 3950.00 | 3950.00 |
| completion tokens | 1551.67 | 1525.00 | 1574.00 |
| total tokens | 5501.67 | 5475.00 | 5524.00 |
| calls | 2.00 | 2.00 | 2.00 |
| seconds | 27.51 | 7.88 | 63.02 |
| errors | 0.00 | 0.00 | 0.00 |
| validation/call diagnostics | 0.00 | 0.00 | 0.00 |

Consistency: 77.50%.

pass^3: 60.00%.

## Reading sheet

Run 1 has 13 wrong/error rows. All are included, then correct rows sampled with seed 42 to reach 20, sorted by id.

## Interpretation

Whole-term triggers count predicted triggers equal to the search term after trimming spaces and ignoring case. Errors are final error rows; validation/call diagnostics also count problems encountered before retry recovery, without reproducing their text.

Token counts, calls, and seconds come from app triage and include retries. Cost is unavailable: the app reports no monetary cost or proxy tariff.

Coverage: 40 terms, one business, one model through the course proxy. The target class has 13 rows, so one error changes its recall by 7.69 percentage points. The block class has 23 rows, so one error changes its recall by 4.35 percentage points. The monitor class has 4 rows, so one error changes its recall by 25.00 percentage points. Intent is reported as a distribution, not accuracy. Demo metrics are synthetic. This scores triage only; it does not test the reviewer, summary, or demo injection.
