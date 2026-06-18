# ♟️ Lichess Physical Board Interface

Play online chess on [Lichess.org](https://lichess.org) using a **real physical chessboard** and your phone camera as the sensor.

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-green?logo=opencv)
![Lichess](https://img.shields.io/badge/Lichess-Board%20API-orange)

## What It Does

This system uses computer vision to watch your physical chess board through a phone camera, detect when you move a piece, and send that move to Lichess in real time. Your opponent's moves are announced out loud via text-to-speech so you never have to look at a screen.

## Features

- 📷 **Camera-based move detection** — SSIM structural comparison on each square detects piece movements
- 🔲 **Automatic grid calibration** — Homography-based perspective transform maps camera view to a perfect 8×8 grid
- 🧠 **Smart move inference** — Handles castling, en passant, pawn promotion, and multi-candidate disambiguation
- 🔊 **Voice announcements** — Opponent moves are spoken aloud ("Knight takes E 4, check")
- 📱 **Mobile control panel** — Flask web server lets you start/resign games from your phone
- 🎯 **State machine monitoring** — CALIBRATING → WATCHING → MOTION_DETECTED → SETTLING → COMPARE with auto-recovery

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Phone Camera │───▶│ board_vision │───▶│move_detector  │
│  (IP Webcam) │    │   (OpenCV)   │    │ (python-chess)│
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
                    ┌──────────────┐    ┌───────▼───────┐
                    │  tts_engine  │◀───│lichess_client │
                    │ (PowerShell) │    │  (Board API)  │
                    └──────────────┘    └───────────────┘
                    
                    ┌──────────────┐    ┌───────────────┐
                    │  web_server  │◀──▶│   gui_app     │
                    │   (Flask)    │    │  (Tkinter)    │
                    └──────────────┘    └───────────────┘
```

## Project Structure

| File | Lines | Description |
|------|-------|-------------|
| `board_vision.py` | ~875 | OpenCV vision pipeline: grid calibration, SSIM motion detection, lens correction |
| `move_detector.py` | ~546 | Chess move inference from changed squares, confidence scoring |
| `gui_app.py` | ~836 | Tkinter GUI with live camera feed, state machine, and game controls |
| `camera_interface.py` | ~294 | IP Webcam / local camera abstraction, MJPEG streaming |
| `lichess_client.py` | ~263 | Lichess Board API client (game streaming, move submission) |
| `web_server.py` | ~118 | Flask web control panel for phone-based game control |
| `tts_engine.py` | ~99 | Windows PowerShell TTS, queued speech to prevent overlap |
| `config.py` | ~33 | Configuration (env vars for token, camera source) |
| `main.py` | ~452 | Entry point and orchestration |

## Setup

### Requirements

```bash
pip install -r requirements.txt
```

Dependencies: `opencv-python`, `numpy`, `berserk`, `python-chess`, `flask`, `scikit-image`, `Pillow`

### Lichess API Token

1. Go to [lichess.org/account/oauth/token/create](https://lichess.org/account/oauth/token/create)
2. Enable scopes: `board:play`, `challenge:read`, `challenge:write`
3. Set it as an environment variable:

```powershell
$env:LICHESS_TOKEN = "lip_your_token_here"
```

Or create a `settings.json` file (ignored by git):

```json
{"lichess_token": "lip_your_token_here", "camera_url": "2"}
```

### Camera

Use your phone as a webcam via [IP Webcam](https://play.google.com/store/apps/details?id=com.pas.webcam) or [DroidCam](https://www.dev47apps.com/).

### Run

```bash
python main.py
```

Or launch the GUI directly:

```bash
python gui_app.py
```

## How It Works

1. **Calibrate** — Point your camera at the board. The system detects the grid using contour detection or manual corner selection, then computes a homography transform.
2. **Watch** — The system continuously compares each square against a baseline image using SSIM (Structural Similarity Index).
3. **Detect** — When enough squares change beyond a threshold, the system enters MOTION_DETECTED and waits for the board to settle.
4. **Infer** — Changed squares are analyzed to determine which legal chess move was made, with confidence scoring for ambiguous cases.
5. **Submit** — The move is sent to Lichess via the Board API. The opponent's response is received via game stream and announced via TTS.

## License

MIT
