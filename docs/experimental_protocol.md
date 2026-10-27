# Experimental protocol: validating against phone slow-motion video

Goal: find out how closely the ESP32-CAM frequency (and, if possible, damping) agrees with an independent, faster reference, before using it to compare physical conditions.

## Reference

A phone recording at 240 fps (or the highest slow-motion rate available) of the same marker, analysed with the same tracking code (`python -m app.main analyze --video clip.mp4 --fps 240`). As a second sanity check, estimate the first natural frequency of the clamped blade from cantilever beam theory:

f1 = (1.875² / 2π) · √(E·I / (ρ·A·L⁴))

using measured length L, width, thickness and handbook values of E and ρ for steel. Expect a rough match only; the clamp is never perfectly rigid.

## Setup

1. Clamp the blade with a marked free length. Record L, width and thickness with a vernier.
2. Fix the ESP32-CAM and the phone on stands so both see the marker. Neither is moved during the session.
3. Lock ESP32-CAM exposure (`/config?lock=1`) after setting the lighting.

## Procedure

1. Start the phone slow-motion recording.
2. Start `python -m app.main record --name ref_tN --condition A --duration 6`.
3. Pull the tip to a fixed stop (a block or a pencil mark, about 10 mm) and release. Use the same stop every time.
4. Stop both recordings after the blade settles.
5. Repeat for at least 10 releases. Save the phone clips as `ref_tN.mp4` so pairs match.
6. Analyse each phone clip and each ESP32-CAM recording.

## Per-trial data to record

| trial | ESP32 f (Hz) | ESP32 fps | phone f (Hz) | ESP32 zeta | phone zeta | warnings |
|---|---|---|---|---|---|---|

## Evaluation

- Frequency agreement: mean and maximum |f_ESP32 − f_phone|, plus a Bland-Altman plot (bias and limits of agreement).
- Repeatability: standard deviation of f across the 10 releases, for each device.
- Damping: compare only trials where both devices report a valid zeta. Expect the ESP32 to be worse here.
- Timing: effective fps, interval CV and gaps from each ESP32 report.

Do not choose a pass/fail tolerance in advance. Report the measured agreement and state the smallest frequency change it would let you detect (about 3 times the repeatability standard deviation is a sensible screening level).

## Then compare conditions

Only after the reference check:

1. Baseline condition A: unchanged blade, 5+ releases.
2. Altered condition B: one controlled change, for example a known small mass taped at the tip (weigh it), or a different free length. A saw-cut notch is a later step and needs several blades per depth.
3. `python -m app.main compare --a ... --b ...`
4. Report the verdict exactly as printed. A supported frequency difference shows the response changed; it does not identify the cause.

## Static-image check (for the claim that the response adds information)

For the altered condition, also save a still of the blade at rest for each trial and compare A vs B stills directly (pixel difference). If the stills already differ clearly (for example a visible mass), the condition is not a fair test of the "looks the same statically" idea. Prefer changes that are not visible from the camera side.
