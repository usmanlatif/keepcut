---
name: run-eval
description: Run the M2 golden-set evaluation for a supplied version name and report its saved artifacts and summary. Makes three model runs.
---

# Run evaluation

Use the version name supplied by the user. From the repository root, run:

```bash
python evaluation/score.py --version <name>
```

Pass the name as one quoted argument. The name identifies the current app triage
and prompt; it does not select or modify a prompt. The scorer uses the app's
course-proxy client and requires the app dependencies and API key setup.

Report the final one-line summary verbatim and the three artifact paths printed
by the scorer: runs CSV, score Markdown, and read20 CSV. Existing results are
preserved with a numbered suffix. On failure, report the failure without
automatically retrying model runs.

Let the scorer read the golden set. Never open or display its terms, and do not
change `app/` or the golden set to run an evaluation.
