# Failure taxonomy

Source: [2026-10-19-current-read20.csv](results/2026-10-19-current-read20.csv). Counts computed from the CSV with Python `collections.Counter`.

| Family | Count | IDs |
| --- | ---: | --- |
| correct | 4 | GS-001, GS-004, GS-028, GS-033 |
| unstable across runs | 3 | GS-008, GS-010, GS-030 |
| sees off-topic, still hedges | 5 | GS-009, GS-013, GS-025, GS-029, GS-038 |
| quotes block rule, answers monitor | 4 | GS-012, GS-014, GS-031, GS-036 |
| hedges on clear buying intent | 4 | GS-016, GS-022, GS-037, GS-039 |

Count check: 4 + 3 + 5 + 4 + 4 = 20.

Families are assigned by the run 1 answer; the table below lists every row whose labels differ across the three runs, computed from the source CSV with Python.

| ID | Family | Run 1 label | Run 2 label | Run 3 label |
| --- | --- | --- | --- | --- |
| GS-008 | unstable across runs | target | monitor | target |
| GS-010 | unstable across runs | target | monitor | monitor |
| GS-014 | quotes block rule, answers monitor | monitor | block | monitor |
| GS-016 | hedges on clear buying intent | monitor | monitor | block |
| GS-029 | sees off-topic, still hedges | monitor | monitor | block |
| GS-030 | unstable across runs | target | target | monitor |
| GS-031 | quotes block rule, answers monitor | monitor | block | block |
| GS-038 | sees off-topic, still hedges | monitor | monitor | block |
| GS-039 | hedges on clear buying intent | monitor | monitor | block |

Total rows with label changes: **9 of 20**.

## correct

### GS-001

> Right in all 3 runs; the trigger is the whole term, not the segment words that decide it.

### GS-004

> Right in all 3 runs; applies the unserved-segment rule and isolates the deciding words.

### GS-028

> Right in all 3 runs; isolates the competitor name and applies the research rule.

### GS-033

> Right in all 3 runs; the trigger matches the golden one exactly.

## unstable across runs

### GS-008

> Right in runs 1 and 3; run 2 hedged to monitor on a plain setup question.

### GS-010

> Right in run 1 only; a comparison search for a served product is not held as target.

### GS-030

> Right in runs 1 and 2; run 3 hedged to monitor.

## sees off-topic, still hedges

### GS-009

> Sees that a storage-card reader is not a payment terminal, yet hedges to monitor instead of blocking.

### GS-013

> Reads "without merchant account" as unclear rather than as a searcher who does not want the product, and hedges.

### GS-025

> Recognizes news intent with no buying interest, then monitors instead of blocking; the competitor name is not mentioned.

### GS-029

> Says the product is unrelated to payments, then hedges; the trigger is the whole term rather than the off-topic word.

### GS-038

> Names a different provider in the reason but hedges on fit; the trigger is "activate", not the provider name.

## quotes block rule, answers monitor

### GS-012

> Quotes the rule that blocks competitor research, then picks monitor as safer; the trigger is the price word, not the competitor name.

### GS-014

> Reads the competitor rule as leaving room for target and hedges; the trigger is the whole term, so the competitor name is not isolated.

### GS-031

> Run 1's reason says the competitor rule blocks, but its label is monitor; runs 2 and 3 block correctly.

### GS-036

> Says the rule blocks competitor research, answers monitor, and picks the cost word as trigger instead of the competitor.

## hedges on clear buying intent

### GS-016

> Treats price shopping for the core service as doubt; never target, and run 3 blocks it.

### GS-022

> A city name plus the core service is local buying intent, but the model wants the business type spelled out and hedges.

### GS-037

> Clear purchase intent for the core service; hedges because it cannot tell whether the hardware is Plover's.

### GS-039

> Reason says the pricing rule keeps it as monitor; never target, and run 3 blocks it.
