#pragma once

#include <Eigen/Dense>
#include <cmath>
#include <array>

namespace sh {

// SH Constants (up to degree 3)
constexpr float SH_C0 = 0.28209479177387814f;
constexpr float SH_C1 = 0.4886025119029199f;

constexpr std::array<float, 5> SH_C2 = {
    1.0925484305920792f, -1.0925484305920792f, 0.31539156525252005f,
    -1.0925484305920792f, 0.5462742152960396f
};

constexpr std::array<float, 7> SH_C3 = {
    -0.5900435899266435f, 2.890611442640554f, -0.4570457994644658f,
    0.3731763325901154f, -0.4570457994644658f, 1.445305721320277f,
    -0.5900435899266435f
};

constexpr int N_SAMPLE_DIRS = 32;
constexpr int MAX_SH_COEFFS = 16;

// Precomputed SH basis and pseudo-inverse
struct SHBasis {
    Eigen::Matrix<float, N_SAMPLE_DIRS, MAX_SH_COEFFS> basis;
    Eigen::Matrix<float, MAX_SH_COEFFS, N_SAMPLE_DIRS> basis_pinv;
    
    SHBasis() {
        const float phi = M_PI * (3.0f - std::sqrt(5.0f));
        
        for (int i = 0; i < N_SAMPLE_DIRS; ++i) {
            float y_coord = 1.0f - (static_cast<float>(i) / (N_SAMPLE_DIRS - 1)) * 2.0f;
            float r = std::sqrt(1.0f - y_coord * y_coord);
            float angle = phi * i;
            
            float x = std::cos(angle) * r;
            float y = y_coord;
            float z = std::sin(angle) * r;
            
            float xx = x*x, yy = y*y, zz = z*z;
            float xy = x*y, yz = y*z, xz = x*z;
            
            basis(i, 0) = SH_C0;
            basis(i, 1) = -SH_C1 * y;
            basis(i, 2) = SH_C1 * z;
            basis(i, 3) = -SH_C1 * x;
            basis(i, 4) = SH_C2[0] * xy;
            basis(i, 5) = SH_C2[1] * yz;
            basis(i, 6) = SH_C2[2] * (2*zz - xx - yy);
            basis(i, 7) = SH_C2[3] * xz;
            basis(i, 8) = SH_C2[4] * (xx - yy);
            basis(i, 9) = SH_C3[0] * y * (3*xx - yy);
            basis(i, 10) = SH_C3[1] * xy * z;
            basis(i, 11) = SH_C3[2] * y * (4*zz - xx - yy);
            basis(i, 12) = SH_C3[3] * z * (2*zz - 3*xx - 3*yy);
            basis(i, 13) = SH_C3[4] * x * (4*zz - xx - yy);
            basis(i, 14) = SH_C3[5] * z * (xx - yy);
            basis(i, 15) = SH_C3[6] * x * (xx - 3*yy);
        }
        
        basis_pinv = (basis.transpose() * basis).ldlt().solve(basis.transpose());
    }
};

inline const SHBasis& get_sh_basis() {
    static SHBasis instance;
    return instance;
}

inline void resample_sh(
    const Eigen::Vector3f& sh_dc_i, const Eigen::VectorXf& sh_rest_i,
    const Eigen::Vector3f& sh_dc_j, const Eigen::VectorXf& sh_rest_j,
    float a_i, float a_j,
    Eigen::Vector3f& new_dc, Eigen::VectorXf& new_rest
) {
    const auto& basis = get_sh_basis();
    
    int n_rest = sh_rest_i.size();
    int n_coeffs = std::min((n_rest / 3) + 1, MAX_SH_COEFFS);
    
    Eigen::Matrix<float, N_SAMPLE_DIRS, 3> colors_i, colors_j;
    
    for (int ch = 0; ch < 3; ++ch) {
        Eigen::Matrix<float, MAX_SH_COEFFS, 1> sh_i = Eigen::Matrix<float, MAX_SH_COEFFS, 1>::Zero();
        Eigen::Matrix<float, MAX_SH_COEFFS, 1> sh_j = Eigen::Matrix<float, MAX_SH_COEFFS, 1>::Zero();
        
        sh_i(0) = sh_dc_i(ch);
        sh_j(0) = sh_dc_j(ch);
        
        for (int c = 1; c < n_coeffs; ++c) {
            int rest_idx = (c - 1) * 3 + ch;
            if (rest_idx < n_rest) {
                sh_i(c) = sh_rest_i(rest_idx);
                sh_j(c) = sh_rest_j(rest_idx);
            }
        }
        
        colors_i.col(ch) = basis.basis.leftCols(n_coeffs) * sh_i.head(n_coeffs);
        colors_j.col(ch) = basis.basis.leftCols(n_coeffs) * sh_j.head(n_coeffs);
    }
    
    Eigen::Matrix<float, N_SAMPLE_DIRS, 3> blended = a_i * colors_i + a_j * colors_j;
    
    new_rest.resize(n_rest);
    new_rest.setZero();
    
    for (int ch = 0; ch < 3; ++ch) {
        Eigen::VectorXf new_sh = basis.basis_pinv.topRows(n_coeffs) * blended.col(ch);
        new_dc(ch) = new_sh(0);
        
        for (int c = 1; c < n_coeffs; ++c) {
            int rest_idx = (c - 1) * 3 + ch;
            if (rest_idx < n_rest) {
                new_rest(rest_idx) = new_sh(c);
            }
        }
    }
}

} // namespace sh
