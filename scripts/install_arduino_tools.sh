#!/usr/bin/env bash
# ==============================================================================
# Cài đặt tự động arduino-cli, core AVR và thư viện cảm biến cho Raspberry Pi 4
# Hỗ trợ nạp trực tiếp firmware Arduino qua cáp USB mà không cần máy tính ngoài.
# ==============================================================================
set -euo pipefail

echo "=== [1/4] Kiểm tra và cài đặt arduino-cli ==="
if ! command -v arduino-cli >/dev/null 2>&1; then
    TMP_DIR="$(mktemp -d)"
    curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$TMP_DIR" sh -s 1.1.1
    sudo install -m 0755 "$TMP_DIR/arduino-cli" /usr/local/bin/arduino-cli
    rm -rf "$TMP_DIR"
    echo "Đã cài đặt arduino-cli tại /usr/local/bin/arduino-cli"
else
    echo "arduino-cli đã được cài sẵn: $(arduino-cli version)"
fi

echo "=== [2/4] Cập nhật chỉ mục và cài đặt gói Arduino AVR (Uno / Nano) ==="
arduino-cli core update-index
arduino-cli core install arduino:avr

echo "=== [3/4] Cài đặt thư viện Servo & DHT11 (Adafruit) ==="
arduino-cli lib install "Servo"
arduino-cli lib install "DHT sensor library"
arduino-cli lib install "Adafruit Unified Sensor"

echo "=== [4/4] Cấp quyền truy cập cổng USB Serial (dialout) ==="
if groups "$USER" | grep -qw dialout; then
    echo "User '$USER' đã nằm trong nhóm dialout."
else
    sudo usermod -aG dialout "$USER"
    echo "Đã thêm '$USER' vào nhóm dialout (đăng xuất/đăng nhập lại nếu báo Permission denied)."
fi

echo ""
echo "HOÀN TẤT! Cách biên dịch & nạp firmware vào Arduino từ Pi 4:"
echo "  - Arduino Nano : arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 firmware/arduino/annha_node -u -p /dev/ttyUSB0"
echo "  - Arduino Uno  : arduino-cli compile --fqbn arduino:avr:uno firmware/arduino/annha_node -u -p /dev/ttyACM0"
