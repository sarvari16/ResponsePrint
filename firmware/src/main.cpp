// ResponsePrint ESP32-CAM firmware (Arduino framework, esp32-camera driver).
//
// Endpoints
//   GET /         small HTML preview page
//   GET /capture  one JPEG frame (Content-Type: image/jpeg)
//   GET /status   JSON: board, sensor, frame size, PSRAM, heap, counters
//   GET /config   change settings: ?framesize=qqvga|qvga|vga &quality=10..40 &lock=0|1
//
// What this firmware does NOT do (deliberately, until validated on hardware):
//   - no precise capture timestamps (X-Uptime-Ms is a coarse millis() value, not validated)
//   - no strobe / flash triggering (the flash LED is only held LOW = off)
//   - no high-speed or equivalent-time reconstruction
// The laptop timestamps frames on arrival; see app/camera_client.py.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"
#include "camera_pins.h"

#if __has_include("secrets.h")
  #include "secrets.h"
#else
  #error "Missing include/secrets.h - copy include/secrets.example.h to include/secrets.h"
#endif

WebServer server(80);

static bool cameraReady = false;
static uint32_t captureCount = 0;
static uint32_t captureFailures = 0;
static uint32_t lastCaptureMs = 0;     // duration of the last esp_camera_fb_get() call
static bool exposureLocked = false;

static const char *frameSizeName(framesize_t fs) {
  switch (fs) {
    case FRAMESIZE_QQVGA: return "QQVGA 160x120";
    case FRAMESIZE_QVGA:  return "QVGA 320x240";
    case FRAMESIZE_VGA:   return "VGA 640x480";
    default:              return "other";
  }
}

static bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;  c.pin_d2 = Y4_GPIO_NUM;
  c.pin_d3 = Y5_GPIO_NUM;  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;       // JPEG keeps transfers small; driver recommends it
  c.frame_size = FRAMESIZE_QVGA;         // 320x240: enough for a tip marker, light on memory
  c.jpeg_quality = 12;                   // 10-63, lower = better quality / bigger file

  if (psramFound()) {
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;
    c.grab_mode = CAMERA_GRAB_LATEST;    // /capture returns the freshest frame
  } else {
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
    c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x (check pin map, power supply, ribbon cable)\n", err);
    return false;
  }
  return true;
}

static void addCommonHeaders() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Cache-Control", "no-store");
}

static void handleCapture() {
  if (!cameraReady) {
    addCommonHeaders();
    server.send(503, "application/json", "{\"error\":\"camera not initialised\"}");
    return;
  }
  uint32_t t0 = millis();
  camera_fb_t *fb = esp_camera_fb_get();
  lastCaptureMs = millis() - t0;
  if (!fb) {
    captureFailures++;
    addCommonHeaders();
    server.send(500, "application/json", "{\"error\":\"capture failed\"}");
    return;
  }
  if (fb->format != PIXFORMAT_JPEG) {    // should not happen with the config above
    esp_camera_fb_return(fb);
    captureFailures++;
    addCommonHeaders();
    server.send(500, "application/json", "{\"error\":\"frame is not JPEG\"}");
    return;
  }
  captureCount++;
  addCommonHeaders();
  server.sendHeader("X-Frame-Index", String(captureCount));
  server.sendHeader("X-Uptime-Ms", String(millis()));   // coarse, NOT a validated timestamp
  server.send_P(200, "image/jpeg", (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

static void handleStatus() {
  sensor_t *s = cameraReady ? esp_camera_sensor_get() : nullptr;
  String j = "{";
  j += "\"board\":\"" BOARD_NAME "\",";
  j += "\"camera_ready\":" + String(cameraReady ? "true" : "false") + ",";
  if (s) {
    j += "\"sensor_pid\":\"0x" + String(s->id.PID, HEX) + "\",";
    j += "\"frame_size\":\"" + String(frameSizeName(s->status.framesize)) + "\",";
    j += "\"jpeg_quality\":" + String(s->status.quality) + ",";
  }
  j += "\"exposure_locked\":" + String(exposureLocked ? "true" : "false") + ",";
  j += "\"psram\":" + String(psramFound() ? "true" : "false") + ",";
  j += "\"free_heap\":" + String(ESP.getFreeHeap()) + ",";
  j += "\"free_psram\":" + String(ESP.getFreePsram()) + ",";
  j += "\"captures\":" + String(captureCount) + ",";
  j += "\"capture_failures\":" + String(captureFailures) + ",";
  j += "\"last_fb_get_ms\":" + String(lastCaptureMs) + ",";
  j += "\"uptime_ms\":" + String(millis()) + ",";
  j += "\"rssi_dbm\":" + String(WiFi.RSSI()) + ",";
  j += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  j += "\"timestamps\":\"not provided - laptop timestamps frames on arrival\",";
  j += "\"strobe\":\"not implemented\"";
  j += "}";
  addCommonHeaders();
  server.send(200, "application/json", j);
}

static void handleConfig() {
  sensor_t *s = esp_camera_sensor_get();
  if (!s) {
    server.send(503, "application/json", "{\"error\":\"camera not initialised\"}");
    return;
  }
  if (server.hasArg("framesize")) {
    String f = server.arg("framesize");
    if (f == "qqvga") s->set_framesize(s, FRAMESIZE_QQVGA);
    else if (f == "qvga") s->set_framesize(s, FRAMESIZE_QVGA);
    else if (f == "vga") s->set_framesize(s, FRAMESIZE_VGA);
    else { server.send(400, "application/json", "{\"error\":\"framesize: qqvga|qvga|vga\"}"); return; }
  }
  if (server.hasArg("quality")) {
    int q = constrain(server.arg("quality").toInt(), 10, 40);
    s->set_quality(s, q);
  }
  if (server.hasArg("lock")) {
    // Lock = turn off auto exposure and auto gain so brightness stays constant between
    // frames. Set it AFTER the scene is lit as it will be during the recording.
    exposureLocked = server.arg("lock") == "1";
    s->set_exposure_ctrl(s, exposureLocked ? 0 : 1);
    s->set_gain_ctrl(s, exposureLocked ? 0 : 1);
  }
  handleStatus();
}

static void handleRoot() {
  addCommonHeaders();
  server.send(200, "text/html",
    "<!doctype html><meta name=viewport content='width=device-width'>"
    "<title>ResponsePrint cam</title><body style='font-family:sans-serif'>"
    "<h3>ResponsePrint ESP32-CAM</h3><img id=i src='/capture' width=320><br>"
    "<button onclick=\"i.src='/capture?'+Date.now()\">refresh</button> "
    "<a href='/status'>/status</a></body>");
}

static void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_HOSTNAME);
  WiFi.setSleep(false);                  // lower, steadier latency
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to %s", WIFI_SSID);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(300);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nConnected. Open http://%s/  (put this in config.yaml camera.base_url)\n",
                  WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\nWi-Fi connection failed - check secrets.h; retrying in loop()");
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
#if FLASH_LED_GPIO >= 0
  pinMode(FLASH_LED_GPIO, OUTPUT);
  digitalWrite(FLASH_LED_GPIO, LOW);     // keep the flash LED off; no strobe in this version
#endif
  Serial.printf("\nResponsePrint firmware - board: %s, PSRAM: %s\n", BOARD_NAME,
                psramFound() ? "yes" : "NO (expect low frame sizes only)");
  cameraReady = initCamera();
  connectWiFi();
  server.on("/", handleRoot);
  server.on("/capture", handleCapture);
  server.on("/status", handleStatus);
  server.on("/config", handleConfig);
  server.onNotFound([]() { server.send(404, "text/plain", "not found"); });
  server.begin();
}

void loop() {
  server.handleClient();
  static uint32_t lastCheck = 0;
  if (millis() - lastCheck > 5000) {
    lastCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("Wi-Fi lost, reconnecting...");
      WiFi.reconnect();
    }
  }
}
