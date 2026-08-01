from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS verifications (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    verified_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS guarantor_codes (
                    code TEXT PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    owner_user_id INTEGER NOT NULL,
                    created_by INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL DEFAULT 0,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS referrals (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    owner_user_id INTEGER NOT NULL,
                    used_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id),
                    FOREIGN KEY (code) REFERENCES guarantor_codes(code)
                );

                CREATE TABLE IF NOT EXISTS guarantor_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    applicant_user_id INTEGER NOT NULL,
                    applicant_username TEXT NOT NULL,
                    applicant_display_name TEXT NOT NULL,
                    applicant_avatar_url TEXT,
                    code TEXT NOT NULL,
                    owner_user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    review_channel_id INTEGER,
                    review_message_id INTEGER UNIQUE,
                    requested_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewer_id INTEGER,
                    reason TEXT,
                    FOREIGN KEY (code) REFERENCES guarantor_codes(code)
                );

                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    answers_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    guarantor_code TEXT,
                    guarantor_user_id INTEGER,
                    review_channel_id INTEGER,
                    review_message_id INTEGER UNIQUE,
                    account_created_at TEXT NOT NULL,
                    guild_joined_at TEXT,
                    verified_at TEXT,
                    submitted_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewer_id INTEGER,
                    reason TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_guarantor_requests_user
                    ON guarantor_requests(guild_id, applicant_user_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_guarantor_requests_review_message
                    ON guarantor_requests(guild_id, review_message_id);
                CREATE INDEX IF NOT EXISTS idx_applications_user
                    ON applications(guild_id, user_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_applications_review_message
                    ON applications(guild_id, review_message_id);
                """
            )

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def mark_verified(self, guild_id: int, user_id: int) -> str:
        verified_at = self.utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO verifications(guild_id, user_id, verified_at)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id)
                DO UPDATE SET verified_at = excluded.verified_at
                """,
                (guild_id, user_id, verified_at),
            )
        return verified_at

    def get_verification(self, guild_id: int, user_id: int) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT verified_at FROM verifications WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
        return str(row["verified_at"]) if row else None

    def create_guarantor_code(
        self,
        *,
        code: str,
        guild_id: int,
        owner_user_id: int,
        created_by: int,
        max_uses: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO guarantor_codes(
                    code, guild_id, owner_user_id, created_by,
                    max_uses, use_count, active, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, 1, ?)
                """,
                (
                    code,
                    guild_id,
                    owner_user_id,
                    created_by,
                    max_uses,
                    self.utc_now(),
                ),
            )

    def disable_guarantor_code(self, guild_id: int, code: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE guarantor_codes SET active = 0 WHERE guild_id = ? AND code = ?",
                (guild_id, code),
            )
        return cursor.rowcount > 0

    def list_guarantor_codes(self, guild_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM guarantor_codes
                WHERE guild_id = ?
                ORDER BY active DESC, created_at DESC
                LIMIT ?
                """,
                (guild_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_available_guarantor_code(
        self,
        guild_id: int,
        owner_user_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM guarantor_codes
                WHERE guild_id = ?
                  AND owner_user_id = ?
                  AND active = 1
                  AND (max_uses = 0 OR use_count < max_uses)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (guild_id, owner_user_id),
            ).fetchone()
        return dict(row) if row else None

    def apply_guarantor_code(
        self,
        *,
        guild_id: int,
        user_id: int,
        code: str,
    ) -> tuple[bool, str, int | None]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                "SELECT code, owner_user_id FROM referrals WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            if existing:
                return (
                    False,
                    f"Bạn đã dùng mã `{existing['code']}` rồi.",
                    int(existing["owner_user_id"]),
                )

            row = connection.execute(
                """
                SELECT * FROM guarantor_codes
                WHERE guild_id = ? AND code = ? AND active = 1
                """,
                (guild_id, code),
            ).fetchone()
            if not row:
                return False, "Mã bảo lãnh không tồn tại hoặc đã bị tắt.", None

            owner_user_id = int(row["owner_user_id"])
            if owner_user_id == user_id:
                return False, "Bạn không thể dùng mã bảo lãnh của chính mình.", None

            max_uses = int(row["max_uses"])
            use_count = int(row["use_count"])
            if max_uses > 0 and use_count >= max_uses:
                return False, "Mã bảo lãnh đã hết lượt sử dụng.", owner_user_id

            connection.execute(
                """
                INSERT INTO referrals(guild_id, user_id, code, owner_user_id, used_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, code, owner_user_id, self.utc_now()),
            )
            connection.execute(
                "UPDATE guarantor_codes SET use_count = use_count + 1 WHERE code = ?",
                (code,),
            )
            return True, "Đã lưu mã bảo lãnh.", owner_user_id

    def get_referral(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM referrals WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def create_guarantor_request(
        self,
        *,
        guild_id: int,
        applicant_user_id: int,
        applicant_username: str,
        applicant_display_name: str,
        applicant_avatar_url: str | None,
        code: str,
    ) -> tuple[bool, str, int | None, int | None]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            referral = connection.execute(
                "SELECT code, owner_user_id FROM referrals WHERE guild_id = ? AND user_id = ?",
                (guild_id, applicant_user_id),
            ).fetchone()
            if referral:
                return (
                    False,
                    f"Bạn đã có bảo lãnh bằng mã `{referral['code']}`.",
                    None,
                    int(referral["owner_user_id"]),
                )

            pending = connection.execute(
                """
                SELECT id, code, owner_user_id FROM guarantor_requests
                WHERE guild_id = ? AND applicant_user_id = ? AND status = 'pending'
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, applicant_user_id),
            ).fetchone()
            if pending:
                return (
                    False,
                    f"Bạn đang có yêu cầu bảo lãnh `#{int(pending['id']):04d}` chờ staff duyệt.",
                    int(pending["id"]),
                    int(pending["owner_user_id"]),
                )

            row = connection.execute(
                """
                SELECT * FROM guarantor_codes
                WHERE guild_id = ? AND code = ? AND active = 1
                """,
                (guild_id, code),
            ).fetchone()
            if not row:
                return False, "Mã bảo lãnh không tồn tại hoặc đã bị tắt.", None, None

            owner_user_id = int(row["owner_user_id"])
            if owner_user_id == applicant_user_id:
                return False, "Bạn không thể dùng mã bảo lãnh của chính mình.", None, None

            max_uses = int(row["max_uses"])
            use_count = int(row["use_count"])
            if max_uses > 0 and use_count >= max_uses:
                return False, "Mã bảo lãnh đã hết lượt sử dụng.", None, owner_user_id

            if max_uses > 0:
                pending_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) AS total FROM guarantor_requests
                        WHERE guild_id = ? AND code = ? AND status = 'pending'
                        """,
                        (guild_id, code),
                    ).fetchone()["total"]
                )
                if use_count + pending_count >= max_uses:
                    return (
                        False,
                        "Mã này đang có yêu cầu khác chờ staff duyệt hoặc đã hết lượt.",
                        None,
                        owner_user_id,
                    )

            cursor = connection.execute(
                """
                INSERT INTO guarantor_requests(
                    guild_id, applicant_user_id, applicant_username,
                    applicant_display_name, applicant_avatar_url, code,
                    owner_user_id, status, requested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    guild_id,
                    applicant_user_id,
                    applicant_username,
                    applicant_display_name,
                    applicant_avatar_url,
                    code,
                    owner_user_id,
                    self.utc_now(),
                ),
            )
            return True, "Đã tạo yêu cầu bảo lãnh.", int(cursor.lastrowid), owner_user_id

    def attach_guarantor_review_message(
        self,
        request_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE guarantor_requests
                SET review_channel_id = ?, review_message_id = ?
                WHERE id = ?
                """,
                (channel_id, message_id, request_id),
            )

    def mark_guarantor_request_error(self, request_id: int, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE guarantor_requests
                SET status = 'error', reason = ?
                WHERE id = ? AND status = 'pending'
                """,
                (reason[:1000], request_id),
            )

    def get_guarantor_request_by_id(self, request_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM guarantor_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_guarantor_request_by_message(
        self,
        guild_id: int,
        message_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM guarantor_requests
                WHERE guild_id = ? AND review_message_id = ?
                """,
                (guild_id, message_id),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_guarantor_request(
        self,
        guild_id: int,
        applicant_user_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM guarantor_requests
                WHERE guild_id = ? AND applicant_user_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, applicant_user_id),
            ).fetchone()
        return dict(row) if row else None

    def get_pending_guarantor_request(
        self,
        guild_id: int,
        applicant_user_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM guarantor_requests
                WHERE guild_id = ? AND applicant_user_id = ? AND status = 'pending'
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, applicant_user_id),
            ).fetchone()
        return dict(row) if row else None

    def finalize_guarantor_request(
        self,
        *,
        request_id: int,
        status: str,
        reviewer_id: int,
        reason: str | None,
    ) -> tuple[bool, str]:
        if status not in {"accepted", "rejected"}:
            return False, "Trạng thái xử lý không hợp lệ."

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = connection.execute(
                "SELECT * FROM guarantor_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if not request:
                return False, "Không tìm thấy yêu cầu bảo lãnh."
            if request["status"] != "pending":
                return False, "Yêu cầu này đã được xử lý trước đó."

            if status == "accepted":
                code_row = connection.execute(
                    """
                    SELECT * FROM guarantor_codes
                    WHERE guild_id = ? AND code = ? AND active = 1
                    """,
                    (int(request["guild_id"]), str(request["code"])),
                ).fetchone()
                if not code_row:
                    return False, "Mã bảo lãnh đã bị tắt hoặc không còn tồn tại."

                max_uses = int(code_row["max_uses"])
                use_count = int(code_row["use_count"])
                if max_uses > 0 and use_count >= max_uses:
                    return False, "Mã bảo lãnh đã hết lượt sử dụng."

                existing = connection.execute(
                    "SELECT code FROM referrals WHERE guild_id = ? AND user_id = ?",
                    (int(request["guild_id"]), int(request["applicant_user_id"])),
                ).fetchone()
                if existing:
                    return False, f"Người này đã có bảo lãnh bằng mã `{existing['code']}`."

                connection.execute(
                    """
                    INSERT INTO referrals(guild_id, user_id, code, owner_user_id, used_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        int(request["guild_id"]),
                        int(request["applicant_user_id"]),
                        str(request["code"]),
                        int(request["owner_user_id"]),
                        self.utc_now(),
                    ),
                )
                connection.execute(
                    "UPDATE guarantor_codes SET use_count = use_count + 1 WHERE code = ?",
                    (str(request["code"]),),
                )

            cursor = connection.execute(
                """
                UPDATE guarantor_requests
                SET status = ?, reviewed_at = ?, reviewer_id = ?, reason = ?
                WHERE id = ? AND status = 'pending'
                """,
                (
                    status,
                    self.utc_now(),
                    reviewer_id,
                    reason[:1000] if reason else None,
                    request_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Không thể cập nhật trạng thái yêu cầu bảo lãnh.")

        return True, "Đã đồng ý bảo lãnh." if status == "accepted" else "Đã từ chối bảo lãnh."

    def create_application(
        self,
        *,
        guild_id: int,
        user_id: int,
        username: str,
        display_name: str,
        avatar_url: str | None,
        answers: list[dict[str, str]],
        account_created_at: str,
        guild_joined_at: str | None,
        verified_at: str | None,
        guarantor_code: str | None,
        guarantor_user_id: int | None,
    ) -> tuple[bool, str, int | None]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                """
                SELECT id, status FROM applications
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, user_id),
            ).fetchone()

            if latest and latest["status"] == "pending":
                return False, "Bạn đang có một đơn chờ duyệt.", int(latest["id"])
            if latest and latest["status"] == "accepted":
                return False, "Bạn đã được duyệt whitelist rồi.", int(latest["id"])

            cursor = connection.execute(
                """
                INSERT INTO applications(
                    guild_id, user_id, username, display_name, avatar_url,
                    answers_json, status, guarantor_code, guarantor_user_id,
                    account_created_at, guild_joined_at, verified_at, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    user_id,
                    username,
                    display_name,
                    avatar_url,
                    json.dumps(answers, ensure_ascii=False),
                    guarantor_code,
                    guarantor_user_id,
                    account_created_at,
                    guild_joined_at,
                    verified_at,
                    self.utc_now(),
                ),
            )
            return True, "Đã tạo đơn.", int(cursor.lastrowid)

    def attach_review_message(
        self,
        application_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE applications
                SET review_channel_id = ?, review_message_id = ?
                WHERE id = ?
                """,
                (channel_id, message_id, application_id),
            )

    def mark_application_error(self, application_id: int, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE applications
                SET status = 'error', reason = ?
                WHERE id = ? AND status = 'pending'
                """,
                (reason[:1000], application_id),
            )

    def get_application_by_id(self, application_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_application_by_message(
        self,
        guild_id: int,
        message_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM applications
                WHERE guild_id = ? AND review_message_id = ?
                """,
                (guild_id, message_id),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_application(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM applications
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def finalize_application(
        self,
        *,
        application_id: int,
        status: str,
        reviewer_id: int,
        reason: str | None,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE applications
                SET status = ?, reviewed_at = ?, reviewer_id = ?, reason = ?
                WHERE id = ? AND status = 'pending'
                """,
                (
                    status,
                    self.utc_now(),
                    reviewer_id,
                    reason[:1000] if reason else None,
                    application_id,
                ),
            )
        return cursor.rowcount == 1

    def reset_user(self, guild_id: int, user_id: int, clear_verification: bool) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM applications WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            connection.execute(
                "DELETE FROM guarantor_requests WHERE guild_id = ? AND applicant_user_id = ?",
                (guild_id, user_id),
            )
            referral = connection.execute(
                "SELECT code FROM referrals WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            if referral:
                connection.execute(
                    "UPDATE guarantor_codes SET use_count = MAX(0, use_count - 1) WHERE code = ?",
                    (referral["code"],),
                )
            connection.execute(
                "DELETE FROM referrals WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            if clear_verification:
                connection.execute(
                    "DELETE FROM verifications WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
