# Labels

## target
A business searching for something Plover sells, in a segment Plover serves, specific enough to deserve its own keyword, in an existing theme or a new one.
Typical signals: "merchant account for salons", "restaurant pos system", "switch credit card processor", "square alternative".

## block
This search should not trigger this campaign: wrong person, wrong product, unserved segment, or looking for a competitor by name without intent to switch.
Typical signals: jobs, careers, login, customer service number, CBD or vape, "free", loans, a country outside the US, consumer card questions.

## monitor
Relevant, but not clear or specific enough to act on today: research, comparison or definition searches, or unclear intent. No action now; look again next week.
Typical signals: "what is a payment gateway", "card processing comparison", "how does card processing work".

## Boundary rules
1. Competitor terms: switching or comparing ("square alternative", "cheaper than stripe") is target. Navigating to the competitor ("square login", "clover customer service") is block. Researching it ("stripe fees") is block for this campaign, because the account has no competitor campaign.
2. Question terms: questions about the concept ("what is interchange") are monitor. Questions about getting set up ("how to accept credit cards at my salon") are target.
3. "Free": "free card processing" is block, because Plover never offers it. "Free card reader" is monitor, because a terminal deal can still convert.
4. Unserved segment wins: any high-risk, non-US or consumer signal makes the term block, however strong the buying intent ("cbd merchant account").

## Tie-breakers
- Between block and monitor, choose monitor. A wrong block cuts off buyers from the campaign for good; a missed one costs a few clicks.
- Between target and monitor, choose monitor. A keyword is added on clear evidence, not on hope.
- monitor is the safe default. There is no "unsure" label.

## Output format
One JSON object per search term:
{"label": "block", "trigger": "login", "reason": "Searcher is an existing Square customer looking for their account."}
- label: exactly one of target, block, monitor.
- trigger: the word or words in the search term that decided the label, copied exactly from the term.
- reason: one sentence.