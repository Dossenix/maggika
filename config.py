import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def env_int(name: str) -> int | none:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else None

def evn_int_list(name: str) -> list[int]:
    values = os.getenv(name, "")
    return [int(x.strip()) for x in values.split(",") if x.strip().isdigit()]

@dataclass
class Settings:
    token: str
    guild_id: int | None
    verified_role_id: int | None
    staff_role_ids: list[int]
    castamagic_role_id: int | None
    castamagic_channel_id: int | None
    report_channel_id: int | None
    ticket_category_id: int | None
    disbord_bot_id: int | None
    bump_ping_role_id: int | None
    disbord_reminder_minutes: int
    db_path: Path

settings = Settings(
    token=os.getenv("DISCORD_TOKEN", ""),
    guild_id=env_int("GUILD_ID"),
    verified_role_id=env_int("VERIFIED_ROLE_ID"),
    staff_role_ids=evn_int_list("STAFF_ROLE_IDS"),
    castamagic_role_id=env_int("CASTAMAGIC_ROLE_ID"),
    castamagic_channel_id=env_int("CASTAMAGIC_CHANNEL_ID"),
    report_channel_id=env_int("REPORT_CHANNEL_ID"),
    ticket_category_id=env_int("TICKET_CATEGORY_ID"),
    disbord_bot_id=env_int("DISBORD_BOT_ID"),
    bump_ping_role_id=env_int("BUMP_PING_ROLE_ID"),
    disbord_reminder_minutes=env_int("DISBORD_REMINDER_MINUTES") or 60,
    db_path=Path(os.getenv("DB_PATH", "data.db")),
)

