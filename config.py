from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là số nguyên.") from exc


def env_int_list(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    values: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise RuntimeError(f"{name} chỉ nhận ID số, cách nhau bằng dấu phẩy.") from exc
        if value not in values:
            values.append(value)
    return tuple(values)


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def env_colour(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip().lower().removeprefix("#").removeprefix("0x")
    if not raw:
        return default
    try:
        value = int(raw, 16)
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là mã màu HEX, ví dụ E17ED6.") from exc
    if not 0 <= value <= 0xFFFFFF:
        raise RuntimeError(f"{name} không hợp lệ.")
    return value


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    label: str
    placeholder: str
    style: str
    required: bool
    min_length: int
    max_length: int


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    test_guild_id: int | None
    review_channel_id: int
    whitelist_role_id: int
    reviewer_role_id: int | None
    unverified_role_id: int | None
    log_channel_id: int | None
    guarantor_log_channel_id: int | None
    self_service_code_max_uses: int
    self_service_code_renew: bool
    guarantor_grant_role_ids: tuple[int, ...]
    guarantor_remove_role_ids: tuple[int, ...]
    server_name: str
    timezone_name: str
    timezone: ZoneInfo
    accent_colour: int
    require_verification: bool
    min_account_age_days: int
    min_join_age_minutes: int
    questions: tuple[Question, ...]
    database_path: Path
    banner_path: Path
    auto_reply_channel_id: int | None
    auto_reply_whitelist_channel_id: int
    auto_reply_guarantor_channel_id: int
    auto_reply_cooldown_seconds: int


def load_questions(path: Path) -> tuple[Question, ...]:
    if not path.is_file():
        raise RuntimeError(f"Không tìm thấy file câu hỏi: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not 1 <= len(raw) <= 5:
        raise RuntimeError("questions.json phải có từ 1 đến 5 câu hỏi.")

    questions: list[Question] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Câu hỏi số {index} không hợp lệ.")

        key = str(item.get("key", f"question_{index}")).strip()
        label = str(item.get("label", "")).strip()
        placeholder = str(item.get("placeholder", "")).strip()
        style = str(item.get("style", "short")).strip().lower()
        required = bool(item.get("required", True))
        min_length = int(item.get("min_length", 1))
        max_length = int(item.get("max_length", 300 if style == "paragraph" else 100))

        if not key or key in seen_keys:
            raise RuntimeError(f"Key câu hỏi số {index} bị trống hoặc trùng.")
        if len(key) > 70 or not all(ch.isalnum() or ch == "_" for ch in key):
            raise RuntimeError(
                f"Key câu hỏi số {index} chỉ dùng chữ, số, dấu _ và tối đa 70 ký tự."
            )
        if not label or len(label) > 45:
            raise RuntimeError(f"Label câu hỏi số {index} phải từ 1 đến 45 ký tự.")
        if len(placeholder) > 100:
            raise RuntimeError(f"Placeholder câu hỏi số {index} tối đa 100 ký tự.")
        if style not in {"short", "paragraph"}:
            raise RuntimeError(f"Style câu hỏi số {index} chỉ nhận short hoặc paragraph.")
        if not 0 <= min_length <= 4000:
            raise RuntimeError(f"min_length câu hỏi số {index} không hợp lệ.")
        if not 1 <= max_length <= 4000 or max_length < min_length:
            raise RuntimeError(f"max_length câu hỏi số {index} không hợp lệ.")

        seen_keys.add(key)
        questions.append(
            Question(
                key=key,
                label=label,
                placeholder=placeholder,
                style=style,
                required=required,
                min_length=min_length,
                max_length=max_length,
            )
        )

    return tuple(questions)


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    review_channel_id = env_int("WHITELIST_REVIEW_CHANNEL_ID")
    whitelist_role_id = env_int("WHITELIST_ROLE_ID")

    if not token:
        raise RuntimeError("Thiếu DISCORD_TOKEN trong .env hoặc Railway Variables.")
    if review_channel_id is None:
        raise RuntimeError("Thiếu WHITELIST_REVIEW_CHANNEL_ID.")
    if whitelist_role_id is None:
        raise RuntimeError("Thiếu WHITELIST_ROLE_ID.")

    timezone_name = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh").strip()
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"TIMEZONE='{timezone_name}' không hợp lệ.") from exc

    database_path = Path(os.getenv("DATABASE_PATH", "data/whitelist.db").strip())
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path

    banner_path = Path(os.getenv("WHITELIST_BANNER_PATH", "assets/whitelist_banner.png").strip())
    if not banner_path.is_absolute():
        banner_path = BASE_DIR / banner_path

    return Settings(
        token=token,
        test_guild_id=env_int("TEST_GUILD_ID"),
        review_channel_id=review_channel_id,
        whitelist_role_id=whitelist_role_id,
        reviewer_role_id=env_int("WHITELIST_REVIEWER_ROLE_ID"),
        unverified_role_id=env_int("UNVERIFIED_ROLE_ID"),
        log_channel_id=env_int("WHITELIST_LOG_CHANNEL_ID"),
        guarantor_log_channel_id=env_int("GUARANTOR_LOG_CHANNEL_ID"),
        self_service_code_max_uses=max(
            1, env_int("GUARANTOR_SELF_MAX_USES", 5) or 5
        ),
        self_service_code_renew=env_bool("GUARANTOR_SELF_RENEW", False),
        guarantor_grant_role_ids=env_int_list(
            "GUARANTOR_GRANT_ROLE_IDS",
            (1531744174947307600, 1531744178210603151),
        ),
        guarantor_remove_role_ids=env_int_list(
            "GUARANTOR_REMOVE_ROLE_IDS",
            (1531744180966002870,),
        ),
        server_name=os.getenv("SERVER_NAME", "VENUS WORLD").strip() or "VENUS WORLD",
        timezone_name=timezone_name,
        timezone=timezone,
        accent_colour=env_colour("ACCENT_COLOR", 0xE17ED6),
        require_verification=env_bool("REQUIRE_VERIFICATION", True),
        min_account_age_days=max(0, env_int("MIN_ACCOUNT_AGE_DAYS", 0) or 0),
        min_join_age_minutes=max(0, env_int("MIN_JOIN_AGE_MINUTES", 0) or 0),
        questions=load_questions(BASE_DIR / "questions.json"),
        database_path=database_path,
        banner_path=banner_path,
        auto_reply_channel_id=env_int("AUTO_REPLY_CHANNEL_ID", 1555069801960050759),
        auto_reply_whitelist_channel_id=env_int(
            "AUTO_REPLY_WHITELIST_CHANNEL_ID", 1531744196443111686
        ) or 1531744196443111686,
        auto_reply_guarantor_channel_id=env_int(
            "AUTO_REPLY_GUARANTOR_CHANNEL_ID", 1531744196443111686
        ) or 1531744196443111686,
        auto_reply_cooldown_seconds=max(0, env_int("AUTO_REPLY_COOLDOWN_SECONDS", 60) or 0),
    )
