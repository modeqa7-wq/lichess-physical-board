import cv2
import numpy as np
from typing import Optional, Tuple, List
from config import BOARD_SIZE
import os
import json

class BoardVision:
    """
    Computer vision system for detecting chessboard state.
    
    Uses color-based detection to identify:
    - Board boundaries and orientation
    - Piece presence on each square
    - Piece color (white/black)
    """
    
    def __init__(self):
        """Initialize the board vision system."""
        self.board_corners: Optional[np.ndarray] = None
        self.perspective_matrix: Optional[np.ndarray] = None
        self.square_size: int = 160  # Pixels per square after perspective transform (increased for better detection)
        self.board_image_size = self.square_size * BOARD_SIZE  # 1280x1280

        # Lens distortion parameters
        self.camera_matrix: Optional[np.ndarray] = None
        self.dist_coeffs: Optional[np.ndarray] = None
        
        # Color detection thresholds (HSV)
        # These may need tuning based on your board/lighting
        self.white_piece_lower = np.array([0, 0, 180])
        self.white_piece_upper = np.array([180, 50, 255])
        
        self.black_piece_lower = np.array([0, 0, 0])
        self.black_piece_upper = np.array([180, 255, 80])
        
        # Minimum piece area (% of square) to consider occupied
        self.min_piece_area = 0.15
        
        # Board orientation: False = a1 at bottom-left, True = a1 at top-right
        self.flipped = False
        
        
        # Polygon Storage
        self.sq_polygons = {} # "a1": [ [x,y], [x,y], ... ]
        
        # Determine script directory reliably to avoid CWD/Permission errors
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.sqdict_path = os.path.join(self.base_dir, "sqdict.json")
        
        # Calibration file path for lens (optional, kept for legacy)
        self.calibration_file = os.path.join(self.base_dir, "camera_calibration.npz") 
    
    def save_sqdict(self) -> bool:
        """Save the 64 square polygons to sqdict.json."""
        try:
            # Convert numpy arrays to lists for JSON serialization
            data = {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in self.sq_polygons.items()}
            with open(self.sqdict_path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Failed to save sqdict: {e}")
            return False

    def load_sqdict(self) -> bool:
        """Load square polygons from sqdict.json."""
        try:
            if not os.path.exists(self.sqdict_path): return False
            with open(self.sqdict_path, 'r') as f:
                data = json.load(f)
                self.sq_polygons = {k: np.array(v, dtype=np.int32) for k, v in data.items()}
                return True
        except Exception as e:
            print(f"Failed to load sqdict: {e}")
        return False

    def manual_calibrate(self, corners: list) -> bool:
        """
        Generate 64 polygons from 4 corner points using Homography.
        Args: corners: [(x,y), (x,y), (x,y), (x,y)] -> TL, TR, BR, BL
        """
        if len(corners) != 4: return False
        
        # 1. Source Points (Logical 8x8 Grid)
        # We define 0,0 as Top-Left of the board (User's script logic)
        src = np.array([[0,0], [8,0], [8,8], [0,8]], dtype=np.float32)
        dst = np.array(corners, dtype=np.float32)
        
        # 2. Compute Homography: Logical -> Screen
        H = cv2.getPerspectiveTransform(src, dst)
        
        # 3. Generate Grid Points
        src_grid = np.array([[[x, y] for x in range(9)] for y in range(9)], dtype=np.float32)
        dst_grid = cv2.perspectiveTransform(src_grid.reshape(-1, 1, 2), H).reshape(9, 9, 2)
        
        # 4. Create Polygons for each square
        # Notation mapping: a-h (cols), 1-8 (rows)
        # User script: r=0 is rank 8! (Top row)
        files = 'abcdefgh'
        ranks = '87654321' # Top row is Rank 8
        
        self.sq_polygons = {}
        
        for r in range(8):
            for c in range(8):
                # Polygon corners
                p1 = dst_grid[r, c]
                p2 = dst_grid[r, c+1]
                p3 = dst_grid[r+1, c+1]
                p4 = dst_grid[r+1, c]
                
                poly = np.array([p1, p2, p3, p4], dtype=np.int32)
                
                # Default mapping (Unrotated)
                sq_name = f"{files[c]}{ranks[r]}"
                self.sq_polygons[sq_name] = poly
                
        return self.save_sqdict()

    def get_active_square(self, point: Tuple[int, int]) -> Optional[str]:
        """Find which square contains the given point."""
        if not self.sq_polygons: return None
        
        for sq, poly in self.sq_polygons.items():
            if cv2.pointPolygonTest(poly, point, False) >= 0:
                return sq
        return None

    def visualize_grid(self, frame: np.ndarray, scores: dict = None) -> np.ndarray:
        """
        Draw the grid on the frame for UI.
        If 'scores' is provided {sq: val}, overlay the values.
        """
        vis = frame.copy()
        if not self.sq_polygons: return vis
        
        # Draw Polygons
        for sq, poly in self.sq_polygons.items():
            pts = poly.reshape((-1, 1, 2))
            cv2.polylines(vis, [pts], True, (0, 255, 255), 1)
            
            # Draw DEBUG Scores
            if scores and sq in scores:
                score_val = scores[sq]
                
                # Center calculation
                M = cv2.moments(poly)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    
                    # Color Logic: Green if "Active", Red if "Inactive", Yellow if "Weak"
                    if score_val > 15:
                        color = (0, 255, 0) # Green (Strong)
                    elif score_val > 3:
                        color = (0, 255, 255) # Yellow (Weak)
                    else:
                        color = (0, 0, 255) # Red (Noise)
                        
                    # Text
                    text = f"{int(score_val)}"
                    cv2.putText(vis, text, (cX - 10, cY + 5), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
                                
        return vis

    
    def save_calibration(self) -> bool:
        """Save calibration data to file."""
        data = {
            'flipped': self.flipped
        }
        
        if self.board_corners is not None and self.perspective_matrix is not None:
             data['corners'] = self.board_corners
             data['matrix'] = self.perspective_matrix
             
        if self.camera_matrix is not None and self.dist_coeffs is not None:
            data['camera_matrix'] = self.camera_matrix
            data['dist_coeffs'] = self.dist_coeffs
            
        np.savez(self.calibration_file, **data)
        return True
    
    def load_calibration(self) -> bool:
        """Load calibration data from file."""
        try:
            data = np.load(self.calibration_file)
            if 'corners' in data: self.board_corners = data['corners']
            if 'matrix' in data: self.perspective_matrix = data['matrix']
            if 'camera_matrix' in data: self.camera_matrix = data['camera_matrix']
            if 'dist_coeffs' in data: self.dist_coeffs = data['dist_coeffs']
            self.flipped = bool(data['flipped'])
            return True
        except:
            return False
    
        return True
    


    
    def calibrate_lens(self, frames: List[np.ndarray]) -> Tuple[bool, float]:
        """
        Perform camera lens calibration using multiple chessboard frames.
        
        Args:
            frames: List of frames containing the chessboard in different poses.
                    Ideally 10+ frames.
        
        Returns:
            (success, error_score)
        """
        # Prepare object points (0,0,0), (1,0,0), (2,0,0) ...
        # (7x7 internal corners)
        objp = np.zeros((7*7, 3), np.float32)
        objp[:, :2] = np.mgrid[0:7, 0:7].T.reshape(-1, 2)
        
        objpoints = [] # 3d point in real world space
        imgpoints = [] # 2d points in image plane
        
        h, w = frames[0].shape[:2]
        
        success_count = 0
        
        for frame in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Find the chess board corners
            ret, corners = cv2.findChessboardCorners(gray, (7, 7), None)
            
            if ret:
                objpoints.append(objp)
                
                corners2 = cv2.cornerSubPix(
                    gray, corners, (11, 11), (-1, -1),
                    (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
                )
                imgpoints.append(corners2)
                success_count += 1
                
        if success_count < 5:
            print(f"Calibration failed: not enough good frames (found {success_count})")
            return False, 999.0
            
        print(f"Calibrating lens with {success_count} frames...")
        
        try:
            ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
                objpoints, imgpoints, (w, h), None, None
            )
            
            if ret:
                self.camera_matrix = mtx
                self.dist_coeffs = dist
                
                # Calculate re-projection error
                mean_error = 0
                for i in range(len(objpoints)):
                    imgpoints2, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], mtx, dist)
                    error = cv2.norm(imgpoints[i], imgpoints2, cv2.NORM_L2)/len(imgpoints2)
                    mean_error += error
                
                total_error = mean_error / len(objpoints)
                return True, total_error
            
        except Exception as e:
            print(f"Calibration crashed: {e}")
            
        return False, 999.0

    def undistort_frame(self, frame: np.ndarray) -> np.ndarray:
        """Apply lens distortion correction to frame."""
        if self.camera_matrix is None or self.dist_coeffs is None:
            return frame
            
        h, w = frame.shape[:2]
        newcameramtx, roi = cv2.getOptimalNewCameraMatrix(
            self.camera_matrix, self.dist_coeffs, (w, h), 1, (w, h)
        )
        
        # undistort
        dst = cv2.undistort(frame, self.camera_matrix, self.dist_coeffs, None, newcameramtx)
        
        # crop the image (optional, sometimes optimal matrix adds black borders)
        x, y, w, h = roi
        if w > 0 and h > 0:
             dst = dst[y:y+h, x:x+w]
             
        return dst

    def _detect_board_corners(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Automatically detect chessboard corners.
        
        Args:
            frame: Camera frame
            
        Returns:
            4 corner points or None if detection failed
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Try to find chessboard corners using OpenCV's built-in
        # This looks for inner corners of the 7x7 grid
        ret, corners = cv2.findChessboardCorners(gray, (7, 7), None)
        
        if ret:
            # Refine corners
            corners = cv2.cornerSubPix(
                gray, corners, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            )
            
            # Extract outer corners from the inner grid
            # The chessboard finder gives us inner corners (7x7 = 49 points)
            # We need to extrapolate to get the board edges
            reshaped_corners = corners.reshape(7, 7, 2)
            
            # Estimate outer corners by extrapolation
            top_left = self._extrapolate_corner(reshaped_corners[0, 0], reshaped_corners[0, 1], reshaped_corners[1, 0])
            top_right = self._extrapolate_corner(reshaped_corners[0, 6], reshaped_corners[0, 5], reshaped_corners[1, 6])
            bottom_right = self._extrapolate_corner(reshaped_corners[6, 6], reshaped_corners[6, 5], reshaped_corners[5, 6])
            bottom_left = self._extrapolate_corner(reshaped_corners[6, 0], reshaped_corners[6, 1], reshaped_corners[5, 0])
            
            final_corners = np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)
            
            # SANITY CHECK: Minimum area
            # Calculate area of the quadrilateral
            # Split into two triangles: (TL, TR, BL) and (TR, BR, BL)
            def triangle_area(p1, p2, p3):
                return 0.5 * abs(p1[0]*(p2[1]-p3[1]) + p2[0]*(p3[1]-p1[1]) + p3[0]*(p1[1]-p2[1]))
            
            area = triangle_area(top_left, top_right, bottom_left) + triangle_area(top_right, bottom_right, bottom_left)
            frame_area = frame.shape[0] * frame.shape[1]
            
            # If board is less than 3% of the frame, it's likely noise
            if area < frame_area * 0.03:
                print(f"DEBUG: Chessboard corners found but too small! Area: {area:.0f}, Threshold: {frame_area * 0.03:.0f}")
                return self._detect_board_by_contours(frame)
            
            print(f"DEBUG: Chessboard corners accepted. Area: {area:.0f}")
            return final_corners
        
        print("DEBUG: findChessboardCorners failed. Trying contours...")
        # Fallback: try contour-based detection
        return self._detect_board_by_contours(frame)
    
    
    def compute_ssim(self, img1, img2):
        """
        Compute Structural Similarity Index (SSIM) map using OpenCV.
        Returns the SSIM map (same size as input), value range [0, 1].
        """
        C1 = 6.5025
        C2 = 58.5225
        
        # Ensure images are floats [0, 255]
        img1 = img1.astype(np.float64)
        img2 = img2.astype(np.float64)
        
        kernel = (11, 11)
        sigma = 1.5
        
        mu1 = cv2.GaussianBlur(img1, kernel, sigma)
        mu2 = cv2.GaussianBlur(img2, kernel, sigma)
        
        mu1_sq = mu1 * mu1
        mu2_sq = mu2 * mu2
        mu1_mu2 = mu1 * mu2
        
        sigma1_sq = cv2.GaussianBlur(img1*img1, kernel, sigma) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(img2*img2, kernel, sigma) - mu2_sq
        sigma12 = cv2.GaussianBlur(img1*img2, kernel, sigma) - mu1_mu2
        
        ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))
        return ssim_map

    def get_motion_squares(self, baseline: np.ndarray, current: np.ndarray, threshold=20) -> List[str]:
        """
        Detect which squares have motion using SSIM (Structural Similarity).
        Replaces 'Threshold' (0-255) with 'Sensitivity' logic.
        
        Threshold here is interpreted roughly:
        - 20 means ~20/100 -> 0.2 structural difference index.
        """
        if baseline is None or current is None: return []
        
        # 1. Preprocess
        g1 = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        
        # 2. Compute SSIM
        # SSIM map: 1.0 = Identical, 0.0 = Different
        ssim_map = self.compute_ssim(g1, g2)
        
        # Diff map: 0.0 = Identical, 1.0 = Different
        diff_map = 1.0 - ssim_map
        
        detected_squares = []
        
        if not self.sq_polygons: return []
        
        # Convert user's 0-255 threshold to 0.0-1.0 float
        # Threshold 20 (Binary) -> 0.2 SSIM diff?
        # Actually, SSIM diff is usually small.
        # Let's map 20 -> 0.15 (15% change)
        
        float_thresh = threshold / 100.0
        if float_thresh > 0.8: float_thresh = 0.8 # Cap
        
        for sq, poly in self.sq_polygons.items():
            # Create mask
            mask = np.zeros_like(g1, dtype=np.uint8)
            cv2.fillPoly(mask, [poly], 255)
            
            # Mean SSIM Diff in this square
            # We want the AVERAGE difference.
            score = cv2.mean(diff_map, mask=mask)[0]
            
            if score > float_thresh:
                detected_squares.append(sq)
                
        return detected_squares

    def get_square_intensities(self, baseline: np.ndarray, current: np.ndarray) -> dict:
        """
        Get SSIM-based intensity score (0-100) for each square.
        """
        if baseline is None or current is None: return {}
        
        g1 = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        
        ssim_map = self.compute_ssim(g1, g2)
        diff_map = 1.0 - ssim_map
        
        scores = {}
        if not self.sq_polygons: return scores
        
        for sq, poly in self.sq_polygons.items():
            mask = np.zeros_like(g1, dtype=np.uint8)
            cv2.fillPoly(mask, [poly], 255)
            
            mean_diff = cv2.mean(diff_map, mask=mask)[0]
            # Convert 0.0-1.0 to 0-100 scale
            scores[sq] = mean_diff * 100.0
            
        return scores
    
    def _detect_board_by_contours(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Detect board using contour detection (fallback method).
        
        Args:
            frame: Camera frame
            
        Returns:
            4 corner points or None
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Apply Gaussian blur
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Edge detection - Lower thresholds for dark-on-dark contrast
        edges = cv2.Canny(blurred, 30, 100)
        
        # Dilate edges to connect broken lines (e.g. hinge or low contrast gap)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            print("DEBUG: No contours found.")
            return None
        
        # Find the largest quadrilateral contour
        frame_area = frame.shape[0] * frame.shape[1]
        print(f"DEBUG: Found {len(contours)} contours. Frame area: {frame_area}. Threshold: {frame_area * 0.03:.0f}")
        
        for i, contour in enumerate(sorted(contours, key=cv2.contourArea, reverse=True)):
            area = cv2.contourArea(contour)
            # Check minimum area
            if area < frame_area * 0.03:
                if i < 3: print(f"DEBUG: Contour {i} rejected. Area: {area:.0f} (Too small)")
                continue

            # Simplify contour using Convex Hull (handles notches/irregularities)
            hull = cv2.convexHull(contour)
            
            # Approximate the contour with increasing epsilon until we get 4 corners
            corners = None
            for factor in [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]:
                epsilon = factor * cv2.arcLength(hull, True)
                approx = cv2.approxPolyDP(hull, epsilon, True)
                
                if len(approx) == 4:
                    print(f"DEBUG: Found Quad Contour {i} with epsilon factor {factor}. Area: {area:.0f}. Accepted.")
                    corners = approx.reshape(4, 2).astype(np.float32)
                    break
            
            if corners is not None:
                print(f"DEBUG: Found Quad Contour {i}. Area: {area:.0f}. Accepted.")
                # Found a quadrilateral
                corners = approx.reshape(4, 2).astype(np.float32)
                
                # Order corners: top-left, top-right, bottom-right, bottom-left
                corners = self._order_corners(corners)
                return corners
            else:
                 if i < 3: print(f"DEBUG: Contour {i} has {len(approx)} sides. Area: {area:.0f}")
        
        return None
    
    def _order_corners(self, corners: np.ndarray) -> np.ndarray:
        """
        Order corners in consistent order: TL, TR, BR, BL.
        
        Args:
            corners: 4 corner points in any order
            
        Returns:
            Corners in standard order
        """
        # Sort by sum of coordinates (top-left has smallest sum)
        s = corners.sum(axis=1)
        diff = np.diff(corners, axis=1).flatten()
        
        ordered = np.zeros((4, 2), dtype=np.float32)
        ordered[0] = corners[np.argmin(s)]      # Top-left
        ordered[2] = corners[np.argmax(s)]      # Bottom-right
        ordered[1] = corners[np.argmin(diff)]   # Top-right
        ordered[3] = corners[np.argmax(diff)]   # Bottom-left
        
        return ordered
    
    def get_bird_eye_view(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Transform frame to bird's eye view of the board.
        
        Args:
            frame: Camera frame
            
        Returns:
            Transformed board image, or None if not calibrated
        """
        if self.perspective_matrix is None:
            return None
        
        return cv2.warpPerspective(
            frame, 
            self.perspective_matrix,
            (self.board_image_size, self.board_image_size)
        )
    
    def get_board_state(self, frame: np.ndarray) -> Optional[List[List[str]]]:
        """
        Analyze frame and return board state.
        
        Args:
            frame: Camera frame
            
        Returns:
            8x8 list where each cell is:
            - 'w': White piece
            - 'b': Black piece  
            - '.': Empty square
            Returns None if analysis failed.
        """
        bird_eye = self.get_bird_eye_view(frame)
        if bird_eye is None:
            return None
        
        state = []
        
        for row in range(BOARD_SIZE):
            row_state = []
            for col in range(BOARD_SIZE):
                # Calculate square boundaries
                x1 = col * self.square_size
                y1 = row * self.square_size
                x2 = x1 + self.square_size
                y2 = y1 + self.square_size
                
                # Extract square image
                square = bird_eye[y1:y2, x1:x2]
                
                # Analyze square
                piece = self._analyze_square(square, row, col)
                row_state.append(piece)
            
            state.append(row_state)
        
        # Flip if board is oriented differently
        if self.flipped:
            state = [row[::-1] for row in state[::-1]]
        
        return state
    
    def get_square_diffs(self, frame1: np.ndarray, frame2: np.ndarray) -> List[float]:
        """
        Calculate difference metric for each square between two frames.
        
        Args:
            frame1: Reference frame (bird's eye view or raw)
            frame2: Current frame
            
        Returns:
            List of 64 float values (0.0 to 1.0) representing change intensity per square.
            Order is row-major (a8..h8, a7..h7...) depending on orientation.
        """
        if self.perspective_matrix is None:
            return [0.0] * 64
        
        # Get bird's eye views
        view1 = self.get_bird_eye_view(frame1)
        view2 = self.get_bird_eye_view(frame2)
        
        if view1 is None or view2 is None:
            return [0.0] * 64
            
        # Convert to grayscale - NO BLUR to preserve diff signal
        # BUT: High res might have grain, so a tiny blur helps stability
        g1 = cv2.GaussianBlur(cv2.cvtColor(view1, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        g2 = cv2.GaussianBlur(cv2.cvtColor(view2, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        
        # Compute absolute difference
        diff = cv2.absdiff(g1, g2)
        
        # Threshold the diff to remove noise (e.g. slight lighting flicker)
        # Any pixel diff < 15 is ignored
        _, thresh_diff = cv2.threshold(diff, 15, 255, cv2.THRESH_BINARY)
        
        # Calculate score per square
        diffs = []
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                x1 = col * self.square_size
                y1 = row * self.square_size
                x2 = x1 + self.square_size
                y2 = y1 + self.square_size
                
                # Extract square absolute difference
                square_diff = thresh_diff[y1:y2, x1:x2]
                
                # Score = Percentage of pixels that changed significantly
                # This is much more robust than mean intensity
                non_zero = cv2.countNonZero(square_diff)
                total_pixels = square_diff.size
                score = non_zero / total_pixels
                
                diffs.append(score)
                
        # If flipped, we need to reorder the list to match standard board order (rank 8->1)
        # diffs is currently [row0col0, row0col1...] i.e. top-left to bottom-right of IMAGE
        # If orientation is flipped (white at top), image top-left (0,0) is actually h1
        # It's safer to return the 8x8 matrix or stick to visual row/col and map later.
        # Let's return visual row-major list for now.
        
        return diffs
        
    def get_pixel_diff_score(self, frame1, frame2):
        """Calculate global normalized pixel difference between two frames."""
        if frame1 is None or frame2 is None: return 1.0
        try:
            # Ensure same size
            f1 = cv2.resize(frame1, (320, 320))
            f2 = cv2.resize(frame2, (320, 320))
            
            g1 = cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY)
            g2 = cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY)
            
            diff = cv2.absdiff(g1, g2)
            score = np.mean(diff) / 255.0
            return score
        except:
            return 1.0
        
    def _analyze_square(self, square: np.ndarray, row: int, col: int) -> str:
        """
        Analyze a single square to detect piece.
        
        Args:
            square: Square image
            row, col: Square position (for determining square color)
            
        Returns:
            'w', 'b', or '.'
        """
        # Determine if this is a light or dark square
        is_light_square = (row + col) % 2 == 0
        
        # Convert to HSV for color detection
        hsv = cv2.cvtColor(square, cv2.COLOR_BGR2HSV)
        
        # Create masks for piece colors
        # Use center region to avoid edge effects
        margin = self.square_size // 4
        center = hsv[margin:-margin, margin:-margin] if margin > 0 else hsv
        
        # Detect white pieces
        white_mask = cv2.inRange(center, self.white_piece_lower, self.white_piece_upper)
        white_ratio = np.sum(white_mask > 0) / white_mask.size
        
        # Detect black pieces
        black_mask = cv2.inRange(center, self.black_piece_lower, self.black_piece_upper)
        black_ratio = np.sum(black_mask > 0) / black_mask.size
        
        # Adjust thresholds based on square color
        # Pieces are easier to detect on contrasting squares
        threshold = self.min_piece_area
        
        if white_ratio > threshold and white_ratio > black_ratio:
            return 'w'
        elif black_ratio > threshold and black_ratio > white_ratio:
            return 'b'
        else:
            return '.'
        
        # Convert to HSV for color detection
        hsv = cv2.cvtColor(square, cv2.COLOR_BGR2HSV)
        
        # Create masks for piece colors
        # Use center region to avoid edge effects
        margin = self.square_size // 4
        center = hsv[margin:-margin, margin:-margin] if margin > 0 else hsv
        
        # Detect white pieces
        white_mask = cv2.inRange(center, self.white_piece_lower, self.white_piece_upper)
        white_ratio = np.sum(white_mask > 0) / white_mask.size
        
        # Detect black pieces
        black_mask = cv2.inRange(center, self.black_piece_lower, self.black_piece_upper)
        black_ratio = np.sum(black_mask > 0) / black_mask.size
        
        # Adjust thresholds based on square color
        # Pieces are easier to detect on contrasting squares
        threshold = self.min_piece_area
        
        if white_ratio > threshold and white_ratio > black_ratio:
            return 'w'
        elif black_ratio > threshold and black_ratio > white_ratio:
            return 'b'
        else:
            return '.'
    
    def set_orientation(self, white_on_bottom: bool) -> None:
        """
        Set board orientation.
        
        Args:
            white_on_bottom: True if white pieces start at bottom of camera view
        """
        self.flipped = not white_on_bottom
    
    def visualize_detection(self, frame: np.ndarray, state: List[List[str]] = None) -> np.ndarray:
        """
        Create visualization of detected board state.
        
        Args:
            frame: Original camera frame
            state: Optional board state (will detect if not provided)
            
        Returns:
            Annotated image
        """
        result = frame.copy()
        
        # Draw board corners if calibrated
        if self.board_corners is not None:
            pts = self.board_corners.astype(np.int32)
            cv2.polylines(result, [pts], True, (0, 255, 0), 2)
            
            for i, pt in enumerate(pts):
                cv2.circle(result, tuple(pt), 5, (0, 0, 255), -1)
                cv2.putText(result, str(i), tuple(pt + 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Get bird's eye view with state overlay
        bird_eye = self.get_bird_eye_view(frame)
        if bird_eye is not None:
            if state is None:
                state = self.get_board_state(frame)
            
            if state:
                # Draw grid and state on bird's eye view
                for row in range(BOARD_SIZE):
                    for col in range(BOARD_SIZE):
                        x = col * self.square_size + self.square_size // 2
                        y = row * self.square_size + self.square_size // 2
                        
                        piece = state[row][col]
                        if piece == 'w':
                            cv2.circle(bird_eye, (x, y), 15, (255, 255, 255), -1)
                            cv2.circle(bird_eye, (x, y), 15, (0, 0, 0), 2)
                        elif piece == 'b':
                            cv2.circle(bird_eye, (x, y), 15, (0, 0, 0), -1)
                            cv2.circle(bird_eye, (x, y), 15, (255, 255, 255), 2)
                
                # Draw grid lines
                for i in range(BOARD_SIZE + 1):
                    pos = i * self.square_size
                    cv2.line(bird_eye, (pos, 0), (pos, self.board_image_size), (0, 255, 0), 1)
                    cv2.line(bird_eye, (0, pos), (self.board_image_size, pos), (0, 255, 0), 1)
            
            # Add bird's eye view to corner of result
            scale = 0.3
            small = cv2.resize(bird_eye, None, fx=scale, fy=scale)
            h, w = small.shape[:2]
            result[10:10+h, 10:10+w] = small
        
        return result
    
    def interactive_calibration(self, frame: np.ndarray) -> bool:
        """
        Interactive calibration by clicking corners.
        
        Args:
            frame: Camera frame
            
        Returns:
            True if calibration completed
        """
        corners = []
        window_name = "Click 4 corners: TL, TR, BR, BL (press 'r' to reset, 'q' to quit)"
        
        def mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN and len(corners) < 4:
                corners.append((x, y))
                print(f"Corner {len(corners)}: ({x}, {y})")
        
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, mouse_callback)
        
        while True:
            display = frame.copy()
            
            # Draw existing corners
            for i, corner in enumerate(corners):
                cv2.circle(display, corner, 5, (0, 0, 255), -1)
                cv2.putText(display, str(i+1), (corner[0]+10, corner[1]+10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Draw lines between corners
            if len(corners) >= 2:
                for i in range(len(corners) - 1):
                    cv2.line(display, corners[i], corners[i+1], (0, 255, 0), 2)
                if len(corners) == 4:
                    cv2.line(display, corners[3], corners[0], (0, 255, 0), 2)
            
            cv2.imshow(window_name, display)
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                cv2.destroyWindow(window_name)
                return False
            elif key == ord('r'):
                corners.clear()
            elif len(corners) == 4:
                cv2.destroyWindow(window_name)
                return self.calibrate(frame, corners)
        
        return False


# Quick test
if __name__ == "__main__":
    print("BoardVision test")
    print("This module requires a camera feed to test.")
    print("Run with main.py for full functionality.")
