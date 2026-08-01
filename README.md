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
6. Khi staff đồng ý, mã mới được gắn vào người được bảo lãnh.
7. Người đó tiếp tục bấm **Đăng ký** để nộp đơn Whitelist.
8. Đơn Whitelist cũng có 4 lựa chọn duyệt như trước.

## Cơ chế mã bảo lãnh

- Chỉ người đang có role được cấu hình tại `WHITELIST_ROLE_ID` mới lấy được mã bằng nút.
- Mỗi mã tự lấy mặc định dùng được cho **1 người**.
- Khi mã đã dùng hết, chủ mã bấm lại sẽ nhận mã mới.
- Mỗi lần người chơi bấm lấy mã, bot gửi log ngay.
- Nếu chưa cấu hình kênh log riêng, log bảo lãnh sẽ dùng `WHITELIST_LOG_CHANNEL_ID`; nếu vẫn trống thì gửi vào `WHITELIST_REVIEW_CHANNEL_ID`.
- Người nhập mã phải chờ staff duyệt bảo lãnh trước khi nộp đơn có bảo lãnh.
- Khi duyệt xong, bot DM kết quả cho cả người bảo lãnh và người được bảo lãnh.

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

Role bot phải nằm cao hơn role Whitelist và role chưa xác thực.

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
GUARANTOR_SELF_MAX_USES=1

SERVER_NAME=VENUS WORLD
TIMEZONE=Asia/Ho_Chi_Minh
ACCENT_COLOR=E17ED6
REQUIRE_VERIFICATION=true
MIN_ACCOUNT_AGE_DAYS=0
MIN_JOIN_AGE_MINUTES=0
DATABASE_PATH=data/whitelist.db
WHITELIST_BANNER_PATH=assets/whitelist_banner.png
```

`GUARANTOR_LOG_CHANNEL_ID` có thể để trống. `GUARANTOR_SELF_MAX_USES=1` nghĩa là mỗi mã tự lấy bảo lãnh được một người.

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
