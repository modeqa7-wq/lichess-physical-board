"""
Graphical User Interface for Lichess Physical Board.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk
import threading
import time
import sys
import queue
import chess
import os
import json

from config import LICHESS_TOKEN, CAMERA_URL, DEFAULT_TIME_CONTROL
from tts_engine import TTSEngine
from lichess_client import LichessClient
from camera_interface import PhoneCamera
from board_vision import BoardVision
from move_detector import MoveDetector
import web_server


class LichessBoardApp(tk.Tk):
    """Main GUI Application."""
    
    def __init__(self):
        super().__init__()
        
        self.title("Lichess Physical Board Interface")
        self.geometry("1100x750")
        
        # Use standard tk styling to avoid theme issues
        self.configure(bg="#f0f0f0")
        
        # Initialize Core Components
        self.tts = TTSEngine()
        # Don't connect immediately to avoid lag
        self.camera = PhoneCamera(CAMERA_URL)
        self.vision = BoardVision()
        self.detector = MoveDetector()
        self.lichess = None
        self.board = chess.Board() # Local board state for validation
        
        # Game State
        self.game_id = None
        self.my_color = None
        self.is_my_turn = False
        self.is_running = True
        self.camera_connected = False
        self.baseline_frame = None # Persistent baseline for move detection
        
        # Debug Mode
        self.debug_mode = tk.BooleanVar(value=False)
        
        # Queue for thread-safe UI updates
        self.msg_queue = queue.Queue()
        
        self._setup_ui()
        
        # Try to load token from config
        if LICHESS_TOKEN:
            self.token_entry.insert(0, LICHESS_TOKEN)
            # Don't auto-connect to avoid blocking start
        
        # Try to load settings to populate UI
        self.settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
        self.saved_settings = self.load_settings()
        
        # Start background threads
        self.after(50, self._process_queue)
        threading.Thread(target=self._camera_thread_loop, daemon=True).start()
        
        # Try to load saved calibration
        if self.vision.load_calibration():
            self.log("Loaded lens calibration.")
            
        # Try to load SQList (Grid)
        if self.vision.load_sqdict():
            self.log("Loaded board grid (sqdict.json).")
        else:
            self.log("WARNING: Board not calibrated. Use 'Calibrate Board' first.")
        
        # Auto-Connect Trigger
        self.after(1000, self._auto_connect_services)
        
        self.log("Application started. Check settings on right.")
        
        # Start Web Control Panel
        web_server.set_main_app(self)
        web_server.start_server(port=5000)
        self._update_web_state()

    def load_settings(self):
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_settings(self):
        settings = {
            'lichess_token': self.token_entry.get(),
            'camera_url': self.url_entry.get()
        }
        self.log(f"Saving settings to {self.settings_path}")
        try:
            with open(self.settings_path, 'w') as f:
                json.dump(settings, f)
            self.log("Settings saved successfully.")
        except Exception as e:
            self.log(f"Failed to save settings: {e}")

    def _auto_connect_services(self):
        """Auto-connect if settings exist."""
        # 1. Lichess
        token = self.saved_settings.get('lichess_token') or LICHESS_TOKEN
        if token:
            self.token_entry.delete(0, tk.END)
            self.token_entry.insert(0, token)
            self._connect_lichess(auto=True)
            
        # 2. Camera
        cam_url = self.saved_settings.get('camera_url') or CAMERA_URL
        if cam_url:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, cam_url)
            self._reconnect_camera(auto=True)

    def _setup_ui(self):
        """Build the UI layout."""
        # Main container
        main_frame = tk.Frame(self, bg="#f0f0f0")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left Side: Video Feed
        video_frame = tk.LabelFrame(main_frame, text="Board View", bg="#f0f0f0")
        video_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.video_label = tk.Label(video_frame, text="Waiting for camera...", bg="black", fg="white")
        self.video_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Right Side: Controls
        control_panel = tk.Frame(main_frame, width=300, bg="#f0f0f0")
        control_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        
        # 1. Connection Settings
        conn_frame = tk.LabelFrame(control_panel, text="Settings", bg="#f0f0f0", padx=5, pady=5)
        conn_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(conn_frame, text="Lichess Token:", bg="#f0f0f0").pack(anchor=tk.W)
        self.token_entry = tk.Entry(conn_frame, show="*")
        self.token_entry.pack(fill=tk.X, pady=2)
        tk.Button(conn_frame, text="Connect Lichess", command=self._connect_lichess).pack(fill=tk.X, pady=2)
        
        tk.Label(conn_frame, text="Camera Source (URL or ID):", bg="#f0f0f0").pack(anchor=tk.W)
        self.url_entry = tk.Entry(conn_frame)
        self.url_entry.pack(fill=tk.X, pady=2)
        tk.Button(conn_frame, text="Connect Camera", command=self._reconnect_camera).pack(fill=tk.X, pady=2)
        
        # Debug Checkbox
        tk.Checkbutton(conn_frame, text="Visual Debug Mode", variable=self.debug_mode, bg="#f0f0f0").pack(anchor=tk.W, pady=5)

        # 2. Game Status
        status_frame = tk.LabelFrame(control_panel, text="Status", bg="#f0f0f0", padx=5, pady=5)
        status_frame.pack(fill=tk.X, pady=5)
        
        self.status_var = tk.StringVar(value="Idle")
        tk.Label(status_frame, textvariable=self.status_var, font=("Arial", 12, "bold"), bg="#f0f0f0").pack(pady=5)
        
        self.turn_indicator_var = tk.StringVar(value="")
        tk.Label(status_frame, textvariable=self.turn_indicator_var, fg="blue", bg="#f0f0f0").pack(pady=2)

        # 3. Game Controls
        game_frame = tk.LabelFrame(control_panel, text="Controls", bg="#f0f0f0", padx=5, pady=5)
        game_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(game_frame, text="Calibrate Board (Click Corners)", command=self._calibrate_manual).pack(fill=tk.X, pady=5)
        
        tk.Label(game_frame, text="Time Control:", bg="#f0f0f0").pack(anchor=tk.W)
        self.time_combo = ttk.Combobox(game_frame, values=["10+0", "5+3", "3+2", "15+10"])
        self.time_combo.current(0)
        self.time_combo.pack(fill=tk.X, pady=2)
        
        # Bot Mode Option
        self.bot_var = tk.BooleanVar(value=True)  # Default to True to avoid bans
        tk.Checkbutton(game_frame, text="Play vs Computer", variable=self.bot_var, bg="#f0f0f0").pack(anchor=tk.W)
        
        tk.Label(game_frame, text="Your Color:", bg="#f0f0f0").pack(anchor=tk.W)
        self.color_combo = ttk.Combobox(game_frame, values=["white", "black", "random"])
        self.color_combo.current(0)
        self.color_combo.pack(fill=tk.X, pady=2)
        
        tk.Button(game_frame, text="Start New Game", command=self._start_game_thread, bg="#ddffdd").pack(fill=tk.X, pady=5)
        tk.Button(game_frame, text="Resign", command=self._resign_game, bg="#ffdddd").pack(fill=tk.X, pady=2)
        
        # 4. Manual Input
        input_frame = tk.LabelFrame(control_panel, text="Manual Move", bg="#f0f0f0", padx=5, pady=5)
        input_frame.pack(fill=tk.X, pady=5)
        
        self.move_entry = tk.Entry(input_frame)
        self.move_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.move_entry.bind('<Return>', lambda e: self._manual_move())
        tk.Button(input_frame, text="Send", command=self._manual_move).pack(side=tk.RIGHT)

        # 5. Logs
        log_frame = tk.LabelFrame(control_panel, text="Log", bg="#f0f0f0", padx=5, pady=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_text = tk.Text(log_frame, height=10, width=30, state='disabled', font=("Consolas", 8))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, message):
        """Add message to log window."""
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        print(message)

    def _connect_lichess(self, auto=False):
        token = self.token_entry.get()
        if not token:
            if not auto: messagebox.showerror("Error", "Please enter a Lichess Token")
            return
            
        try:
            self.lichess = LichessClient(token)
            self.username = self.lichess.username
            self.log(f"Connected to Lichess as: {self.username}")
            self.save_settings() # Save on success
            if not auto: messagebox.showinfo("Success", f"Connected as {self.username}")
        except Exception as e:
            self.log(f"Connection failed: {e}")
            if not auto: messagebox.showerror("Error", f"Failed to connect: {e}")

    def _camera_thread_loop(self):
        """Background thread for continuous camera capture."""
        while self.is_running:
            if self.camera_connected:
                # Capture frame
                frame = self.camera.capture_frame()
                if frame is not None:
                    # Apply Lens Correction (if calibrated)
                    frame = self.vision.undistort_frame(frame)
                    
                    # Debug Visualization Logic
                    scores = None
                    if self.debug_mode.get() and self.baseline_frame is not None:
                        # Compute live SSIM scores against baseline
                        scores = self.vision.get_square_intensities(self.baseline_frame, frame)
                    
                    # Update UI via main thread
                    try:
                        # Visualize (pass scores if debugging)
                        display_frame = self.vision.visualize_grid(frame, scores=scores)
                        
                        # Add indicator if baseline is missing in debug mode
                        if self.debug_mode.get() and self.baseline_frame is None:
                            cv2.putText(display_frame, "NO BASELINE - PLAY A MOVE", (10, 30), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                        
                        # Resize for display (1280 is too big for screen)
                        display_frame = cv2.resize(display_frame, (640, 640))
                        
                        # Convert for tkinter (must do in main thread or carefully here)
                        # We'll send the raw array to queue to be safe and avoid thread issues with PhotoImage
                        self.msg_queue.put({'type': 'frame', 'data': display_frame})
                    except Exception as e:
                        import traceback
                        print(f"Vis error: {e}")
                        traceback.print_exc()
                else:
                    self.camera_connected = False
                    self.msg_queue.put({'type': 'log', 'data': "Camera signal lost"})
            
            time.sleep(0.05)  # Cap at ~20fps

    def _process_queue(self):
        """Process messages from other threads."""
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if msg['type'] == 'log':
                    self.log(msg['data'])
                elif msg['type'] == 'status':
                    self.status_var.set(msg['data'])
                elif msg['type'] == 'turn':
                    self.turn_indicator_var.set(msg['data'])
                elif msg['type'] == 'move':
                    self.tts.announce_move(msg['data'])
                elif msg['type'] == 'speech':
                    self.tts.say(msg['data'])
                elif msg['type'] == 'game_end':
                    self.tts.announce_game_end(msg['data'])
                elif msg['type'] == 'frame':
                    self._update_video_label(msg['data'])
        except queue.Empty:
            pass
        self.after(50, self._process_queue)

    def _update_video_label(self, frame):
        """Update the video label with new frame."""
        try:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame.shape[:2]
            
            # Simple resize logic
            target_h = 500
            scale = target_h / h
            new_w = int(w * scale)
            display_frame = cv2.resize(frame, (new_w, target_h))
            
            img = Image.fromarray(display_frame)
            imgtk = ImageTk.PhotoImage(image=img)
            
            self.video_label.imgtk = imgtk
            self.video_label.configure(image=imgtk, text="")
        except Exception:
            pass

    def _reconnect_camera(self, auto=False):
        input_val = self.url_entry.get()
        # Check if it's an integer index (0, 1) or URL
        if input_val.isdigit():
            source = int(input_val)
        else:
            source = input_val
        
        self.save_settings() # Save requested URL    
        # Do connection in thread to avoid freeze
        threading.Thread(target=self._connect_camera_thread, args=(source,), daemon=True).start()
        
    def _connect_camera_thread(self, source):
        self.msg_queue.put({'type': 'log', 'data': f"Connecting to source: {source}..."})
        temp_cam = PhoneCamera(source)
        if temp_cam.connect():
            self.camera = temp_cam
            self.camera_connected = True
            self.msg_queue.put({'type': 'log', 'data': "Camera Connected!"})
        else:
            self.msg_queue.put({'type': 'log', 'data': "Connection failed."})

    def _calibrate_manual(self):
        """Interactive manual calibration (Click 4 corners)."""
        if not self.camera_connected:
            self.log("Connect camera first!")
            return
            
        self.log("Starting Manual Calibration...")
        self.log("Please click the 4 corners of the board in order: TL, TR, BR, BL")
        
        # Grab a single frame for clicking
        frame = self.camera.capture_frame(flush_buffer=True)
        if frame is None: return
        
        # Apply lens correction if available
        frame = self.vision.undistort_frame(frame)
        
        corners = []
        window_name = "Calibration: Click TL -> TR -> BR -> BL"
        
        def mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN and len(corners) < 4:
                corners.append((x, y))
                print(f"Clicked: {x}, {y}")
        
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, mouse_callback)
        
        while len(corners) < 4:
            display = frame.copy()
            for i, pt in enumerate(corners):
                cv2.circle(display, pt, 5, (0, 0, 255), -1)
                cv2.putText(display, str(i+1), (pt[0]+10, pt[1]+10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
                
            cv2.imshow(window_name, display)
            if cv2.waitKey(50) & 0xFF == 27: # Esc
                break
                
        cv2.destroyWindow(window_name)
        
        if len(corners) == 4:
            if self.vision.manual_calibrate(corners):
                self.log("Manual Calibration Saved (sqlist.json)!")
                self.msg_queue.put({'type': 'speech', 'data': "Grid calibrated"})
            else:
                self.log("Error saving calibration.")
        else:
            self.log("Calibration cancelled.")

    def _resign_game(self):
        if not self.game_id: return
        if not messagebox.askyesno("Confirm", "Resign current game?"): return
        
        try:
            self.lichess.resign(self.game_id)
            self.log("Resigned game.")
            self.msg_queue.put({'type': 'speech', 'data': "Game resigned"})
        except Exception as e:
            # Handle "Game cannot be resigned" (400 Bad Request)
            self.log(f"Resign failed (Game likely ended): {e}")
    
    def _start_game_thread(self):
        if not self.lichess:
            return
        threading.Thread(target=self._run_game, daemon=True).start()

    def _run_game(self):
        time_control = self.time_combo.get()
        # Check if "Bot" or "Computer" is selected 
        
        is_bot = self.bot_var.get()
        color_choice = self.color_combo.get()
        
        self.msg_queue.put({'type': 'log', 'data': f"Searching for {'Bot' if is_bot else 'Opponent'}..."})
        self.msg_queue.put({'type': 'status', 'data': "Searching..."})
        try:
            if is_bot:
                # Play level 1-3 for testing
                game = self.lichess.create_ai_game(level=3, color=color_choice)
            else:
                game = self.lichess.create_game(time_control, False, color=color_choice)
                
            self.game_id = game.get('id')
            self.baseline_frame = None # Reset baseline for new game
            self.msg_queue.put({'type': 'log', 'data': f"Game started! ID: {self.game_id}"})
            
            # Start stream loop
            self._game_stream_loop()
        except Exception as e:
            self.msg_queue.put({'type': 'log', 'data': f"Error: {e}"})
            self.msg_queue.put({'type': 'status', 'data': "Error"})

    def _game_stream_loop(self):
        for event in self.lichess.stream_game_state(self.game_id):
            if not self.is_running: break
            
            type = event.get('type')
            if type == 'gameFull':
                self.my_color = self.lichess.get_my_color(event)
                self.msg_queue.put({'type': 'log', 'data': f"You are {self.my_color.upper()}"})
                self.tts.announce_color(self.my_color == 'white')
                self._handle_state(event.get('state', {}))
            elif type == 'gameState':
                self._handle_state(event)

    def _handle_state(self, state):
        status = state.get('status')
        if status != 'started':
            self.msg_queue.put({'type': 'status', 'data': f"Game Over: {status}"})
            self.msg_queue.put({'type': 'game_end', 'data': status})
            return

        moves = state.get('moves', '').split()
        
        # Set orientation if not set (check every time or just on gameFull)
        # Assuming we can just set it here safely
        self.vision.set_orientation(self.my_color == 'white')
        
        # Sync board logic
        self.detector.reset()
        self.board.reset() # Reset local board
        for m in moves:
            self.detector.apply_move(m)
            try:
                self.board.push_uci(m) # Sync local board
            except:
                pass
        
        # Check turn
        turn_idx = len(moves)
        is_white_turn = (turn_idx % 2 == 0)
        self.is_my_turn = (self.my_color == 'white') == is_white_turn
        
        # Determine who made the last move
        last_move_san = None
        if moves:
            last_move_uci = moves[-1]
            # Replay efficiently to get SAN (could optimize)
            temp_det = MoveDetector()
            for m in moves[:-1]: temp_det.apply_move(m)
            last_move_san = temp_det.get_san(last_move_uci)
        
        if self.is_my_turn:
            self.msg_queue.put({'type': 'status', 'data': "YOUR TURN"})
            # If it's my turn, the LAST move was made by Opponent
            last_move_uci = None
            if moves:
                last_move_uci = moves[-1]
                
            if last_move_san:
                self.msg_queue.put({'type': 'log', 'data': f"Opponent: {last_move_san}"})
                
            self.msg_queue.put({'type': 'turn', 'data': f"Opponent played {last_move_san or 'nothing'}. Your Move!"})
            
            # Start monitoring
            threading.Thread(target=self._monitor_move, args=(last_move_uci,), daemon=True).start()
        else:
            self.msg_queue.put({'type': 'status', 'data': "OPPONENT'S TURN"})
            self.msg_queue.put({'type': 'turn', 'data': "Waiting..."})
            # If not my turn, I just moved. Do not announce my own move via TTS usually.

    def _monitor_move(self, last_move_uci=None):
        """
        State Machine Monitoring:
        CALIBRATING -> WATCHING -> MOTION_DETECTED -> SETTLING -> [Result]
        
        Now uses Persistent Baseline to handle fast play/combined moves.
        """
        if not self.is_my_turn: return
        
        # Calculate expected squares (Opponent's move) to filter out
        # ONLY filter the SOURCE square (where opponent's piece came from)
        # DON'T filter destination - user might be capturing there!
        opponent_squares = set()
        if last_move_uci:
            try:
                move = chess.Move.from_uci(last_move_uci)
                # Filter SOURCE - opponent's piece left this square (user moved it)
                opponent_squares.add(chess.square_name(move.from_square))
                # DON'T filter destination - user might capture there!
                # opponent_squares.add(chess.square_name(move.to_square))  # DISABLED
            except:
                pass
        
        # TTS Announcement
        if last_move_uci:
            self.msg_queue.put({'type': 'speech', 'data': f"Opponent played {last_move_uci}"})
            self.log(f"Opponent played {last_move_uci}. Waiting for you to update board...")

        # Initialize State Machine
        state = "CALIBRATING"
        baseline = None
        last_stable_time = time.time()
        candidate_frame = None
        
        # Flags
        advice_given = False
        consecutive_failures = 0  # Auto-recovery counter
        
        self.log("Entering Autonomous State Machine...")
        self.msg_queue.put({'type': 'status', 'data': "CALIBRATING (Study)..."})

        while self.is_my_turn and self.is_running:
            # Main State Loop - Runs at ~10 FPS
            time.sleep(0.1)
            
            # Capture Frame (Always flush buffer)
            curr_frame = self.camera.capture_frame(flush_buffer=True)
            if curr_frame is None: continue
            
            # 1. State: CALIBRATING (Study)
            if state == "CALIBRATING":
                # STRATEGY: ALWAYS capture a fresh baseline to prevent "ghosting" from previous turns.
                # Disabled Persistent Baseline per user request (Step 2363).
                if False: # self.baseline_frame is not None:
                     baseline = self.baseline_frame
                     state = "WATCHING"
                     self.log("Using Persistent Baseline (Pre-Move). State: WATCHING")
                     self.msg_queue.put({'type': 'status', 'data': "Watching for move..."})
                else:
                    # First turn or fresh capture: Must wait for stability
                    baseline = self.camera.wait_for_stable_frame(max_wait=10, stability_threshold=0.98)
                    if baseline is not None:
                        baseline = self.vision.undistort_frame(baseline)
                        self.baseline_frame = baseline # Save for future
                        state = "WATCHING"
                        self.log("New Baseline captured. State: WATCHING")
                        self.msg_queue.put({'type': 'status', 'data': "Watching for move..."})
                        
                        if not advice_given:
                            self.msg_queue.put({'type': 'speech', 'data': "Make your move"})
                            advice_given = True
                    else:
                        self.log("Could not stabilize board. Retrying...")
            
            # 2. State: WATCHING (Wait for Move)
            elif state == "WATCHING":
                # Check for motion
                active_squares = self.vision.get_motion_squares(baseline, curr_frame, threshold=20)
                
                if len(active_squares) >= 1:
                    state = "MOTION_DETECTED"
                    last_stable_time = time.time()
                    self.log(f"Motion detected in {len(active_squares)} squares! State: MOTION_DETECTED")
                    self.msg_queue.put({'type': 'status', 'data': "Motion detected..."})
            
            # 3. State: MOTION_DETECTED (Hand Over Board)
            elif state == "MOTION_DETECTED":
                prev_check_frame = curr_frame
                time.sleep(0.1)
                next_check_frame = self.camera.capture_frame(flush_buffer=True)
                
                if next_check_frame is None: continue
                
                frame_diff = self.vision.get_pixel_diff_score(prev_check_frame, next_check_frame)
                
                if frame_diff < 0.02: # Static
                     if time.time() - last_stable_time > 1.0: # Settling time
                        state = "SETTLING"
                        self.log("Motion stopped. State: SETTLING (Buffering exposure...)")
                else:
                     last_stable_time = time.time()

            # 4. State: SETTLING & COMPARE
            elif state == "SETTLING":
                # EXPOSURE BUFFER: Discard frames to let camera auto-exposure stabilize after hand removal
                for _ in range(5):
                    self.camera.capture_frame(flush_buffer=False)
                    time.sleep(0.05)
                
                # Capture the actual candidate frame
                raw_candidate = self.camera.capture_frame(flush_buffer=True)
                if raw_candidate is None:
                    state = "CALIBRATING"
                    continue
                    
                candidate_frame = self.vision.undistort_frame(raw_candidate)
                
                # BINARY Detection Logic (Rolled back as requested, but now powered by SSIM)
                active_now = self.vision.get_motion_squares(baseline, candidate_frame, threshold=15)
                active_weak = self.vision.get_motion_squares(baseline, candidate_frame, threshold=3) 
                
                # FILTER: Remove Opponent's Move Squares from the "Changes" list
                filtered_active = [sq for sq in active_now if sq not in opponent_squares]
                filtered_weak = [sq for sq in active_weak if sq not in opponent_squares]
                
                num_active = len(filtered_active)
                self.log(f"Active: {active_now} -> Filtered: {filtered_active} (Opponent: {opponent_squares})")
                
                if num_active == 0:
                    if len(active_now) > 0:
                         self.log("Only opponent move detected. Waiting for YOUR move...")
                    else:
                         self.log("False alarm. Returning to WATCHING.")
                    
                    state = "WATCHING"
                    continue
                    
                elif num_active > 4:
                    # SPECIAL CASE: Castling (exactly 4 squares in specific pattern)
                    castling_move = None
                    active_set = set(filtered_active)
                    
                    # White Kingside: e1, f1, g1, h1
                    if active_set == {'e1', 'f1', 'g1', 'h1'}:
                        castling_move = chess.Move.from_uci('e1g1')
                    # White Queenside: e1, d1, c1, a1
                    elif active_set == {'e1', 'd1', 'c1', 'a1'}:
                        castling_move = chess.Move.from_uci('e1c1')
                    # Black Kingside: e8, f8, g8, h8
                    elif active_set == {'e8', 'f8', 'g8', 'h8'}:
                        castling_move = chess.Move.from_uci('e8g8')
                    # Black Queenside: e8, d8, c8, a8
                    elif active_set == {'e8', 'd8', 'c8', 'a8'}:
                        castling_move = chess.Move.from_uci('e8c8')
                    
                    if castling_move and castling_move in self.board.legal_moves:
                        move_san = self.board.san(castling_move)
                        self.log(f"Castling Detected: {move_san}")
                        self.msg_queue.put({'type': 'speech', 'data': f"Castling {move_san}"})
                        
                        if self.lichess.make_move(self.game_id, castling_move.uci()):
                            self.log("Move sent!")
                            self.board.push(castling_move)
                            self.baseline_frame = candidate_frame
                            self.is_my_turn = False
                            return
                    
                    # Not castling - treat as hand obstruction
                    consecutive_failures += 1
                    if consecutive_failures >= 10:
                        self.log("Too many failures! Resetting baseline...")
                        self.msg_queue.put({'type': 'speech', 'data': "Resetting. Fix the board, then replay your move."})
                        self.log(">>> Fix board and replay move in 5 seconds...")
                        time.sleep(5)  # Give user time to fix board
                        state = "CALIBRATING"
                        baseline = None
                        consecutive_failures = 0
                        continue
                    self.log(f"Too many changes (>4). Hand obstructing. ({consecutive_failures}/10)")
                    state = "MOTION_DETECTED"
                    continue
                
                # Detect Move using Binary Squares
                move_uci = self.detector.detect_move_from_squares(filtered_active, self.board, weak_squares=filtered_weak)
                
                if move_uci:
                    try:
                        move_obj = chess.Move.from_uci(move_uci)
                        if move_obj in self.board.legal_moves:
                            move_san = self.board.san(move_obj)
                            self.log(f"Move Confirmed: {move_san}")
                            self.msg_queue.put({'type': 'speech', 'data': f"Detected {move_san}"})
                            
                            if self.lichess.make_move(self.game_id, move_uci):
                                self.log("Move sent!")
                                self.msg_queue.put({'type': 'speech', 'data': f"{move_san} sent"})
                                self.board.push(move_obj)
                                
                                # CRITICAL: Update Persistent Baseline to the current state!
                                self.baseline_frame = candidate_frame
                                
                                self.is_my_turn = False
                                return
                            else:
                                self.log("API rejected move.")
                        else:
                            self.log(f"Illegal move: {move_uci}")
                            self.msg_queue.put({'type': 'speech', 'data': "Check move"})
                            state = "CALIBRATING" 
                    except:
                        pass
                else:
                    self.log("Move analysis failed. Retrying... (Baseline preserved)")
                    # Do NOT reset to CALIBRATING. Keep the current 'baseline' and keep watching.
                    state = "WATCHING"



    def _manual_move(self):
        move = self.move_entry.get()
        if self.game_id and move:
            # Add promotion logic if needed
            move = self.detector.suggest_promotion(move)
            self.lichess.make_move(self.game_id, move)
            self.msg_queue.put({'type': 'log', 'data': f"Manual: {move}"})
            self.move_entry.delete(0, tk.END)

    # ========== Web Control Panel Methods ==========
    
    def _update_web_state(self):
        """Update the shared state for web control panel."""
        try:
            # Get move history as SAN list
            moves_san = []
            temp_board = chess.Board()
            for move in self.board.move_stack:
                moves_san.append(temp_board.san(move))
                temp_board.push(move)
            
            web_server.update_game_state({
                'status': self.status_var.get() if hasattr(self, 'status_var') else 'Idle',
                'is_my_turn': self.is_my_turn,
                'my_color': self.my_color or 'white',
                'game_id': self.game_id,
                'my_time': getattr(self, 'my_time', 600),
                'opponent_time': getattr(self, 'opponent_time', 600),
                'moves': moves_san,
                'camera_connected': self.camera_connected,
                'lichess_connected': self.lichess is not None,
                'last_opponent_move': getattr(self, 'last_opponent_move', None),
            })
        except Exception as e:
            print(f"Web state update error: {e}")
        
        # Schedule next update
        self.after(500, self._update_web_state)
    
    def start_new_game_from_web(self, level=3, color='white'):
        """Start a new game (called from web panel)."""
        self.log(f"Web: Starting new game (Level {level}, {color})")
        # Start game in thread (directly call lichess API)
        def run():
            import traceback
            try:
                if not self.lichess:
                    self.log("Not connected to Lichess")
                    return
                self.msg_queue.put({'type': 'status', 'data': 'Creating game...'})
                self.log("Calling Lichess API...")
                game = self.lichess.create_ai_game(level=level, color=color)
                self.log(f"API returned: {game}")
                self.game_id = game.get('id')
                if not self.game_id:
                    self.log(f"ERROR: No game ID returned! Response: {game}")
                    return
                self.baseline_frame = None
                self.board = chess.Board()
                self.msg_queue.put({'type': 'log', 'data': f"Game created! ID: {self.game_id}"})
                self.msg_queue.put({'type': 'speech', 'data': "Game started"})
                self.log("Starting game stream loop...")
                # Start the game stream loop (this handles the actual game)
                self._game_stream_loop()
                self.log("Game stream loop ended")
            except Exception as e:
                self.log(f"Failed to start game: {e}")
                self.log(f"Traceback: {traceback.format_exc()}")
                self.msg_queue.put({'type': 'status', 'data': 'Error'})
        threading.Thread(target=run, daemon=True).start()
    
    def force_reset_baseline(self):
        """Force baseline recapture with countdown (called from web panel)."""
        self.log("Web: Force reset baseline - Countdown starting")
        
        def countdown():
            # Announce and countdown
            self.tts.say("Adjust board and replay your move")
            self.msg_queue.put({'type': 'status', 'data': 'RESETTING...'})
            
            for i in range(5, 0, -1):
                self.log(f"Reset in {i}...")
                self.msg_queue.put({'type': 'status', 'data': f'Reset in {i}...'})
                self.tts.say(str(i))
                time.sleep(1)
            
            # Reset baseline
            self.baseline_frame = None
            self.log("Baseline reset! Make your move.")
            self.msg_queue.put({'type': 'speech', 'data': "Go"})
            self.msg_queue.put({'type': 'status', 'data': 'YOUR TURN'})
        
        threading.Thread(target=countdown, daemon=True).start()
    
    def resign_game_from_web(self):
        """Resign current game (called from web panel)."""
        if self.game_id:
            self.log("Web: Resigning game")
            self._resign_game()

    def on_close(self):
        self.is_running = False
        self.camera.disconnect()
        # Kill python process to ensure threads die
        self.destroy()
        os._exit(0)

if __name__ == "__main__":
    app = LichessBoardApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
