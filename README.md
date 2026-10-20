# KeepCut

Keep what works. Cut what doesn't.

KeepCut reviews your Google Ads search terms every week and drafts what to keep, what to cut and what to watch, with a reason for each.

## The problem

Every week a search terms report lists the queries people actually typed before clicking your ads. Reading it properly takes hours, so most teams skim it. Irrelevant queries keep spending, and the good ones never become keywords.

## How it works

KeepCut reads each term against your business profile and drafts a decision: target, block or monitor. A second check challenges every block. You review the table, change anything you disagree with and approve. KeepCut then builds three CSV files (negatives, new keywords, a watchlist) and a short weekly summary written from figures the code calculated. Nothing changes in your ad account: KeepCut drafts, you decide.

The app is one screen with six steps:

1. **Account**: edit the business profile and see exactly what the model is given.
2. **Report**: upload or paste a search terms export, or load the demo, then pick a campaign.
3. **Review terms**: the model drafts a decision and reason for each term, and a reviewer challenges the blocks.
4. **Check**: filter the table, read the reasons and reviewer notes, and change any decision.
5. **Dashboard**: see spend by decision, intent stage and ad group.
6. **Approve**: download the three CSV files and read the weekly summary.

## Who it is for

Paid search managers and in-house marketers who run Google Ads.

## Scope

Google Ads search terms today. Other ad platforms later.

## Try it

Click **Load demo report** in step 2. The demo report is synthetic, for Plover Payments, a fictional company.

## Run it locally

### Add your API key locally

You will receive your group's API key by e-mail. They go in a local `.env` file, which Git ignores.

1. Copy the example file:

   ```bash
   cp .env.example .env
   ```

2. Open `.env` and paste the key from the e-mail:

   ```
   LLM_API_KEY=...
   ```

   The proxy URL and model name are already built in; you do not need to set them.

3. Save the file. Do not rename it, and do not move the key anywhere else (code, notes, chat, issues).

4. Check that Git is not tracking it. This command must **not** list `.env`:

   ```bash
   git status
   ```

Never commit `.env` or paste the key into any file that is committed. If you think the key has leaked, e-mail the instructor straight away.

### Install and start

```bash
pip install -r app/requirements.txt
streamlit run app/main.py
```

## Run it in a Codespace

Open the repository in a Codespace. Dependencies install on create, and the app starts on port 8501 when you attach.

## How it is checked

`evaluation/` scores the triage decisions against a frozen golden set over three model runs (`python evaluation/score.py --version <name>`), checks that every number in the weekly summary appears in the figures it was written from, and tests a model judge of the summaries against human labels. `tests/` holds the unit tests.

## License

MIT. See [LICENSE](LICENSE).
