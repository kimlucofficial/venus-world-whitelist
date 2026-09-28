from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import secrets
import sqlite3
import string
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import Question, Settings, load_settings
from database import Database

SETTINGS: Settings = load_settings()
DB = Database(SETTINGS.database_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("venus-whitelist")

ALLOWED_MENTIONS = discord.AllowedMentions.none()
REVIEW_LOCK = asyncio.Lock()
GUARANTOR_REVIEW_LOCK = asyncio.Lock()
CODE_PATTERN = re.compile(r"^[A-Z0-9-]{4,20}$")

EMOJI_WHITELIST = "<:96359bubbleheart:1532387513031721101>"
EMOJI_WELCOME = "<a:fwb_cloudfly:1532586588658204724>"
EMOJI_VERIFY = "<a:SaF_Bluerollingstar:1532586674952081519>"
EMOJI_APPLY = "<:emoji_71:1533137766228168754>"
EMOJI_GUARANTOR = "<a:65447kuromi:1532351473889841293>"
EMOJI_GET_GUARANTOR = "<a:758151kuromithx:1532351505569419296>"
EMOJI_NOTE = "<:2039bubblequestion:1532386833764319374>"
EMOJI_FALLBACKS = {
    EMOJI_WHITELIST: "💜",
    EMOJI_WELCOME: "☁️",
    EMOJI_VERIFY: "⭐",
    EMOJI_APPLY: "📝",
    EMOJI_GUARANTOR: "🎀",
    EMOJI_GET_GUARANTOR: "🎟️",
    EMOJI_NOTE: "❔",
}
STATUS_LABELS = {
    "pending": "⏳ Đang chờ duyệt",
    "accepted": "✅ Đã đồng ý",
    "rejected": "❌ Đã từ chối",
    "error": "⚠️ Lỗi gửi đơn",
}
GUARANTOR_STATUS_LABELS = {
    "pending": "⏳ Chờ duyệt bảo lãnh",
    "accepted": "✅ Bảo lãnh đã được duyệt",
    "rejected": "❌ Bảo lãnh bị từ chối",
    "error": "⚠️ Lỗi gửi yêu cầu",
}


def usable_emoji(
    raw: str,
    guild: discord.Guild | None = None,
    permissions: discord.Permissions | None = None,
) -> str:
    """Return the custom emoji if the bot can really use it, otherwise a Unicode fallback."""
    partial = discord.PartialEmoji.from_str(raw)
    if partial.id is None:
        return raw
    fallback = EMOJI_FALLBACKS.get(raw, "💜")
    custom = bot.get_emoji(partial.id)
    if custom is None or not custom.available:
        return fallback
    if (
        guild is not None
        and permissions is not None
        and custom.guild_id != guild.id
        and not permissions.use_external_emojis
    ):
        return fallback
    return raw


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def discord_timestamp(value: str | None, style: str = "f") -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return "Không rõ"
    return f"<t:{int(parsed.timestamp())}:{style}>"


def trim(value: str, limit: int) -> str:
    clean = value.strip() or "-"
    if len(clean) <= limit:
        return clean
    return clean[: max(1, limit - 1)].rstrip() + "…"


def is_reviewer(member: discord.Member) -> bool:
    permissions = member.guild_permissions
    if permissions.administrator or permissions.manage_guild:
        return True
    role_id = SETTINGS.reviewer_role_id
    return bool(role_id and any(role.id == role_id for role in member.roles))


def build_panel_text(
    guild_name: str,
    guild: discord.Guild | None = None,
    permissions: discord.Permissions | None = None,
) -> str:
    def e(raw: str) -> str:
        return usable_emoji(raw, guild, permissions)

    return (
        f"## {e(EMOJI_WHITELIST)} ĐĂNG KÝ WHITELIST\n"
        f"{e(EMOJI_WELCOME)} Chào mừng bạn đến với **{guild_name}**. Hoàn thành các bước bên dưới để gửi hồ sơ.\n\n"
        f"### {e(EMOJI_VERIFY)} 1. Xác thực tài khoản\n"
        "> Bấm **Xác thực tài khoản** để hệ thống ghi nhận Discord của bạn.\n\n"
        f"### {e(EMOJI_GET_GUARANTOR)} 2. Lấy mã bảo lãnh\n"
        "> Chỉ thành viên đã có **role Whitelist** mới lấy được mã để bảo lãnh bạn bè.\n\n"
        f"### {e(EMOJI_GUARANTOR)} 3. Nhập mã bảo lãnh\n"
        "> Nhập mã và chờ staff duyệt. Nếu được đồng ý, hệ thống sẽ tự cấp role cho bạn.\n\n"
        f"### {e(EMOJI_APPLY)} 4. Nộp đơn\n"
        "> Điền đúng thông tin và trả lời câu hỏi Roleplay trong form.\n\n"
        f"### {e(EMOJI_NOTE)} Lưu ý\n"
        "> Thông tin sai hoặc spam form có thể bị từ chối.\n\n"
        f"-# {SETTINGS.server_name} • WHITELIST SYSTEM"
    )


def load_answers(application: dict[str, Any]) -> list[dict[str, str]]:
    try:
        raw = json.loads(application["answers_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    answers: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            answers.append(
                {
                    "label": str(item.get("label", "Câu hỏi")),
                    "value": str(item.get("value", "-")),
                }
            )
    return answers


def review_colour(status: str) -> int:
    return {
        "pending": SETTINGS.accent_colour,
        "accepted": 0x57F287,
        "rejected": 0xED4245,
        "error": 0xFEE75C,
    }.get(status, SETTINGS.accent_colour)


def build_review_header(application: dict[str, Any]) -> str:
    status = str(application["status"])
    return (
        f"## 💌 ĐƠN WHITELIST `#{application['id']:04d}`\n"
        f"**Người nộp:** <@{application['user_id']}>\n"
        f"-# @{trim(str(application['username']), 80)} • "
        f"{STATUS_LABELS.get(status, status)} • "
        f"{discord_timestamp(application.get('submitted_at'), 'R')}"
    )


def build_review_answers(application: dict[str, Any]) -> str:
    blocks: list[str] = []
    remaining = 1900
    for index, answer in enumerate(load_answers(application), start=1):
        label = trim(answer["label"], 120)
        prefix = f"### {index}. {label}\n> "
        separator_cost = 2 if blocks else 0
        available = remaining - len(prefix) - separator_cost
        if available < 20:
            blocks.append("> …")
            break

        value = trim(answer["value"], min(850, available))
        block = prefix + value.replace("\n", "\n> ")
        blocks.append(block)
        remaining -= len(block) + separator_cost

    return "\n\n".join(blocks) or "> Không đọc được nội dung đơn."


def build_review_stats(application: dict[str, Any]) -> str:
    guarantor = "Không sử dụng"
    if application.get("guarantor_user_id"):
        code = application.get("guarantor_code") or "-"
        guarantor = f"<@{application['guarantor_user_id']}> • `{code}`"

    return (
        "### 🪪 THÔNG TIN DISCORD\n"
        f"**User ID:** `{application['user_id']}`\n"
        f"**Tài khoản tạo:** {discord_timestamp(application.get('account_created_at'), 'R')}\n"
        f"**Vào server:** {discord_timestamp(application.get('guild_joined_at'), 'R')}\n"
        f"**Xác thực:** {'✅ Có' if application.get('verified_at') else '❌ Chưa'}\n"
        f"**Bảo lãnh:** {guarantor}"
    )


def build_review_result(application: dict[str, Any]) -> str | None:
    status = str(application["status"])
    if status not in {"accepted", "rejected"}:
        return None

    result = (
        "### ✨ KẾT QUẢ XÉT DUYỆT\n"
        f"**Trạng thái:** {STATUS_LABELS[status]}\n"
        f"**Người duyệt:** <@{application.get('reviewer_id')}>\n"
        f"**Thời gian:** {discord_timestamp(application.get('reviewed_at'))}"
    )
    if application.get("reason"):
        result += f"\n**Lý do:** {trim(str(application['reason']), 650)}"
    return result


def guarantor_review_colour(status: str) -> int:
    return {
        "pending": SETTINGS.accent_colour,
        "accepted": 0x57F287,
        "rejected": 0xED4245,
        "error": 0xFEE75C,
    }.get(status, SETTINGS.accent_colour)


def build_guarantor_review_header(request: dict[str, Any]) -> str:
    status = str(request["status"])
    return (
        f"## {usable_emoji(EMOJI_GET_GUARANTOR)} DUYỆT BẢO LÃNH `#{request['id']:04d}`\n"
        f"**Người được bảo lãnh:** <@{request['applicant_user_id']}>\n"
        f"-# @{trim(str(request['applicant_username']), 80)} • "
        f"{GUARANTOR_STATUS_LABELS.get(status, status)} • "
        f"{discord_timestamp(request.get('requested_at'), 'R')}"
    )


def build_guarantor_review_body(request: dict[str, Any]) -> str:
    return (
        f"### {usable_emoji(EMOJI_GUARANTOR)} THÔNG TIN BẢO LÃNH\n"
        f"**Người bảo lãnh:** <@{request['owner_user_id']}>\n"
        f"**Người được bảo lãnh:** <@{request['applicant_user_id']}>\n"
        f"**Mã sử dụng:** `{request['code']}`\n"
        f"**Gửi lúc:** {discord_timestamp(request.get('requested_at'))}\n"
        "-# Đồng ý bảo lãnh sẽ tự cấp role cho người được bảo lãnh."
    )


def build_guarantor_review_result(request: dict[str, Any]) -> str | None:
    status = str(request["status"])
    if status not in {"accepted", "rejected"}:
        return None

    text = (
        "### ✨ KẾT QUẢ DUYỆT BẢO LÃNH\n"
        f"**Trạng thái:** {GUARANTOR_STATUS_LABELS[status]}\n"
        f"**Người duyệt:** <@{request.get('reviewer_id')}>\n"
        f"**Thời gian:** {discord_timestamp(request.get('reviewed_at'))}"
    )
    if status == "accepted":
        text += "\n**Role Whitelist:** ✅ Đã cấp tự động"
    if request.get("reason"):
        text += f"\n**Lý do:** {trim(str(request['reason']), 650)}"
    return text


async def get_channel(channel_id: int) -> discord.abc.Messageable | None:
    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        log.exception("Không truy cập được channel ID %s", channel_id)
        return None


async def fetch_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def send_log(guild: discord.Guild, application: dict[str, Any]) -> None:
    if not SETTINGS.log_channel_id:
        return
    channel = await get_channel(SETTINGS.log_channel_id)
    if channel is None:
        return

    status = str(application["status"])
    embed = discord.Embed(
        title="Whitelist đã được xử lý",
        description=(
            f"<@{application['user_id']}> • {STATUS_LABELS.get(status, status)}\n"
            f"Người duyệt: <@{application.get('reviewer_id')}>"
        ),
        colour=0x57F287 if status == "accepted" else 0xED4245,
    )
    if application.get("reason"):
        embed.add_field(name="Lý do", value=trim(str(application["reason"]), 1000))
    try:
        await channel.send(embed=embed, allowed_mentions=ALLOWED_MENTIONS)
    except discord.HTTPException:
        log.exception("Không gửi được whitelist log trong %s", guild.id)


async def send_guarantor_code_log(
    guild: discord.Guild,
    owner: discord.Member,
    code: dict[str, Any],
    *,
    reused: bool,
) -> None:
    channel_id = (
        SETTINGS.guarantor_log_channel_id
        or SETTINGS.log_channel_id
        or SETTINGS.review_channel_id
    )
    channel = await get_channel(channel_id)
    if channel is None:
        return

    maximum = "∞" if int(code["max_uses"]) == 0 else str(code["max_uses"])
    embed = discord.Embed(
        title="Mã bảo lãnh đã được lấy" if not reused else "Mã bảo lãnh được xem lại",
        description=(
            f"**Người lấy mã:** {owner.mention}\n"
            f"**User ID:** `{owner.id}`\n"
            f"**Mã:** `{code['code']}`\n"
            f"**Lượt dùng:** {code['use_count']}/{maximum}"
        ),
        colour=SETTINGS.accent_colour,
        timestamp=utc_now(),
    )
    embed.set_thumbnail(url=owner.display_avatar.url)
    embed.set_footer(text=f"{SETTINGS.server_name} • GUARANTOR LOG")
    try:
        await channel.send(embed=embed, allowed_mentions=ALLOWED_MENTIONS)
    except discord.HTTPException:
        log.exception("Không gửi được log lấy mã bảo lãnh trong %s", guild.id)


async def send_guarantor_result_log(
    guild: discord.Guild,
    request: dict[str, Any],
) -> None:
    channel_id = SETTINGS.guarantor_log_channel_id or SETTINGS.log_channel_id
    if not channel_id:
        return
    channel = await get_channel(channel_id)
    if channel is None:
        return

    status = str(request["status"])
    embed = discord.Embed(
        title="Yêu cầu bảo lãnh đã được xử lý",
        description=(
            f"**Người bảo lãnh:** <@{request['owner_user_id']}>\n"
            f"**Người được bảo lãnh:** <@{request['applicant_user_id']}>\n"
            f"**Mã:** `{request['code']}`\n"
            f"**Kết quả:** {GUARANTOR_STATUS_LABELS.get(status, status)}\n"
            f"**Người duyệt:** <@{request.get('reviewer_id')}>\n"
            f"**Role Whitelist:** {'✅ Đã cấp' if status == 'accepted' else '—'}"
        ),
        colour=0x57F287 if status == "accepted" else 0xED4245,
        timestamp=utc_now(),
    )
    if request.get("reason"):
        embed.add_field(name="Lý do", value=trim(str(request["reason"]), 1000), inline=False)
    try:
        await channel.send(embed=embed, allowed_mentions=ALLOWED_MENTIONS)
    except discord.HTTPException:
        log.exception("Không gửi được log duyệt bảo lãnh trong %s", guild.id)


async def notify_guarantor_parties(
    applicant: discord.Member | None,
    owner: discord.Member | None,
    request: dict[str, Any],
) -> None:
    status = str(request["status"])
    accepted = status == "accepted"
    title = "✅ Bảo lãnh đã được đồng ý" if accepted else "❌ Bảo lãnh đã bị từ chối"
    colour = 0x57F287 if accepted else 0xED4245

    if applicant is not None:
        description = (
            f"Yêu cầu bảo lãnh bằng mã `{request['code']}` tại **{SETTINGS.server_name}** "
            + (
                "đã được duyệt và bạn đã được cấp role tự động."
                if accepted
                else "đã bị từ chối. Bạn vẫn có thể nộp đơn không dùng bảo lãnh hoặc nhập mã khác."
            )
        )
        embed = discord.Embed(title=title, description=description, colour=colour)
        if request.get("reason"):
            embed.add_field(name="Lý do", value=trim(str(request["reason"]), 1000), inline=False)
        try:
            await applicant.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            log.info("Không DM được kết quả bảo lãnh cho %s", applicant.id)

    if owner is not None:
        description = (
            f"Yêu cầu dùng mã `{request['code']}` của bạn cho <@{request['applicant_user_id']}> "
            + ("đã được staff đồng ý." if accepted else "đã bị staff từ chối.")
        )
        embed = discord.Embed(title=title, description=description, colour=colour)
        if request.get("reason"):
            embed.add_field(name="Lý do", value=trim(str(request["reason"]), 1000), inline=False)
        try:
            await owner.send(embed=embed, allowed_mentions=ALLOWED_MENTIONS)
        except (discord.Forbidden, discord.HTTPException):
            log.info("Không DM được kết quả bảo lãnh cho chủ mã %s", owner.id)


async def issue_self_service_guarantor_code(
    guild: discord.Guild,
    member: discord.Member,
) -> tuple[bool, str]:
    existing = await asyncio.to_thread(
        DB.get_available_guarantor_code,
        guild.id,
        member.id,
    )
    reused = existing is not None
    code_row = existing

    if code_row is None and not SETTINGS.self_service_code_renew:
        latest = await asyncio.to_thread(
            DB.get_latest_self_service_code,
            guild.id,
            member.id,
        )
        if latest is not None:
            if not int(latest["active"]):
                return False, f"Mã bảo lãnh `{latest['code']}` của bạn đã bị tắt."
            return (
                False,
                f"Mã bảo lãnh `{latest['code']}` của bạn đã dùng hết "
                f"**{latest['max_uses']}** lượt.",
            )

    if code_row is None:
        for _ in range(5):
            code = generate_code()
            try:
                await asyncio.to_thread(
                    DB.create_guarantor_code,
                    code=code,
                    guild_id=guild.id,
                    owner_user_id=member.id,
                    created_by=member.id,
                    max_uses=SETTINGS.self_service_code_max_uses,
                )
                code_row = await asyncio.to_thread(
                    DB.get_available_guarantor_code,
                    guild.id,
                    member.id,
                )
                break
            except sqlite3.IntegrityError:
                continue
        if code_row is None:
            return False, "Không tạo được mã bảo lãnh. Hãy thử lại sau."

    await send_guarantor_code_log(guild, member, code_row, reused=reused)
    max_uses = int(code_row["max_uses"])
    if max_uses == 0:
        usage = "Lượt tối đa: **không giới hạn**."
    else:
        remaining = max(0, max_uses - int(code_row["use_count"]))
        usage = f"Còn **{remaining}/{max_uses}** lượt bảo lãnh."
    return (
        True,
        f"Mã bảo lãnh của bạn: `{code_row['code']}`\n"
        f"{usage} Chỉ gửi mã cho người bạn thật sự bảo lãnh.",
    )


async def submit_guarantor_request(
    interaction: discord.Interaction,
    code: str,
) -> str:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return "❌ Chỉ có thể dùng trong server."

    guild = interaction.guild
    member = interaction.user
    whitelist_role = guild.get_role(SETTINGS.whitelist_role_id)
    if whitelist_role and whitelist_role in member.roles:
        return "❌ Bạn đã có role Whitelist nên không cần dùng mã bảo lãnh."

    ok, message, request_id, owner_user_id = await asyncio.to_thread(
        DB.create_guarantor_request,
        guild_id=guild.id,
        applicant_user_id=member.id,
        applicant_username=member.name,
        applicant_display_name=member.display_name,
        applicant_avatar_url=member.display_avatar.url,
        code=code,
    )
    if not ok or request_id is None:
        return f"❌ {message}"

    request = await asyncio.to_thread(DB.get_guarantor_request_by_id, request_id)
    if request is None:
        return "❌ Không đọc lại được yêu cầu bảo lãnh vừa tạo."

    review_channel = await get_channel(SETTINGS.review_channel_id)
    if review_channel is None:
        await asyncio.to_thread(
            DB.mark_guarantor_request_error,
            request_id,
            "Không truy cập được kênh xét duyệt.",
        )
        return "❌ Bot không truy cập được kênh staff xét duyệt."

    try:
        review_message = await review_channel.send(
            view=GuarantorReviewLayout(request),
            allowed_mentions=ALLOWED_MENTIONS,
        )
        await asyncio.to_thread(
            DB.attach_guarantor_review_message,
            request_id,
            review_message.channel.id,
            review_message.id,
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        log.exception("Không gửi được yêu cầu bảo lãnh #%s", request_id)
        await asyncio.to_thread(
            DB.mark_guarantor_request_error,
            request_id,
            f"Discord API: {type(exc).__name__}",
        )
        return "❌ Không gửi được yêu cầu bảo lãnh sang kênh staff."

    return (
        f"✅ Đã gửi yêu cầu bảo lãnh **#{request_id:04d}** cho staff duyệt. "
        "Nếu được đồng ý, bot sẽ tự cấp role cho bạn."
    )


async def notify_applicant(member: discord.Member | None, application: dict[str, Any]) -> None:
    if member is None:
        return
    status = str(application["status"])
    accepted = status == "accepted"
    embed = discord.Embed(
        title="✅ Đơn Whitelist đã được đồng ý" if accepted else "❌ Đơn Whitelist đã bị từ chối",
        description=(
            f"Đơn đăng ký của bạn tại **{SETTINGS.server_name}** đã được xử lý."
        ),
        colour=0x57F287 if accepted else 0xED4245,
    )
    if application.get("reason"):
        embed.add_field(name="Lý do", value=trim(str(application["reason"]), 1000), inline=False)
    embed.set_footer(text=SETTINGS.server_name)
    try:
        await member.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        log.info("Không DM được kết quả whitelist cho %s", member.id)


async def account_eligibility(member: discord.Member) -> tuple[bool, str | None]:
    now = utc_now()
    account_age_seconds = (now - member.created_at).total_seconds()
    required_account_seconds = SETTINGS.min_account_age_days * 86400
    if account_age_seconds < required_account_seconds:
        remaining_days = max(
            1,
            int((required_account_seconds - account_age_seconds + 86399) // 86400),
        )
        return False, f"Tài khoản Discord cần đủ tuổi. Vui lòng thử lại sau khoảng **{remaining_days} ngày**."

    if SETTINGS.min_join_age_minutes > 0 and member.joined_at:
        joined_seconds = (now - member.joined_at).total_seconds()
        required_join_seconds = SETTINGS.min_join_age_minutes * 60
        if joined_seconds < required_join_seconds:
            remaining_minutes = max(
                1,
                int((required_join_seconds - joined_seconds + 59) // 60),
            )
            return False, f"Bạn cần ở trong server thêm khoảng **{remaining_minutes} phút** trước khi xác thực."

    return True, None


async def submit_application(
    interaction: discord.Interaction,
    answers: list[dict[str, str]],
) -> str:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return "❌ Chỉ có thể nộp đơn trong server."

    guild = interaction.guild
    member = interaction.user
    verified_at = await asyncio.to_thread(DB.get_verification, guild.id, member.id)
    if SETTINGS.require_verification and not verified_at:
        return "❌ Bạn cần bấm **Xác thực tài khoản** trước khi nộp đơn."

    pending_guarantor = await asyncio.to_thread(
        DB.get_pending_guarantor_request,
        guild.id,
        member.id,
    )
    if pending_guarantor:
        return (
            f"⏳ Yêu cầu bảo lãnh **#{pending_guarantor['id']:04d}** đang chờ staff duyệt. "
            "Hãy chờ kết quả rồi nộp đơn."
        )

    referral = await asyncio.to_thread(DB.get_referral, guild.id, member.id)
    ok, message, application_id = await asyncio.to_thread(
        DB.create_application,
        guild_id=guild.id,
        user_id=member.id,
        username=member.name,
        display_name=member.display_name,
        avatar_url=member.display_avatar.url,
        answers=answers,
        account_created_at=member.created_at.isoformat(),
        guild_joined_at=member.joined_at.isoformat() if member.joined_at else None,
        verified_at=verified_at,
        guarantor_code=str(referral["code"]) if referral else None,
        guarantor_user_id=int(referral["owner_user_id"]) if referral else None,
    )
    if not ok or application_id is None:
        return f"❌ {message}"

    application = await asyncio.to_thread(DB.get_application_by_id, application_id)
    if application is None:
        return "❌ Không đọc lại được đơn vừa tạo."

    review_channel = await get_channel(SETTINGS.review_channel_id)
    if review_channel is None:
        await asyncio.to_thread(
            DB.mark_application_error,
            application_id,
            "Không truy cập được kênh xét duyệt.",
        )
        return "❌ Bot không truy cập được kênh xét duyệt. Hãy báo cho quản trị viên."

    try:
        review_message = await review_channel.send(
            view=ReviewLayout(application),
            allowed_mentions=ALLOWED_MENTIONS,
        )
        await asyncio.to_thread(
            DB.attach_review_message,
            application_id,
            review_message.channel.id,
            review_message.id,
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        log.exception("Không gửi được đơn whitelist #%s", application_id)
        await asyncio.to_thread(
            DB.mark_application_error,
            application_id,
            f"Discord API: {type(exc).__name__}",
        )
        return "❌ Không gửi được đơn sang kênh xét duyệt. Hãy báo cho quản trị viên."

    return f"✅ Đã gửi đơn **#{application_id:04d}**. Kết quả sẽ được bot gửi qua tin nhắn riêng."


async def process_decision(
    interaction: discord.Interaction,
    *,
    status: str,
    reason: str | None,
) -> str:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return "❌ Thao tác này chỉ dùng trong server."
    if interaction.message is None:
        return "❌ Không tìm thấy tin nhắn đơn đăng ký."
    if not is_reviewer(interaction.user):
        return "❌ Bạn không có quyền xét duyệt whitelist."

    async with REVIEW_LOCK:
        application = await asyncio.to_thread(
            DB.get_application_by_message,
            interaction.guild.id,
            interaction.message.id,
        )
        if application is None:
            return "❌ Không tìm thấy dữ liệu của đơn này."
        if application["status"] != "pending":
            return f"ℹ️ Đơn này đã được xử lý: **{STATUS_LABELS.get(application['status'], application['status'])}**."

        applicant = await fetch_member(interaction.guild, int(application["user_id"]))

        if status == "accepted":
            whitelist_role = interaction.guild.get_role(SETTINGS.whitelist_role_id)
            if whitelist_role is None:
                return "❌ Không tìm thấy WHITELIST_ROLE_ID trong server."
            bot_member = interaction.guild.me
            if bot_member is None or not bot_member.guild_permissions.manage_roles:
                return "❌ Bot thiếu quyền **Manage Roles**."
            if whitelist_role >= bot_member.top_role:
                return "❌ Role whitelist đang cao hơn hoặc ngang role cao nhất của bot."
            if applicant is None:
                return "❌ Người nộp đơn không còn trong server."

            try:
                if whitelist_role not in applicant.roles:
                    await applicant.add_roles(
                        whitelist_role,
                        reason=f"Whitelist accepted by {interaction.user} ({interaction.user.id})",
                    )

                if SETTINGS.unverified_role_id:
                    unverified_role = interaction.guild.get_role(SETTINGS.unverified_role_id)
                    if (
                        unverified_role
                        and unverified_role in applicant.roles
                        and unverified_role < bot_member.top_role
                    ):
                        await applicant.remove_roles(
                            unverified_role,
                            reason="Whitelist accepted",
                        )
            except discord.Forbidden:
                return "❌ Bot không đủ quyền thêm hoặc gỡ role."
            except discord.HTTPException:
                log.exception("Discord API lỗi khi cập nhật role whitelist")
                return "❌ Discord lỗi khi cập nhật role whitelist."

        finalized = await asyncio.to_thread(
            DB.finalize_application,
            application_id=int(application["id"]),
            status=status,
            reviewer_id=interaction.user.id,
            reason=reason,
        )
        if not finalized:
            return "ℹ️ Đơn vừa được một người khác xử lý trước."

        updated = await asyncio.to_thread(DB.get_application_by_id, int(application["id"]))
        if updated is None:
            return "✅ Đã xử lý đơn nhưng không đọc lại được dữ liệu."

        try:
            await interaction.message.edit(
                content=None,
                embeds=[],
                attachments=[],
                view=ReviewLayout(updated, disabled=True),
            )
        except discord.HTTPException:
            log.exception("Không cập nhật được review message %s", interaction.message.id)

        await notify_applicant(applicant, updated)
        await send_log(interaction.guild, updated)

        return (
            f"✅ Đã **đồng ý** đơn #{updated['id']:04d}."
            if status == "accepted"
            else f"✅ Đã **từ chối** đơn #{updated['id']:04d}."
        )


def resolve_guarantor_roles(
    guild: discord.Guild,
    bot_member: discord.Member | None,
) -> tuple[list[discord.Role], list[discord.Role], str | None]:
    """Roles given / removed when a guarantor request is accepted."""
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return [], [], "❌ Bot thiếu quyền **Manage Roles**."

    grant_roles: list[discord.Role] = []
    for role_id in SETTINGS.guarantor_grant_role_ids:
        role = guild.get_role(role_id)
        if role is None:
            return [], [], f"❌ Không tìm thấy role `{role_id}` trong server."
        if role >= bot_member.top_role:
            return [], [], f"❌ Role {role.mention} đang cao hơn hoặc ngang role cao nhất của bot."
        grant_roles.append(role)

    if not grant_roles:
        return [], [], "❌ Chưa cấu hình role cấp khi đồng ý bảo lãnh."

    grant_ids = {role.id for role in grant_roles}
    remove_roles: list[discord.Role] = []
    for role_id in SETTINGS.guarantor_remove_role_ids:
        if role_id in grant_ids:
            continue
        role = guild.get_role(role_id)
        if role is None:
            log.warning("Không tìm thấy role cần gỡ khi duyệt bảo lãnh: %s", role_id)
            continue
        if role >= bot_member.top_role:
            return [], [], f"❌ Role {role.mention} đang cao hơn hoặc ngang role cao nhất của bot."
        remove_roles.append(role)

    if SETTINGS.unverified_role_id and SETTINGS.unverified_role_id not in grant_ids:
        unverified_role = guild.get_role(SETTINGS.unverified_role_id)
        if (
            unverified_role
            and unverified_role < bot_member.top_role
            and unverified_role not in remove_roles
        ):
            remove_roles.append(unverified_role)

    return grant_roles, remove_roles, None


async def remove_guarantor_roles(
    member: discord.Member,
    remove_roles: list[discord.Role],
    reason: str,
) -> bool:
    to_remove = [role for role in remove_roles if role in member.roles]
    if not to_remove:
        return True
    try:
        await member.remove_roles(*to_remove, reason=reason)
    except (discord.Forbidden, discord.HTTPException):
        log.warning("Đã cấp role bảo lãnh nhưng không gỡ được role cũ cho %s", member.id)
        return False
    return True


async def process_guarantor_decision(
    interaction: discord.Interaction,
    *,
    status: str,
    reason: str | None,
) -> str:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return "❌ Thao tác này chỉ dùng trong server."
    if interaction.message is None:
        return "❌ Không tìm thấy tin nhắn yêu cầu bảo lãnh."
    if not is_reviewer(interaction.user):
        return "❌ Bạn không có quyền xét duyệt bảo lãnh."

    async with GUARANTOR_REVIEW_LOCK:
        request = await asyncio.to_thread(
            DB.get_guarantor_request_by_message,
            interaction.guild.id,
            interaction.message.id,
        )
        if request is None:
            return "❌ Không tìm thấy dữ liệu yêu cầu bảo lãnh này."
        if request["status"] != "pending":
            return (
                "ℹ️ Yêu cầu này đã được xử lý: "
                f"**{GUARANTOR_STATUS_LABELS.get(request['status'], request['status'])}**."
            )

        applicant = await fetch_member(
            interaction.guild,
            int(request["applicant_user_id"]),
        )

        grant_roles: list[discord.Role] = []
        remove_roles: list[discord.Role] = []
        bot_member = interaction.guild.me
        if status == "accepted":
            grant_roles, remove_roles, role_error = resolve_guarantor_roles(
                interaction.guild,
                bot_member,
            )
            if role_error:
                return role_error
            if applicant is None:
                return "❌ Người được bảo lãnh không còn trong server."

        finalized, message = await asyncio.to_thread(
            DB.finalize_guarantor_request,
            request_id=int(request["id"]),
            status=status,
            reviewer_id=interaction.user.id,
            reason=reason,
        )
        if not finalized:
            return f"❌ {message}"

        removed_ok = True
        if status == "accepted" and applicant is not None and grant_roles:
            try:
                missing_roles = [role for role in grant_roles if role not in applicant.roles]
                if missing_roles:
                    await applicant.add_roles(
                        *missing_roles,
                        reason=(
                            "Guarantor request accepted by "
                            f"{interaction.user} ({interaction.user.id})"
                        ),
                    )
            except discord.Forbidden:
                rolled_back = await asyncio.to_thread(
                    DB.rollback_guarantor_acceptance,
                    int(request["id"]),
                )
                if rolled_back:
                    return (
                        "❌ Bot không đủ quyền cấp role bảo lãnh. "
                        "Yêu cầu đã được hoàn tác về trạng thái chờ để staff sửa quyền rồi duyệt lại."
                    )
                return (
                    "⚠️ Bảo lãnh đã được ghi nhận nhưng bot không cấp được role và không thể hoàn tác. "
                    "Staff cần cấp role thủ công và kiểm tra log."
                )
            except discord.HTTPException:
                log.exception("Discord API lỗi khi cấp role qua bảo lãnh")
                rolled_back = await asyncio.to_thread(
                    DB.rollback_guarantor_acceptance,
                    int(request["id"]),
                )
                if rolled_back:
                    return (
                        "❌ Discord lỗi khi cấp role bảo lãnh. "
                        "Yêu cầu đã được hoàn tác về trạng thái chờ để duyệt lại."
                    )
                return (
                    "⚠️ Bảo lãnh đã được ghi nhận nhưng Discord lỗi khi cấp role và không thể hoàn tác. "
                    "Staff cần cấp role thủ công."
                )

            removed_ok = await remove_guarantor_roles(
                applicant,
                remove_roles,
                "Guarantor request accepted",
            )

        updated = await asyncio.to_thread(
            DB.get_guarantor_request_by_id,
            int(request["id"]),
        )
        if updated is None:
            return "✅ Đã xử lý bảo lãnh nhưng không đọc lại được dữ liệu."

        try:
            await interaction.message.edit(
                content=None,
                embeds=[],
                attachments=[],
                view=GuarantorReviewLayout(updated, disabled=True),
            )
        except discord.HTTPException:
            log.exception(
                "Không cập nhật được guarantor review message %s",
                interaction.message.id,
            )

        owner = await fetch_member(
            interaction.guild,
            int(updated["owner_user_id"]),
        )
        await notify_guarantor_parties(applicant, owner, updated)
        await send_guarantor_result_log(interaction.guild, updated)

        if status == "accepted":
            result = f"✅ Đã **đồng ý** bảo lãnh #{updated['id']:04d} và cấp role."
            if not removed_ok:
                result += "\n⚠️ Không gỡ được role cũ, staff cần gỡ thủ công."
            return result
        return f"✅ Đã **từ chối** bảo lãnh #{updated['id']:04d}."


class ApplicationModal(discord.ui.Modal):
    def __init__(self) -> None:
        super().__init__(title="Đăng ký Whitelist", timeout=600)
        self.question_inputs: list[tuple[Question, discord.ui.TextInput]] = []

        for question in SETTINGS.questions:
            text_input = discord.ui.TextInput(
                label=question.label,
                placeholder=question.placeholder or None,
                style=(
                    discord.TextStyle.paragraph
                    if question.style == "paragraph"
                    else discord.TextStyle.short
                ),
                required=question.required,
                min_length=question.min_length,
                max_length=question.max_length,
                custom_id=f"whitelist_question_{question.key}",
            )
            self.question_inputs.append((question, text_input))
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        answers = [
            {"key": question.key, "label": question.label, "value": str(text_input.value)}
            for question, text_input in self.question_inputs
        ]
        result = await submit_application(interaction, answers)
        await interaction.followup.send(result, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Lỗi modal nộp whitelist", exc_info=error)
        message = "❌ Có lỗi khi gửi đơn. Hãy thử lại hoặc báo quản trị viên."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class GuarantorCodeModal(discord.ui.Modal, title="Nhập mã bảo lãnh"):
    code = discord.ui.TextInput(
        label="Mã bảo lãnh",
        placeholder="Ví dụ: VENUS-AB12",
        min_length=4,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
            return

        normalized = str(self.code.value).strip().upper()
        if not CODE_PATTERN.fullmatch(normalized):
            await interaction.response.send_message(
                "❌ Mã chỉ được dùng chữ in hoa, số và dấu `-`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await submit_guarantor_request(interaction, normalized)
        await interaction.followup.send(
            result,
            ephemeral=True,
            allowed_mentions=ALLOWED_MENTIONS,
        )


class ReasonModal(discord.ui.Modal):
    def __init__(self, status: str) -> None:
        title = "Đồng ý kèm lý do" if status == "accepted" else "Từ chối kèm lý do"
        super().__init__(title=title, timeout=300)
        self.status = status
        self.reason = discord.ui.TextInput(
            label="Lý do",
            placeholder="Nhập nội dung gửi cho người nộp đơn",
            style=discord.TextStyle.paragraph,
            min_length=3,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_decision(
            interaction,
            status=self.status,
            reason=str(self.reason.value).strip(),
        )
        await interaction.followup.send(result, ephemeral=True)


class GuarantorReasonModal(discord.ui.Modal):
    def __init__(self, status: str) -> None:
        title = "Đồng ý bảo lãnh + lý do" if status == "accepted" else "Từ chối bảo lãnh + lý do"
        super().__init__(title=title, timeout=300)
        self.status = status
        self.reason = discord.ui.TextInput(
            label="Lý do",
            placeholder="Nhập nội dung gửi cho hai bên",
            style=discord.TextStyle.paragraph,
            min_length=3,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_guarantor_decision(
            interaction,
            status=self.status,
            reason=str(self.reason.value).strip(),
        )
        await interaction.followup.send(result, ephemeral=True)


class WhitelistActionRow(discord.ui.ActionRow):
    def __init__(
        self,
        guild: discord.Guild | None = None,
        permissions: discord.Permissions | None = None,
    ) -> None:
        super().__init__()
        # Chỉ kiểm tra emoji khi gửi bảng thật; view persistent chỉ cần custom_id.
        if guild is None:
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.emoji and child.emoji.id:
                child.emoji = usable_emoji(str(child.emoji), guild, permissions)
    @discord.ui.button(
        label="Xác thực tài khoản",
        emoji=EMOJI_VERIFY,
        style=discord.ButtonStyle.secondary,
        custom_id="venus_whitelist_verify",
    )
    async def verify(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
            return

        eligible, error = await account_eligibility(interaction.user)
        if not eligible:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        verified_at = await asyncio.to_thread(
            DB.mark_verified,
            interaction.guild.id,
            interaction.user.id,
        )
        await interaction.response.send_message(
            f"✅ Đã xác thực tài khoản lúc {discord_timestamp(verified_at)}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Lấy mã bảo lãnh",
        emoji=EMOJI_GET_GUARANTOR,
        style=discord.ButtonStyle.secondary,
        custom_id="venus_whitelist_get_guarantor",
    )
    async def get_guarantor_code(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
            return

        whitelist_role = interaction.guild.get_role(SETTINGS.whitelist_role_id)
        if whitelist_role is None:
            await interaction.response.send_message(
                "❌ Server chưa cấu hình đúng role Whitelist.",
                ephemeral=True,
            )
            return
        if whitelist_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ Chỉ thành viên **đã được Whitelist** mới lấy được mã bảo lãnh.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await issue_self_service_guarantor_code(
            interaction.guild,
            interaction.user,
        )
        await interaction.followup.send(
            f"{'✅' if ok else '❌'} {message}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Nhập mã bảo lãnh",
        emoji=EMOJI_GUARANTOR,
        style=discord.ButtonStyle.success,
        custom_id="venus_whitelist_guarantor",
    )
    async def guarantor(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
            return
        if SETTINGS.require_verification:
            verified_at = await asyncio.to_thread(
                DB.get_verification,
                interaction.guild.id,
                interaction.user.id,
            )
            if not verified_at:
                await interaction.response.send_message(
                    "❌ Hãy bấm **Xác thực tài khoản** trước khi nhập mã bảo lãnh.",
                    ephemeral=True,
                )
                return
        await interaction.response.send_modal(GuarantorCodeModal())

    @discord.ui.button(
        label="Đăng ký",
        emoji=EMOJI_APPLY,
        style=discord.ButtonStyle.primary,
        custom_id="venus_whitelist_apply",
    )
    async def apply(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
            return

        if SETTINGS.require_verification:
            verified_at = await asyncio.to_thread(
                DB.get_verification,
                interaction.guild.id,
                interaction.user.id,
            )
            if not verified_at:
                await interaction.response.send_message(
                    "❌ Hãy bấm **Xác thực tài khoản** trước.",
                    ephemeral=True,
                )
                return

        pending_guarantor = await asyncio.to_thread(
            DB.get_pending_guarantor_request,
            interaction.guild.id,
            interaction.user.id,
        )
        if pending_guarantor:
            await interaction.response.send_message(
                f"⏳ Yêu cầu bảo lãnh **#{pending_guarantor['id']:04d}** đang chờ staff duyệt.",
                ephemeral=True,
            )
            return

        latest = await asyncio.to_thread(
            DB.get_latest_application,
            interaction.guild.id,
            interaction.user.id,
        )
        if latest and latest["status"] == "pending":
            await interaction.response.send_message(
                "⏳ Bạn đang có một đơn chờ duyệt.",
                ephemeral=True,
            )
            return
        if latest and latest["status"] == "accepted":
            await interaction.response.send_message(
                "✅ Bạn đã được whitelist rồi.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(ApplicationModal())


class ReviewActionRow(discord.ui.ActionRow):
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__()
        if disabled:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True

    @discord.ui.button(
        label="Đồng ý",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="venus_review_accept",
    )
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_decision(interaction, status="accepted", reason=None)
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(
        label="Từ chối",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="venus_review_reject",
    )
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_decision(interaction, status="rejected", reason=None)
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(
        label="Đồng ý + lý do",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="venus_review_accept_reason",
    )
    async def accept_reason(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_reviewer(interaction.user):
            await interaction.response.send_message("❌ Bạn không có quyền xét duyệt.", ephemeral=True)
            return
        await interaction.response.send_modal(ReasonModal("accepted"))

    @discord.ui.button(
        label="Từ chối + lý do",
        emoji="💬",
        style=discord.ButtonStyle.secondary,
        custom_id="venus_review_reject_reason",
    )
    async def reject_reason(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_reviewer(interaction.user):
            await interaction.response.send_message("❌ Bạn không có quyền xét duyệt.", ephemeral=True)
            return
        await interaction.response.send_modal(ReasonModal("rejected"))


class GuarantorReviewActionRow(discord.ui.ActionRow):
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__()
        if disabled:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True

    @discord.ui.button(
        label="Đồng ý bảo lãnh",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="venus_guarantor_review_accept",
    )
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_guarantor_decision(
            interaction,
            status="accepted",
            reason=None,
        )
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(
        label="Từ chối bảo lãnh",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="venus_guarantor_review_reject",
    )
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_guarantor_decision(
            interaction,
            status="rejected",
            reason=None,
        )
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(
        label="Đồng ý + lý do",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="venus_guarantor_review_accept_reason",
    )
    async def accept_reason(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_reviewer(interaction.user):
            await interaction.response.send_message(
                "❌ Bạn không có quyền xét duyệt.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(GuarantorReasonModal("accepted"))

    @discord.ui.button(
        label="Từ chối + lý do",
        emoji="💬",
        style=discord.ButtonStyle.secondary,
        custom_id="venus_guarantor_review_reject_reason",
    )
    async def reject_reason(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_reviewer(interaction.user):
            await interaction.response.send_message(
                "❌ Bạn không có quyền xét duyệt.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(GuarantorReasonModal("rejected"))


class WhitelistPanelLayout(discord.ui.LayoutView):
    def __init__(
        self,
        guild_name: str | None = None,
        image_filename: str | None = None,
        guild: discord.Guild | None = None,
        permissions: discord.Permissions | None = None,
    ) -> None:
        super().__init__(timeout=None)
        container = discord.ui.Container(accent_colour=SETTINGS.accent_colour)

        if image_filename:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(
                media=f"attachment://{image_filename}",
                description=f"Đăng ký whitelist {guild_name or SETTINGS.server_name}",
            )
            container.add_item(gallery)
            container.add_item(discord.ui.Separator())

        container.add_item(
            discord.ui.TextDisplay(
                build_panel_text(guild_name or SETTINGS.server_name, guild, permissions)
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(WhitelistActionRow(guild, permissions))
        self.add_item(container)


class ReviewLayout(discord.ui.LayoutView):
    def __init__(
        self,
        application: dict[str, Any] | None = None,
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        status = str(application["status"]) if application else "pending"
        container = discord.ui.Container(accent_colour=review_colour(status))

        if application:
            avatar_url = application.get("avatar_url")
            if avatar_url:
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(build_review_header(application)),
                        accessory=discord.ui.Thumbnail(
                            avatar_url,
                            description=f"Avatar của {application.get('display_name') or application.get('username')}",
                        ),
                    )
                )
            else:
                container.add_item(discord.ui.TextDisplay(build_review_header(application)))

            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(build_review_answers(application)))
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(build_review_stats(application)))

            result_text = build_review_result(application)
            if result_text:
                container.add_item(discord.ui.Separator())
                container.add_item(discord.ui.TextDisplay(result_text))
        else:
            container.add_item(discord.ui.TextDisplay("## 💌 VENUS WHITELIST REVIEW"))

        container.add_item(discord.ui.Separator())
        container.add_item(ReviewActionRow(disabled=disabled))
        self.add_item(container)


class GuarantorReviewLayout(discord.ui.LayoutView):
    def __init__(
        self,
        request: dict[str, Any] | None = None,
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        status = str(request["status"]) if request else "pending"
        container = discord.ui.Container(accent_colour=guarantor_review_colour(status))

        if request:
            avatar_url = request.get("applicant_avatar_url")
            if avatar_url:
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(build_guarantor_review_header(request)),
                        accessory=discord.ui.Thumbnail(
                            avatar_url,
                            description=(
                                "Avatar của "
                                f"{request.get('applicant_display_name') or request.get('applicant_username')}"
                            ),
                        ),
                    )
                )
            else:
                container.add_item(
                    discord.ui.TextDisplay(build_guarantor_review_header(request))
                )

            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(build_guarantor_review_body(request)))

            result_text = build_guarantor_review_result(request)
            if result_text:
                container.add_item(discord.ui.Separator())
                container.add_item(discord.ui.TextDisplay(result_text))
        else:
            container.add_item(
                discord.ui.TextDisplay(
                    f"## {usable_emoji(EMOJI_GET_GUARANTOR)} VENUS GUARANTOR REVIEW"
                )
            )

        container.add_item(discord.ui.Separator())
        container.add_item(GuarantorReviewActionRow(disabled=disabled))
        self.add_item(container)


class VenusWhitelistBot(commands.Bot):
    async def setup_hook(self) -> None:
        await asyncio.to_thread(DB.initialize)
        upgraded = await asyncio.to_thread(
            DB.upgrade_self_service_codes,
            SETTINGS.self_service_code_max_uses,
        )
        if upgraded:
            log.info("Đã nâng %s mã bảo lãnh lên %s lượt", upgraded, SETTINGS.self_service_code_max_uses)
        self.add_view(WhitelistPanelLayout())
        self.add_view(ReviewLayout())
        self.add_view(GuarantorReviewLayout())

        try:
            if SETTINGS.test_guild_id:
                guild_object = discord.Object(id=SETTINGS.test_guild_id)
                self.tree.copy_global_to(guild=guild_object)
                await self.tree.sync(guild=guild_object)
                log.info("Đã sync slash command cho test guild %s", SETTINGS.test_guild_id)
            else:
                await self.tree.sync()
                log.info("Đã sync slash command global")
        except discord.HTTPException:
            log.exception("Không sync được slash command")


intents = discord.Intents.default()
intents.members = True
bot = VenusWhitelistBot(command_prefix=commands.when_mentioned, intents=intents)


@bot.event
async def on_ready() -> None:
    log.info("Bot online: %s (%s)", bot.user, bot.user.id if bot.user else "?")


@bot.tree.command(name="whitelist_panel", description="Gửi bảng đăng ký whitelist")
@app_commands.guild_only()
@app_commands.describe(channel="Kênh muốn gửi bảng; để trống sẽ dùng kênh hiện tại")
async def whitelist_panel(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ Bạn cần quyền **Manage Server**.", ephemeral=True)
        return

    target = channel or interaction.channel
    if target is None or not hasattr(target, "send"):
        await interaction.response.send_message("❌ Kênh không hợp lệ.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    image_filename = SETTINGS.banner_path.name if SETTINGS.banner_path.is_file() else None

    bot_member = interaction.guild.me
    permissions = (
        target.permissions_for(bot_member)
        if bot_member is not None and hasattr(target, "permissions_for")
        else None
    )
    if permissions is not None:
        required = {
            "View Channel": permissions.view_channel,
            "Send Messages": permissions.send_messages,
        }
        if image_filename:
            required["Attach Files"] = permissions.attach_files
        missing = [name for name, allowed in required.items() if not allowed]
        if missing:
            await interaction.followup.send(
                f"❌ Bot thiếu quyền tại {target.mention}: **{', '.join(missing)}**.",
                ephemeral=True,
            )
            return

    kwargs: dict[str, Any] = {
        "view": WhitelistPanelLayout(
            interaction.guild.name,
            image_filename,
            interaction.guild,
            permissions,
        ),
        "allowed_mentions": ALLOWED_MENTIONS,
    }
    file: discord.File | None = None
    if image_filename:
        file = discord.File(SETTINGS.banner_path, filename=image_filename)
        kwargs["file"] = file

    try:
        message = await target.send(**kwargs)
    except discord.Forbidden as exc:
        log.exception("Không gửi được whitelist panel (Forbidden)")
        await interaction.followup.send(
            "❌ Discord chặn bot gửi bảng tại kênh này "
            f"(mã lỗi `{exc.code}`). Kiểm tra quyền riêng của kênh hoặc category.",
            ephemeral=True,
        )
        return
    except discord.HTTPException as exc:
        log.exception("Không gửi được whitelist panel")
        await interaction.followup.send(
            f"❌ Discord từ chối bảng (HTTP {exc.status}, mã `{exc.code}`):\n"
            f"```{trim(str(exc.text), 1500)}```",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"✅ Đã gửi bảng whitelist: {message.jump_url}",
        ephemeral=True,
    )


@bot.tree.command(name="whitelist_status", description="Xem trạng thái đơn whitelist của bạn")
@app_commands.guild_only()
async def whitelist_status(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        return

    application = await asyncio.to_thread(
        DB.get_latest_application,
        interaction.guild.id,
        interaction.user.id,
    )
    verified_at = await asyncio.to_thread(
        DB.get_verification,
        interaction.guild.id,
        interaction.user.id,
    )
    referral = await asyncio.to_thread(
        DB.get_referral,
        interaction.guild.id,
        interaction.user.id,
    )
    guarantor_request = await asyncio.to_thread(
        DB.get_latest_guarantor_request,
        interaction.guild.id,
        interaction.user.id,
    )

    lines = [f"**Xác thực:** {'✅ Có' if verified_at else '❌ Chưa'}"]
    if referral:
        lines.append(f"**Mã bảo lãnh:** `{referral['code']}` • <@{referral['owner_user_id']}>")
    else:
        lines.append("**Mã bảo lãnh:** Không sử dụng")

    if guarantor_request:
        lines.append(
            f"**Duyệt bảo lãnh:** `#{guarantor_request['id']:04d}` • "
            f"{GUARANTOR_STATUS_LABELS.get(guarantor_request['status'], guarantor_request['status'])}"
        )
        if guarantor_request.get("reason"):
            lines.append(
                f"**Lý do bảo lãnh:** {trim(str(guarantor_request['reason']), 600)}"
            )

    if application:
        lines.append(
            f"**Đơn gần nhất:** `#{application['id']:04d}` • {STATUS_LABELS.get(application['status'], application['status'])}"
        )
        if application.get("reason"):
            lines.append(f"**Lý do:** {trim(str(application['reason']), 900)}")
    else:
        lines.append("**Đơn gần nhất:** Chưa nộp")

    embed = discord.Embed(
        title="Trạng thái Whitelist",
        description="\n".join(lines),
        colour=SETTINGS.accent_colour,
    )
    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
        allowed_mentions=ALLOWED_MENTIONS,
    )


@bot.tree.command(
    name="whitelist_guarantor_sync",
    description="Cấp lại role cho người đã được duyệt bảo lãnh",
)
@app_commands.guild_only()
@app_commands.describe(member="Người đã được staff đồng ý bảo lãnh")
async def whitelist_guarantor_sync(
    interaction: discord.Interaction,
    member: discord.Member,
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        return
    if not is_reviewer(interaction.user):
        await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)
        return

    request = await asyncio.to_thread(
        DB.get_latest_guarantor_request,
        interaction.guild.id,
        member.id,
    )
    if request is None or request["status"] != "accepted":
        await interaction.response.send_message(
            "❌ Thành viên này chưa có yêu cầu bảo lãnh đã được đồng ý.",
            ephemeral=True,
        )
        return

    grant_roles, remove_roles, role_error = resolve_guarantor_roles(
        interaction.guild,
        interaction.guild.me,
    )
    if role_error:
        await interaction.response.send_message(role_error, ephemeral=True)
        return

    try:
        missing_roles = [role for role in grant_roles if role not in member.roles]
        if missing_roles:
            await member.add_roles(
                *missing_roles,
                reason=f"Guarantor role sync by {interaction.user} ({interaction.user.id})",
            )
        to_remove = [role for role in remove_roles if role in member.roles]
        if to_remove:
            await member.remove_roles(*to_remove, reason="Guarantor role sync")
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Bot không đủ quyền cấp hoặc gỡ role.",
            ephemeral=True,
        )
        return
    except discord.HTTPException:
        log.exception("Discord API lỗi khi đồng bộ role bảo lãnh")
        await interaction.response.send_message(
            "❌ Discord lỗi khi đồng bộ role.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"✅ Đã đồng bộ role bảo lãnh cho {member.mention} từ bảo lãnh `#{int(request['id']):04d}`.",
        ephemeral=True,
        allowed_mentions=ALLOWED_MENTIONS,
    )


@bot.tree.command(name="whitelist_reset", description="Xóa hồ sơ whitelist để thành viên nộp lại")
@app_commands.guild_only()
@app_commands.describe(
    member="Thành viên cần reset",
    clear_verification="Xóa luôn trạng thái xác thực",
)
async def whitelist_reset(
    interaction: discord.Interaction,
    member: discord.Member,
    clear_verification: bool = False,
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        return
    if not is_reviewer(interaction.user):
        await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    await asyncio.to_thread(DB.reset_user, interaction.guild.id, member.id, clear_verification)

    whitelist_role = interaction.guild.get_role(SETTINGS.whitelist_role_id)
    if whitelist_role and whitelist_role in member.roles:
        try:
            await member.remove_roles(whitelist_role, reason=f"Whitelist reset by {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                "⚠️ Đã xóa dữ liệu nhưng bot không gỡ được role whitelist.",
                ephemeral=True,
            )
            return

    await interaction.followup.send(
        f"✅ Đã reset whitelist của {member.mention}.",
        ephemeral=True,
        allowed_mentions=ALLOWED_MENTIONS,
    )


def generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"VENUS-{suffix}"


@bot.tree.command(name="whitelist_code_create", description="Tạo mã bảo lãnh")
@app_commands.guild_only()
@app_commands.describe(
    owner="Người sở hữu mã",
    max_uses="Số lượt tối đa; 0 là không giới hạn",
    custom_code="Mã tự chọn, chỉ chữ in hoa, số và dấu -",
)
async def whitelist_code_create(
    interaction: discord.Interaction,
    owner: discord.Member,
    max_uses: app_commands.Range[int, 0, 1000] = 0,
    custom_code: str | None = None,
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        return
    if not is_reviewer(interaction.user):
        await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)
        return

    code = (custom_code or generate_code()).strip().upper()
    if not CODE_PATTERN.fullmatch(code):
        await interaction.response.send_message(
            "❌ Mã phải dài 4–20 ký tự, chỉ gồm chữ in hoa, số và dấu `-`.",
            ephemeral=True,
        )
        return

    try:
        await asyncio.to_thread(
            DB.create_guarantor_code,
            code=code,
            guild_id=interaction.guild.id,
            owner_user_id=owner.id,
            created_by=interaction.user.id,
            max_uses=int(max_uses),
        )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            await interaction.response.send_message("❌ Mã này đã tồn tại.", ephemeral=True)
            return
        log.exception("Không tạo được mã bảo lãnh")
        await interaction.response.send_message("❌ Không tạo được mã.", ephemeral=True)
        return

    usage_text = "không giới hạn" if int(max_uses) == 0 else str(max_uses)
    await interaction.response.send_message(
        f"✅ Đã tạo mã `{code}` cho {owner.mention} • lượt dùng: **{usage_text}**.",
        ephemeral=True,
        allowed_mentions=ALLOWED_MENTIONS,
    )


@bot.tree.command(name="whitelist_code_disable", description="Tắt một mã bảo lãnh")
@app_commands.guild_only()
async def whitelist_code_disable(interaction: discord.Interaction, code: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        return
    if not is_reviewer(interaction.user):
        await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)
        return

    normalized = code.strip().upper()
    disabled = await asyncio.to_thread(DB.disable_guarantor_code, interaction.guild.id, normalized)
    await interaction.response.send_message(
        f"✅ Đã tắt mã `{normalized}`." if disabled else "❌ Không tìm thấy mã.",
        ephemeral=True,
    )


@bot.tree.command(name="whitelist_code_list", description="Xem danh sách mã bảo lãnh")
@app_commands.guild_only()
async def whitelist_code_list(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        return
    if not is_reviewer(interaction.user):
        await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)
        return

    rows = await asyncio.to_thread(DB.list_guarantor_codes, interaction.guild.id, 20)
    if not rows:
        await interaction.response.send_message("Chưa có mã bảo lãnh.", ephemeral=True)
        return

    lines: list[str] = []
    for row in rows:
        maximum = "∞" if int(row["max_uses"]) == 0 else str(row["max_uses"])
        state = "🟢" if int(row["active"]) else "⚫"
        lines.append(
            f"{state} `{row['code']}` • <@{row['owner_user_id']}> • {row['use_count']}/{maximum}"
        )

    embed = discord.Embed(
        title="Mã bảo lãnh",
        description="\n".join(lines),
        colour=SETTINGS.accent_colour,
    )
    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
        allowed_mentions=ALLOWED_MENTIONS,
    )


bot.run(SETTINGS.token, log_handler=None)
