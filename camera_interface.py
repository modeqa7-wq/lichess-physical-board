"""
Phone camera interface for capturing frames via IP Webcam.
"""
import cv2
import numpy as np
import requests
import time
import sys
from typing import Optional
from config import CAMERA_URL


class PhoneCamera:
    """
    Interface to phone camera via IP Webcam app.
    
    Supports two modes:
    1. MJPEG stream: Continuous video stream (preferred)
    2. Snapshot: Single image requests (fallback or forced)
    """
    
    def __init__(self, source=None, force_snapshot: bool = False):
        """
        Initialize camera interface.
        
        Args:
            source: Video source (int for local webcam, str for IP URL)
            force_snapshot: If True, use HTTP snapshots (only for IP URL)
        """
        # Determine if source is local webcam (int) or IP (str)
        self.source = source if source is not None else CAMERA_URL
        self.is_local = isinstance(self.source, int) or (isinstance(self.source, str) and self.source.isdigit())
        
        if self.is_local:
            self.source = int(self.source)
            self.base_url = ""
            self.stream_url = self.source
            self.snapshot_url = ""
            self.force_snapshot = False # Cannot snapshot a local webcam
        else:
            self.base_url = str(self.source).rstrip('/')
            self.stream_url = self._get_stream_url()
            self.snapshot_url = self._get_snapshot_url()
            self.force_snapshot = force_snapshot
        
        self._cap: Optional[cv2.VideoCapture] = None
        self._last_frame: Optional[np.ndarray] = None
        self._last_frame_time: float = 0
        
        # Session for IP camera requests
        self.session = requests.Session()
        self.session.trust_env = False

    def _get_stream_url(self) -> str:
        if self.is_local: return self.source
        if '/video' in self.base_url: return self.base_url
        return f"{self.base_url}/video"
    
    def _get_snapshot_url(self) -> str:
        if self.is_local: return ""
        base = self.base_url.replace('/video', '')
        return f"{base}/shot.jpg"
    
    def connect(self) -> bool:
        """Connect to the camera."""
        if self.force_snapshot and not self.is_local:
            return self._capture_snapshot() is not None

        try:
            # cv2.VideoCapture handles both int (local) and str (IP)
            self._cap = cv2.VideoCapture(self.stream_url)
            
            # For local webcams, DSHOW can sometimes cause issues with virtual drivers like DroidCam
            # if self.is_local and sys.platform == 'win32':
            #      self._cap = cv2.VideoCapture(self.stream_url, cv2.CAP_DSHOW)
                 
            if self._cap.isOpened():
                # Read one frame to prove connectivity
                ret, _ = self._cap.read()
                if ret:
                    print(f"Connected to camera source: {self.source}")
                    return True
            
            print(f"Failed to open source: {self.source}")
            return False
            
        except Exception as e:
            print(f"Camera connection error: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from the camera."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.session.close() # Close persistent connection
    
    def is_connected(self) -> bool:
        """
        Check if camera is connected and responding.
        
        Returns:
            True if connected
        """
        if self._cap is not None and self._cap.isOpened():
            return True
        
        # Try snapshot as fallback test
        try:
            response = self.session.get(self.snapshot_url, timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def capture_frame(self, flush_buffer: bool = False) -> Optional[np.ndarray]:
        """
        Capture a single frame from the camera.
        
        Args:
            flush_buffer: If True, read and discard several frames first to get a fresh frame
        """
        if self.force_snapshot and not self.is_local:
            return self._capture_snapshot()

        # Try stream first
        if self._cap is not None and self._cap.isOpened():
            # Flush buffer if requested to get a fresh frame
            if flush_buffer:
                for _ in range(5):  # Discard 5 frames
                    self._cap.grab()
            
            ret, frame = self._cap.read()
            if ret:
                self._last_frame = frame
                self._last_frame_time = time.time()
                return frame
                
        # Fallback to snapshot (IP only)
        if not self.is_local:
            return self._capture_snapshot()
            
        return None
    
    def _capture_snapshot(self) -> Optional[np.ndarray]:
        """
        Capture frame via HTTP snapshot (fallback).
        
        Returns:
            Frame as numpy array, or None if failed
        """
        try:
            # Explicit timeout of 30s for slow networks
            response = self.session.get(self.snapshot_url, timeout=30)
            if response.status_code == 200:
                img_array = np.frombuffer(response.content, dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if frame is not None:
                    self._last_frame = frame
                    self._last_frame_time = time.time()
                return frame
        except Exception as e:
            print(f"Snapshot capture failed: {e}")
        
        return None
    
    def get_last_frame(self) -> Optional[np.ndarray]:
        """
        Get the most recent captured frame.
        
        Returns:
            Last captured frame, or None
        """
        return self._last_frame
    
    def wait_for_stable_frame(
        self,
        stability_threshold: float = 0.98,
        max_wait: float = 5.0,
        check_interval: float = 0.5
    ) -> Optional[np.ndarray]:
        """
        Wait for the camera view to stabilize (board not moving).
        
        Useful for detecting when user has finished moving a piece.
        
        Args:
            stability_threshold: Similarity threshold (0-1) to consider stable
            max_wait: Maximum seconds to wait
            check_interval: Seconds between checks
            
        Returns:
            Stable frame, or None if timeout
        """
        # Try to get initial frame with retries
        prev_frame = None
        for _ in range(5):  # Try 5 times
            prev_frame = self.capture_frame()
            if prev_frame is not None:
                break
            time.sleep(0.5)
        
        if prev_frame is None:
            print("Failed to get initial frame for stability check")
            return None
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            time.sleep(check_interval)
            
            curr_frame = self.capture_frame()
            if curr_frame is None:
                continue
            
            # Compare frames using structural similarity
            similarity = self._compare_frames(prev_frame, curr_frame)
            
            if similarity >= stability_threshold:
                return curr_frame
            
            prev_frame = curr_frame
        
        # Return last frame even if not fully stable
        return prev_frame if prev_frame is not None else self._last_frame
    
    def _compare_frames(self, frame1: np.ndarray, frame2: np.ndarray) -> float:
        """
        Compare two frames for similarity.
        
        Args:
            frame1: First frame
            frame2: Second frame
            
        Returns:
            Similarity score 0-1
        """
        # Resize to same dimensions if needed
        if frame1.shape != frame2.shape:
            frame2 = cv2.resize(frame2, (frame1.shape[1], frame1.shape[0]))
        
        # Convert to grayscale
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        
        # Calculate absolute difference
        diff = cv2.absdiff(gray1, gray2)
        
        # Normalize difference to 0-1 range
        diff_normalized = diff.astype(float) / 255.0
        
        # Calculate mean similarity
        similarity = 1.0 - np.mean(diff_normalized)
        
        return similarity
    
    def show_preview(self, window_name: str = "Camera Preview") -> None:
        """
        Show a live preview window for camera positioning.
        
        Press 'q' to close.
        """
        print(f"Opening preview window. Press 'q' to close.")
        
        while True:
            frame = self.capture_frame()
            if frame is not None:
                cv2.imshow(window_name, frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        cv2.destroyWindow(window_name)


# Quick test
if __name__ == "__main__":
    import sys
    
    url = sys.argv[1] if len(sys.argv) > 1 else CAMERA_URL
    print(f"Testing camera at: {url}")
    
    camera = PhoneCamera(url)
    
    if camera.connect():
        print("Connected! Showing preview...")
        camera.show_preview()
        camera.disconnect()
    else:
        print("Could not connect to camera.")
        print("\nMake sure:")
        print("1. IP Webcam app is running on your phone")
        print("2. Phone and computer are on the same WiFi network")
        print("3. Update CAMERA_URL in config.py with your phone's IP")
