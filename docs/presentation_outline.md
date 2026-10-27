# ResponsePrint: 8-slide presentation outline

## 1. Problem statement
- Two states of a part can look the same in a photo but respond differently when disturbed (stiffness, mass, clamping).
- Contact sensors (accelerometers) add mass and wiring; high-speed cameras are expensive.
- Question: how far can a ₹500 to ₹700 ESP32-CAM go in measuring a free-decay vibration response?

## 2. Existing limitations
- Video-based vibration measurement works well with high-speed cameras (MIT visual vibrometry, motion magnification work).
- The published ESP32-CAM vision monitoring system samples at 1 Hz and handles quasi-static strain only.
- Low frame rate brings aliasing: a fast vibration looks like a slow one. Many hobby projects ignore this.

## 3. Proposed system
- Clamped blade with a printed tip marker, plucked by hand for now.
- ESP32-CAM captures frames; the laptop tracks the marker and extracts frequency and damping.
- Every result is checked for sampling validity before it is reported.
- Show: the free-decay equation x(t) = A·e^(−ζωₙt)·cos(ω_d t + φ).

## 4. Architecture
- Use the Mermaid diagram from `docs/architecture.md`.
- Point out what runs on the board (capture, HTTP) versus the laptop (everything else).

## 5. Hardware and software
- Hardware: ESP32-CAM, USB programmer, 5 V supply, blade, clamp, printed marker.
- Firmware: PlatformIO, `/capture`, `/status`, `/config`.
- Software: Python, OpenCV template matching with sub-pixel peak, FFT / Lomb-Scargle, damped-sine fit, Welch t-test, Streamlit dashboard.

## 6. Demonstration
- Live: run the dashboard, synthetic tab, show Condition A (4.0 Hz) vs B (3.6 Hz).
- Show the aliasing tab: 14 Hz at 25 fps appears as 11 Hz, and the software flags it.
- Say clearly on the slide: **synthetic data, not a hardware measurement.**
- If the board is working by then: one live recording, with its timing report.

## 7. Evaluation plan
- Validate frequency against 240 fps phone video over 10+ releases (bias, limits of agreement, repeatability).
- Then compare a baseline and one controlled change (known tip mass or free length) with 5+ trials each.
- Report the smallest detectable frequency change, not a chosen accuracy number.

## 8. Limitations and future work
- Not yet validated on hardware; synthetic data is idealised.
- Wi-Fi timestamps add jitter; usable frequency range is limited by fps.
- Single camera, in-plane motion, first mode only.
- Next: electromagnet release for repeatable stimulus, then stroboscopic equivalent-time capture to extend the frequency range. Novelty of that step is not yet established.
