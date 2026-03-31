#include <Wire.h>
#include "MAX30105.h"
#include "spo2_algorithm.h"
#include "WiFiS3.h"
#include <ArduinoHttpClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// 🔥 FIX: Include Graphics BEFORE the Matrix library
#include <ArduinoGraphics.h> 
#include <Arduino_LED_Matrix.h>
ArduinoLEDMatrix matrix;

// WIFI
char ssid[] = "GalaxyA36";
char pass[] = "ishan1234";
char server_ip[] = "10.172.176.5";   // ✅ YOUR LAPTOP IP
int port = 5000;

// OBJECTS
MAX30105 particleSensor;
OneWire oneWire(4);
DallasTemperature tempSensor(&oneWire);
WiFiClient wifi;
HttpClient client(wifi, server_ip, port);

// DATA
uint32_t irBuffer[80];
uint32_t redBuffer[80];
int32_t bufferLength = 80;
int32_t spo2;
int8_t validSPO2;
int32_t heartRate;
int8_t validHeartRate;

unsigned long lastSend = 0;
bool sensorReady = false;

void displayText(String msg) {
  matrix.beginDraw();
  matrix.stroke(0xFFFFFF);
  matrix.textFont(Font_5x7);        // ← was missing
  matrix.textScrollSpeed(80);        // ← was missing
  matrix.clear();
  matrix.beginText(0, 1, 0xFFFFFF);
  matrix.print(msg.c_str());
  matrix.endText(SCROLL_LEFT);
  matrix.endDraw();

  // Block until scroll completes before next sensor cycle
  delay(msg.length() * 200 + 1000);
}

void setup() {
  Serial.begin(115200);
  matrix.begin();          // ← move here, FIRST
  displayText("Starting.......");
  Wire.begin();
  delay(500);
  Wire.setClock(100000);

  Serial.println("Booting system...");

  tempSensor.begin();
  tempSensor.setWaitForConversion(false);

  Serial.println("Connecting WiFi...");
  WiFi.begin(ssid, pass);

  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\nWiFi OK");
  
  client.setTimeout(3000);

  Serial.println("System ready, initializing SPO2 in loop...");
}

void loop() {

  if (!sensorReady) {
    Serial.println("Trying SPO2 init...");

    if (particleSensor.begin(Wire, I2C_SPEED_STANDARD)) {
      delay(800);
      particleSensor.setup(60, 4, 2, 100, 411, 4096);
      sensorReady = true;
      Serial.println("✅ SPO2 READY");

      for (byte i = 0 ; i < bufferLength ; i++) {
        while (!particleSensor.available()) particleSensor.check();
        redBuffer[i] = particleSensor.getRed();
        irBuffer[i] = particleSensor.getIR();
        particleSensor.nextSample();
      }

    } else {
      Serial.println("❌ SPO2 FAIL → retrying...");
      delay(2000);
      return;
    }
  }

  for (byte i = 20; i < bufferLength; i++) {
    redBuffer[i - 20] = redBuffer[i];
    irBuffer[i - 20] = irBuffer[i];
  }

  byte count = 0;
  while (count < 20) {
    particleSensor.check();

    if (particleSensor.available()) {
      redBuffer[bufferLength - 20 + count] = particleSensor.getRed();
      irBuffer[bufferLength - 20 + count] = particleSensor.getIR();
      particleSensor.nextSample();
      count++;
    }
  }

  maxim_heart_rate_and_oxygen_saturation(
    irBuffer, bufferLength, redBuffer,
    &spo2, &validSPO2, &heartRate, &validHeartRate
  );

  int sendHR = (validHeartRate && heartRate > 30) ? heartRate : 0;
  int sendSpO2 = (validSPO2 && spo2 > 50) ? spo2 : 0;

  Serial.print("HR: "); Serial.print(sendHR);
  Serial.print(" | SPO2: "); Serial.println(sendSpO2);

  tempSensor.requestTemperatures();
  delay(75);
  float temp = tempSensor.getTempCByIndex(0);

  Serial.print("Temp: ");
  Serial.println(temp);

  // =====================
  // 🔥 SEND TO SERVER
  // =====================

  if (millis() - lastSend > 3000) {

    String postData = "{\"hr\":" + String(sendHR) +
                      ",\"spo2\":" + String(sendSpO2) +
                      ",\"temp\":" + String(temp) + "}";

    Serial.println("Sending: " + postData);

    client.beginRequest();
    client.post("/data");
    client.sendHeader("Content-Type", "application/json");
    client.sendHeader("Content-Length", postData.length());
    client.beginBody();
    client.print(postData);
    client.endRequest();

    int status = client.responseStatusCode();

    if (status > 0) {
      Serial.print("Server: ");
      Serial.println(status);

      // 🔥 NEW: READ RESPONSE FROM BACKEND
      String response = client.responseBody();

      Serial.println("DISPLAY: " + response);
      displayText(response);

      // 👉 IF USING LED MATRIX:
      // scrollMessage(response);

    } else {
      Serial.println("⚠️ Server timeout, continuing...");
    }

    client.stop();
    lastSend = millis();
  }
}