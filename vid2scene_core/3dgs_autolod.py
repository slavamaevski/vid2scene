#!/usr/bin/env python3
"""
3D Gaussian Splatting LOD Reducer (Optimized)
=============================================
Usage:
    python gaussian_lod.py input.ply output.ply --reduction 50

Requirements:
    pip install numpy plyfile tqdm pykdtree numba
"""

import numpy as np
from typing import Tuple
import argparse
import concurrent.futures
import math
import os

from plyfile import PlyData, PlyElement
from pykdtree.kdtree import KDTree
from tqdm import tqdm
from numba import njit, prange


# ============== SH CONSTANTS ==============

SH_C0 = 0.28209479177387814
SH_C1 = 0.4886025119029199
SH_C2 = np.array([1.0925484305920792, -1.0925484305920792, 0.31539156525252005,
                  -1.0925484305920792, 0.5462742152960396], dtype=np.float32)
SH_C3 = np.array([-0.5900435899266435, 2.890611442640554, -0.4570457994644658,
                  0.3731763325901154, -0.4570457994644658, 1.445305721320277,
                  -0.5900435899266435], dtype=np.float32)


def _build_sh_basis():
    """Build SH basis matrices for resampling (32 directions, up to 16 coeffs)."""
    n = 32
    i = np.arange(n, dtype=np.float32)
    phi = np.pi * (3 - np.sqrt(5))
    y = 1 - (i / (n - 1)) * 2
    r = np.sqrt(1 - y*y)
    dirs = np.stack([np.cos(phi*i)*r, y, np.sin(phi*i)*r], axis=1)
    
    x, y, z = dirs[:, 0], dirs[:, 1], dirs[:, 2]
    basis = np.zeros((n, 16), dtype=np.float32)
    basis[:, 0] = SH_C0
    basis[:, 1] = -SH_C1 * y
    basis[:, 2] = SH_C1 * z
    basis[:, 3] = -SH_C1 * x
    xx, yy, zz, xy, yz, xz = x*x, y*y, z*z, x*y, y*z, x*z
    basis[:, 4] = SH_C2[0] * xy
    basis[:, 5] = SH_C2[1] * yz
    basis[:, 6] = SH_C2[2] * (2*zz - xx - yy)
    basis[:, 7] = SH_C2[3] * xz
    basis[:, 8] = SH_C2[4] * (xx - yy)
    basis[:, 9] = SH_C3[0] * y * (3*xx - yy)
    basis[:, 10] = SH_C3[1] * xy * z
    basis[:, 11] = SH_C3[2] * y * (4*zz - xx - yy)
    basis[:, 12] = SH_C3[3] * z * (2*zz - 3*xx - 3*yy)
    basis[:, 13] = SH_C3[4] * x * (4*zz - xx - yy)
    basis[:, 14] = SH_C3[5] * z * (xx - yy)
    basis[:, 15] = SH_C3[6] * x * (xx - 3*yy)
    return basis, np.linalg.pinv(basis)

_SH_BASIS, _SH_BASIS_PINV = _build_sh_basis()


# ============== GAUSSIAN CLOUD ==============

class GaussianCloud:
    __slots__ = ('positions', 'scales', 'rotations', 'opacities', 'sh_dc', 'sh_rest', '_covariances')
    
    def __init__(self, positions, scales, rotations, opacities, sh_dc, sh_rest):
        self.positions = np.ascontiguousarray(positions, dtype=np.float32)
        self.scales = np.ascontiguousarray(scales, dtype=np.float32)
        self.rotations = np.ascontiguousarray(rotations, dtype=np.float32)
        self.opacities = np.ascontiguousarray(opacities, dtype=np.float32)
        self.sh_dc = np.ascontiguousarray(sh_dc, dtype=np.float32)
        self.sh_rest = np.ascontiguousarray(sh_rest, dtype=np.float32)
        self._covariances = None
    
    def __len__(self):
        return len(self.positions)
    
    @property
    def covariances(self):
        if self._covariances is None:
            self._covariances = compute_covariances_batched(self.rotations, self.scales)
        return self._covariances


# ============== BATCHED OPERATIONS ==============

def compute_covariances_batched(rotations, scales):
    """Compute covariance matrices for all Gaussians. (N, 4), (N, 3) -> (N, 3, 3)"""
    q = rotations / np.linalg.norm(rotations, axis=1, keepdims=True)
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    
    n = len(rotations)
    R = np.zeros((n, 3, 3), dtype=np.float32)
    R[:, 0, 0] = 1 - 2*y*y - 2*z*z
    R[:, 0, 1] = 2*x*y - 2*w*z
    R[:, 0, 2] = 2*x*z + 2*w*y
    R[:, 1, 0] = 2*x*y + 2*w*z
    R[:, 1, 1] = 1 - 2*x*x - 2*z*z
    R[:, 1, 2] = 2*y*z - 2*w*x
    R[:, 2, 0] = 2*x*z - 2*w*y
    R[:, 2, 1] = 2*y*z + 2*w*x
    R[:, 2, 2] = 1 - 2*x*x - 2*y*y
    
    S_sq = scales ** 2
    # cov = R @ diag(S^2) @ R.T = sum_k S_k^2 * outer(R[:, k], R[:, k])
    cov = np.einsum('ni,nj,n->nij', R[:, :, 0], R[:, :, 0], S_sq[:, 0])
    cov += np.einsum('ni,nj,n->nij', R[:, :, 1], R[:, :, 1], S_sq[:, 1])
    cov += np.einsum('ni,nj,n->nij', R[:, :, 2], R[:, :, 2], S_sq[:, 2])
    return cov


def mat_to_quat_batched(R):
    """Batched rotation matrices to quaternions. (N, 3, 3) -> (N, 4)"""
    N = R.shape[0]
    q = np.zeros((N, 4), dtype=np.float32)
    tr = np.trace(R, axis1=1, axis2=2)
    
    # Case 1: tr > 0
    m1 = tr > 0
    if m1.any():
        s = 0.5 / np.sqrt(tr[m1] + 1.0)
        q[m1, 0] = 0.25 / s
        q[m1, 1] = (R[m1, 2, 1] - R[m1, 1, 2]) * s
        q[m1, 2] = (R[m1, 0, 2] - R[m1, 2, 0]) * s
        q[m1, 3] = (R[m1, 1, 0] - R[m1, 0, 1]) * s
    
    # Case 2: R[0,0] dominant
    m2 = ~m1 & (R[:, 0, 0] > R[:, 1, 1]) & (R[:, 0, 0] > R[:, 2, 2])
    if m2.any():
        s = 2.0 * np.sqrt(1.0 + R[m2, 0, 0] - R[m2, 1, 1] - R[m2, 2, 2])
        q[m2, 0] = (R[m2, 2, 1] - R[m2, 1, 2]) / s
        q[m2, 1] = 0.25 * s
        q[m2, 2] = (R[m2, 0, 1] + R[m2, 1, 0]) / s
        q[m2, 3] = (R[m2, 0, 2] + R[m2, 2, 0]) / s
    
    # Case 3: R[1,1] dominant
    m3 = ~m1 & ~m2 & (R[:, 1, 1] > R[:, 2, 2])
    if m3.any():
        s = 2.0 * np.sqrt(1.0 + R[m3, 1, 1] - R[m3, 0, 0] - R[m3, 2, 2])
        q[m3, 0] = (R[m3, 0, 2] - R[m3, 2, 0]) / s
        q[m3, 1] = (R[m3, 0, 1] + R[m3, 1, 0]) / s
        q[m3, 2] = 0.25 * s
        q[m3, 3] = (R[m3, 1, 2] + R[m3, 2, 1]) / s
    
    # Case 4: R[2,2] dominant
    m4 = ~m1 & ~m2 & ~m3
    if m4.any():
        s = 2.0 * np.sqrt(1.0 + R[m4, 2, 2] - R[m4, 0, 0] - R[m4, 1, 1])
        q[m4, 0] = (R[m4, 1, 0] - R[m4, 0, 1]) / s
        q[m4, 1] = (R[m4, 0, 2] + R[m4, 2, 0]) / s
        q[m4, 2] = (R[m4, 1, 2] + R[m4, 2, 1]) / s
        q[m4, 3] = 0.25 * s
    
    return q / np.linalg.norm(q, axis=1, keepdims=True)


# ============== PLY I/O ==============

def load_ply(path: str) -> GaussianCloud:
    ply = PlyData.read(path)
    v = ply['vertex']
    
    positions = np.stack([v['x'], v['y'], v['z']], axis=1)
    scales = np.exp(np.stack([v['scale_0'], v['scale_1'], v['scale_2']], axis=1))
    rotations = np.stack([v['rot_0'], v['rot_1'], v['rot_2'], v['rot_3']], axis=1)
    rotations /= np.linalg.norm(rotations, axis=1, keepdims=True)
    opacities = 1 / (1 + np.exp(-np.asarray(v['opacity'])))
    sh_dc = np.stack([v['f_dc_0'], v['f_dc_1'], v['f_dc_2']], axis=1)
    
    sh_rest_cols = sorted(
        [p for p in v.data.dtype.names if p.startswith('f_rest_')],
        key=lambda x: int(x.split('_')[-1])
    )
    if sh_rest_cols:
        sh_rest = np.stack([v[c] for c in sh_rest_cols], axis=1).reshape(-1, len(sh_rest_cols) // 3, 3)
    else:
        sh_rest = np.zeros((len(v), 0, 3), dtype=np.float32)
    
    return GaussianCloud(positions, scales, rotations, opacities, sh_dc, sh_rest)


def save_ply(cloud: GaussianCloud, path: str):
    n = len(cloud)
    n_rest = cloud.sh_rest.shape[1]
    
    dtype = [
        ('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
        ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
        ('f_dc_0', 'f4'), ('f_dc_1', 'f4'), ('f_dc_2', 'f4'),
    ]
    for i in range(n_rest * 3):
        dtype.append((f'f_rest_{i}', 'f4'))
    dtype.extend([
        ('opacity', 'f4'),
        ('scale_0', 'f4'), ('scale_1', 'f4'), ('scale_2', 'f4'),
        ('rot_0', 'f4'), ('rot_1', 'f4'), ('rot_2', 'f4'), ('rot_3', 'f4'),
    ])
    
    data = np.zeros(n, dtype=dtype)
    data['x'], data['y'], data['z'] = cloud.positions.T
    data['f_dc_0'], data['f_dc_1'], data['f_dc_2'] = cloud.sh_dc.T
    
    sh_flat = cloud.sh_rest.reshape(n, -1)
    for j in range(sh_flat.shape[1]):
        data[f'f_rest_{j}'] = sh_flat[:, j]
    
    o = np.clip(cloud.opacities, 1e-6, 1 - 1e-6)
    data['opacity'] = np.log(o / (1 - o))
    data['scale_0'] = np.log(cloud.scales[:, 0])
    data['scale_1'] = np.log(cloud.scales[:, 1])
    data['scale_2'] = np.log(cloud.scales[:, 2])
    data['rot_0'], data['rot_1'] = cloud.rotations[:, 0], cloud.rotations[:, 1]
    data['rot_2'], data['rot_3'] = cloud.rotations[:, 2], cloud.rotations[:, 3]
    
    PlyData([PlyElement.describe(data, 'vertex')]).write(path)


# ============== COST COMPUTATION ==============

@njit
def select_pairs_greedy(sorted_i, sorted_j, max_pairs, n):
    """Select non-overlapping pairs greedily. Numba-compiled for speed."""
    used = np.zeros(n, dtype=np.bool_)
    pairs_i = np.empty(max_pairs, dtype=np.int64)
    pairs_j = np.empty(max_pairs, dtype=np.int64)
    count = 0
    
    for k in range(len(sorted_i)):
        if count >= max_pairs:
            break
        i = sorted_i[k]
        j = sorted_j[k]
        if not used[i] and not used[j]:
            pairs_i[count] = i
            pairs_j[count] = j
            used[i] = True
            used[j] = True
            count += 1
    
    return pairs_i[:count], pairs_j[:count]


@njit(parallel=True, fastmath=True)
def compute_merge_costs_numba(pos_i, pos_j, cov_i, cov_j, sh_dc_i, sh_dc_j, op_i, op_j):
    """
    Compute cost for candidate pairs using Numba for memory efficiency (no intermediate allocations).
    """
    n = len(pos_i)
    costs = np.empty(n, dtype=np.float32)
    
    for k in prange(n):
        # Bhattacharyya distance
        # Average covariance
        cov_avg = 0.5 * (cov_i[k] + cov_j[k])
        
        # Determinants
        det_i = np.linalg.det(cov_i[k])
        det_j = np.linalg.det(cov_j[k])
        det_avg = np.linalg.det(cov_avg)
        
        # Check for numerical stability/degeneracy
        if det_i <= 1e-20 or det_j <= 1e-20 or det_avg <= 1e-20:
            costs[k] = 1e9  # Penalty
            continue

        # Inverse of average covariance
        try:
            inv_avg = np.linalg.inv(cov_avg)
        except:
            costs[k] = 1e9
            continue
            
        # Mahalanobis term
        diff = pos_i[k] - pos_j[k]
        # diff.T @ inv @ diff
        mahal_sq = 0.0
        for r in range(3):
            dot_row = 0.0
            for c in range(3):
                dot_row += inv_avg[r, c] * diff[c]
            mahal_sq += diff[r] * dot_row
            
        # Log determinant term
        # 0.5 * ln(det_avg / sqrt(det_i * det_j))
        det_term = 0.5 * np.log(det_avg / (np.sqrt(det_i * det_j) + 1e-20))
        
        bhatt = 0.125 * mahal_sq + det_term
        
        # Color difference
        # norm of first 3 SH coeffs (DC)
        color_diff = 0.0
        for c in range(3):
            d = sh_dc_i[k, c] - sh_dc_j[k, c]
            color_diff += d * d
        color_diff = np.sqrt(color_diff)
        
        costs[k] = bhatt + 0.5 * color_diff
        
    return costs


# ============== VECTORIZED MERGING ==============

def resample_sh_batched(sh_dc_i, sh_rest_i, sh_dc_j, sh_rest_j, alpha_i, alpha_j):
    """
    Batched SH resampling: blend in color space, then project back to SH.
    sh_dc_*: (M, 3), sh_rest_*: (M, n_rest, 3), alpha_*: (M,)
    Returns: new_dc (M, 3), new_rest (M, n_rest, 3)
    """
    M = sh_dc_i.shape[0]
    n_rest = sh_rest_i.shape[1]
    n_coeffs = min(n_rest + 1, 16)
    
    # Build full SH coefficient arrays: (M, n_coeffs, 3)
    sh_i = np.concatenate([sh_dc_i[:, None, :], sh_rest_i[:, :n_coeffs-1, :]], axis=1)
    sh_j = np.concatenate([sh_dc_j[:, None, :], sh_rest_j[:, :n_coeffs-1, :]], axis=1)
    
    # Evaluate SH at sample directions: basis (64, n_coeffs) @ sh (M, n_coeffs, 3) -> (M, 64, 3)
    basis = _SH_BASIS[:, :n_coeffs]
    colors_i = np.einsum('dc,mcD->mdD', basis, sh_i)  # (M, 64, 3)
    colors_j = np.einsum('dc,mcD->mdD', basis, sh_j)  # (M, 64, 3)
    
    # Blend in color space
    a_i = alpha_i[:, None, None]
    a_j = alpha_j[:, None, None]
    blended = a_i * colors_i + a_j * colors_j  # (M, 64, 3)
    
    # Project back to SH: pinv (n_coeffs, 64) @ blended (M, 64, 3) -> (M, n_coeffs, 3)
    basis_pinv = _SH_BASIS_PINV[:n_coeffs, :]
    new_sh = np.einsum('cd,mdD->mcD', basis_pinv, blended)  # (M, n_coeffs, 3)
    
    new_dc = new_sh[:, 0, :]
    new_rest = np.zeros((M, n_rest, 3), dtype=np.float32)
    new_rest[:, :n_coeffs-1, :] = new_sh[:, 1:, :]
    
    return new_dc, new_rest


@njit(parallel=True, fastmath=True)
def adjust_scales_for_coverage(positions, scales, rotations, neighbor_indices, neighbor_distances, 
                                coverage_fraction=0.7, min_scale_mult=1.0, max_scale_mult=3.0):
    """
    Adjust gaussian scales to ensure coverage to nearest neighbors along principal axes.
    Uses anisotropic scaling - scales more in directions where neighbors are far away.
    This prevents spottiness at high reduction levels by ensuring gaussians are large enough
    to reach partway toward their neighbors in all directions.
    
    Args:
        positions: (N, 3) gaussian positions
        scales: (N, 3) gaussian scales (will be modified in-place)
        rotations: (N, 4) gaussian rotations (quaternions)
        neighbor_indices: (N, K) indices of K nearest neighbors for each gaussian
        neighbor_distances: (N, K) distances to those neighbors
        coverage_fraction: target fraction of distance to neighbor to cover (default 0.7)
        min_scale_mult: minimum scale multiplier to prevent shrinking (default 1.0)
        max_scale_mult: maximum scale multiplier to prevent over-inflation (default 3.0)
    """
    n = len(positions)
    k_neighbors = neighbor_indices.shape[1]
    
    for i in prange(n):
        # Convert quaternion to rotation matrix
        q = rotations[i]
        qw, qx, qy, qz = q[0], q[1], q[2], q[3]
        
        # Normalize quaternion
        qnorm = math.sqrt(qw*qw + qx*qx + qy*qy + qz*qz)
        if qnorm < 1e-8:
            continue
        qw, qx, qy, qz = qw/qnorm, qx/qnorm, qy/qnorm, qz/qnorm
        
        # Build rotation matrix (columns are principal axes)
        R = np.zeros((3, 3), dtype=np.float32)
        R[0, 0] = 1 - 2*qy*qy - 2*qz*qz
        R[0, 1] = 2*qx*qy - 2*qw*qz
        R[0, 2] = 2*qx*qz + 2*qw*qy
        R[1, 0] = 2*qx*qy + 2*qw*qz
        R[1, 1] = 1 - 2*qx*qx - 2*qz*qz
        R[1, 2] = 2*qy*qz - 2*qw*qx
        R[2, 0] = 2*qx*qz - 2*qw*qy
        R[2, 1] = 2*qy*qz + 2*qw*qx
        R[2, 2] = 1 - 2*qx*qx - 2*qy*qy
        
        # For each principal axis, find nearest neighbor in BOTH directions
        # Track min in positive and negative direction separately, then take max
        max_dist_per_axis = np.zeros(3, dtype=np.float32)
        
        for k in range(k_neighbors):
            neighbor_idx = neighbor_indices[i, k]
            if neighbor_idx < 0 or neighbor_idx >= n:
                continue
                
            # Vector to neighbor
            delta = positions[neighbor_idx] - positions[i]
            
            # Project onto each principal axis
            for axis in range(3):
                # Dot product with axis (signed projection)
                projection = delta[0] * R[0, axis] + delta[1] * R[1, axis] + delta[2] * R[2, axis]
                
                # Use absolute value - we care about distance in this axis direction
                abs_proj = abs(projection)
                
                # Track MAXIMUM distance along this axis (we scale to reach the farthest neighbor)
                if abs_proj > max_dist_per_axis[axis]:
                    max_dist_per_axis[axis] = abs_proj
        
        # Adjust scale for each axis based on maximum neighbor distance
        current_scales = scales[i]
        for axis in range(3):
            if max_dist_per_axis[axis] > 1e-6:  # Found at least one neighbor with projection on this axis
                # Target scale: cover coverage_fraction of distance to farthest neighbor in this direction
                target_scale = max_dist_per_axis[axis] * coverage_fraction
                
                # Compute scale multiplier, clamped to reasonable range
                if current_scales[axis] > 1e-6:
                    scale_mult = target_scale / current_scales[axis]
                    scale_mult = max(min_scale_mult, min(max_scale_mult, scale_mult))
                    scales[i, axis] = current_scales[axis] * scale_mult


@njit(parallel=True, fastmath=True)
def merge_pairs_numba(pos_i, pos_j, scale_i, scale_j, rot_i, rot_j, op_i, op_j, 
                      sh_dc_i, sh_dc_j, sh_rest_i, sh_rest_j, 
                      cov_i, cov_j, use_resampling, opacity_boost, scale_boost):
    """
    Merge pairs using Numba parallel execution.
    Returns separated arrays for the new cloud subset.
    """
    n = len(pos_i)
    # Allocation for results
    new_pos = np.empty((n, 3), dtype=np.float32)
    new_scales = np.empty((n, 3), dtype=np.float32)
    new_rots = np.empty((n, 4), dtype=np.float32)
    new_op = np.empty(n, dtype=np.float32)
    new_cov = np.empty((n, 3, 3), dtype=np.float32)
    
    # SH
    new_dc = np.empty_like(sh_dc_i)
    new_rest = np.empty_like(sh_rest_i)
    
    for k in prange(n):
        # 1. Weights Calculation
        v_i = scale_i[k, 0] * scale_i[k, 1] * scale_i[k, 2]
        v_j = scale_j[k, 0] * scale_j[k, 1] * scale_j[k, 2]
        
        o_i = min(op_i[k], 0.9999999)
        o_j = min(op_j[k], 0.9999999)
        
        # Optical mass
        m_i = -np.log(1.0 - o_i) * v_i
        m_j = -np.log(1.0 - o_j) * v_j
        
        # Boost mass
        w_total = (m_i + m_j) * opacity_boost
        
        # Geometric weight
        geom_mass = m_i + m_j
        if geom_mass > 1e-10:
            a_i = m_i / geom_mass
        else:
            a_i = 0.5
        a_j = 1.0 - a_i
        
        # 2. Position
        p_i = pos_i[k]
        p_j = pos_j[k]
        new_p = a_i * p_i + a_j * p_j
        new_pos[k] = new_p
        
        # 3. Covariance
        # outer_i = (p_i - new_p) * (p_i - new_p).T
        di = p_i - new_p
        dj = p_j - new_p
        
        # Manual 3x3 outer product + sum
        # new_cov = a_i * (cov_i + outer_i) + a_j * (cov_j + outer_j)
        for r in range(3):
            for c in range(3):
                # Outer products
                out_i_rc = di[r] * di[c]
                out_j_rc = dj[r] * dj[c]
                
                c_i_rc = cov_i[k, r, c]
                c_j_rc = cov_j[k, r, c]
                
                new_cov[k, r, c] = a_i * (c_i_rc + out_i_rc) + a_j * (c_j_rc + out_j_rc)
                
        # 4. Eigensolve for Scale/Rot
        try:
            evals, evecs = np.linalg.eigh(new_cov[k])
            # Cast to float32 for type consistency
            evals = evals.astype(np.float32)
            evecs = evecs.astype(np.float32)
        except:
            # Fallback for numerical instability
            evals = np.array([1e-6, 1e-6, 1e-6], dtype=np.float32)
            evecs = np.eye(3, dtype=np.float32)

        # Clamp evals
        s1 = max(evals[0], 1e-7)
        s2 = max(evals[1], 1e-7)
        s3 = max(evals[2], 1e-7)
        
        # Sqrt for scales
        ns1 = math.sqrt(s1)
        ns2 = math.sqrt(s2)
        ns3 = math.sqrt(s3)
        
        # Apply scale boost to fill gaps
        if scale_boost != 1.0:
            ns1 *= scale_boost
            ns2 *= scale_boost
            ns3 *= scale_boost
            
        new_scales[k, 0] = ns1
        new_scales[k, 1] = ns2
        new_scales[k, 2] = ns3
        
        # Fix handedness
        cx, cy, cz = evecs[:, 0], evecs[:, 1], evecs[:, 2]
        det = cx[0]*(cy[1]*cz[2] - cy[2]*cz[1]) - cx[1]*(cy[0]*cz[2] - cy[2]*cz[0]) + cx[2]*(cy[0]*cz[1] - cy[1]*cz[0])
        
        if det < 0:
            evecs[0, 0] = -evecs[0, 0]
            evecs[1, 0] = -evecs[1, 0]
            evecs[2, 0] = -evecs[2, 0]
            
        # Convert Matrix to Quaternion
        trace = evecs[0,0] + evecs[1,1] + evecs[2,2]
        if trace > 0:
            S = 0.5 / math.sqrt(trace + 1.0)
            qw = 0.25 / S
            qx = (evecs[2,1] - evecs[1,2]) * S
            qy = (evecs[0,2] - evecs[2,0]) * S
            qz = (evecs[1,0] - evecs[0,1]) * S
        else:
            if (evecs[0,0] > evecs[1,1]) and (evecs[0,0] > evecs[2,2]):
                S = 2.0 * math.sqrt(1.0 + evecs[0,0] - evecs[1,1] - evecs[2,2])
                qw = (evecs[2,1] - evecs[1,2]) / S
                qx = 0.25 * S
                qy = (evecs[0,1] + evecs[1,0]) / S
                qz = (evecs[0,2] + evecs[2,0]) / S
            elif evecs[1,1] > evecs[2,2]:
                S = 2.0 * math.sqrt(1.0 + evecs[1,1] - evecs[0,0] - evecs[2,2])
                qw = (evecs[0,2] - evecs[2,0]) / S
                qx = (evecs[0,1] + evecs[1,0]) / S
                qy = 0.25 * S
                qz = (evecs[1,2] + evecs[2,1]) / S
            else:
                S = 2.0 * math.sqrt(1.0 + evecs[2,2] - evecs[0,0] - evecs[1,1])
                qw = (evecs[1,0] - evecs[0,1]) / S
                qx = (evecs[0,2] + evecs[2,0]) / S
                qy = (evecs[1,2] + evecs[2,1]) / S
                qz = 0.25 * S
                
        new_rots[k, 0] = qw
        new_rots[k, 1] = qx
        new_rots[k, 2] = qy
        new_rots[k, 3] = qz
        
        # 5. Opacity
        new_vol = ns1 * ns2 * ns3
        eff_vol = min(new_vol, v_i + v_j)
        
        op_val = 1.0 - math.exp(-w_total / (eff_vol + 1e-10))
        new_op[k] = op_val
        
        # 6. SH
        new_dc[k] = a_i * sh_dc_i[k] + a_j * sh_dc_j[k]
        new_rest[k] = a_i * sh_rest_i[k] + a_j * sh_rest_j[k]
        
    return new_pos, new_scales, new_rots, new_op, new_dc, new_rest, new_cov


# ============== MAIN REDUCTION ==============

def reduce_cloud(cloud: GaussianCloud, target_count: int, use_bhattacharyya: bool = True, use_resampling: bool = True, opacity_boost: float = 1.0, scale_boost: float = 1.0, coverage_aware: bool = True, output_path: str = None, checkpoint_targets: list = None, checkpoint_lod_counter: dict = None) -> GaussianCloud:
    if len(cloud) <= target_count:
        return cloud
    
    print(f"Reducing {len(cloud)} -> {target_count} Gaussians")
    print(f"Using Bhattacharyya: {use_bhattacharyya}, SH resampling: {use_resampling}, Opacity boost: {opacity_boost}, Scale boost: {scale_boost}, Coverage-aware: {coverage_aware}")
    
    # Work arrays (contiguous for speed)
    positions = cloud.positions.copy()
    scales = cloud.scales.copy()
    rotations = cloud.rotations.copy()
    opacities = cloud.opacities.copy()
    sh_dc = cloud.sh_dc.copy()
    sh_rest = cloud.sh_rest.copy()
    covariances = cloud.covariances.copy()
    
    n = len(positions)
    active = np.ones(n, dtype=bool)
    
    iteration = 0
    with tqdm(total=n - target_count, desc="Reducing") as pbar:
        while True:
            n_active = np.sum(active)
            if n_active <= target_count:
                break
            
            iteration += 1
            active_idx = np.where(active)[0]
            active_pos = positions[active_idx]
            
            # KD-tree for nearest neighbor
            tree = KDTree(active_pos)
            k_neighbors = min(2, n_active)
            distances, local_nn = tree.query(active_pos, k=k_neighbors)
            
            # Apply coverage-aware scaling using the KDTree we just built
            # Skip first iteration since original cloud hasn't been reduced yet
            if coverage_aware and iteration > 1 and n_active > 1:
                # Query more neighbors for coverage analysis
                k_coverage = min(9, n_active)  # k=9 because first is self
                coverage_distances, coverage_nn_local = tree.query(active_pos, k=k_coverage)
                
                # Convert local indices to global, skip self (index 0)
                coverage_nn_global = active_idx[coverage_nn_local[:, 1:]]
                coverage_dists = coverage_distances[:, 1:]
                
                # Adjust scales for active gaussians
                adjust_scales_for_coverage(
                    positions[active_idx],
                    scales[active_idx],
                    rotations[active_idx],
                    coverage_nn_global,
                    coverage_dists,
                    coverage_fraction=0.7,
                    min_scale_mult=1.0,
                    max_scale_mult=3.0
                )
                
                # Recompute covariances after scale adjustment
                covariances[active_idx] = compute_covariances_batched(
                    rotations[active_idx], scales[active_idx]
                )
            
            # Get neighbor indices (handle case where k < 2)
            if k_neighbors < 2:
                # Should not happen given loop condition, but safety first
                break
                
            nn_global = active_idx[local_nn[:, 1]]
            
            # Consider all (i, nn_i) pairs
            candidate_i = active_idx
            candidate_j = nn_global
            
            # Compute costs for all candidate pairs using Numba
            if use_bhattacharyya:
                costs = compute_merge_costs_numba(
                    positions[candidate_i], positions[candidate_j],
                    covariances[candidate_i], covariances[candidate_j],
                    sh_dc[candidate_i], sh_dc[candidate_j],
                    opacities[candidate_i].ravel(), opacities[candidate_j].ravel()
                )
            else:
                # Simple distance-based cost
                dists = np.linalg.norm(positions[candidate_i] - positions[candidate_j], axis=1)
                avg_scale = (np.mean(scales[candidate_i], axis=1) + 
                            np.mean(scales[candidate_j], axis=1)) / 2
                costs = dists / np.maximum(avg_scale, 1e-6)
            
            # Sort by cost
            order = np.argsort(costs)
            sorted_i = candidate_i[order]
            sorted_j = candidate_j[order]
            
            # Find next checkpoint target we might cross
            next_checkpoint = None
            if checkpoint_targets:
                # Find the highest checkpoint that's below current count
                potential_checkpoints = [t for t in checkpoint_targets if t < n_active]
                if potential_checkpoints:
                    next_checkpoint = max(potential_checkpoints)
            
            # Limit pairs to avoid overshooting next checkpoint or final target
            max_by_target = n_active - target_count
            max_by_batch = n_active // 4
            
            if next_checkpoint:
                max_by_checkpoint = n_active - next_checkpoint
                max_pairs = max(1, min(max_by_checkpoint, max_by_target, max_by_batch))
            else:
                max_pairs = max(1, min(max_by_target, max_by_batch))
            
            pairs_i, pairs_j = select_pairs_greedy(sorted_i, sorted_j, max_pairs, n)
            
            if len(pairs_i) == 0:
                break
            
            # Gather inputs for Numba merge
            p_i, p_j = positions[pairs_i], positions[pairs_j]
            s_i, s_j = scales[pairs_i], scales[pairs_j]
            r_i, r_j = rotations[pairs_i], rotations[pairs_j]
            # Flatten opacities from (M, 1) to (M,) for Numba
            o_i, o_j = opacities[pairs_i].ravel(), opacities[pairs_j].ravel()
            dc_i, dc_j = sh_dc[pairs_i], sh_dc[pairs_j]
            rest_i, rest_j = sh_rest[pairs_i], sh_rest[pairs_j]
            c_i, c_j = covariances[pairs_i], covariances[pairs_j]
            
            # Numba merge
            (new_pos, new_scales, new_rots, new_opacity, 
             new_dc, new_rest, new_cov) = merge_pairs_numba(
                p_i, p_j, s_i, s_j, r_i, r_j, o_i, o_j, 
                dc_i, dc_j, rest_i, rest_j, c_i, c_j, 
                use_resampling, float(opacity_boost), float(scale_boost)
            )
            
            # Update arrays (opacities stay 1D, directly assignable)
            positions[pairs_i] = new_pos
            scales[pairs_i] = new_scales
            rotations[pairs_i] = new_rots
            opacities[pairs_i] = new_opacity
            sh_dc[pairs_i] = new_dc
            sh_rest[pairs_i] = new_rest
            covariances[pairs_i] = new_cov
            active[pairs_j] = False
            pbar.update(len(pairs_i))
            
            # Check if we've crossed any checkpoint targets
            if checkpoint_targets and output_path:
                current_count = np.sum(active)
                
                # Find checkpoints we've crossed (count dropped below them)
                crossed = [t for t in checkpoint_targets if current_count <= t]
                
                if crossed:
                    # Save at current count
                    active_idx_save = np.where(active)[0]
                    import os
                    base, ext = os.path.splitext(output_path)
                    
                    # Get LOD level from counter (increments each checkpoint)
                    if checkpoint_lod_counter is not None:
                        lod_level = checkpoint_lod_counter['count']
                        checkpoint_lod_counter['count'] += 1
                    else:
                        lod_level = 0
                    
                    checkpoint_path = f"{base}_lod{lod_level}_{current_count}{ext}"
                    
                    checkpoint_cloud = GaussianCloud(
                        positions[active_idx_save], scales[active_idx_save],
                        rotations[active_idx_save], opacities[active_idx_save],
                        sh_dc[active_idx_save], sh_rest[active_idx_save]
                    )
                    save_ply(checkpoint_cloud, checkpoint_path)
                    print(f"\n  ✓ Checkpoint saved: {checkpoint_path}")
                    
                    # Remove crossed checkpoints
                    for t in crossed:
                        checkpoint_targets.remove(t)
    
    # Collect results
    active_idx = np.where(active)[0]
    return GaussianCloud(
        positions[active_idx], scales[active_idx], rotations[active_idx],
        opacities[active_idx], sh_dc[active_idx], sh_rest[active_idx]
    )


# ============== MAIN ==============

def main():
    parser = argparse.ArgumentParser(description="3DGS LOD reducer (optimized)")
    parser.add_argument("input", help="Input PLY file")
    parser.add_argument("output", help="Output PLY file")
    parser.add_argument("-r", "--reduction", type=str, default="50",
                        help="Target percentage(s) of original (default: 50). Use comma-separated for multiple: -r 50,25,10. Supports decimals.")
    parser.add_argument("--fast", action="store_true",
                        help="Use simple distance metric instead of Bhattacharyya")
    parser.add_argument("--min-opacity", type=float, default=0.005,
                        help="Cull Gaussians with opacity below this threshold (default: 0.005)")
    parser.add_argument("--opacity-boost", type=float, default=1.0,
                        help="Boost opacity during merge to counteract drift (e.g. 1.1)")
    parser.add_argument("--scale-boost", type=float, default=1.1,
                        help="Boost scale (size) of merged Gaussians to fill gaps (e.g. 1.1)")
    parser.add_argument("--no-coverage", action="store_true",
                        help="Disable coverage-aware anisotropic scaling (enabled by default)")
    parser.add_argument("-n", "--target-count", type=str, default=None,
                        help="Target number(s) of Gaussians (overrides --reduction). Use comma-separated for multiple: -n 1000000,500000")
    args = parser.parse_args()
    
    # Parse comma-separated reduction percentages
    try:
        reduction_values = [float(x.strip()) for x in args.reduction.split(',')]
    except ValueError as e:
        print(f"Error: Invalid reduction values '{args.reduction}'. Must be comma-separated numbers.")
        return
    
    # Parse comma-separated target counts if provided
    target_count_values = None
    if args.target_count is not None:
        try:
            target_count_values = [int(x.strip()) for x in args.target_count.split(',')]
        except ValueError as e:
            print(f"Error: Invalid target count values '{args.target_count}'. Must be comma-separated integers.")
            return
    
    print(f"Loading {args.input}...")
    cloud = load_ply(args.input)
    print(f"Loaded {len(cloud)} Gaussians")
    
    # Calculate target counts BEFORE opacity culling (so percentages match original file)
    if target_count_values is not None:
        targets = sorted(target_count_values, reverse=True)  # Descending order
        print(f"Targeting absolute counts: {targets}")
    else:
        # Convert percentages to absolute counts based on original loaded count
        original_count = len(cloud)
        targets = sorted([max(1, int(original_count * r / 100)) for r in reduction_values], reverse=True)
        print(f"Targeting percentage reductions {reduction_values}% -> counts: {targets}")
    
    # Cull low opacity noise AFTER calculating targets
    if args.min_opacity > 0:
        mask = cloud.opacities >= args.min_opacity
        n_culled = len(cloud) - np.sum(mask)
        if n_culled > 0:
            print(f"Culling {n_culled} low-opacity Gaussians (< {args.min_opacity})")
            indices = np.where(mask)[0]
            cloud = GaussianCloud(
                cloud.positions[indices], cloud.scales[indices], cloud.rotations[indices],
                cloud.opacities[indices], cloud.sh_dc[indices], cloud.sh_rest[indices]
            )
    
    # Filter targets that are now impossible due to opacity culling
    original_targets = targets.copy()
    targets = [t for t in targets if t < len(cloud)]
    
    # Warn about skipped targets
    skipped = [t for t in original_targets if t >= len(cloud)]
    if skipped:
        print(f"⚠️  Warning: Skipping {len(skipped)} target(s) {skipped} - higher than count after opacity culling ({len(cloud)}).")
    
    if not targets:
        print("No valid reduction targets. Exiting.")
        return
    
    # Reduce to lowest target, checkpointing at intermediate targets
    base, ext = os.path.splitext(args.output)
    
    lowest_target = targets[-1]  # Last one (lowest count)
    intermediate_targets = targets[:-1]  # All except the last
    
    print(f"\n{'='*60}")
    print(f"Reducing from {len(cloud)} to {lowest_target} Gaussians")
    if intermediate_targets:
        print(f"Checkpoints at: {intermediate_targets}")
    print(f"{'='*60}\n")
    
    # Initialize LOD counter (dict so it's mutable and can be updated in reduce_cloud)
    lod_counter = {'count': 0}
    
    # Single reduction call with checkpoints
    reduced = reduce_cloud(
        cloud, lowest_target,
        use_bhattacharyya=not args.fast,
        use_resampling=not args.fast,
        opacity_boost=args.opacity_boost,
        scale_boost=args.scale_boost,
        coverage_aware=not args.no_coverage,
        output_path=args.output,
        checkpoint_targets=intermediate_targets.copy(),  # Copy so we can modify it
        checkpoint_lod_counter=lod_counter
    )
    
    # Save final result
    final_lod_level = lod_counter['count']  # Use counter value
    final_path = f"{base}_lod{final_lod_level}_{len(reduced)}{ext}"
    print(f"\nSaving final result ({len(reduced)} Gaussians) to {final_path}...")
    save_ply(reduced, final_path)
    
    # Also save to user's requested filename for convenience
    if final_path != args.output:
        print(f"Copying to {args.output}...")
        import shutil
        shutil.copy2(final_path, args.output)
    
    print("\nDone!")


if __name__ == "__main__":
    main()