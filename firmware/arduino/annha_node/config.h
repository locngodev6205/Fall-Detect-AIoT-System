#pragma once

#include <Arduino.h>

namespace Config {
// --- Chân cắm Động cơ Servo Pan-Tilt (PWM) ---
constexpr uint8_t PAN_PIN = 7;
constexpr uint8_t TILT_PIN = 8;

// Giới hạn góc cơ khí an toàn (độ) - Bảo vệ cáp camera & khớp nhựa
constexpr int PAN_MIN = 30;
constexpr int PAN_CENTER = 90;
constexpr int PAN_MAX = 150;

constexpr int TILT_MIN = 45;
constexpr int TILT_CENTER = 90;
constexpr int TILT_MAX = 135;

// Tốc độ bước dịch chuyển mượt: 1 độ mỗi 20ms (~50 độ/giây)
constexpr uint8_t SERVO_STEP_DEGREES = 1;
constexpr unsigned long SERVO_STEP_INTERVAL_MS = 20;

// --- Chân cắm Cảm biến Môi trường ---
constexpr uint8_t DHT_PIN = 2;          // Chân Digital D2 nối chân DATA của DHT11
constexpr uint8_t DHT_TYPE = 11;        // Cảm biến DHT11
constexpr uint8_t MQ2_PIN = A0;         // Chân Analog A0 nối chân A0 của MQ-2 (0..1023)

// Chu kỳ đọc & gửi dữ liệu cảm biến (ms) - DHT11 yêu cầu tối thiểu >= 2000ms
constexpr unsigned long SENSOR_INTERVAL_MS = 2000;
// Thời gian tối đa hoãn đọc DHT11 khi servo đang quay để chống rung xung PWM
constexpr unsigned long SENSOR_MAX_DEFER_MS = 600;
// Thời gian làm nóng điện trở nhiệt của cảm biến khí gas MQ-2 sau khi cấp nguồn (ms)
constexpr unsigned long MQ2_WARMUP_MS = 20000;

// --- Giao tiếp USB Serial với Raspberry Pi 4 ---
constexpr unsigned long SERIAL_BAUD_RATE = 115200;
constexpr size_t SERIAL_BUFFER_SIZE = 64;
constexpr uint8_t SERIAL_BYTES_PER_LOOP = 32;

static_assert(PAN_MIN >= 0 && PAN_MAX <= 180 &&
                  PAN_MIN <= PAN_CENTER && PAN_CENTER <= PAN_MAX,
              "Pan limits must contain the center and be within 0..180");
static_assert(TILT_MIN >= 0 && TILT_MAX <= 180 &&
                  TILT_MIN <= TILT_CENTER && TILT_CENTER <= TILT_MAX,
              "Tilt limits must contain the center and be within 0..180");
static_assert(SERVO_STEP_DEGREES > 0 && SERVO_STEP_INTERVAL_MS > 0,
              "Servo step and interval must be positive");
static_assert(SERIAL_BUFFER_SIZE >= 2 && SERIAL_BYTES_PER_LOOP > 0,
              "Serial buffer and read budget must be positive");
}  // namespace Config
