// Camera pin maps. Select ONE with a build flag in platformio.ini.
// AI-Thinker is the default because it is the most common ESP32-CAM; verify against
// your board's documentation before assuming it matches.
#pragma once

#if defined(CAMERA_MODEL_AI_THINKER)
  #define BOARD_NAME     "AI-Thinker ESP32-CAM (default pin map)"
  #define PWDN_GPIO_NUM  32
  #define RESET_GPIO_NUM -1
  #define XCLK_GPIO_NUM   0
  #define SIOD_GPIO_NUM  26
  #define SIOC_GPIO_NUM  27
  #define Y9_GPIO_NUM    35
  #define Y8_GPIO_NUM    34
  #define Y7_GPIO_NUM    39
  #define Y6_GPIO_NUM    36
  #define Y5_GPIO_NUM    21
  #define Y4_GPIO_NUM    19
  #define Y3_GPIO_NUM    18
  #define Y2_GPIO_NUM     5
  #define VSYNC_GPIO_NUM 25
  #define HREF_GPIO_NUM  23
  #define PCLK_GPIO_NUM  22
  #define FLASH_LED_GPIO  4    // on-board flash LED; only driven LOW (kept off) here

#elif defined(CAMERA_MODEL_WROVER_KIT)
  #define BOARD_NAME     "ESP-WROVER-KIT"
  #define PWDN_GPIO_NUM  -1
  #define RESET_GPIO_NUM -1
  #define XCLK_GPIO_NUM  21
  #define SIOD_GPIO_NUM  26
  #define SIOC_GPIO_NUM  27
  #define Y9_GPIO_NUM    35
  #define Y8_GPIO_NUM    34
  #define Y7_GPIO_NUM    39
  #define Y6_GPIO_NUM    36
  #define Y5_GPIO_NUM    19
  #define Y4_GPIO_NUM    18
  #define Y3_GPIO_NUM     5
  #define Y2_GPIO_NUM     4
  #define VSYNC_GPIO_NUM 25
  #define HREF_GPIO_NUM  23
  #define PCLK_GPIO_NUM  22
  #define FLASH_LED_GPIO -1

#else
  #error "Select a camera model: add -DCAMERA_MODEL_AI_THINKER (or another) to build_flags"
#endif
