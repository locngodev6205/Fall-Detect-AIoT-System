#include <Servo.h>

// Match AnNhà wiring. Use a separate 5 V servo supply and share GND with Uno.
constexpr byte PAN_PIN = 9;
constexpr byte TILT_PIN = 10;
constexpr int CENTER = 90;
constexpr int TEST_MIN = 85;
constexpr int TEST_MAX = 95;
constexpr unsigned long STEP_MS = 20;
constexpr unsigned long HOLD_MS = 650;

Servo pan;
Servo tilt;

void showHelp() {
  Serial.println(F("P: test Pan D9 | T: test Tilt D10 | ?: help"));
}

void moveTo(Servo& servo, int& angle, int target) {
  while (angle != target) {
    angle += target > angle ? 1 : -1;
    servo.write(angle);
    delay(STEP_MS);
  }
  Serial.print(F("Angle command: "));
  Serial.println(angle);
  delay(HOLD_MS);
}

void testAxis(Servo& servo, byte pin, const __FlashStringHelper* axis) {
  Serial.print(F("Testing "));
  Serial.println(axis);
  int angle = CENTER;
  servo.attach(pin);
  servo.write(angle);
  delay(HOLD_MS);

  moveTo(servo, angle, TEST_MIN);
  moveTo(servo, angle, TEST_MAX);
  moveTo(servo, angle, CENTER);
  servo.detach();
  // Drop input entered during the sweep to avoid triggering queued motion.
  while (Serial.available()) Serial.read();
  Serial.println(F("Done. PWM detached."));
}

void setup() {
  Serial.begin(115200);
  showHelp();
}

void loop() {
  if (!Serial.available()) return;
  const char command = Serial.read();
  switch (command) {
    case 'p':
    case 'P':
      testAxis(pan, PAN_PIN, F("Pan"));
      break;
    case 't':
    case 'T':
      testAxis(tilt, TILT_PIN, F("Tilt"));
      break;
    case '\r':
    case '\n':
      break;
    default:
      showHelp();
  }
}
