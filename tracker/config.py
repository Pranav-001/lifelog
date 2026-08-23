import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)


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
    return Settings(bot_token=token, allowed_user_ids=allowed)
