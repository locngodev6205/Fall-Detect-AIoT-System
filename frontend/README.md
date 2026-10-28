# AnNhà frontend

React 19/Vite, giao diện Calm Home, font và hình landing từ ZIP. Các màn hình ứng dụng dùng API backend thật; không dùng localStorage làm nguồn dữ liệu quyền, tài khoản hoặc nghiệp vụ.

```bash
npm ci
npm run dev
npm run build
npm run test:sites
```

Vite chạy ở **127.0.0.1:5188**, `strictPort: true`, proxy `/api` và `/ws` đến backend **8018**. Docker dùng nginx trên **8188** với cùng origin cho cookie/API/media.

`Landing.jsx` giữ nội dung giới thiệu và ảnh minh họa; `App.jsx` quản lý phiên/nhà/navigation. Các nhóm màn hình nằm trong `HomeScreens`, `EventScreens`, `AdminScreens`, `Zones`, `Reminders`, `Auth`. File/font/CSS gốc được giữ. `live.css` mở rộng bố cục màn hình đã nối API.

Chỉ dùng sessionStorage cho nhà đang chọn và đường dẫn quay lại sau đăng nhập. Session thật nằm trong cookie HttpOnly; CSRF lấy từ backend và giữ trong bộ nhớ. Không có tùy chọn tự đổi vai trò hoặc biến dữ liệu mẫu thành thiết bị online.

Camera chỉ báo đang nhận hình sau khi nhận frame thật. Nhấn để nói yêu cầu microphone qua thao tác người dùng và có device audio peer; không có peer thì báo chưa sẵn sàng. Không tự bật microphone hoặc âm thanh khi mở trang.

Bộ đóng gói `worker/`, `scripts/prepare-sites-build.mjs`, `tests/sites-worker.test.mjs`, `.openai/hosting.json` giữ từ ZIP. Chúng chỉ phục vụ gói tĩnh, không thay backend nghiệp vụ hoặc tự publish.
