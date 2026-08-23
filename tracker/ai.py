"""Phase 3: AI brain via OpenRouter.

Sends recent chat history to a model through OpenRouter's OpenAI-compatible
API. The model classifies the latest message, extracts structured data, and
writes the natural-language reply. Model-agnostic on purpose: strict-JSON
output is requested in the prompt and parsed defensively, instead of relying
on per-model JSON modes.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date

import httpx

from tracker.storage import Message

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

VALID_CATEGORIES = {"finance", "gym", "diet", "note", "question", "other"}

SYSTEM_PROMPT = """\
You are Lifelog, a personal tracking assistant living in a Telegram chat.
The user sends free-form notes about their life. Today is {today}.

For the LATEST user message:
1. Classify it into exactly one category: finance, gym, diet, note, question, other.
2. Extract structured data for that category:
   - finance: {"kind": "expense" or "income", "amount": number, "currency": string or null, "description": string}
   - gym: {"exercises": [{"name": string, "sets": number or null, "reps": number or null, "weight_kg": number or null}], "notes": string or null}
   - diet: {"meal": "breakfast", "lunch", "dinner" or "snack" (or null), "items": [string], "calories_estimate": number or null}
   - note, question, other: {"summary": string}
3. Write a short friendly reply (1-3 sentences) confirming what you logged,
   or answering the question using the chat history. Reply in the user's language.

Respond with ONLY one JSON object, no markdown fences, exactly this shape:
{"category": "...", "data": {...}, "reply": "..."}
"""


@dataclass(frozen=True)
class Understanding:
    category: str | None
    data: dict | list | None
    reply: str


def _extract_json(content: str) -> dict:
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(content[start : end + 1])


class AIClient:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=60)

    async def understand(self, history: list[Message]) -> Understanding:
        system = SYSTEM_PROMPT.replace("{today}", date.today().isoformat())
        messages = [{"role": "system", "content": system}]
        for m in history:
            role = "user" if m.direction == "in" else "assistant"
            messages.append({"role": role, "content": m.text})

        response = await self._client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "X-Title": "lifelog",
            },
            json={"model": self._model, "messages": messages, "temperature": 0.3},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]

        try:
            parsed = _extract_json(content)
        except (ValueError, json.JSONDecodeError):
            logger.warning("Model returned non-JSON output, using it as a plain reply")
            return Understanding(category=None, data=None, reply=content.strip())

        category = parsed.get("category")
        if category not in VALID_CATEGORIES:
            category = "other"
        return Understanding(
            category=category,
            data=parsed.get("data"),
            reply=str(parsed.get("reply") or "Noted!"),
        )

    async def close(self) -> None:
        await self._client.aclose()
