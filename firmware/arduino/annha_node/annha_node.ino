/*
 * ============================================================================
 * ANNHA SMART NODE FIRMWARE - ARDUINO UNO / NANO (ATmega328P)
 * ============================================================================
 * Nhiệm vụ:
 *   1. Điều khiển mượt 2 động cơ Servo Pan-Tilt (Non-blocking, Lazy-attach,
 *      giới hạn góc cơ khí an toàn [Pan 30..150, Tilt 45..135]).
 *   2. Đọc cảm biến nhiệt độ & độ ẩm DHT11 (chân D2) và khí gas MQ-2 (chân A0).
 *   3. Phát định kỳ dữ liệu JSON qua cổng USB Serial (115200 baud) lên Pi 4:
 *        {"temp":28.5,"hum":65.0,"gas":180,"gas_warmup":0}
 *      (Nếu cảm biến lỗi/tuột dây -> trả null thay vì 0 để tránh báo giả).
 *
 * Tập lệnh điều khiển từ Raspberry Pi 4 -> Arduino (kết thúc bằng '\n'):
 *   - PAN <angle>          : Quay trục ngang tới góc tuyệt đối [30..150]
 *   - TILT <angle>         : Quay trục dọc tới góc tuyệt đối [45..135]
 *   - BOTH <pan> <tilt>    : Quay đồng thời cả 2 trục
 *   - SERVO:<pan>,<tilt>   : Cú pháp rút gọn tương đương BOTH <pan> <tilt>
 *   - MOVE <dpan> <dtilt>  : Quay tương đối theo độ lệch (dùng cho Tracking/PTZ)
 *   - CENTER               : Đưa camera về chính giữa (90, 90)
 *   - DETACH               : Ngắt xung giữ PWM (tắt tiếng kêu servo khi khóa/ngủ)
 *   - STATUS               : Truy vấn góc hiện tại và trạng thái chuyển động
 *   - SENSORS              : Yêu cầu gửi ngay 1 gói JSON cảm biến
 *   - PING                 : Kiểm tra kết nối (trả về PONG)
 *   - HELP                 : In hướng dẫn tập lệnh
 * ============================================================================
 */

#include <Arduino.h>
#include <DHT.h>
#include <Servo.h>
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "config.h"

static Servo panServo;
static Servo tiltServo;
static DHT dht(Config::DHT_PIN, Config::DHT_TYPE);

static int panCurrent = Config::PAN_CENTER;
static int tiltCurrent = Config::TILT_CENTER;
static int panTarget = Config::PAN_CENTER;
static int tiltTarget = Config::TILT_CENTER;
static bool outputsEnabled = false;

static unsigned long bootMs = 0;
static unsigned long lastStepMs = 0;
static unsigned long lastSensorMs = 0;

static float cachedTemp = NAN;
static float cachedHum = NAN;
static bool hasReadDhtOnce = false;

static char lineBuffer[Config::SERIAL_BUFFER_SIZE];
static size_t lineLength = 0;
static bool discardLine = false;

static void setupServos() {
  // Preload góc trung tâm, chưa xuất xung PWM khi mới cắm nguồn để chống giật servo.
  panServo.write(Config::PAN_CENTER);
  tiltServo.write(Config::TILT_CENTER);
  lastStepMs = millis();
}

bool setTargetAngles(int pan, int tilt) {
  if (pan < Config::PAN_MIN || pan > Config::PAN_MAX ||
      tilt < Config::TILT_MIN || tilt > Config::TILT_MAX) {
    return false;
  }
  if (!outputsEnabled) {
    panServo.attach(Config::PAN_PIN);
    tiltServo.attach(Config::TILT_PIN);
    outputsEnabled = true;
    lastStepMs = millis();
  }
  panTarget = pan;
  tiltTarget = tilt;
  return true;
}

void detachServos() {
  if (outputsEnabled) {
    panServo.detach();
    tiltServo.detach();
    outputsEnabled = false;
  }
  panTarget = panCurrent;
  tiltTarget = tiltCurrent;
}

bool moveRelative(long deltaPan, long deltaTilt) {
  if (deltaPan < Config::PAN_MIN - panTarget ||
      deltaPan > Config::PAN_MAX - panTarget ||
      deltaTilt < Config::TILT_MIN - tiltTarget ||
      deltaTilt > Config::TILT_MAX - tiltTarget) {
    return false;
  }
  return setTargetAngles(static_cast<int>(panTarget + deltaPan),
                         static_cast<int>(tiltTarget + deltaTilt));
}

void stepServo(Servo& servo, int& current, int target) {
  if (current == target) return;
  const int remaining = abs(target - current);
  const int step = remaining < Config::SERVO_STEP_DEGREES
                       ? remaining
                       : Config::SERVO_STEP_DEGREES;
  current += target > current ? step : -step;
  servo.write(current);
}

bool isServoMoving() {
  return outputsEnabled && (panCurrent != panTarget || tiltCurrent != tiltTarget);
}

void updateServos() {
  const unsigned long now = millis();
  if (!outputsEnabled || now - lastStepMs < Config::SERVO_STEP_INTERVAL_MS) return;
  lastStepMs = now;
  stepServo(panServo, panCurrent, panTarget);
  stepServo(tiltServo, tiltCurrent, tiltTarget);
}

void sendStatus() {
  Serial.print(F("STATUS PAN=")); Serial.print(panCurrent);
  Serial.print(F(" TILT=")); Serial.print(tiltCurrent);
  Serial.print(F(" TARGET_PAN=")); Serial.print(panTarget);
  Serial.print(F(" TARGET_TILT=")); Serial.print(tiltTarget);
  Serial.print(F(" ENABLED=")); Serial.print(outputsEnabled ? 1 : 0);
  Serial.print(F(" MOVING="));
  Serial.println(isServoMoving() ? 1 : 0);
}

int readMq2Filtered() {
  // Đọc trung bình 4 mẫu liên tiếp (~0.4ms, không khóa ngắt) giúp lọc nhiễu ADC.
  long sum = 0;
  for (uint8_t i = 0; i < 4; ++i) {
    sum += analogRead(Config::MQ2_PIN);
  }
  return static_cast<int>(sum / 4);
}

void readAndPrintSensors(bool refreshDht) {
  if (refreshDht || !hasReadDhtOnce) {
    cachedHum = dht.readHumidity();
    cachedTemp = dht.readTemperature();
    hasReadDhtOnce = true;
  }
  const int gasAdc = readMq2Filtered();
  const bool warmingUp = (millis() - bootMs) < Config::MQ2_WARMUP_MS;

  Serial.print(F("{\"temp\":"));
  if (isnan(cachedTemp)) {
    Serial.print(F("null"));
  } else {
    Serial.print(cachedTemp, 1);
  }

  Serial.print(F(",\"hum\":"));
  if (isnan(cachedHum)) {
    Serial.print(F("null"));
  } else {
    Serial.print(cachedHum, 1);
  }

  Serial.print(F(",\"gas\":"));
  Serial.print(gasAdc);

  Serial.print(F(",\"gas_warmup\":"));
  Serial.print(warmingUp ? 1 : 0);

  Serial.print(F(",\"pan\":"));
  Serial.print(panCurrent);

  Serial.print(F(",\"tilt\":"));
  Serial.print(tiltCurrent);

  Serial.println('}');
}

void updateSensors() {
  const unsigned long now = millis();
  const unsigned long elapsed = now - lastSensorMs;
  if (elapsed < Config::SENSOR_INTERVAL_MS) return;

  // Nếu servo đang bước dở, hoãn đọc 1-wire DHT11 tối đa 600ms để xung PWM mượt tuyệt đối.
  if (isServoMoving() && elapsed < (Config::SENSOR_INTERVAL_MS + Config::SENSOR_MAX_DEFER_MS)) {
    return;
  }
  lastSensorMs = now;
  readAndPrintSensors(true);
}

bool parseInteger(const char* token, long& value) {
  if (!token || !*token) return false;
  const char* p = token;
  if (*p == '+' || *p == '-') ++p;
  if (!*p) return false;
  for (; *p; ++p) {
    if (*p < '0' || *p > '9') return false;
  }
  errno = 0;
  char* end;
  value = strtol(token, &end, 10);
  return errno != ERANGE && *end == '\0';
}

void processCommand(const char* command) {
  char copy[Config::SERIAL_BUFFER_SIZE];
  if (strlen(command) >= sizeof(copy)) {
    Serial.println(F("ERR INVALID_COMMAND"));
    return;
  }
  strcpy(copy, command);

  // Hỗ trợ cú pháp "SERVO:pan,tilt" đã thống nhất trong giao thức Edge Pi 4
  if (strncmp(copy, "SERVO:", 6) == 0) {
    char* state = nullptr;
    const char* first = strtok_r(copy + 6, ", \t", &state);
    const char* second = strtok_r(nullptr, ", \t", &state);
    const char* extra = strtok_r(nullptr, ", \t", &state);
    long p = 0, t = 0;
    if (!first || !second || extra || !parseInteger(first, p) || !parseInteger(second, t)) {
      Serial.println(F("ERR INVALID_ANGLE"));
      return;
    }
    if (!setTargetAngles(static_cast<int>(p), static_cast<int>(t))) {
      Serial.println(F("ERR OUT_OF_RANGE"));
      return;
    }
    Serial.print(F("OK SERVO "));
    Serial.print(p);
    Serial.print(' ');
    Serial.println(t);
    return;
  }

  char* state = nullptr;
  const char* name = strtok_r(copy, " \t", &state);
  if (!name) return;
  const char* first = strtok_r(nullptr, " \t", &state);
  const char* second = strtok_r(nullptr, " \t", &state);
  const char* extra = strtok_r(nullptr, " \t", &state);

  const bool pan = strcmp(name, "PAN") == 0;
  const bool tilt = strcmp(name, "TILT") == 0;
  const bool both = strcmp(name, "BOTH") == 0;
  const bool move = strcmp(name, "MOVE") == 0;

  if (pan || tilt || both || move) {
    const bool two = both || move;
    if (!first || (two ? !second : second != nullptr) || extra) {
      Serial.println(F("ERR INVALID_COMMAND"));
      return;
    }
    long a = 0, b = 0;
    if (!parseInteger(first, a) || (two && !parseInteger(second, b))) {
      Serial.println(F("ERR INVALID_ANGLE"));
      return;
    }
    bool accepted = false;
    if (move) {
      accepted = moveRelative(a, b);
    } else {
      const long p = pan || both ? a : panTarget;
      const long t = tilt ? a : (both ? b : tiltTarget);
      if (p >= Config::PAN_MIN && p <= Config::PAN_MAX &&
          t >= Config::TILT_MIN && t <= Config::TILT_MAX) {
        accepted = setTargetAngles(static_cast<int>(p), static_cast<int>(t));
      }
    }
    if (!accepted) {
      Serial.println(F("ERR OUT_OF_RANGE"));
      return;
    }
    Serial.print(F("OK "));
    Serial.print(name);
    Serial.print(' ');
    Serial.print(a);
    if (two) {
      Serial.print(' ');
      Serial.print(b);
    }
    Serial.println();
    return;
  }

  if (first) {
    Serial.println(F("ERR INVALID_COMMAND"));
    return;
  }

  if (strcmp(name, "CENTER") == 0) {
    setTargetAngles(Config::PAN_CENTER, Config::TILT_CENTER);
    Serial.println(F("OK CENTER"));
  } else if (strcmp(name, "DETACH") == 0) {
    detachServos();
    Serial.println(F("OK DETACH"));
  } else if (strcmp(name, "STATUS") == 0) {
    sendStatus();
  } else if (strcmp(name, "SENSORS") == 0) {
    readAndPrintSensors(false);
  } else if (strcmp(name, "PING") == 0) {
    Serial.println(F("PONG"));
  } else if (strcmp(name, "HELP") == 0) {
    Serial.println(F("HELP PAN n | TILT n | BOTH p t | SERVO:p,t | MOVE dp dt | CENTER | DETACH | STATUS | SENSORS | PING | HELP"));
  } else {
    Serial.println(F("ERR INVALID_COMMAND"));
  }
}

void handleSerial() {
  for (uint8_t count = 0;
       count < Config::SERIAL_BYTES_PER_LOOP && Serial.available() > 0; ++count) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n') {
      if (discardLine) {
        Serial.println(F("ERR INVALID_COMMAND"));
      } else {
        if (lineLength && lineBuffer[lineLength - 1] == '\r') --lineLength;
        lineBuffer[lineLength] = '\0';
        processCommand(lineBuffer);
      }
      lineLength = 0;
      discardLine = false;
    } else if (!discardLine) {
      if (lineLength >= sizeof(lineBuffer) - 1 ||
          (c != '\t' && c != '\r' && (c < ' ' || c > '~'))) {
        discardLine = true;
      } else {
        lineBuffer[lineLength++] = c;
      }
    }
  }
}

void setup() {
  Serial.begin(Config::SERIAL_BAUD_RATE);
  bootMs = millis();
  lastSensorMs = bootMs;
  pinMode(Config::MQ2_PIN, INPUT);
  dht.begin();
  setupServos();
  Serial.println(F("READY"));
}

void loop() {
  updateServos();
  handleSerial();
  updateSensors();
}
