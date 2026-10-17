# Course proxy check

Run (UTC): 2026-10-17T21:57:03+00:00
Model: course-chat. Requests: 3; automatic retries: 0.

One neutral diagnostic prompt from `scripts/proxy_check_prompt.md` was reused unchanged.
No token cap was sent; the prompt requests a sentence of at most 12 words.

| Setting | Accepted | Exact error if no / observation | Token usage | Text before JSON answer | Seconds |
| --- | --- | --- | --- | --- | ---: |
| Baseline | yes | None; finish_reason=stop | Yes: prompt_tokens=51, completion_tokens=18, total_tokens=69, reasoning_tokens=0 | No | 2.038 |
| temperature=0 | yes | None; finish_reason=stop | Yes: prompt_tokens=51, completion_tokens=20, total_tokens=71, reasoning_tokens=0 | No | 1.435 |
| response_format={"type":"json_object"} | yes | JSON object returned: yes; finish_reason=stop | Yes: prompt_tokens=51, completion_tokens=22, total_tokens=73, reasoning_tokens=0 | No | 1.409 |

Accepted means the request succeeded, not that the proxy honored the setting. Errors are preserved verbatim after the exception type, except credential redaction and Markdown escaping. Transport failures cannot establish whether a setting is supported.
Times measure each complete SDK call, including network and generation. Visible prefixes are evidence only for these replies; hidden reasoning, rate limits, and the group's credit budget are not established by this check.
