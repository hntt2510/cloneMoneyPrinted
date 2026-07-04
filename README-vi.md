# MoneyPrinterTurbo

MoneyPrinterTurbo là công cụ tạo video ngắn tự động. Bạn nhập chủ đề hoặc từ khóa, ứng dụng có thể tạo kịch bản, tìm/tải tư liệu video, tạo phụ đề, thêm nhạc nền và xuất video hoàn chỉnh.

## Chạy nhanh trên Windows

Yêu cầu khuyến nghị:

- Windows 10 trở lên
- Python 3.11
- `uv` để cài dependency nhanh và đúng theo `uv.lock`

Tại thư mục gốc dự án:

```powershell
uv python install 3.11
uv sync --frozen
.\webui.bat
```

Sau khi chạy, mở:

```text
http://127.0.0.1:8501
```

Nếu cổng `8501` bận, `webui.bat` sẽ tự chọn cổng khác trong khoảng `8502-8599` và in địa chỉ ra màn hình.

## Cấu hình bắt buộc

Nếu chưa có `config.toml`, chương trình sẽ tự copy từ `config.example.toml`. Bạn cũng có thể tạo thủ công:

```powershell
Copy-Item config.example.toml config.toml
```

Mở `config.toml` và cấu hình tối thiểu:

- `llm_provider`: nhà cung cấp LLM bạn muốn dùng
- API key tương ứng với provider đó
- `pexels_api_keys`, `pixabay_api_keys` hoặc `coverr_api_keys` nếu dùng nguồn video online

TTS mặc định là Edge TTS, hiển thị trong WebUI là `Azure TTS V1`, không cần API key.

## Chạy API

```powershell
uv run python main.py
```

API docs:

```text
http://127.0.0.1:8080/docs
```

## Chạy bằng CLI

```powershell
uv run python cli.py --video-subject "Vai trò của tiền bạc"
```

Ví dụ dùng tư liệu local:

```powershell
uv run python cli.py --video-subject "Vai trò của tiền bạc" --video-source local --video-materials "1.mp4,2.mp4" --stop-at video
```

## Chạy bằng Docker

Trước khi chạy Docker, đảm bảo có `config.toml` ở thư mục gốc.

```powershell
docker compose -f docker-compose.release.yml up
```

WebUI:

```text
http://127.0.0.1:8501
```

API:

```text
http://127.0.0.1:8080/docs
```

## Ghi chú lỗi thường gặp

- Nếu thiếu FFmpeg, cài FFmpeg hoặc đặt `ffmpeg_path` trong `[app]` của `config.toml`.
- Nếu dùng phụ đề `whisper`, máy sẽ cần tải model từ HuggingFace và chạy chậm hơn `edge`.
- Nếu muốn truy cập WebUI từ máy khác trong cùng mạng LAN, chạy trước:

```powershell
$env:MPT_WEBUI_HOST="0.0.0.0"
.\webui.bat
```
