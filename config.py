import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def env_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else None


def env_int_list(name: str) -> list[int]:
    raw = os.getenv(name, "")
    return [int(item.strip()) for item in raw.split(",") if item.strip().isdigit()]


def env_minutes(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    return int(value) if value.isdigit() else default


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int | None
    verified_role_id: int | None
    staff_role_ids: list[int]
    castamagic_role_id: int | None
    castamagic_channel_id: int | None
    report_channel_id: int | None
    ticket_category_id: int | None
    disboard_bot_id: int | None
    disboard_reminder_minutes: int
    db_path: Path


settings = Settings(
    token=os.getenv("DISCORD_TOKEN", "").strip(),
    guild_id=env_int("GUILD_ID"),
    verified_role_id=env_int("VERIFIED_ROLE_ID"),
    staff_role_ids=env_int_list("STAFF_ROLE_IDS"),
    castamagic_role_id=env_int("CASTAMAGIC_ROLE_ID"),
    castamagic_channel_id=env_int("CASTAMAGIC_CHANNEL_ID"),
    report_channel_id=env_int("REPORT_CHANNEL_ID"),
    ticket_category_id=env_int("TICKET_CATEGORY_ID"),
    disboard_bot_id=env_int("DISBOARD_BOT_ID"),
    disboard_reminder_minutes=env_minutes("DISBOARD_REMINDER_MINUTES", 120),
    db_path=Path(os.getenv("DB_PATH", "maggika.sqlite3")),
)
