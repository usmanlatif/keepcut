# Labels

## add_keyword
The searcher is a business looking to buy or switch a product Plover sells, in a segment Plover serves, and the term is specific enough to bid on deliberately.
Typical signals: "merchant account for salons", "restaurant pos system", "switch credit card processor", "square alternative".

## add_negative
The searcher can never become a Plover customer from this search: wrong person, wrong product, unserved segment, or navigating to someone else's account.
Typical signals: jobs, careers, login, customer service number, CBD or vape, "free", loans, a country outside the US, consumer card questions.

## ignore
Relevant enough to keep matching, but not worth a dedicated keyword: research, comparison or definition searches, or intent too unclear to act on.
Typical signals: "what is a payment gateway", "square fees", "how does card processing work".

## Boundary rules
1. Competitor terms: switching or comparing ("square alternative", "cheaper than stripe") is add_keyword. Navigating to the competitor ("square login", "clover customer service") is add_negative. Researching it ("stripe fees") is ignore.
2. Question terms: questions about the concept ("what is interchange") are ignore. Questions about getting set up ("how to accept credit cards at my salon") are add_keyword.
3. "Free": "free card processing" is add_negative, because Plover never offers it. "Free card reader" is ignore, because a terminal deal can still convert.
4. Unserved segment wins: any high-risk, non-US or consumer signal makes the term add_negative, however strong the buying intent ("cbd merchant account").

## Tie-breakers
- Between add_negative and ignore, choose ignore. A wrong negative blocks revenue for good; a missed one costs a few clicks.
- Between add_keyword and ignore, choose ignore. A keyword is added on clear evidence, not on hope.
- ignore is the safe default. There is no "unsure" label.

## Output format
One JSON object per search term:
{"label": "add_negative", "trigger": "login", "reason": "Searcher is an existing Square customer looking for their account."}
- label: exactly one of add_keyword, add_negative, ignore.
- trigger: the word or words in the search term that decided the label, copied exactly from the term.
- reason: one sentence.