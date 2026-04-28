"""
Configuration for the Lichess Physical Board Interface.
"""
import os

# Lichess API Token - set via environment variable or replace directly
LICHESS_TOKEN = os.environ.get("LICHESS_TOKEN", "")

# Phone camera URL (IP Webcam stream) or Local Webcam Index (Integer)
# Example IP: "http://10.0.0.43:8080"
# Example Local: "0" (for default webcam/DroidCam)
# Phone camera URL (IP Webcam stream) or Local Webcam Index (Integer)
# Example IP: "http://10.0.0.43:8080"
# Example Local: "0" (for default webcam/DroidCam)
CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "2")
# Legacy support
if "http" in CAMERA_SOURCE:
    CAMERA_URL = CAMERA_SOURCE
else:
    CAMERA_URL = int(CAMERA_SOURCE)

# Text-to-Speech settings
TTS_RATE = 150  # Words per minute
TTS_VOICE = None  # None = system default, or specify voice ID

# Board detection settings
BOARD_SIZE = 8  # 8x8 squares
CALIBRATION_SQUARES = 4  # Number of corner squares to detect

# Game settings
DEFAULT_TIME_CONTROL = "10+0"  # 10 minutes, no increment
DEFAULT_RATED = False  # Unrated games by default
