# Fall-Detect-AIoT-System - Hệ Thống Phát Hiện Té Ngã Thông Minh

Hệ thống phát hiện té ngã tích hợp Trí tuệ Nhân tạo tại biên kết hợp Nền tảng Giám sát Web thời gian thực.

## Cấu trúc Dự án

```
Fall-Detect-AIoT-System/
├── fall_detect/            # [TRỌNG TÂM] Toàn bộ Model, Nhận diện & Huấn luyện
│   ├── models/             # File weights/mô hình (.tflite, .onnx)
│   │   └── fall_detection_transformer.tflite
│   ├── sample_videos/      # Các video tình huống ngã mẫu để kiểm thử
│   │   ├── fall_example_1.mp4
│   │   ├── fall_example_2.mp4
│   │   ├── fall_example_3.mp4
│   │   └── fall_example_4.mp4
│   ├── detect.py           # Script chạy nhận diện té ngã (Webcam hoặc File video)
│   ├── config.py           # Cấu hình tham số mô hình, ngưỡng, cooldown, MQTT
│   ├── .env.example        # Mẫu biến môi trường
│   ├── export_onnx.py      # Tool xuất mô hình sang ONNX
│   ├── notebooks/          # Bộ Jupyter Notebooks huấn luyện Transformer, LSTM, Bi-LSTM
│   ├── utils/              # Tools trích xuất keypoints và tiền xử lý dữ liệu CSV
│   ├── dataset/            # Hướng dẫn tải và tổ chức dataset (URFD / Kaggle)
│   └── requirements.txt    # Thư viện cho module AI (đã kiểm tra tương thích 100%)
│
├── backend/                # Máy chủ Backend API & MQTT Gateway
│   ├── src/main.py         # FastAPI Server + MQTT Subscriber + WebSocket Realtime
│   ├── requirements.txt
│   └── README.md
│
├── frontend/               # Giao diện Web Dashboard Giám Sát (Client App)
│   ├── src/index.html      # Giao diện Web Dashboard nhận cảnh báo thời gian thực
│   └── README.md
│
├── docker/                 # Cấu hình hạ tầng Docker
│   ├── mosquitto/          # Cấu hình Eclipse Mosquitto MQTT Broker
│   └── docker-compose.yml  # Khởi chạy MQTT Broker nhanh
│
├── docs/                   # Tài liệu thiết kế hệ thống
│   ├── ARCHITECTURE.md     # Sơ đồ kiến trúc kết nối
│   └── PROJECT_SPECIFICATION.md # Đặc tả toàn bộ yêu cầu & nghiệp vụ dự án
└── README.md
```

## Bắt đầu Nhanh (Quick Start)

### 1. Kiểm thử Nhận diện Té ngã (Fall Detect)
```bash
cd fall_detect
pip install -r requirements.txt

# Chạy test với video mẫu:
python detect.py --source file --file sample_videos/fall_example_1.mp4

# Hoặc chạy trực tiếp với Webcam:
python detect.py --source webcam
```

### 2. Khởi động MQTT Broker & Backend Server (Khi kết nối với Web)
```bash
# Khởi động MQTT Broker (Tùy chọn)
docker compose up -d

# Khởi động Backend
cd backend
pip install -r requirements.txt
python src/main.py
```

### 3. Mở Web Dashboard
Mở file `frontend/src/index.html` trên trình duyệt để theo dõi cảnh báo trực tiếp!
