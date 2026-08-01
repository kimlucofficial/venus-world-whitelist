# Venus World Whitelist Bot 🎟️

Bot whitelist riêng, tách hoàn toàn khỏi bot welcome hiện tại.

## Luồng hoạt động

1. Staff dùng `/whitelist_panel` để gửi bảng đăng ký.
2. Người chơi bấm **Xác thực tài khoản**.
3. Có mã bảo lãnh thì bấm **Nhập mã bảo lãnh**.
4. Bấm **Đăng ký** và trả lời tối đa 5 câu hỏi.
5. Đơn được gửi vào kênh staff với 4 lựa chọn:
   - **Đồng ý**
   - **Từ chối**
   - **Đồng ý + lý do**
   - **Từ chối + lý do**
6. Khi đồng ý, bot tự cấp role whitelist và gửi kết quả qua DM.

Dữ liệu đơn, trạng thái xác thực và mã bảo lãnh được lưu bằng SQLite trong `data/whitelist.db`. Nút panel và nút xét duyệt vẫn hoạt động sau khi bot restart.

## Cài đặt

### 1. Discord Developer Portal

Bật **Server Members Intent** cho bot.

Quyền bot cần có:

- View Channels
- Send Messages
- Embed Links
- Attach Files
- Read Message History
- Manage Roles
- Use Application Commands

Đặt role của bot cao hơn role whitelist và role chưa xác thực.

### 2. Variables

Copy `.env.example` thành `.env`, sau đó điền:

```env
DISCORD_TOKEN=TOKEN_MOI
TEST_GUILD_ID=ID_SERVER
WHITELIST_REVIEW_CHANNEL_ID=ID_KENH_NHAN_DON
WHITELIST_ROLE_ID=ID_ROLE_WHITELIST
WHITELIST_REVIEWER_ROLE_ID=ID_ROLE_STAFF
UNVERIFIED_ROLE_ID=ID_ROLE_CHUA_XAC_THUC
WHITELIST_LOG_CHANNEL_ID=ID_KENH_LOG
```

Không đưa token thật lên GitHub.

### 3. Chạy trên Windows VPS

Chạy lần lượt:

```text
setup.bat
start.bat
```

### 4. Railway

Upload source lên một GitHub repository riêng, kết nối Railway và thêm Variables giống `.env.example`.

Để dữ liệu đơn không mất khi redeploy, tạo **Railway Volume** và mount vào:

```text
/app/data
```

Giữ `DATABASE_PATH=data/whitelist.db` như mặc định.

## Slash commands

- `/whitelist_panel` — gửi bảng đăng ký.
- `/whitelist_status` — xem trạng thái đơn cá nhân.
- `/whitelist_reset` — reset hồ sơ để nộp lại.
- `/whitelist_code_create` — tạo mã bảo lãnh.
- `/whitelist_code_disable` — tắt mã bảo lãnh.
- `/whitelist_code_list` — xem mã đang có.

## Chỉnh câu hỏi

Sửa `questions.json`. Discord modal chỉ hiển thị tối đa 5 câu trong một lần, vì vậy file phải có từ 1 đến 5 câu.

Mỗi câu có cấu trúc:

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

## Xác thực tài khoản

Nút xác thực trong source này là xác thực Discord-native: người dùng phải tự bấm nút, bot ghi lại Discord ID và có thể kiểm tra tuổi tài khoản/thời gian đã ở server qua hai biến:

```env
MIN_ACCOUNT_AGE_DAYS=0
MIN_JOIN_AGE_MINUTES=0
```

Source không dùng website OAuth, webhook lạ, lệnh tải code từ xa, `eval` hoặc token hard-code.
