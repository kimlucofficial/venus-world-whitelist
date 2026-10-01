# Venus World Whitelist Bot 🎟️

Bot whitelist riêng của Venus World, dùng **Discord Components V2** cùng phong cách khung lớn của bot Welcome.

## Luồng Whitelist

1. Staff dùng `/whitelist_panel` để gửi bảng đăng ký.
2. Người chơi bấm **Xác thực tài khoản**.
3. Người đã có role Whitelist có thể bấm **Lấy mã bảo lãnh**.
4. Người được bảo lãnh bấm **Nhập mã bảo lãnh**.
5. Bot gửi ngay một phiếu bảo lãnh vào kênh staff với 4 nút:
   - Đồng ý bảo lãnh
   - Từ chối bảo lãnh
   - Đồng ý + lý do
   - Từ chối + lý do
6. Khi staff đồng ý, bot tự cấp các role trong `GUARANTOR_GRANT_ROLE_IDS` và gỡ các role trong `GUARANTOR_REMOVE_ROLE_IDS`.
7. Nếu có `UNVERIFIED_ROLE_ID`, bot cũng tự gỡ role này khi đủ quyền.
8. Người được bảo lãnh không cần nộp thêm đơn Whitelist.

## Cơ chế mã bảo lãnh

- Chỉ người đang có role được cấu hình tại `WHITELIST_ROLE_ID` mới lấy được mã bằng nút.
- Mỗi người chỉ có **1 mã**, mỗi mã bảo lãnh được tối đa **5 người** (`GUARANTOR_SELF_MAX_USES`).
- Khi mã đã dùng hết, chủ mã không nhận được mã mới (bật lại bằng `GUARANTOR_SELF_RENEW=true`).
- Khi khởi động, bot tự nâng mã tự lấy mới nhất của từng người lên số lượt mới.
- Mỗi lần người chơi bấm lấy mã, bot gửi log ngay.
- Nếu chưa cấu hình kênh log riêng, log bảo lãnh sẽ dùng `WHITELIST_LOG_CHANNEL_ID`; nếu vẫn trống thì gửi vào `WHITELIST_REVIEW_CHANNEL_ID`.
- Người nhập mã phải chờ staff duyệt bảo lãnh.
- Khi đồng ý, bot cấp role Whitelist trực tiếp và DM kết quả cho cả hai bên.
- Nếu bot không cấp được role, hệ thống hoàn tác yêu cầu về trạng thái chờ để staff sửa quyền rồi duyệt lại.

## Discord Developer Portal

Bật **Server Members Intent**.

Quyền bot cần có:

- View Channels
- Send Messages
- Embed Links
- Attach Files
- Read Message History
- Manage Roles
- Use Application Commands

Role bot phải nằm cao hơn role Whitelist, role chưa xác thực và toàn bộ role bảo lãnh được cấp/gỡ.

## Railway Variables

```env
DISCORD_TOKEN=TOKEN_BOT
TEST_GUILD_ID=ID_SERVER
WHITELIST_REVIEW_CHANNEL_ID=ID_KENH_STAFF_NHAN_DON
WHITELIST_ROLE_ID=ID_ROLE_WHITELIST
WHITELIST_REVIEWER_ROLE_ID=ID_ROLE_STAFF
UNVERIFIED_ROLE_ID=ID_ROLE_CHUA_XAC_THUC
WHITELIST_LOG_CHANNEL_ID=ID_KENH_LOG

# Không bắt buộc
GUARANTOR_LOG_CHANNEL_ID=ID_KENH_LOG_BAO_LANH
GUARANTOR_SELF_MAX_USES=5
GUARANTOR_SELF_RENEW=false
GUARANTOR_GRANT_ROLE_IDS=1531744174947307600,1531744178210603151
GUARANTOR_REMOVE_ROLE_IDS=1531744180966002870

SERVER_NAME=VENUS WORLD
TIMEZONE=Asia/Ho_Chi_Minh
ACCENT_COLOR=E17ED6
REQUIRE_VERIFICATION=true
MIN_ACCOUNT_AGE_DAYS=0
MIN_JOIN_AGE_MINUTES=0
DATABASE_PATH=data/whitelist.db
WHITELIST_BANNER_PATH=assets/whitelist_banner.png

# Tự động trả lời
AUTO_REPLY_CHANNEL_ID=1555069801960050759
AUTO_REPLY_WHITELIST_CHANNEL_ID=1531744196443111686
AUTO_REPLY_GUARANTOR_CHANNEL_ID=1531744196443111686
AUTO_REPLY_COOLDOWN_SECONDS=60
```

Auto-reply: ai chat trong `AUTO_REPLY_CHANNEL_ID` sẽ được bot reply bằng embed hướng dẫn nộp whitelist và bảo lãnh. Mỗi người chỉ được bot reply lại sau `AUTO_REPLY_COOLDOWN_SECONDS` giây (chống spam). Đặt `AUTO_REPLY_CHANNEL_ID=0` để tắt. Bot cần quyền **View Channel, Send Messages, Embed Links, Read Message History** tại kênh đó. Không cần bật Message Content Intent.

`GUARANTOR_LOG_CHANNEL_ID` có thể để trống. `GUARANTOR_SELF_MAX_USES=5` nghĩa là mỗi mã tự lấy bảo lãnh được 5 người. Các biến role bảo lãnh nhận nhiều ID, cách nhau bằng dấu phẩy; để trống thì dùng giá trị mặc định ở trên.

## Railway Volume

Mount Volume vào:

```text
/app/data
```

Giữ:

```env
DATABASE_PATH=data/whitelist.db
```

Bản cập nhật tự tạo thêm bảng database mới, không cần xóa file SQLite cũ.

## Slash commands

- `/whitelist_panel` — gửi bảng đăng ký.
- `/whitelist_status` — xem trạng thái xác thực, bảo lãnh và đơn.
- `/whitelist_guarantor_sync` — cấp lại role cho trường hợp bảo lãnh cũ đã duyệt trước bản V5.
- `/whitelist_reset` — reset hồ sơ để thành viên nộp lại.
- `/whitelist_code_create` — staff tạo mã thủ công.
- `/whitelist_code_disable` — tắt mã.
- `/whitelist_code_list` — xem danh sách mã.

## Chỉnh câu hỏi

Sửa `questions.json`. Discord modal hỗ trợ tối đa 5 câu hỏi trong một form.

```json
{
  "key": "steam_hex",
  "label": "Steam Hex",
  "placeholder": "Ví dụ: steam:11000010xxxxxxxx",
  "style": "short",
  "required": true,
  "min_length": 8,
  "max_length": 80
}
```

`style` nhận `short` hoặc `paragraph`.
