#include "WiFiS3.h"
#include <ArduinoHttpClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include "MAX30100_PulseOximeter.h"
#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"

// --- CONFIG ---
char ssid[] = "GalaxyA36";
char pass[] = "ishan1234";
char server_ip[] = "10.87.215.5";
int port = 5000;

// --- OBJECTS ---
PulseOximeter pox;
OneWire oneWire(2); 
DallasTemperature tempSensor(&oneWire);
ArduinoLEDMatrix matrix;
WiFiClient wifi;
HttpClient client = HttpClient(wifi, server_ip, port);

float currentTemp = 0, currentHR = 0, currentSpO2 = 0;
unsigned long lastSend = 0;

void scrollMessage(String msg) {
  matrix.beginDraw();
  matrix.stroke(0xFFFFFFFF);
  matrix.textScrollSpeed(50);
  matrix.textFont(Font_5x7);
  matrix.beginText(0, 1, 0xFFFFFF);
  matrix.println(msg);
  matrix.endText(SCROLL_LEFT);
  matrix.endDraw();
}

void setup() {
  Serial.begin(115200);
  matrix.begin();
  tempSensor.begin();
  
  scrollMessage("WIFI...");
  Serial.println("Connecting to WiFi...");

  WiFi.begin(ssid, pass);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");

  Serial.println("Initializing MAX30100...");
  if (!pox.begin()) { 
    Serial.println("MAX30100 ERROR: Wiring or I2C issue!"); 
    scrollMessage("SENSOR ERROR");
    while(1); // STUCK HERE IF SENSOR WIRING IS WRONG
  }
  pox.setIRLedCurrent(MAX30100_LED_CURR_7_6MA);

  Serial.println("Sensors Ready. Starting loop.");
  scrollMessage("Ready");
}

void loop() {
  pox.update(); // CRITICAL: Must be called constantly

  if (millis() - lastSend > 1000) {
    tempSensor.requestTemperatures();
    currentTemp = tempSensor.getTempCByIndex(0);
    currentHR = pox.getHeartRate();
    currentSpO2 = pox.getSpO2();

    String postData = "{\"hr\":" + String(currentHR) + ",\"spo2\":" + String(currentSpO2) + ",\"temp\":" + String(currentTemp) + "}";
    
    // Print what we are sending to the Serial Monitor
    Serial.println("Sending: " + postData);

    // Robust POST syntax
    client.beginRequest();
    client.post("/data");
    client.sendHeader("Content-Type", "application/json");
    client.sendHeader("Content-Length", postData.length());
    client.beginBody();
    client.print(postData);
    client.endRequest();
    
    // Read the server's response code
    int statusCode = client.responseStatusCode();
    Serial.print("Server Response Code: ");
    Serial.println(statusCode);

    if (statusCode == 200) {
       String response = client.responseBody();
       if(response.length() > 2) {
         scrollMessage(response);
       }
    } else {
       Serial.println("Failed to reach Flask Server (Check Firewall or IP)");
    }
    lastSend = millis();
  }
}