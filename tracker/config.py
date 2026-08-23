import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    db_path: str = "data/lifelog.db"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"


def load_settings() -> Settings:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and paste "
            "the token you got from @BotFather."
        )

    raw_ids = os.getenv("ALLOWED_USER_IDS", "")
    allowed = frozenset(
        int(part) for part in (p.strip() for p in raw_ids.split(",")) if part
    )
    db_path = os.getenv("DATABASE_PATH", "").strip() or "data/lifelog.db"
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "").strip() or "openai/gpt-4o-mini"
    return Settings(
        bot_token=token,
        allowed_user_ids=allowed,
        db_path=db_path,
        openrouter_api_key=api_key,
        openrouter_model=model,
    )
