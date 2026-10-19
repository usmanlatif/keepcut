# AGENTS.md

Read this first, every session. Before building anything, read the `docs/prd.md` section the task names.

## What this is

A weekly search-terms review assistant: it reads each term in a Google Ads search terms report against a business profile and drafts a target, block or monitor decision with a reason, for a paid media manager to review.

## Two zones

- **`app/` is the product.** It holds everything the running app needs and nothing else.
- **Everything outside `app/` is build and proof** (`evaluation/`, `tests/`, `scripts/`, `docs/`, `.githooks/`). It never ships with the app.
- **`app/` never imports from or reads anything outside `app/`. The one exception: `app/core/llm.py` loads the `.env` at the repository root, by its exact path, for the API key.**

## Review

- The agent that writes a change never reviews it.
- Review happens in a separate session with the read-only `reviewer` agent. An agent that loads agents natively uses it by name; any other agent follows `.agents/agents/reviewer.md`.
- Evaluation code is written in a separate session from the app code it scores.

## Run it

```bash
pip install -r app/requirements.txt
streamlit run app/main.py
# Evaluation (three model runs; use a unique version name):
python evaluation/score.py --version <name>
```

## Conventions

- **App prompts live in `app/prompts/` as files**, never inside code, so every version can be shown and re-run. Build and evaluation prompts may live with their scripts.
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
- Shared skill: `.agents/skills/leak-check/SKILL.md`; run `python3 .agents/skills/leak-check/scripts/leak_check.py`.

## Working rule

1. Run the checks before you report.
2. Never commit. The project owner commits.
3. Report what changed: files touched and check results.

## One-time setup

Each clone runs `git config core.hooksPath .githooks` once so the pre-commit hook fires.
