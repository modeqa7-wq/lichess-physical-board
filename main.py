"""
Lichess Physical Board Interface - Main Application

Play online Lichess games using a physical chessboard and phone camera.
"""
import sys
import time
import argparse
from typing import Optional

import chess

from config import LICHESS_TOKEN, CAMERA_URL, DEFAULT_TIME_CONTROL
from tts_engine import TTSEngine
from lichess_client import LichessClient
from camera_interface import PhoneCamera
from board_vision import BoardVision
from move_detector import MoveDetector


class PhysicalBoardGame:
    """
    Main application for playing Lichess with a physical board.
    """
    
    def __init__(self, token: str = None, camera_url: str = None):
        """
        Initialize all components.
        
        Args:
            token: Lichess API token
            camera_url: Phone camera stream URL
        """
        print("Initializing Lichess Physical Board Interface...")
        
        # Initialize components
        self.tts = TTSEngine()
        self.lichess = LichessClient(token)
        self.camera = PhoneCamera(camera_url)
        self.vision = BoardVision()
        self.detector = MoveDetector()
        
        # Game state
        self.game_id: Optional[str] = None
        self.my_color: Optional[str] = None
        self.is_my_turn: bool = False
        self.prev_board_state: Optional[list] = None
        
        print(f"Connected to Lichess as: {self.lichess.username}")
    
    def setup_camera(self) -> bool:
        """
        Connect to camera and calibrate board detection.
        
        Returns:
            True if setup successful
        """
        print("\n=== Camera Setup ===")
        
        # Connect to camera
        if not self.camera.connect():
            print("Failed to connect to phone camera.")
            print(f"Make sure IP Webcam is running at: {self.camera.base_url}")
            return False
        
        print("Camera connected!")
        
        # Calibrate board detection
        print("\nPosition your phone camera above the chessboard.")
        print("The board should be in starting position with pieces.")
        input("Press Enter when ready to calibrate...")
        
        frame = self.camera.capture_frame()
        if frame is None:
            print("Failed to capture frame.")
            return False
        
        # Try automatic calibration first
        print("Attempting automatic board detection...")
        if self.vision.calibrate(frame):
            print("Board detected automatically!")
        else:
            print("Automatic detection failed. Starting manual calibration...")
            print("Click the 4 corners of the board: Top-Left, Top-Right, Bottom-Right, Bottom-Left")
            if not self.vision.interactive_calibration(frame):
                print("Calibration cancelled.")
                return False
        
        # Ask about board orientation
        response = input("\nAre WHITE pieces at the BOTTOM of the camera view? (y/n): ")
        self.vision.set_orientation(response.lower() == 'y')
        
        # Capture initial board state
        self.prev_board_state = self.vision.get_board_state(frame)
        if self.prev_board_state:
            print("Initial board state captured.")
            self._print_board_state(self.prev_board_state)
        
        return True
    
    def start_game(self, time_control: str = None, rated: bool = False) -> bool:
        """
        Start a new game on Lichess.
        
        Args:
            time_control: Time control (e.g., "10+0")
            rated: Whether game is rated
            
        Returns:
            True if game started successfully
        """
        time_control = time_control or DEFAULT_TIME_CONTROL
        
        print(f"\n=== Starting {time_control} {'Rated' if rated else 'Casual'} Game ===")
        self.tts.say("Searching for opponent...")
        
        try:
            game = self.lichess.create_game(time_control, rated)
            self.game_id = game.get('id') or game.get('gameId')
            
            if not self.game_id:
                print("Failed to create game")
                return False
            
            print(f"Game created: https://lichess.org/{self.game_id}")
            return True
            
        except Exception as e:
            print(f"Error creating game: {e}")
            return False
    
    def play_game(self) -> None:
        """
        Main game loop - stream game events and handle moves.
        """
        if not self.game_id:
            print("No active game. Call start_game() first.")
            return
        
        print("\n=== Game Started ===")
        self.tts.announce_game_start()
        
        try:
            for event in self.lichess.stream_game_state(self.game_id):
                if not self._handle_game_event(event):
                    break
        
        except KeyboardInterrupt:
            print("\nGame interrupted by user.")
            response = input("Resign? (y/n): ")
            if response.lower() == 'y':
                self.lichess.resign(self.game_id)
                self.tts.say("You have resigned.")
        
        except Exception as e:
            print(f"Error during game: {e}")
        
        finally:
            self.camera.disconnect()
    
    def _handle_game_event(self, event: dict) -> bool:
        """
        Handle a game event from the stream.
        
        Args:
            event: Event dict from Lichess
            
        Returns:
            True to continue, False to stop
        """
        event_type = event.get('type')
        
        if event_type == 'gameFull':
            # Initial game state
            return self._handle_game_full(event)
        
        elif event_type == 'gameState':
            # Move made
            return self._handle_game_state(event)
        
        elif event_type == 'chatLine':
            # Chat message (optional handling)
            pass
        
        return True
    
    def _handle_game_full(self, event: dict) -> bool:
        """Handle initial game state."""
        # Determine our color
        self.my_color = self.lichess.get_my_color(event)
        is_white = self.my_color == "white"
        
        print(f"\nYou are playing as: {self.my_color.upper()}")
        self.tts.announce_color(is_white)
        
        # Get opponent info
        opponent_key = "black" if is_white else "white"
        opponent = event.get(opponent_key, {})
        opponent_name = opponent.get('name', opponent.get('id', 'Anonymous'))
        print(f"Opponent: {opponent_name}")
        self.tts.say(f"Playing against {opponent_name}")
        
        # Process initial game state
        initial_state = event.get('state', {})
        return self._handle_game_state(initial_state)
    
    def _handle_game_state(self, state: dict) -> bool:
        """Handle game state update (move made)."""
        # Check for game end
        status = state.get('status')
        if status and status != 'started':
            return self._handle_game_end(state)
        
        # Get moves
        moves_str = state.get('moves', '').strip()
        moves = moves_str.split() if moves_str else []
        
        # Sync internal board
        self.detector.reset()
        for move_uci in moves:
            self.detector.apply_move(move_uci)
        
        # Announce last opponent move
        if moves:
            move_count = len(moves)
            is_white_to_move = move_count % 2 == 0
            
            if (self.my_color == "white" and not is_white_to_move) or \
               (self.my_color == "black" and is_white_to_move):
                # Opponent just moved
                last_move = moves[-1]
                # Get SAN before the move was made for proper notation
                self.detector.reset()
                for m in moves[:-1]:
                    self.detector.apply_move(m)
                san = self.detector.get_san(last_move)
                self.detector.apply_move(last_move)
                
                print(f"\nOpponent played: {san} ({last_move})")
                self.tts.announce_move(san)
        
        # Check if it's our turn
        move_count = len(moves)
        is_white_to_move = move_count % 2 == 0
        self.is_my_turn = (self.my_color == "white") == is_white_to_move
        
        if self.is_my_turn:
            self._handle_my_turn()
        
        return True
    
    def _handle_my_turn(self) -> None:
        """Handle our turn - detect and submit move."""
        print("\n--- Your Turn ---")
        self.tts.announce_your_turn()
        
        # Wait for user to make physical move
        print("Make your move on the physical board...")
        print("Press Enter when done (or type move manually, e.g., 'e2e4'):")
        
        user_input = input("> ").strip()
        
        move_uci = None
        
        if user_input:
            # Manual input provided
            move_uci = user_input.lower()
            
            # Handle SAN input (e.g., "Nf3")
            if not self._is_uci_format(move_uci):
                try:
                    chess_move = self.detector.board.parse_san(user_input)
                    move_uci = chess_move.uci()
                except ValueError:
                    print(f"Invalid move: {user_input}")
                    return self._handle_my_turn()  # Retry
        else:
            # Try to detect move from camera
            move_uci = self._detect_move_from_camera()
        
        if not move_uci:
            # Fallback to manual input
            print("Could not detect move. Please enter manually:")
            return self._handle_my_turn()
        
        # Add promotion if needed
        move_uci = self.detector.suggest_promotion(move_uci)
        
        # Validate and submit
        san = self.detector.get_san(move_uci)
        print(f"Submitting move: {san} ({move_uci})")
        
        if self.lichess.make_move(self.game_id, move_uci):
            print("Move accepted!")
            self.detector.apply_move(move_uci)
        else:
            print("Move rejected by Lichess. Try again.")
            return self._handle_my_turn()
    
    def _detect_move_from_camera(self) -> Optional[str]:
        """
        Detect move by comparing board states.
        
        Returns:
            UCI move string, or None if detection failed
        """
        print("Capturing board state...")
        
        # Wait for stable frame (hand removed)
        frame = self.camera.wait_for_stable_frame()
        if frame is None:
            print("Failed to capture stable frame.")
            return None
        
        # Get current board state
        curr_state = self.vision.get_board_state(frame)
        if curr_state is None:
            print("Failed to analyze board.")
            return None
        
        self._print_board_state(curr_state)
        
        if self.prev_board_state is None:
            print("No previous state to compare.")
            self.prev_board_state = curr_state
            return None
        
        # Detect the move
        move = self.detector.detect_move(
            self.prev_board_state, 
            curr_state, 
            self.my_color
        )
        
        # Update previous state
        self.prev_board_state = curr_state
        
        if move:
            print(f"Detected move: {move}")
        else:
            print("Could not detect move from board changes.")
        
        return move
    
    def _handle_game_end(self, state: dict) -> bool:
        """Handle game end."""
        status = state.get('status', 'ended')
        winner = state.get('winner')
        
        print(f"\n=== Game Over ===")
        print(f"Status: {status}")
        
        if winner:
            if winner == self.my_color:
                result = "win"
            else:
                result = "loss"
        else:
            result = "draw"
        
        self.tts.announce_game_end(result, status)
        
        return False  # Stop game loop
    
    def _is_uci_format(self, move: str) -> bool:
        """Check if move is in UCI format (e.g., e2e4)."""
        if len(move) < 4 or len(move) > 5:
            return False
        
        if move[0] not in 'abcdefgh' or move[2] not in 'abcdefgh':
            return False
        
        if move[1] not in '12345678' or move[3] not in '12345678':
            return False
        
        if len(move) == 5 and move[4] not in 'qrbn':
            return False
        
        return True
    
    def _print_board_state(self, state: list) -> None:
        """Print board state for debugging."""
        print("\n  a b c d e f g h")
        for i, row in enumerate(state):
            rank = 8 - i
            print(f"{rank} {' '.join(row)} {rank}")
        print("  a b c d e f g h\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Play Lichess with a physical chessboard"
    )
    parser.add_argument(
        '--token', '-t',
        default=LICHESS_TOKEN,
        help='Lichess API token (or set LICHESS_TOKEN env var)'
    )
    parser.add_argument(
        '--camera', '-c',
        default=CAMERA_URL,
        help='Phone camera URL (e.g., http://192.168.1.100:8080/video)'
    )
    parser.add_argument(
        '--time', '-T',
        default=DEFAULT_TIME_CONTROL,
        help='Time control (e.g., 10+0, 5+3, 3+2)'
    )
    parser.add_argument(
        '--rated', '-r',
        action='store_true',
        help='Play rated game'
    )
    parser.add_argument(
        '--no-camera',
        action='store_true',
        help='Skip camera setup (manual input only)'
    )
    
    args = parser.parse_args()
    
    if not args.token:
        print("ERROR: Lichess API token required.")
        print("Set LICHESS_TOKEN environment variable or use --token flag.")
        print("Get a token at: https://lichess.org/account/oauth/token")
        print("Required scope: board:play")
        sys.exit(1)
    
    # Initialize game
    try:
        game = PhysicalBoardGame(args.token, args.camera)
    except Exception as e:
        print(f"Initialization failed: {e}")
        sys.exit(1)
    
    # Setup camera (unless skipped)
    if not args.no_camera:
        if not game.setup_camera():
            print("\nContinuing with manual input only...")
    
    # Start and play game
    if game.start_game(args.time, args.rated):
        game.play_game()
    else:
        print("Failed to start game.")
        sys.exit(1)


if __name__ == "__main__":
    main()
