#pragma once

#include <vector>
#include <string>
#include <cmath>
#include <Eigen/Dense>

// SH Constants
constexpr float SH_C0 = 0.28209479177387814f;
constexpr float SH_C1 = 0.4886025119029199f;

struct GaussianCloud {
    // Core data (N gaussians)
    Eigen::MatrixXf positions;     // N x 3
    Eigen::MatrixXf scales;        // N x 3
    Eigen::MatrixXf rotations;     // N x 4 (quaternions: w, x, y, z)
    Eigen::VectorXf opacities;     // N
    Eigen::MatrixXf sh_dc;         // N x 3
    Eigen::MatrixXf sh_rest;       // N x (n_coeffs * 3)
    
    // Cached covariances (computed lazily)
    std::vector<Eigen::Matrix3f> covariances;
    bool covariances_valid = false;
    bool lazy_covariance = false;  // If true, compute on-demand instead of storing
    
    size_t size() const { return positions.rows(); }
    
    // Compute covariance for a single gaussian
    Eigen::Matrix3f get_covariance(size_t i) const {
        if (!lazy_covariance && covariances_valid) {
            return covariances[i];
        }
        
        // Compute on-demand
        Eigen::Vector4f q = rotations.row(i).normalized();
        float w = q(0), x = q(1), y = q(2), z = q(3);
        
        Eigen::Matrix3f R;
        R << 1 - 2*y*y - 2*z*z,     2*x*y - 2*w*z,     2*x*z + 2*w*y,
             2*x*y + 2*w*z,     1 - 2*x*x - 2*z*z,     2*y*z - 2*w*x,
             2*x*z - 2*w*y,         2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y;
        
        Eigen::Vector3f s = scales.row(i);
        Eigen::Matrix3f S_sq = Eigen::Vector3f(s(0)*s(0), s(1)*s(1), s(2)*s(2)).asDiagonal();
        
        return R * S_sq * R.transpose();
    }
    
    // Set covariance (only stores if not in lazy mode)
    void set_covariance(size_t i, const Eigen::Matrix3f& cov) {
        if (!lazy_covariance) {
            if (covariances.size() <= i) {
                covariances.resize(i + 1);
            }
            covariances[i] = cov;
        }
    }
    
    void compute_covariances() {
        if (covariances_valid || lazy_covariance) return;
        
        size_t n = size();
        covariances.resize(n);
        
        #pragma omp parallel for schedule(static)
        for (size_t i = 0; i < n; ++i) {
            covariances[i] = get_covariance(i);
        }
        covariances_valid = true;
    }
    
    // Subset extraction
    GaussianCloud subset(const std::vector<size_t>& indices) const {
        GaussianCloud result;
        size_t n = indices.size();
        
        result.positions.resize(n, 3);
        result.scales.resize(n, 3);
        result.rotations.resize(n, 4);
        result.opacities.resize(n);
        result.sh_dc.resize(n, 3);
        result.sh_rest.resize(n, sh_rest.cols());
        
        for (size_t i = 0; i < n; ++i) {
            size_t idx = indices[i];
            result.positions.row(i) = positions.row(idx);
            result.scales.row(i) = scales.row(idx);
            result.rotations.row(i) = rotations.row(idx);
            result.opacities(i) = opacities(idx);
            result.sh_dc.row(i) = sh_dc.row(idx);
            result.sh_rest.row(i) = sh_rest.row(idx);
        }
        
        return result;
    }
    
    // In-place compaction: removes inactive entries without allocating a new cloud
    // Returns the new size after compaction
    size_t compact_inplace(std::vector<bool>& active) {
        size_t n = size();
        size_t write_idx = 0;
        
        for (size_t read_idx = 0; read_idx < n; ++read_idx) {
            if (active[read_idx]) {
                if (write_idx != read_idx) {
                    // Move row from read_idx to write_idx (always write_idx < read_idx)
                    positions.row(write_idx) = positions.row(read_idx);
                    scales.row(write_idx) = scales.row(read_idx);
                    rotations.row(write_idx) = rotations.row(read_idx);
                    opacities(write_idx) = opacities(read_idx);
                    sh_dc.row(write_idx) = sh_dc.row(read_idx);
                    sh_rest.row(write_idx) = sh_rest.row(read_idx);
                    
                    // Move covariance if stored
                    if (!lazy_covariance && covariances_valid && covariances.size() > read_idx) {
                        covariances[write_idx] = covariances[read_idx];
                    }
                }
                ++write_idx;
            }
        }
        
        // Shrink matrices using conservativeResize (keeps existing data)
        positions.conservativeResize(write_idx, Eigen::NoChange);
        scales.conservativeResize(write_idx, Eigen::NoChange);
        rotations.conservativeResize(write_idx, Eigen::NoChange);
        opacities.conservativeResize(write_idx);
        sh_dc.conservativeResize(write_idx, Eigen::NoChange);
        sh_rest.conservativeResize(write_idx, Eigen::NoChange);
        
        if (!lazy_covariance && covariances_valid) {
            covariances.resize(write_idx);
        }
        
        // Reset active vector to match new size (all entries now active)
        active.assign(write_idx, true);
        
        return write_idx;
    }
};
