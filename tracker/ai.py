"""Phase 3: AI brain via OpenRouter.

Sends recent chat history to a model through OpenRouter's OpenAI-compatible
API. The model classifies the latest message, extracts structured data, and
writes the natural-language reply. Model-agnostic on purpose: strict-JSON
output is requested in the prompt and parsed defensively, instead of relying
on per-model JSON modes.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date

import httpx

from tracker.finance import CATEGORIES as EXPENSE_CATEGORIES
from tracker.storage import Food, Message

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Backoff for 429/5xx. Free-tier models are limited per minute, so waiting
# a few seconds often succeeds where an instant retry won't.
RETRY_DELAYS = [2, 5]

VALID_CATEGORIES = {"finance", "gym", "diet", "food_info", "note", "question", "other"}

SYSTEM_PROMPT = """\
You are Lifelog, a personal tracking assistant living in a Telegram chat.
The user sends free-form notes about their life. Today is {today}.

For the LATEST user message:
1. Classify it into exactly one category: finance, gym, diet, food_info, note, question, other.
2. Extract structured data for that category:
   - finance: {"kind": "expense" or "income", "amount": number, "currency": string or null, "description": string, "merchant": string or null, "category": string, "tags": [strings], "date": "YYYY-MM-DD" or null}
     category MUST be one of: {expense_categories} (categorise by purpose, not by shop).
     date: the day the money actually moved if the user mentions one ("yesterday",
     "last friday" — today is {today}); null means today. Never a future date.
     tags: 0-3 short lowercase cross-cutting labels like "office", "trip-goa", "family".
   - gym: {"exercises": [{"name": string, "sets": number or null, "reps": number or null, "weight_kg": number or null}], "notes": string or null}
   - diet (user ate/drank something): {"meal": "breakfast", "lunch", "dinner" or "snack" (or null), "items": [{"name": string, "grams": number or null}], "calories_estimate": number or null, "protein_g": number or null, "fat_g": number or null, "carbs_g": number or null}
     For items: use the exact name from KNOWN FOODS when it matches; estimate grams
     from context (one scoop of powder is about 30g); skip water and other
     zero-calorie drinks. Estimate calories and macros using KNOWN FOODS data
     where available.
   - food_info (user states nutrition facts of a food): {"name": string, "calories_per_100g": number or null, "protein_per_100g": number or null, "fat_per_100g": number or null, "carbs_per_100g": number or null}
     Convert to per-100g if the user gives values per serving or scoop with a known weight.
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


def _foods_block(foods: list[Food]) -> str:
    if not foods:
        return ""
    lines = ["", "KNOWN FOODS (per 100g):"]
    for f in foods:
        parts = []
        if f.calories_per_100g is not None:
            parts.append(f"{f.calories_per_100g:g} kcal")
        if f.protein_per_100g is not None:
            parts.append(f"protein {f.protein_per_100g:g}g")
        if f.fat_per_100g is not None:
            parts.append(f"fat {f.fat_per_100g:g}g")
        if f.carbs_per_100g is not None:
            parts.append(f"carbs {f.carbs_per_100g:g}g")
        lines.append(f"- {f.name}: " + (", ".join(parts) if parts else "no data"))
    return "\n".join(lines)


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

    async def understand(
        self, history: list[Message], foods: list[Food] | None = None
    ) -> Understanding:
        system = SYSTEM_PROMPT.replace("{today}", date.today().isoformat())
        system = system.replace("{expense_categories}", ", ".join(EXPENSE_CATEGORIES))
        system += _foods_block(foods or [])
        messages = [{"role": "system", "content": system}]
        for m in history:
            role = "user" if m.direction == "in" else "assistant"
            messages.append({"role": role, "content": m.text})

        content = await self.complete(messages)

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

    async def complete(self, messages: list[dict]) -> str:
        response = await self._post(
            {"model": self._model, "messages": messages, "temperature": 0.3}
        )
        return response.json()["choices"][0]["message"]["content"]

    async def _post(self, payload: dict) -> httpx.Response:
        attempts = len(RETRY_DELAYS) + 1
        for attempt in range(attempts):
            response = await self._client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-Title": "lifelog",
                },
                json=payload,
            )
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(
                    "OpenRouter %s on attempt %d/%d: %s",
                    response.status_code,
                    attempt + 1,
                    attempts,
                    response.text[:300],
                )
                if attempt < len(RETRY_DELAYS):
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
            response.raise_for_status()
            return response

    async def close(self) -> None:
        await self._client.aclose()
