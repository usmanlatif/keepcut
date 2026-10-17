# AGENTS.md

Read this first, every session. Before building anything, read the `docs/prd.md` section the task names.

## What this is

A weekly search-terms review assistant: it reads each term in a Google Ads search terms report against a business profile and drafts a target, block or monitor decision with a reason, for a paid media manager to review.

## Two zones

- **`app/` is the product.** It holds everything the running app needs and nothing else.
- **Everything outside `app/` is build and proof** (`evaluation/`, `tests/`, `scripts/`, `docs/`, `.githooks/`). It never ships with the app.
- **`app/` never imports from or reads anything outside `app/`.**

## Who builds what

- **Claude builds the app** (`app/`).
- **Codex builds the evaluation** (`evaluation/`, the scorer and checks).
- Each reviews the other's changes before the owner commits.

## Run it

```bash
pip install -r app/requirements.txt
python app/main.py              # for now
streamlit run app/main.py       # once the screen exists
```

## Conventions

- **Prompts live in `app/prompts/` as files**, never inside code, so every version can be shown and re-run.
- **Every model call goes through `app/core/llm.py`**, the starter's client for the course proxy. No other provider, SDK or client.
- **Paths resolve from `app/`**, never from the working directory, so the app runs the same locally and in Codespaces.
- **The API key lives only in `.env` or the `LLM_API_KEY` environment variable.** Never in code, notes, prompts or commits.

## App rules

- Search metrics (clicks, cost, conversions) never reach the triage prompt.
- Data is synthetic or public only; nothing scraped.
- Nothing is stored between sessions.
- The app never writes to Google Ads.

## Golden-set rule

- Only `evaluation/golden_set.csv` is off limits, and it is never edited. It is read only by the scorer.
- Never open it, quote it, or use its terms as examples, in a prompt or anywhere in `app/`.
- The rest of `evaluation/` (scorer, checks, results) may be read and reviewed.
- `leak-check` enforces this on every commit.

## Working rule

1. Run the checks before you report.
2. Never commit. The project owner commits.
3. Report what changed: files touched and check results.

## One-time setup

Each clone runs `git config core.hooksPath .githooks` once so the pre-commit hook fires.
