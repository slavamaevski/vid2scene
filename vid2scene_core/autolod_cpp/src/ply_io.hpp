#pragma once

#include "gaussian.hpp"
#include <fstream>
#include <iostream>
#include <sstream>
#include <algorithm>
#include <stdexcept>
#include <filesystem>

// Simple PLY parser for 3DGS files
namespace ply {

GaussianCloud load(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Cannot open file: " + path);
    
    // Parse header
    std::string line;
    size_t vertex_count = 0;
    std::vector<std::string> properties;
    
    while (std::getline(file, line)) {
        if (line.find("element vertex") != std::string::npos) {
            std::istringstream iss(line);
            std::string tmp;
            iss >> tmp >> tmp >> vertex_count;
        } else if (line.find("property float") != std::string::npos) {
            std::istringstream iss(line);
            std::string tmp, type, name;
            iss >> tmp >> type >> name;
            properties.push_back(name);
        } else if (line == "end_header") {
            break;
        }
    }
    
    // Build property index map
    auto prop_idx = [&](const std::string& name) -> int {
        auto it = std::find(properties.begin(), properties.end(), name);
        return (it != properties.end()) ? (it - properties.begin()) : -1;
    };
    
    // Read binary data
    size_t n_props = properties.size();
    std::vector<float> buffer(n_props);
    
    GaussianCloud cloud;
    cloud.positions.resize(vertex_count, 3);
    cloud.scales.resize(vertex_count, 3);
    cloud.rotations.resize(vertex_count, 4);
    cloud.opacities.resize(vertex_count);
    cloud.sh_dc.resize(vertex_count, 3);
    
    // Count SH rest coefficients
    int n_sh_rest = 0;
    for (const auto& p : properties) {
        if (p.find("f_rest_") == 0) n_sh_rest++;
    }
    cloud.sh_rest.resize(vertex_count, n_sh_rest);
    
    // Property indices
    int idx_x = prop_idx("x"), idx_y = prop_idx("y"), idx_z = prop_idx("z");
    int idx_s0 = prop_idx("scale_0"), idx_s1 = prop_idx("scale_1"), idx_s2 = prop_idx("scale_2");
    int idx_r0 = prop_idx("rot_0"), idx_r1 = prop_idx("rot_1"), idx_r2 = prop_idx("rot_2"), idx_r3 = prop_idx("rot_3");
    int idx_op = prop_idx("opacity");
    int idx_dc0 = prop_idx("f_dc_0"), idx_dc1 = prop_idx("f_dc_1"), idx_dc2 = prop_idx("f_dc_2");
    
    // Pre-compute SH rest indices (critical optimization - avoids 12.5M x 45 string lookups!)
    std::vector<int> idx_sh_rest(n_sh_rest);
    for (int j = 0; j < n_sh_rest; ++j) {
        idx_sh_rest[j] = prop_idx("f_rest_" + std::to_string(j));
    }
    
    // Chunked reading for performance (reduces syscalls)
    constexpr size_t CHUNK_SIZE = 1048576; // 1M vertices per I/O chunk
    constexpr size_t BLOCK_SIZE = 4096;    // Process in smaller blocks for L2 cache
    std::vector<float> chunk_buffer(CHUNK_SIZE * n_props);
    
    std::cerr << "Loading " << vertex_count << " vertices..." << std::flush;
    
    int last_pct = -1;
    size_t vertices_loaded = 0;
    while (vertices_loaded < vertex_count) {
        // Determine chunk size
        size_t chunk_vertices = std::min(CHUNK_SIZE, vertex_count - vertices_loaded);
        size_t chunk_bytes = chunk_vertices * n_props * sizeof(float);
        
        // Read chunk
        file.read(reinterpret_cast<char*>(chunk_buffer.data()), chunk_bytes);
        
        // Process chunk in blocks
        for (size_t b_start = 0; b_start < chunk_vertices; b_start += BLOCK_SIZE) {
            size_t b_count = std::min(BLOCK_SIZE, chunk_vertices - b_start);
            
            // Helper for reading columns (Strided read -> Sequential write)
            auto read_prop_col = [&](int buf_offset, Eigen::MatrixXf& mat, int mat_col) {
                for (size_t k = 0; k < b_count; ++k) {
                    size_t v_idx = vertices_loaded + b_start + k;
                    size_t b_idx = b_start + k;
                    mat(v_idx, mat_col) = chunk_buffer[b_idx * n_props + buf_offset];
                }
            };
            
            // Position
            read_prop_col(idx_x, cloud.positions, 0);
            read_prop_col(idx_y, cloud.positions, 1);
            read_prop_col(idx_z, cloud.positions, 2);
            
            // Scales (log to exp)
            for (int d = 0; d < 3; ++d) {
                int idx_s = (d == 0) ? idx_s0 : (d == 1 ? idx_s1 : idx_s2);
                for (size_t k = 0; k < b_count; ++k) {
                    size_t v_idx = vertices_loaded + b_start + k;
                    size_t b_idx = b_start + k;
                    cloud.scales(v_idx, d) = std::exp(chunk_buffer[b_idx * n_props + idx_s]);
                }
            }
            
            // Rotations (raw)
            read_prop_col(idx_r0, cloud.rotations, 0);
            read_prop_col(idx_r1, cloud.rotations, 1);
            read_prop_col(idx_r2, cloud.rotations, 2);
            read_prop_col(idx_r3, cloud.rotations, 3);
            
            // Opacity (sigmoid)
            for (size_t k = 0; k < b_count; ++k) {
                size_t v_idx = vertices_loaded + b_start + k;
                size_t b_idx = b_start + k;
                cloud.opacities(v_idx) = 1.0f / (1.0f + std::exp(-chunk_buffer[b_idx * n_props + idx_op]));
            }
            
            // SH DC
            read_prop_col(idx_dc0, cloud.sh_dc, 0);
            read_prop_col(idx_dc1, cloud.sh_dc, 1);
            read_prop_col(idx_dc2, cloud.sh_dc, 2);
            
            // SH Rest
            for (int j = 0; j < n_sh_rest; ++j) {
                int idx = idx_sh_rest[j];
                if (idx >= 0) {
                    read_prop_col(idx, cloud.sh_rest, j);
                } else {
                    for (size_t k = 0; k < b_count; ++k) {
                        cloud.sh_rest(vertices_loaded + b_start + k, j) = 0.0f;
                    }
                }
            }
        }
        
        vertices_loaded += chunk_vertices;
        
        // Progress every ~5% (not every chunk)
        int pct = static_cast<int>((100 * vertices_loaded) / vertex_count);
        if (pct >= last_pct + 5 || vertices_loaded == vertex_count) {
            last_pct = pct;
#ifdef __EMSCRIPTEN__
            std::cerr << "Loading " << vertex_count << " vertices... " << pct << "%" << std::endl;
#else
            std::cerr << "\rLoading " << vertex_count << " vertices... " << pct << "%" << std::flush;
#endif
        }
    }
    
    std::cerr << "\rLoading " << vertex_count << " vertices... done" << std::endl;
    
    return cloud;
}

void save(const GaussianCloud& cloud, const std::string& path) {
    // Create parent directories if they don't exist
    std::filesystem::path fs_path(path);
    if (fs_path.has_parent_path()) {
        std::filesystem::create_directories(fs_path.parent_path());
    }
    
    std::ofstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Cannot write file: " + path);
    
    size_t n = cloud.size();
    int n_sh_rest = cloud.sh_rest.cols();
    
    // Write header
    file << "ply\n";
    file << "format binary_little_endian 1.0\n";
    file << "element vertex " << n << "\n";
    file << "property float x\n";
    file << "property float y\n";
    file << "property float z\n";
    file << "property float nx\n";
    file << "property float ny\n";
    file << "property float nz\n";
    file << "property float f_dc_0\n";
    file << "property float f_dc_1\n";
    file << "property float f_dc_2\n";
    for (int j = 0; j < n_sh_rest; ++j) {
        file << "property float f_rest_" << j << "\n";
    }
    file << "property float opacity\n";
    file << "property float scale_0\n";
    file << "property float scale_1\n";
    file << "property float scale_2\n";
    file << "property float rot_0\n";
    file << "property float rot_1\n";
    file << "property float rot_2\n";
    file << "property float rot_3\n";
    file << "end_header\n";
    
    // Calculate floats per vertex: x,y,z, nx,ny,nz, dc0,dc1,dc2, sh_rest..., op, s0,s1,s2, r0,r1,r2,r3
    size_t floats_per_vertex = 3 + 3 + 3 + n_sh_rest + 1 + 3 + 4; // = 17 + n_sh_rest
    
    // Chunked writing to avoid huge memory spike
    constexpr size_t CHUNK_SIZE = 1048576; // 1M vertices per I/O chunk
    constexpr size_t BLOCK_SIZE = 4096;    // Process in smaller blocks for cache locality (fits in L2)
    std::vector<float> buffer(CHUNK_SIZE * floats_per_vertex);
    
    size_t vertices_written = 0;
    while (vertices_written < n) {
        size_t chunk_vertices = std::min(CHUNK_SIZE, n - vertices_written);
        
        // Process chunk in blocks to maximize cache usage
        // We write property-by-property within a small block (Structure-of-Arrays style read, Array-of-Structures style write)
        for (size_t b_start = 0; b_start < chunk_vertices; b_start += BLOCK_SIZE) {
            size_t b_count = std::min(BLOCK_SIZE, chunk_vertices - b_start);
            
            // Helper to fill a column property
            auto write_prop_col = [&](int buf_offset, const Eigen::MatrixXf& mat, int mat_col) {
                for (size_t k = 0; k < b_count; ++k) {
                    size_t v_idx = vertices_written + b_start + k; // Global vertex index
                    size_t b_idx = b_start + k;                    // Buffer vertex index
                    buffer[b_idx * floats_per_vertex + buf_offset] = mat(v_idx, mat_col);
                }
            };

            // Position (0,1,2)
            write_prop_col(0, cloud.positions, 0);
            write_prop_col(1, cloud.positions, 1);
            write_prop_col(2, cloud.positions, 2);
            
            // Normals (3,4,5) - unused, fill with 0
            for (size_t k = 0; k < b_count; ++k) {
                size_t offset = (b_start + k) * floats_per_vertex + 3;
                buffer[offset] = 0.0f;
                buffer[offset+1] = 0.0f;
                buffer[offset+2] = 0.0f;
            }
            
            int offset = 6;
            
            // SH DC (6,7,8)
            write_prop_col(offset++, cloud.sh_dc, 0);
            write_prop_col(offset++, cloud.sh_dc, 1);
            write_prop_col(offset++, cloud.sh_dc, 2);
            
            // SH Rest
            for (int j = 0; j < n_sh_rest; ++j) {
                write_prop_col(offset++, cloud.sh_rest, j);
            }
            
            // Opacity
            for (size_t k = 0; k < b_count; ++k) {
                 size_t v_idx = vertices_written + b_start + k;
                 size_t b_idx = b_start + k;
                 float op = std::clamp(cloud.opacities(v_idx), 1e-6f, 1.0f - 1e-6f);
                 buffer[b_idx * floats_per_vertex + offset] = std::log(op / (1.0f - op));
            }
            offset++;
            
            // Scales (log)
            for (int d = 0; d < 3; ++d) {
                 for (size_t k = 0; k < b_count; ++k) {
                     size_t v_idx = vertices_written + b_start + k;
                     size_t b_idx = b_start + k;
                     buffer[b_idx * floats_per_vertex + offset] = std::log(cloud.scales(v_idx, d));
                 }
                 offset++;
            }
            
            // Rotation
            write_prop_col(offset++, cloud.rotations, 0);
            write_prop_col(offset++, cloud.rotations, 1);
            write_prop_col(offset++, cloud.rotations, 2);
            write_prop_col(offset++, cloud.rotations, 3);
        }
        
        // Write chunk
        file.write(reinterpret_cast<const char*>(buffer.data()), 
                   chunk_vertices * floats_per_vertex * sizeof(float));
        vertices_written += chunk_vertices;
    }
}

} // namespace ply
