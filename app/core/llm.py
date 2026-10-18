"""Single place where the LLM client is created. Reads settings from the environment."""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # loads .env if present; harmless if not

# Course proxy defaults (not secrets). Only LLM_API_KEY is personal to your group.
DEFAULT_BASE_URL = "https://llm-proxy-obfzuamujq-ew.a.run.app/v1"
DEFAULT_MODEL = "course-chat"


def get_client() -> OpenAI:
    base_url = os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY not set. Check your .env file.")
    return OpenAI(base_url=base_url, api_key=api_key)


def complete(messages: list[dict], **options) -> tuple[str, dict]:
    """One chat call. options pass through to the API (e.g. temperature, response_format).
    Returns the reply text and the token usage reported by the proxy (empty if none)."""
    response = get_client().chat.completions.create(
        model=os.environ.get("LLM_MODEL") or DEFAULT_MODEL, messages=messages, **options
    )
    usage = response.usage
    tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens} if usage else {}
    return response.choices[0].message.content, tokens


def ask(prompt: str, system: str | None = None) -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    return complete(messages)[0]
