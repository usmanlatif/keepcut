---
name: leak-check
description: Check app files for golden-set search terms before reporting changes or committing.
---

# Leak check

Run from the repository root:

```bash
python3 .agents/skills/leak-check/scripts/leak_check.py
```

Default mode scans the working tree under `app/`, including untracked and ignored
files. Pass `--staged` to scan only staged app files using their Git index content.
The pre-commit hook uses `--staged` and explicitly selects the real golden set.

Let the script read the protected CSV; never open it or display its terms.
Exit 0 reports the number of terms checked. Exit 1 lists matching file and start
line locations without printing terms or source lines. Fix product leaks and
rerun; never change the golden set to make the check pass.

Matching applies Unicode NFKC, casefolding, and collapses non-alphanumeric runs
to spaces on both terms and text. Matches require whole words and can cross
line breaks. UTF-16 BOM files are decoded; other files containing NUL are skipped.

Use `--golden /path/to/fixture.csv` only for manual synthetic tests with a
`search_term` column. The default is `evaluation/golden_set.csv`. CSV files are
read as UTF-8 with an optional BOM.
Remove and unstage temporary app files after testing.

Known limits: UTF-16 without a byte-order mark, compressed files, words run together, and URL-encoded text are not caught.
