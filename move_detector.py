"""
Move detection by comparing board states.
"""
import chess
from typing import Optional, List, Tuple


class MoveDetector:
    """
    Detects chess moves by comparing board states.
    
    Uses python-chess for move validation and notation.
    """
    
    def __init__(self):
        """Initialize the move detector."""
        self.board = chess.Board()
    
    def reset(self) -> None:
        """Reset to starting position."""
        self.board.reset()
    
    def set_position(self, fen: str) -> None:
        """
        Set board to a specific position.
        
        Args:
            fen: Position in FEN notation
        """
        self.board.set_fen(fen)
    
    def apply_move(self, move_uci: str) -> bool:
        """
        Apply a move to the internal board state.
        
        Args:
            move_uci: Move in UCI format (e.g., "e2e4")
            
        Returns:
            True if move was legal and applied
        """
        try:
            move = chess.Move.from_uci(move_uci)
            if move in self.board.legal_moves:
                self.board.push(move)
                return True
        except ValueError:
            pass
        return False
    
    def detect_move_from_diffs(
        self,
        diffs: List[float],
        flipped: bool = False,
        threshold: float = 0.1,
        expected_squares: List[int] = None
    ) -> Optional[str]:
        """
        Detect move using 'top 2 changed squares' approach.
        
        Logic:
        1. Find the 2-4 squares with the HIGHEST diff scores
        2. Filter to keep only those above threshold
        3. Map to chess squares
        4. Find a legal move that uses exactly those squares
        """
        if expected_squares is None:
            expected_squares = []
        expected_set = set(expected_squares)
        
        # Sort squares by diff score (highest first)
        indexed_diffs = [(i, score) for i, score in enumerate(diffs)]
        sorted_diffs = sorted(indexed_diffs, key=lambda x: x[1], reverse=True)
        
        # Take top changed squares (above threshold)
        top_changed = [(i, s) for i, s in sorted_diffs if s > threshold]
        
        # Need at least 2 squares (from and to)
        if len(top_changed) < 2:
            return None
            
        # Convert visual indices to chess squares
        def visual_to_chess(idx):
            row = idx // 8
            col = idx % 8
            if flipped:
                rank_idx = row
                file_idx = 7 - col
            else:
                rank_idx = 7 - row
                file_idx = col
            return chess.square(file_idx, rank_idx)
        
        # Get all changed chess squares
        changed_squares = [visual_to_chess(i) for i, _ in top_changed]
        changed_set = set(changed_squares)
        
        # Debug: Print the chess square names
        square_names = [chess.square_name(sq) for sq in changed_squares[:5]]
        print(f"DEBUG: Top changed squares mapped to chess: {square_names}")
        
        # Subtract expected squares (opponent's move) to get MY move squares
        my_changed = changed_set - expected_set
        
        # If after removing expected, we have less than 2 squares, use all
        if len(my_changed) < 2:
            my_changed = changed_set
        
        # Find a legal move where from_square AND to_square are in my_changed
        for move in self.board.legal_moves:
            from_sq = move.from_square
            to_sq = move.to_square
            
            if from_sq in my_changed and to_sq in my_changed:
                return move.uci()
        
        # Fallback: Try all changed squares (including expected)
        for move in self.board.legal_moves:
            if move.from_square in changed_set and move.to_square in changed_set:
                return move.uci()
        
        return None
        
    def detect_move_from_scores(
        self,
        scores: dict,
        board: chess.Board
    ) -> Optional[str]:
        """
        Detect move using analog intensity scores.
        
        Args:
            scores: Dict {square: intensity_0_to_255}
            board: Current board state
            
        Returns:
            Best matching UCI move, or None.
        """
        DEST_THRESHOLD = 15.0 # Significant change (Piece arriving/hand moving)
        SOURCE_THRESHOLD = 10.0 # Raised: Source must show clear change, not just shadow
        SOURCE_STRONG = 50.0   # If source is this strong, it's definitely the real source
        
        # 1. Find potential destinations
        dest_candidates = []
        for sq_name, score in scores.items():
            if score > DEST_THRESHOLD:
                try:
                    sq = chess.parse_square(sq_name)
                    dest_candidates.append((sq, score))
                except: pass
        
        best_move = None
        best_confidence = 0.0
        
        # 2. Evaluate all legal moves ending on these candidates
        print(f"DEBUG: Checking {len(dest_candidates)} potential destinations: {dest_candidates}")
        for dest_sq, dest_score in dest_candidates:
            for move in board.legal_moves:
                if move.to_square == dest_sq:
                    # Check Source Score
                    from_name = chess.square_name(move.from_square)
                    source_score = scores.get(from_name, 0.0)
                    
                    print(f"DEBUG: Found legal move {move.uci()} to dest {chess.square_name(dest_sq)} ({dest_score}). Source {from_name} ({source_score})")
                    
                    if source_score > SOURCE_THRESHOLD:
                        # Weight source heavily - a piece leaving is more distinctive
                        # Multiply source by 2 so strong sources dominate
                        confidence = dest_score + (source_score * 2)
                        
                        # Big bonus for STRONG source (definitely the real move)
                        if source_score >= SOURCE_STRONG:
                            confidence += 100
                        
                        # Bonus for castling (Rook moves too)
                        if board.is_castling(move):
                            confidence += 20 
                        
                        print(f"DEBUG:   -> Valid Candidate. Confidence: {confidence}")
                        
                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_move = move
                    else:
                        print(f"DEBUG:   -> Rejected (Weak Source)")
                        
        if best_move:
             return best_move.uci()
             
        return None

    def detect_move_from_squares(
        self,
        active_squares: List[str],
        board: chess.Board,
        weak_squares: List[str] = None
    ) -> Optional[str]:
        """
        Legacy/Binary method: Detect move from lists of active squares.
        Wrapper around score-based logic or standalone implementation.
        """
        if not active_squares: return None
        if weak_squares is None: weak_squares = []
        
        # Convert lists to dummy scores for usage 
        # Strong = 100, Weak = 10
        scores = {}
        # 1. Initialize Weak Scores First (Base layer)
        for s in weak_squares: scores[s] = 10.0
        
        # 2. Overwrite with Strong Scores (Top layer)
        for s in active_squares: scores[s] = 100.0
        
        # Reuse the robust score-based logic! 
        # This keeps our "Destination First" + "Source verification" logic
        # without duplicating code.
        return self.detect_move_from_scores(scores, board)

    def detect_move(
        self,
        prev_state: List[List[str]],
        curr_state: List[List[str]],
        my_color: str = "white"
    ) -> Optional[str]:
        """
        Detect a move by comparing two board states.
        
        Args:
            prev_state: Previous 8x8 board state ('w', 'b', '.')
            curr_state: Current 8x8 board state
            my_color: "white" or "black" (player making the move)
            
        Returns:
            Move in UCI format, or None if detection failed
        """
        # Find squares that changed
        changes = self._find_changes(prev_state, curr_state)
        
        if not changes:
            return None
        
        # Determine piece color that moved
        piece_color = 'w' if my_color == "white" else 'b'
        
        # Analyze changes to determine move
        move = self._analyze_changes(changes, prev_state, curr_state, piece_color)
        
        if move:
            # Validate move is legal
            try:
                chess_move = chess.Move.from_uci(move)
                if chess_move in self.board.legal_moves:
                    return move
            except ValueError:
                pass
        
        # Try to find any legal move that matches the changes
        return self._find_matching_legal_move(changes, prev_state, curr_state, piece_color)
    
    def _find_changes(
        self,
        prev_state: List[List[str]],
        curr_state: List[List[str]]
    ) -> List[Tuple[int, int, str, str]]:
        """
        Find all squares that changed between states.
        
        Returns:
            List of (row, col, old_value, new_value)
        """
        changes = []
        for row in range(8):
            for col in range(8):
                old = prev_state[row][col]
                new = curr_state[row][col]
                if old != new:
                    changes.append((row, col, old, new))
        return changes
    
    def _analyze_changes(
        self,
        changes: List[Tuple[int, int, str, str]],
        prev_state: List[List[str]],
        curr_state: List[List[str]],
        piece_color: str
    ) -> Optional[str]:
        """
        Analyze changes to determine the move.
        
        Args:
            changes: List of changed squares
            prev_state: Previous board state
            curr_state: Current board state
            piece_color: 'w' or 'b'
            
        Returns:
            Move in UCI format, or None
        """
        # Normal move: 2 squares change
        # - Source: piece -> empty
        # - Dest: empty/enemy -> piece
        
        if len(changes) == 2:
            # Find source and destination
            source = None
            dest = None
            
            for row, col, old, new in changes:
                if old == piece_color and new == '.':
                    source = (row, col)
                elif new == piece_color:
                    dest = (row, col)
            
            if source and dest:
                return self._coords_to_uci(source, dest)
        
        # Castling: 4 squares change (king + rook)
        elif len(changes) == 4:
            return self._detect_castling(changes, piece_color)
        
        # En passant: 3 squares change
        elif len(changes) == 3:
            return self._detect_en_passant(changes, piece_color)
        
        return None
    
    def _detect_castling(
        self,
        changes: List[Tuple[int, int, str, str]],
        piece_color: str
    ) -> Optional[str]:
        """Detect castling moves."""
        # Find king movement
        king_row = 7 if piece_color == 'w' else 0
        
        sources = []
        dests = []
        
        for row, col, old, new in changes:
            if row == king_row:
                if old == piece_color:
                    sources.append(col)
                if new == piece_color:
                    dests.append(col)
        
        # Kingside: king e->g, rook h->f
        if 4 in sources and 7 in sources and 6 in dests and 5 in dests:
            return f"e{8-king_row}g{8-king_row}"
        
        # Queenside: king e->c, rook a->d
        if 4 in sources and 0 in sources and 2 in dests and 3 in dests:
            return f"e{8-king_row}c{8-king_row}"
        
        return None
    
    def _detect_en_passant(
        self,
        changes: List[Tuple[int, int, str, str]],
        piece_color: str
    ) -> Optional[str]:
        """Detect en passant capture."""
        enemy_color = 'b' if piece_color == 'w' else 'w'
        
        source = None
        dest = None
        captured = None
        
        for row, col, old, new in changes:
            if old == piece_color and new == '.':
                source = (row, col)
            elif old == '.' and new == piece_color:
                dest = (row, col)
            elif old == enemy_color and new == '.':
                captured = (row, col)
        
        if source and dest and captured:
            # En passant: pawn moves diagonally, captured pawn is on different row
            if dest[1] == captured[1]:  # Same column
                return self._coords_to_uci(source, dest)
        
        return None
    
    def _find_matching_legal_move(
        self,
        changes: List[Tuple[int, int, str, str]],
        prev_state: List[List[str]],
        curr_state: List[List[str]],
        piece_color: str
    ) -> Optional[str]:
        """
        Find a legal move that matches the detected changes.
        
        Falls back to checking all legal moves against the changes.
        """
        changed_squares = set()
        for row, col, _, _ in changes:
            square_name = self._coords_to_square(row, col)
            changed_squares.add(chess.parse_square(square_name))
        
        for move in self.board.legal_moves:
            move_squares = {move.from_square, move.to_square}
            
            # For castling, add rook squares
            if self.board.is_castling(move):
                if self.board.is_kingside_castling(move):
                    move_squares.add(move.from_square + 3)  # Rook from
                    move_squares.add(move.from_square + 1)  # Rook to
                else:
                    move_squares.add(move.from_square - 4)  # Rook from
                    move_squares.add(move.from_square - 1)  # Rook to
            
            # For en passant, add captured pawn square
            if self.board.is_en_passant(move):
                # Captured pawn is on the from_square row, to_square file
                captured = chess.square(chess.square_file(move.to_square),
                                       chess.square_rank(move.from_square))
                move_squares.add(captured)
            
            if move_squares == changed_squares:
                return move.uci()
        
        return None
    
    def _coords_to_uci(self, source: Tuple[int, int], dest: Tuple[int, int]) -> str:
        """
        Convert board coordinates to UCI move notation.
        
        Args:
            source: (row, col) of source square
            dest: (row, col) of destination square
            
        Returns:
            UCI move string
        """
        from_sq = self._coords_to_square(source[0], source[1])
        to_sq = self._coords_to_square(dest[0], dest[1])
        return from_sq + to_sq
    
    def _coords_to_square(self, row: int, col: int) -> str:
        """
        Convert row/col to algebraic square name.
        
        Row 0 = rank 8 (top), Row 7 = rank 1 (bottom)
        Col 0 = file a (left), Col 7 = file h (right)
        """
        file = chr(ord('a') + col)
        rank = str(8 - row)
        return file + rank
    
    def get_san(self, move_uci: str) -> str:
        """
        Convert UCI move to Standard Algebraic Notation.
        
        Args:
            move_uci: Move in UCI format
            
        Returns:
            Move in SAN format (e.g., "Nf3")
        """
        try:
            move = chess.Move.from_uci(move_uci)
            return self.board.san(move)
        except (ValueError, chess.IllegalMoveError):
            return move_uci
    
    def get_legal_moves(self) -> List[str]:
        """Get all legal moves in current position."""
        return [move.uci() for move in self.board.legal_moves]
    
    def is_game_over(self) -> bool:
        """Check if the game is over."""
        return self.board.is_game_over()
    
    def get_result(self) -> Optional[str]:
        """
        Get game result if game is over.
        
        Returns:
            "1-0", "0-1", "1/2-1/2", or None
        """
        if self.board.is_checkmate():
            return "0-1" if self.board.turn == chess.WHITE else "1-0"
        elif self.board.is_stalemate() or self.board.is_insufficient_material():
            return "1/2-1/2"
        return None
    
    def suggest_promotion(self, move_uci: str) -> str:
        """
        Add promotion to a pawn move if needed.
        
        Args:
            move_uci: Move without promotion (e.g., "e7e8")
            
        Returns:
            Move with promotion if applicable (e.g., "e7e8q")
        """
        if len(move_uci) != 4:
            return move_uci
        
        try:
            from_sq = chess.parse_square(move_uci[:2])
            to_sq = chess.parse_square(move_uci[2:4])
            
            piece = self.board.piece_at(from_sq)
            if piece and piece.piece_type == chess.PAWN:
                to_rank = chess.square_rank(to_sq)
                if to_rank == 7 or to_rank == 0:
                    # Pawn reaching last rank - default to queen
                    return move_uci + 'q'
        except ValueError:
            pass
        
        return move_uci


# Quick test
if __name__ == "__main__":
    detector = MoveDetector()
    
    # Simulate detecting e2-e4
    initial_state = [
        ['b', 'b', 'b', 'b', 'b', 'b', 'b', 'b'],  # Rank 8
        ['b', 'b', 'b', 'b', 'b', 'b', 'b', 'b'],  # Rank 7 (black pawns)
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['w', 'w', 'w', 'w', 'w', 'w', 'w', 'w'],  # Rank 2 (white pawns)
        ['w', 'w', 'w', 'w', 'w', 'w', 'w', 'w'],  # Rank 1
    ]
    
    after_e4 = [
        ['b', 'b', 'b', 'b', 'b', 'b', 'b', 'b'],
        ['b', 'b', 'b', 'b', 'b', 'b', 'b', 'b'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', 'w', '.', '.', '.'],  # e4 pawn
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['w', 'w', 'w', 'w', '.', 'w', 'w', 'w'],  # e2 empty
        ['w', 'w', 'w', 'w', 'w', 'w', 'w', 'w'],
    ]
    
    move = detector.detect_move(initial_state, after_e4, "white")
    print(f"Detected move: {move}")
    print(f"SAN notation: {detector.get_san(move)}")
