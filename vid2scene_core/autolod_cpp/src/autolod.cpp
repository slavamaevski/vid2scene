#include "autolod.hpp"
#include "nanoflann.hpp"
#include "sh_resampling.hpp"
#include <Eigen/Eigenvalues>
#include <algorithm>
#include <numeric>
#include <iostream>
#include <iomanip>
#include <chrono>
#include <cmath>

namespace autolod {

// KDTree adapter for nanoflann
struct PointCloud {
    const Eigen::MatrixXf& pts;
    PointCloud(const Eigen::MatrixXf& p) : pts(p) {}
    
    size_t kdtree_get_point_count() const { return pts.rows(); }
    float kdtree_get_pt(size_t idx, size_t dim) const { return pts(idx, dim); }
    
    template <class BBOX>
    bool kdtree_get_bbox(BBOX&) const { return false; }
};

using KDTree = nanoflann::KDTreeSingleIndexAdaptor<
    nanoflann::L2_Simple_Adaptor<float, PointCloud>,
    PointCloud, 3, size_t>;

// ============== MERGE COST COMPUTATION ==============

std::vector<float> compute_merge_costs(
    const GaussianCloud& cloud,
    const std::vector<size_t>& candidate_i,
    const std::vector<size_t>& candidate_j
) {
    size_t n = candidate_i.size();
    std::vector<float> costs(n);
    
    #pragma omp parallel for schedule(dynamic)
    for (size_t k = 0; k < n; ++k) {
        size_t i = candidate_i[k];
        size_t j = candidate_j[k];
        
        // Average covariance
        Eigen::Matrix3f cov_i = cloud.get_covariance(i);
        Eigen::Matrix3f cov_j = cloud.get_covariance(j);
        Eigen::Matrix3f cov_avg = 0.5f * (cov_i + cov_j);
        
        // Determinants
        float det_i = cov_i.determinant();
        float det_j = cov_j.determinant();
        float det_avg = cov_avg.determinant();
        
        // Check stability
        if (det_i <= 1e-20f || det_j <= 1e-20f || det_avg <= 1e-20f) {
            costs[k] = 1e9f;
            continue;
        }
        
        // Inverse of average covariance
        Eigen::Matrix3f inv_avg = cov_avg.inverse();
        
        // Mahalanobis distance
        Eigen::Vector3f diff = cloud.positions.row(i) - cloud.positions.row(j);
        float mahal_sq = diff.transpose() * inv_avg * diff;
        
        // Log determinant term
        float det_term = 0.5f * std::log(det_avg / (std::sqrt(det_i * det_j) + 1e-20f));
        float bhatt = 0.125f * mahal_sq + det_term;
        
        // Color difference (SH DC)
        Eigen::Vector3f color_diff = cloud.sh_dc.row(i) - cloud.sh_dc.row(j);
        float color_dist = color_diff.norm();
        
        costs[k] = bhatt + 0.5f * color_dist;
    }
    
    return costs;
}

// Version that writes to pre-allocated output vector (avoids allocation)
void compute_merge_costs_into(
    const GaussianCloud& cloud,
    const std::vector<size_t>& candidate_i,
    const std::vector<size_t>& candidate_j,
    std::vector<float>& costs
) {
    size_t n = candidate_i.size();
    
    #pragma omp parallel for schedule(dynamic)
    for (size_t k = 0; k < n; ++k) {
        size_t i = candidate_i[k];
        size_t j = candidate_j[k];
        
        // Average covariance
        Eigen::Matrix3f cov_i = cloud.get_covariance(i);
        Eigen::Matrix3f cov_j = cloud.get_covariance(j);
        Eigen::Matrix3f cov_avg = 0.5f * (cov_i + cov_j);
        
        // Determinants
        float det_i = cov_i.determinant();
        float det_j = cov_j.determinant();
        float det_avg = cov_avg.determinant();
        
        // Check stability
        if (det_i <= 1e-20f || det_j <= 1e-20f || det_avg <= 1e-20f) {
            costs[k] = 1e9f;
            continue;
        }
        
        // Inverse of average covariance
        Eigen::Matrix3f inv_avg = cov_avg.inverse();
        
        // Mahalanobis distance
        Eigen::Vector3f diff = cloud.positions.row(i) - cloud.positions.row(j);
        float mahal_sq = diff.transpose() * inv_avg * diff;
        
        // Log determinant term
        float det_term = 0.5f * std::log(det_avg / (std::sqrt(det_i * det_j) + 1e-20f));
        float bhatt = 0.125f * mahal_sq + det_term;
        
        // Color difference (SH DC)
        Eigen::Vector3f color_diff = cloud.sh_dc.row(i) - cloud.sh_dc.row(j);
        float color_dist = color_diff.norm();
        
        costs[k] = bhatt + 0.5f * color_dist;
    }
}

// ============== GREEDY PAIR SELECTION ==============

std::pair<std::vector<size_t>, std::vector<size_t>> select_pairs_greedy(
    const std::vector<size_t>& sorted_i,
    const std::vector<size_t>& sorted_j,
    size_t max_pairs,
    size_t n
) {
    std::vector<bool> used(n, false);
    std::vector<size_t> pairs_i, pairs_j;
    pairs_i.reserve(max_pairs);
    pairs_j.reserve(max_pairs);
    
    for (size_t k = 0; k < sorted_i.size() && pairs_i.size() < max_pairs; ++k) {
        size_t i = sorted_i[k];
        size_t j = sorted_j[k];
        
        if (!used[i] && !used[j]) {
            pairs_i.push_back(i);
            pairs_j.push_back(j);
            used[i] = true;
            used[j] = true;
        }
    }
    
    return {pairs_i, pairs_j};
}

// ============== PAIR MERGING ==============

void merge_pairs_inplace(
    GaussianCloud& cloud,
    const std::vector<size_t>& pairs_i,
    const std::vector<size_t>& pairs_j,
    std::vector<bool>& active,
    const ReductionParams& params
) {
    size_t n_pairs = pairs_i.size();
    
    #pragma omp parallel for schedule(dynamic)
    for (size_t k = 0; k < n_pairs; ++k) {
        size_t i = pairs_i[k];
        size_t j = pairs_j[k];
        
        // Compute optical mass weights
        float v_i = cloud.scales(i, 0) * cloud.scales(i, 1) * cloud.scales(i, 2);
        float v_j = cloud.scales(j, 0) * cloud.scales(j, 1) * cloud.scales(j, 2);
        
        float o_i = std::min(cloud.opacities(i), 0.9999999f);
        float o_j = std::min(cloud.opacities(j), 0.9999999f);
        
        float m_i = -std::log(1.0f - o_i) * v_i;
        float m_j = -std::log(1.0f - o_j) * v_j;
        
        float w_total = (m_i + m_j) * params.opacity_boost;
        
        float geom_mass = m_i + m_j;
        float a_i = (geom_mass > 1e-10f) ? (m_i / geom_mass) : 0.5f;
        float a_j = 1.0f - a_i;
        
        // New position
        Eigen::Vector3f pos_i = cloud.positions.row(i);
        Eigen::Vector3f pos_j = cloud.positions.row(j);
        Eigen::Vector3f new_pos = a_i * pos_i + a_j * pos_j;
        
        // New covariance
        Eigen::Vector3f d_i = pos_i - new_pos;
        Eigen::Vector3f d_j = pos_j - new_pos;
        Eigen::Matrix3f outer_i = d_i * d_i.transpose();
        Eigen::Matrix3f outer_j = d_j * d_j.transpose();
        Eigen::Matrix3f new_cov = a_i * (cloud.get_covariance(i) + outer_i) + 
                                   a_j * (cloud.get_covariance(j) + outer_j);
        
        // Eigensolve for scale/rotation (use computeDirect for 3x3 closed-form solution)
        Eigen::SelfAdjointEigenSolver<Eigen::Matrix3f> solver;
        solver.computeDirect(new_cov);
        Eigen::Vector3f evals = solver.eigenvalues().cwiseMax(1e-7f);
        Eigen::Matrix3f evecs = solver.eigenvectors();
        
        // Fix handedness
        if (evecs.determinant() < 0) {
            evecs.col(0) *= -1;
        }
        
        // Extract scales and apply boost
        Eigen::Vector3f new_scales = evals.cwiseSqrt() * params.scale_boost;
        
        // Convert rotation matrix to quaternion
        Eigen::Quaternionf quat(evecs);
        quat.normalize();
        
        // New opacity
        float new_vol = new_scales(0) * new_scales(1) * new_scales(2);
        float eff_vol = std::min(new_vol, v_i + v_j);
        float new_op = 1.0f - std::exp(-w_total / (eff_vol + 1e-10f));
        
        // Blend SH coefficients
        Eigen::Vector3f new_dc = a_i * cloud.sh_dc.row(i).transpose() + 
                                  a_j * cloud.sh_dc.row(j).transpose();
        Eigen::VectorXf new_rest = a_i * cloud.sh_rest.row(i).transpose() + 
                                    a_j * cloud.sh_rest.row(j).transpose();
        
        // Update cloud at position i
        cloud.positions.row(i) = new_pos;
        cloud.scales.row(i) = new_scales;
        cloud.rotations(i, 0) = quat.w();
        cloud.rotations(i, 1) = quat.x();
        cloud.rotations(i, 2) = quat.y();
        cloud.rotations(i, 3) = quat.z();
        cloud.opacities(i) = new_op;
        cloud.sh_dc.row(i) = new_dc;
        cloud.sh_rest.row(i) = new_rest;
        cloud.set_covariance(i, new_cov);
    }
    
    // Mark j indices as inactive
    for (size_t j : pairs_j) {
        active[j] = false;
    }
}

// ============== COVERAGE-AWARE SCALING ==============

void adjust_scales_for_coverage_local(
    GaussianCloud& cloud,
    const std::vector<size_t>& active_indices,
    const Eigen::MatrixXf& active_pos,
    const std::vector<std::vector<size_t>>& neighbors,
    float coverage_fraction,
    float min_mult,
    float max_mult
) {
    size_t n = active_indices.size();
    
    #pragma omp parallel for schedule(static)
    for (size_t idx = 0; idx < n; ++idx) {
        size_t global_i = active_indices[idx];
        
        // Get rotation matrix from cloud
        Eigen::Vector4f q = cloud.rotations.row(global_i).normalized();
        float w = q(0), x = q(1), y = q(2), z = q(3);
        
        Eigen::Matrix3f R;
        R << 1 - 2*y*y - 2*z*z,     2*x*y - 2*w*z,     2*x*z + 2*w*y,
             2*x*y + 2*w*z,     1 - 2*x*x - 2*z*z,     2*y*z - 2*w*x,
             2*x*z - 2*w*y,         2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y;
        
        // Find max distance along each principal axis
        Eigen::Vector3f max_dist = Eigen::Vector3f::Zero();
        Eigen::Vector3f pos_i = active_pos.row(idx);
        
        for (size_t local_neighbor : neighbors[idx]) {
            Eigen::Vector3f delta = active_pos.row(local_neighbor).transpose() - pos_i;
            
            for (int axis = 0; axis < 3; ++axis) {
                float proj = std::abs(delta.dot(R.col(axis)));
                max_dist(axis) = std::max(max_dist(axis), proj);
            }
        }
        
        // Adjust scales
        Eigen::Vector3f current_scales = cloud.scales.row(global_i);
        for (int axis = 0; axis < 3; ++axis) {
            if (max_dist(axis) > 1e-6f && current_scales(axis) > 1e-6f) {
                float target = max_dist(axis) * coverage_fraction;
                float mult = std::clamp(target / current_scales(axis), min_mult, max_mult);
                cloud.scales(global_i, axis) = current_scales(axis) * mult;
            }
        }
    }
    
    // Recompute covariances for modified gaussians (only needed in non-lazy mode)
    if (!cloud.lazy_covariance) {
        for (size_t global_i : active_indices) {
            Eigen::Vector4f q = cloud.rotations.row(global_i).normalized();
            float w = q(0), x = q(1), y = q(2), z = q(3);
            
            Eigen::Matrix3f R;
            R << 1 - 2*y*y - 2*z*z,     2*x*y - 2*w*z,     2*x*z + 2*w*y,
                 2*x*y + 2*w*z,     1 - 2*x*x - 2*z*z,     2*y*z - 2*w*x,
                 2*x*z - 2*w*y,         2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y;
            
            Eigen::Vector3f s = cloud.scales.row(global_i);
            Eigen::Matrix3f S_sq = Eigen::Vector3f(s(0)*s(0), s(1)*s(1), s(2)*s(2)).asDiagonal();
            cloud.set_covariance(global_i, R * S_sq * R.transpose());
        }
    }
}

// Version using flat neighbor array (memory optimized - avoids millions of small allocations)
void adjust_scales_for_coverage_flat(
    GaussianCloud& cloud,
    const std::vector<size_t>& active_indices,
    const Eigen::MatrixXf& active_pos,
    const std::vector<size_t>& neighbor_flat,
    size_t k_neighbors,
    float coverage_fraction,
    float min_mult,
    float max_mult
) {
    size_t n = active_indices.size();
    
    #pragma omp parallel for schedule(static)
    for (size_t idx = 0; idx < n; ++idx) {
        size_t global_i = active_indices[idx];
        
        // Get rotation matrix from cloud
        Eigen::Vector4f q = cloud.rotations.row(global_i).normalized();
        float w = q(0), x = q(1), y = q(2), z = q(3);
        
        Eigen::Matrix3f R;
        R << 1 - 2*y*y - 2*z*z,     2*x*y - 2*w*z,     2*x*z + 2*w*y,
             2*x*y + 2*w*z,     1 - 2*x*x - 2*z*z,     2*y*z - 2*w*x,
             2*x*z - 2*w*y,         2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y;
        
        // Find max distance along each principal axis
        Eigen::Vector3f max_dist = Eigen::Vector3f::Zero();
        Eigen::Vector3f pos_i = active_pos.row(idx);
        
        // Read from flat neighbor array
        size_t base = idx * k_neighbors;
        for (size_t ni = 0; ni < k_neighbors; ++ni) {
            size_t local_neighbor = neighbor_flat[base + ni];
            if (local_neighbor == SIZE_MAX) break;  // Sentinel value
            
            Eigen::Vector3f delta = active_pos.row(local_neighbor).transpose() - pos_i;
            
            for (int axis = 0; axis < 3; ++axis) {
                float proj = std::abs(delta.dot(R.col(axis)));
                max_dist(axis) = std::max(max_dist(axis), proj);
            }
        }
        
        // Adjust scales
        Eigen::Vector3f current_scales = cloud.scales.row(global_i);
        for (int axis = 0; axis < 3; ++axis) {
            if (max_dist(axis) > 1e-6f && current_scales(axis) > 1e-6f) {
                float target = max_dist(axis) * coverage_fraction;
                float mult = std::clamp(target / current_scales(axis), min_mult, max_mult);
                cloud.scales(global_i, axis) = current_scales(axis) * mult;
            }
        }
    }
    
    // Recompute covariances for modified gaussians (only needed in non-lazy mode)
    if (!cloud.lazy_covariance) {
        for (size_t global_i : active_indices) {
            Eigen::Vector4f q = cloud.rotations.row(global_i).normalized();
            float w = q(0), x = q(1), y = q(2), z = q(3);
            
            Eigen::Matrix3f R;
            R << 1 - 2*y*y - 2*z*z,     2*x*y - 2*w*z,     2*x*z + 2*w*y,
                 2*x*y + 2*w*z,     1 - 2*x*x - 2*z*z,     2*y*z - 2*w*x,
                 2*x*z - 2*w*y,         2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y;
            
            Eigen::Vector3f s = cloud.scales.row(global_i);
            Eigen::Matrix3f S_sq = Eigen::Vector3f(s(0)*s(0), s(1)*s(1), s(2)*s(2)).asDiagonal();
            cloud.set_covariance(global_i, R * S_sq * R.transpose());
        }
    }
}

// ============== MAIN REDUCTION ==============

GaussianCloud reduce_cloud(
    GaussianCloud&& cloud,
    size_t target_count,
    const ReductionParams& params,
    CheckpointConfig* checkpoint,
    std::function<void(const GaussianCloud&, const std::string&)> save_fn
) {
    if (cloud.size() <= target_count) return cloud;
 
    auto start_time = std::chrono::steady_clock::now();
    
    // Set lazy covariance mode from params
    cloud.lazy_covariance = params.lazy_covariance;
    
    // Compute initial covariances (skipped in lazy mode)
    cloud.compute_covariances();
    
    const size_t original_count = cloud.size();
    size_t to_remove = original_count - target_count;
    size_t iteration = 0;
    
    // Keep vector for marking gaussians to remove each iteration
    // After each merge, we compact the cloud so indices are always 0..n-1
    std::vector<bool> keep;
    
    // ===== PRE-ALLOCATE LOOP TEMPORARIES =====
    std::vector<size_t> candidate_i, candidate_j;
    candidate_i.reserve(original_count);
    candidate_j.reserve(original_count);
    
    std::vector<float> costs;
    costs.reserve(original_count);
    
    std::vector<size_t> order;
    order.reserve(original_count);
    
    std::vector<size_t> sorted_i, sorted_j;
    sorted_i.reserve(original_count);
    sorted_j.reserve(original_count);
    
    // Flat neighbor storage for coverage-aware scaling
    constexpr size_t K_NEIGHBORS = 8;
    std::vector<size_t> neighbor_flat;
    if (params.coverage_aware) {
        neighbor_flat.reserve(original_count * K_NEIGHBORS);
    }
    // ===== END PRE-ALLOCATION =====
    
    while (cloud.size() > target_count) {
        ++iteration;
        size_t n = cloud.size();
        
        // Build KDTree directly on cloud.positions (already compact)
        PointCloud pc(cloud.positions);
        KDTree tree(3, pc, nanoflann::KDTreeSingleIndexAdaptorParams(10));
        tree.buildIndex();
        
        // Coverage-aware scaling (skip first iteration)
        if (params.coverage_aware && iteration > 1 && n > 8) {
            neighbor_flat.resize(n * K_NEIGHBORS);
            
            // Create identity index mapping (cloud is already compact)
            std::vector<size_t> identity_idx(n);
            std::iota(identity_idx.begin(), identity_idx.end(), 0);
            
            #pragma omp parallel for schedule(static)
            for (size_t i = 0; i < n; ++i) {
                size_t k = std::min<size_t>(K_NEIGHBORS + 1, n);
                // Use stack arrays instead of heap allocation
                size_t indices[K_NEIGHBORS + 2];
                float dists[K_NEIGHBORS + 2];
                
                nanoflann::KNNResultSet<float, size_t> result(k);
                result.init(indices, dists);
                
                float query[3] = {cloud.positions(i, 0), cloud.positions(i, 1), cloud.positions(i, 2)};
                tree.findNeighbors(result, query, {});
                
                size_t base = i * K_NEIGHBORS;
                size_t stored = 0;
                for (size_t j = 1; j < result.size() && stored < K_NEIGHBORS; ++j) {
                    neighbor_flat[base + stored++] = indices[j];
                }
                while (stored < K_NEIGHBORS) {
                    neighbor_flat[base + stored++] = SIZE_MAX;
                }
            }
            
            adjust_scales_for_coverage_flat(cloud, identity_idx, cloud.positions, neighbor_flat,
                                            K_NEIGHBORS, params.coverage_fraction, 1.0f, 1.5f);
        }
        
        // Find nearest neighbor for each gaussian
        candidate_i.resize(n);
        candidate_j.resize(n);
        
        #pragma omp parallel for schedule(static)
        for (size_t i = 0; i < n; ++i) {
            size_t indices[2];
            float dists[2];
            
            nanoflann::KNNResultSet<float, size_t> result(2);
            result.init(indices, dists);
            
            float query[3] = {cloud.positions(i, 0), cloud.positions(i, 1), cloud.positions(i, 2)};
            tree.findNeighbors(result, query, {});
            
            candidate_i[i] = i;
            candidate_j[i] = indices[1];
        }
        
        // Compute merge costs
        costs.resize(n);
        if (params.use_bhattacharyya) {
            compute_merge_costs_into(cloud, candidate_i, candidate_j, costs);
        } else {
            #pragma omp parallel for
            for (size_t k = 0; k < n; ++k) {
                Eigen::Vector3f diff = cloud.positions.row(candidate_i[k]) - 
                                       cloud.positions.row(candidate_j[k]);
                float avg_scale = (cloud.scales.row(candidate_i[k]).mean() + 
                                   cloud.scales.row(candidate_j[k]).mean()) / 2.0f;
                costs[k] = diff.norm() / std::max(avg_scale, 1e-6f);
            }
        }
        
        // Partial sort by cost (only need top max_pairs, not full sort)
        order.resize(n);
        std::iota(order.begin(), order.end(), 0);
        
        // Determine max pairs first so we know how many to partial_sort
        size_t max_by_target = n - target_count;
        size_t max_by_batch = n / 4;
        size_t max_pairs = std::max<size_t>(1, std::min(max_by_target, max_by_batch));
        
        // Check for checkpoint
        if (checkpoint && !checkpoint->targets.empty()) {
            size_t next_checkpoint = 0;
            for (size_t t : checkpoint->targets) {
                if (t < n) next_checkpoint = std::max(next_checkpoint, t);
            }
            if (next_checkpoint > 0) {
                size_t max_by_cp = n - next_checkpoint;
                max_pairs = std::max<size_t>(1, std::min({max_by_cp, max_by_target, max_by_batch}));
            }
        }
        
        // Partial sort: only sort enough to get the lowest-cost candidates
        // We need 4x max_pairs because greedy selection may skip many due to conflicts
        size_t sort_count = std::min(n, max_pairs * 4);
        std::partial_sort(order.begin(), order.begin() + sort_count, order.end(),
                          [&](size_t a, size_t b) { return costs[a] < costs[b]; });
        
        sorted_i.resize(sort_count);
        sorted_j.resize(sort_count);
        for (size_t k = 0; k < sort_count; ++k) {
            sorted_i[k] = candidate_i[order[k]];
            sorted_j[k] = candidate_j[order[k]];
        }
        
        // Select pairs greedily
        auto [pairs_i, pairs_j] = select_pairs_greedy(sorted_i, sorted_j, max_pairs, n);
        
        if (pairs_i.empty()) break;
        
        // Initialize keep vector (all true)
        keep.assign(n, true);
        
        // Merge pairs - result stored at pairs_i[k], pairs_j[k] marked for removal
        merge_pairs_inplace(cloud, pairs_i, pairs_j, keep, params);
        
        // Compact the cloud immediately (shrinks in-place)
        cloud.compact_inplace(keep);
        
        // Print progress
        auto now = std::chrono::steady_clock::now();
        double elapsed = std::chrono::duration<double>(now - start_time).count();
        size_t removed = original_count - cloud.size();
        double rate = elapsed > 0 ? removed / elapsed : 0;
        double pct = 100.0 * removed / std::max<size_t>(1, to_remove);
#ifdef __EMSCRIPTEN__
        std::cout << "  " << std::fixed << std::setprecision(1)
                  << pct << "% (" << removed << "/" << to_remove << " removed) "
                  << std::setprecision(0) << rate << " g/s" << std::endl;
#else
        std::cout << "\r  " << std::fixed << std::setprecision(1)
                  << pct << "% (" << removed << "/" << to_remove << " removed) "
                  << std::setprecision(0) << rate << " g/s   " << std::flush;
#endif
        
        // Checkpoint saving
        if (checkpoint && save_fn && !checkpoint->targets.empty()) {
            std::vector<size_t> crossed;
            for (size_t t : checkpoint->targets) {
                if (cloud.size() <= t) crossed.push_back(t);
            }
            
            if (!crossed.empty()) {
                std::string base = checkpoint->output_path;
                size_t dot = base.rfind('.');
                if (dot != std::string::npos) base = base.substr(0, dot);
                
                std::string path = base + "_lod" + std::to_string(checkpoint->lod_counter++) 
                                 + "_" + std::to_string(cloud.size()) + ".ply";
                
                std::cout << "\n  Saving checkpoint: " << path << "..." << std::flush;
                save_fn(cloud, path);
                std::cout << " done\n";
                
                for (size_t t : crossed) {
                    checkpoint->targets.erase(
                        std::remove(checkpoint->targets.begin(), checkpoint->targets.end(), t),
                        checkpoint->targets.end());
                }
            }
        }
    }
    
    // Print final progress
    auto end_time = std::chrono::steady_clock::now();
    double total_elapsed = std::chrono::duration<double>(end_time - start_time).count();
    size_t final_removed = original_count - cloud.size();
    double final_rate = total_elapsed > 0 ? final_removed / total_elapsed : 0;
#ifdef __EMSCRIPTEN__
    std::cout << "  100.0% (" << final_removed << "/" << to_remove << " removed) "
              << std::fixed << std::setprecision(0) << final_rate << " g/s" << std::endl;
#else
    std::cout << "\r  100.0% (" << final_removed << "/" << to_remove << " removed) "
              << std::fixed << std::setprecision(0) << final_rate << " g/s   \n";
#endif
    
    // Cloud is already compact - return it directly
    return cloud;
}

} // namespace autolod
