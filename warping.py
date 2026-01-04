import cv2
import numpy as np
from abc import ABC, abstractmethod

class AbstractWarper(ABC):
    @abstractmethod
    def warp(self, img_src, src_pts, dst_pts, output_size):
        """
        Warp img_src to match dst_pts using the correspondence from src_pts.
        
        Args:
            img_src: Source image (numpy array)
            src_pts: Nx2 numpy array of points in source image
            dst_pts: Nx2 numpy array of corresponding points in destination space
            output_size: (width, height) tuple for the output image
            
        Returns:
            Warped image
        """
        pass

class HomographyWarper(AbstractWarper):
    def warp(self, img_src, src_pts, dst_pts, output_size):
        # Existing logic using RANSAC
        H, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        if H is None:
            return None
        return cv2.warpPerspective(img_src, H, output_size)

class TPSWarper(AbstractWarper):
    def warp(self, img_src, src_pts, dst_pts, output_size):
        """
        Thin Plate Spline warping using pure numpy + cv2.remap
        """
        target_w, target_h = output_size
        
        # 1. Solve for TPS parameters
        # We need to find mapping from Dest (Screen) -> Source (Image) for inverse warping (remap)
        # So X (inputs) = dst_pts, Y (targets) = src_pts
        
        N = dst_pts.shape[0]
        
        # Construct K matrix (r^2 * log(r))
        # Distance matrix between each pair of control points in destination
        # dst_pts: (N, 2)
        
        # Expand dims for broadcasting: (N, 1, 2) - (1, N, 2) -> (N, N, 2)
        diff = dst_pts[:, None, :] - dst_pts[None, :, :]
        dist_sq = np.sum(diff**2, axis=-1)
        dist_sq = np.maximum(dist_sq, 1e-10) # Avoid log(0)
        K = 0.5 * dist_sq * np.log(dist_sq)
        
        # Construct P matrix [1, x, y]
        P = np.column_stack((np.ones(N), dst_pts)) # (N, 3)
        
        # Construct L matrix
        # [ K  P ]
        # [ P.T 0 ]
        # L is (N+3, N+3)
        
        L = np.zeros((N + 3, N + 3))
        L[:N, :N] = K
        L[:N, N:] = P
        L[N:, :N] = P.T
        
        # Construct Y vectors (target coords in source image)
        # We want to solve L * W = V
        # Where V is [src_pts; 0 0 0]
        # src_pts is (N, 2)
        # We treat x and y coordinates as separate problems or vectorize
        
        V = np.zeros((N + 3, 2))
        V[:N, :] = src_pts
        
        # Solve linear system L * Weights = V
        # Regularization can be added to diagonal of K if needed (e.g. + lambda * I)
        # using a small lambda for numerical stability
        L[:N, :N] += np.eye(N) * 1e-4
        
        try:
            weights = np.linalg.solve(L, V)
        except np.linalg.LinAlgError:
            return None
            
        # weights contains [w1..wn, a0, ax, ay] for x and y dimensions
        
        # 2. Generate Grid for Remap
        grid_y, grid_x = np.mgrid[0:target_h, 0:target_w]
        
        # Flatten for vectorized calc
        pts_flatten = np.column_stack((grid_x.ravel(), grid_y.ravel())) # (H*W, 2)
        
        # Calculate distances from grid points to control points (dst_pts)
        # (Pixel_count, 1, 2) - (1, N, 2) -> (Pixel_count, N, 2)
        # Memory intensive! 
        # For 12MP image this will crash. We should process in chunks or use numba.
        # Given "Desktop App" context, let's assume reasonable sizes, but let's be safe(r).
        # Optimization: Don't compute full dense matrix if unnecessary, but standard TPS does.
        # Alternatively, loop over chunks of the image.
        
        map_x = np.zeros((target_h, target_w), dtype=np.float32)
        map_y = np.zeros((target_h, target_w), dtype=np.float32)
        
        CHUNK_SIZE = 1000 # Process 1000 pixels at a time? Too slow in python.
        # Better: Process by rows or blocks.
        
        # Let's try processing by rows to keep memory usage manageable
        # dst_pts is small (usually < 20-30 points)
        
        # Extract weights
        w_vals = weights[:N, :] # (N, 2)
        a_vals = weights[N:, :] # (3, 2) -> [ones, x, y] coeffs
        
        for y in range(target_h):
            # Create a row of points: (0,y), (1,y)... (w-1, y)
            row_x = np.arange(target_w)
            row_y = np.full(target_w, y)
            row_pts = np.column_stack((row_x, row_y)) # (W, 2)
            
            # Linear part (Affine approximation)
            # [1, x, y] dot a_vals
            # (W, 3) dot (3, 2) -> (W, 2)
            affine_part = np.dot(np.column_stack((np.ones(target_w), row_pts)), a_vals)
            
            # Non-linear part (Radial Basis Functions)
            # Dist between (W, 2) and (N, 2)
            # (W, 1, 2) - (1, N, 2) -> (W, N, 2)
            d_diff = row_pts[:, None, :] - dst_pts[None, :, :]
            d_sq = np.sum(d_diff**2, axis=-1) # (W, N)
            d_sq = np.maximum(d_sq, 1e-10)
            
            # U(r) = 0.5 * r^2 * log(r^2) = 0.5 * d_sq * log(d_sq)
            U = 0.5 * d_sq * np.log(d_sq) # (W, N)
            
            # Sum weighted RBFs
            # (W, N) dot (N, 2) -> (W, 2)
            non_linear_part = np.dot(U, w_vals)
            
            mapped_pts = affine_part + non_linear_part
            
            map_x[y, :] = mapped_pts[:, 0]
            map_y[y, :] = mapped_pts[:, 1]
            
        # 3. Remap
        return cv2.remap(img_src, map_x, map_y, cv2.INTER_CUBIC)
