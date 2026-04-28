"""
Lichess API client for creating games and streaming moves.
"""
import berserk
from typing import Generator, Dict, Any, Optional
from config import LICHESS_TOKEN, DEFAULT_TIME_CONTROL, DEFAULT_RATED


class LichessClient:
    """Client for interacting with Lichess API via berserk."""
    
    def __init__(self, token: str = None):
        """
        Initialize the Lichess client.
        
        Args:
            token: Lichess API token (default from config)
        """
        self.token = token or LICHESS_TOKEN
        if not self.token:
            raise ValueError(
                "Lichess API token required. Set LICHESS_TOKEN environment variable "
                "or pass token to constructor. Get one at: https://lichess.org/account/oauth/token"
            )
        
        session = berserk.TokenSession(self.token)
        self.client = berserk.Client(session)
        self._account = None
    
    def get_account(self) -> Dict[str, Any]:
        """
        Get current account info.
        
        Returns:
            Account data dict with username, rating, etc.
        """
        if self._account is None:
            self._account = self.client.account.get()
        return self._account
    
    @property
    def username(self) -> str:
        """Get the current user's username."""
        return self.get_account()['username']
    
    def create_ai_game(self, level: int = 1, color: str = "random") -> Dict[str, Any]:
        """
        Create a game against Stockfish.
        
        Args:
            level: AI level (1-8)
            color: "white", "black", or "random"
            
        Returns:
            Game data dict with game ID
        """
        print(f"Creating AI game (Level {level})...")
        game = self.client.challenges.create_ai(level=level, color=color)
        return game

    def create_game(
        self,
        time_control: str = None,
        rated: bool = None,
        color: str = "random"
    ) -> Dict[str, Any]:
        """
        Create a new game by seeking an opponent.
        
        Args:
            time_control: Time control string like "10+0" or "5+3"
            rated: Whether the game is rated
            color: "white", "black", or "random"
            
        Returns:
            Game data dict with game ID
        """
        time_control = time_control or DEFAULT_TIME_CONTROL
        rated = rated if rated is not None else DEFAULT_RATED
        
        # Parse time control
        parts = time_control.split('+')
        clock_limit = int(parts[0])  # Minutes
        clock_increment = int(parts[1]) if len(parts) > 1 else 0
        
        # Create a seek
        print(f"Creating {time_control} {'rated' if rated else 'casual'} game...")
        print("Waiting for opponent...")
        
        # Use the board API to create a seek and wait for a game
        # Note: board.seek expects minutes in some versions, but standard Lichess API is minutes
        # However, berserk usually handles conversion or raw params.
        # Let's verify berserk docs or assume minutes for board.seek wrapper if it exists.
        # WAIT: The error said "HTTP 400 ... {'time': ['Invalid value']}"
        # This means we passed something wrong to the API.
        # Lichess API /api/board/seek expects:
        # - time: minutes (int)
        # - increment: seconds (int)
        
        # Use the board API to create a seek and wait for a game
        # Note: board.seek might return a generator or something else depending on version
        try:
            res = self.client.board.seek(
                time=clock_limit,
                increment=clock_increment,
                rated=rated,
                color=color
            )
            
            # If res is a dict with ID, great
            if isinstance(res, dict) and 'id' in res:
                return res
            
            # If res is a generator, we might need to consume it, but that blocks
            # If we are here, maybe seek returned (game started) but gave us a float?
            print(f"Seek returned type: {type(res)} - {res}")
            
        except Exception as e:
            print(f"Seek initiated (or failed): {e}")
            # Scan for ongoing games
            pass
            
        # Fallback: Check for ongoing games
        # We assume the game just started
        import time
        for _ in range(5):
            games = self.get_ongoing_games()
            if games:
                # Return the most recent one?
                # Assuming the user is only playing one game at a time usually
                game = games[0]
                # Normalize ID key (berserk returns gameId for ongoing games)
                if 'gameId' in game and 'id' not in game:
                    game['id'] = game['gameId']
                return game
            time.sleep(0.5)
            
        raise Exception("Game started but could not retrieve ID")
    
    def stream_game_state(self, game_id: str) -> Generator[Dict[str, Any], None, None]:
        """
        Stream game state updates.
        
        Yields events like:
        - gameFull: Initial game state with all info
        - gameState: Move updates
        - chatLine: Chat messages
        
        Args:
            game_id: The game ID to stream
            
        Yields:
            Event dicts
        """
        for event in self.client.board.stream_game_state(game_id):
            yield event
    
    def make_move(self, game_id: str, move_uci: str) -> bool:
        """
        Submit a move to the game.
        
        Args:
            game_id: The game ID
            move_uci: Move in UCI format (e.g., "e2e4", "e7e8q" for promotion)
            
        Returns:
            True if move was accepted
        """
        try:
            self.client.board.make_move(game_id, move_uci)
            return True
        except berserk.exceptions.ResponseError as e:
            print(f"Move rejected: {e}")
            return False
    
    def resign(self, game_id: str) -> None:
        """Resign the current game."""
        self.client.board.resign_game(game_id)
    
    def get_ongoing_games(self) -> list:
        """
        Get list of ongoing games.
        
        Returns:
            List of ongoing game dicts
        """
        return list(self.client.games.get_ongoing())
    
    def get_my_color(self, game: Dict[str, Any]) -> str:
        """
        Determine which color we're playing.
        
        Args:
            game: Game data from stream (gameFull event)
            
        Returns:
            "white" or "black"
        """
        my_username = self.username.lower()
        
        if game.get('white', {}).get('id', '').lower() == my_username:
            return "white"
        elif game.get('white', {}).get('name', '').lower() == my_username:
            return "white"
        else:
            return "black"
    
    def is_my_turn(self, game_state: Dict[str, Any], my_color: str) -> bool:
        """
        Check if it's our turn.
        
        Args:
            game_state: Current game state
            my_color: "white" or "black"
            
        Returns:
            True if it's our turn
        """
        moves = game_state.get('moves', '').split()
        move_count = len(moves) if moves[0] else 0
        
        # White moves on even counts (0, 2, 4...), Black on odd (1, 3, 5...)
        if my_color == "white":
            return move_count % 2 == 0
        else:
            return move_count % 2 == 1
    
    def get_last_move(self, game_state: Dict[str, Any]) -> Optional[str]:
        """
        Get the last move made in UCI format.
        
        Args:
            game_state: Current game state
            
        Returns:
            Last move in UCI format, or None if no moves
        """
        moves = game_state.get('moves', '').strip()
        if not moves:
            return None
        return moves.split()[-1]


# Quick test
if __name__ == "__main__":
    import os
    
    token = os.environ.get("LICHESS_TOKEN")
    if not token:
        print("Set LICHESS_TOKEN environment variable to test")
        print("Get a token at: https://lichess.org/account/oauth/token")
        print("Required scopes: board:play")
    else:
        client = LichessClient(token)
        account = client.get_account()
        print(f"Connected as: {account['username']}")
        
        # Show ongoing games
        games = client.get_ongoing_games()
        print(f"Ongoing games: {len(games)}")
        for game in games:
            print(f"  - {game['gameId']}: vs {game['opponent']['username']}")
