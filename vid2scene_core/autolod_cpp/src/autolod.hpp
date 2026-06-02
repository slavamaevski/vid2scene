#pragma once

#include "gaussian.hpp"
#include <vector>
#include <string>
#include <functional>

namespace autolod {

struct ReductionParams {
    bool use_bhattacharyya = true;
    bool use_resampling = true;  // SH resampling in color space
    bool lazy_covariance = false; // Cache covariances for speed (uses more memory)
    float opacity_boost = 1.0f;
    float scale_boost = 1.1f;
    bool coverage_aware = true;
    float coverage_fraction = 0.1f;
    float min_opacity = 0.005f;
};

struct CheckpointConfig {
    std::string output_path;
    std::vector<size_t> targets;  // Intermediate save points
    size_t lod_counter = 0;
};

// Core algorithms
std::vector<float> compute_merge_costs(
    const GaussianCloud& cloud,
    const std::vector<size_t>& candidate_i,
    const std::vector<size_t>& candidate_j
);

std::pair<std::vector<size_t>, std::vector<size_t>> select_pairs_greedy(
    const std::vector<size_t>& sorted_i,
    const std::vector<size_t>& sorted_j,
    size_t max_pairs,
    size_t n
);

void merge_pairs_inplace(
    GaussianCloud& cloud,
    const std::vector<size_t>& pairs_i,
    const std::vector<size_t>& pairs_j,
    std::vector<bool>& active,
    const ReductionParams& params
);

void adjust_scales_for_coverage_local(
    GaussianCloud& cloud,
    const std::vector<size_t>& active_indices,
    const Eigen::MatrixXf& active_pos,
    const std::vector<std::vector<size_t>>& neighbors,
    float coverage_fraction,
    float min_mult,
    float max_mult
);

// Main reduction - uses move semantics to avoid copying large clouds
GaussianCloud reduce_cloud(
    GaussianCloud&& cloud,
    size_t target_count,
    const ReductionParams& params = {},
    CheckpointConfig* checkpoint = nullptr,
    std::function<void(const GaussianCloud&, const std::string&)> save_fn = nullptr
);

} // namespace autolod
