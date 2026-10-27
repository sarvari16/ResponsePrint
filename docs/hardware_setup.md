# Hardware setup

## Parts for the first demonstration

- ESP32-CAM board (AI-Thinker with OV2640 is the assumed default)
- USB programmer: ESP32-CAM-MB base board, or any 3.3 V USB-serial adapter
- 5 V 2 A supply separate from the laptop USB port (weak supplies cause brownouts and camera init failures)
- Steel ruler or hacksaw blade, a vise or two C-clamps on a heavy base
- Printed marker: a solid black dot about 8 to 10 mm across on white paper, glued to the tip
- Steady lighting (a desk lamp is fine; avoid flickering tube lights, they can show up as a spurious frequency)

No second microcontroller or extra sensors are needed for this stage.

## Flashing the firmware

1. Install VS Code and the PlatformIO IDE extension.
2. Open the `firmware` folder in VS Code (File → Open Folder → `ResponsePrint/firmware`).
3. Copy `include/secrets.example.h` to `include/secrets.h` and put in your Wi-Fi name and password. The ESP32 only supports 2.4 GHz Wi-Fi.
4. Check `platformio.ini`. If your board is not AI-Thinker, change `-DCAMERA_MODEL_AI_THINKER` and confirm the pin map in `src/camera_pins.h` against your board's documentation.
5. Connect the board. With the ESP32-CAM-MB the boot mode is handled for you. With a plain USB-serial adapter: connect GPIO0 to GND before powering up, upload, then remove the link and reset.
6. PlatformIO: Upload, then Serial Monitor (115200 baud). The board prints its IP address.
7. Open `http://<ip>/` in a browser to see a preview. `http://<ip>/status` returns JSON.
8. Put the IP in `config.yaml` → `camera.base_url` and run `python -m app.main status`.

Note: this firmware has not been compiled or tested on a board yet. If the build fails, the most likely causes are an older or newer `espressif32` platform version (the camera config field names changed across driver versions) or a different board pin map.

## Optional camera settings

`/config` changes settings at runtime:

- `http://<ip>/config?framesize=qqvga` (160x120: smaller files, usually more frames per second)
- `http://<ip>/config?quality=10` (JPEG quality 10 to 40; lower number is better quality)
- `http://<ip>/config?lock=1` turns off auto exposure and auto gain. Do this after the lighting is set, so brightness does not change during a recording.

## Mechanical setup

- Bolt or tape the camera and the clamp to the same board. Do not touch the camera between conditions.
- Choose the free length of the blade so its first frequency is low. The rule used by the software: the camera needs at least 2.5 samples per cycle, and in practice 4 or more. At 20 fps that means keeping the vibration under about 5 Hz. A longer blade vibrates slower.
- Point the camera so the tip moves left-right in the image (the tracker searches the full width and only a small vertical band).
- Put a ruler in the frame once to work out `tracking.mm_per_px` if you want millimetres.

## First test

1. Run `python -m app.main record --name test --duration 5`.
2. Pluck the blade right after the command starts.
3. Read the printed effective fps and warnings. If the frequency is flagged as close to Nyquist, lengthen the blade or lower the frame size.
