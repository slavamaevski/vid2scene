#include "ply_io.hpp"
#include "autolod.hpp"
#include <iostream>
#include <iomanip>
#include <string>
#include <vector>
#include <algorithm>
#include <cstdlib>

void print_usage(const char* prog) {
    std::cout << "3DGS AutoLOD Reducer (C++ version)\n\n";
    std::cout << "Usage: " << prog << " input.ply output.ply [options]\n\n";
    std::cout << "Options:\n";
    std::cout << "  -r, --reduction PCT     Target percentage (default: 50)\n";
    std::cout << "  -n, --target-count N    Target absolute count\n";
    std::cout << "  --fast                  Use simple distance metric\n";
    std::cout << "  --min-opacity FLOAT     Cull low-opacity gaussians (default: 0.005)\n";
    std::cout << "  --opacity-boost FLOAT   Opacity boost factor (default: 1.0)\n";
    std::cout << "  --scale-boost FLOAT     Scale boost factor (default: 1.1)\n";
    std::cout << "  --no-coverage           Disable coverage-aware scaling\n";
    std::cout << "  -h, --help              Show this help\n";
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }
    
    std::string input_path = argv[1];
    std::string output_path = argv[2];
    
    // Defaults
    std::vector<float> reduction_values = {50.0f};
    std::vector<size_t> target_counts;
    autolod::ReductionParams params;
    
    // Parse arguments
    for (int i = 3; i < argc; ++i) {
        std::string arg = argv[i];
        
        if (arg == "-h" || arg == "--help") {
            print_usage(argv[0]);
            return 0;
        } else if ((arg == "-r" || arg == "--reduction") && i + 1 < argc) {
            reduction_values.clear();
            std::string vals = argv[++i];
            size_t pos = 0;
            while ((pos = vals.find(',')) != std::string::npos) {
                reduction_values.push_back(std::stof(vals.substr(0, pos)));
                vals = vals.substr(pos + 1);
            }
            reduction_values.push_back(std::stof(vals));
        } else if ((arg == "-n" || arg == "--target-count") && i + 1 < argc) {
            std::string vals = argv[++i];
            size_t pos = 0;
            while ((pos = vals.find(',')) != std::string::npos) {
                target_counts.push_back(std::stoul(vals.substr(0, pos)));
                vals = vals.substr(pos + 1);
            }
            target_counts.push_back(std::stoul(vals));
        } else if (arg == "--fast") {
            params.use_bhattacharyya = false;
        } else if (arg == "--min-opacity" && i + 1 < argc) {
            params.min_opacity = std::stof(argv[++i]);
        } else if (arg == "--opacity-boost" && i + 1 < argc) {
            params.opacity_boost = std::stof(argv[++i]);
        } else if (arg == "--scale-boost" && i + 1 < argc) {
            params.scale_boost = std::stof(argv[++i]);
        } else if (arg == "--no-coverage") {
            params.coverage_aware = false;
        }
    }
    
    // Load input
    std::cout << "Loading " << input_path << "...\n";
    GaussianCloud cloud = ply::load(input_path);
    
    size_t original_count = cloud.size();
    
    // Calculate targets
    std::vector<size_t> targets;
    if (!target_counts.empty()) {
        targets = target_counts;
        std::sort(targets.begin(), targets.end(), std::greater<>());
    } else {
        for (float r : reduction_values) {
            targets.push_back(std::max<size_t>(1, static_cast<size_t>(original_count * r / 100.0f)));
        }
        std::sort(targets.begin(), targets.end(), std::greater<>());
    }
    
    // Cull low opacity
    if (params.min_opacity > 0) {
        std::cout <<"\n============================================================\n";
        std::cout << "Culling low-opacity Gaussians under " << params.min_opacity << " opacity...\n";
        std::vector<size_t> keep_indices;
        for (size_t i = 0; i < cloud.size(); ++i) {
            if (cloud.opacities(i) >= params.min_opacity) {
                keep_indices.push_back(i);
            }
        }
        
        size_t n_culled = cloud.size() - keep_indices.size();
        if (n_culled > 0) {
            cloud = cloud.subset(keep_indices);
        }
        std::cout << "Culled " << n_culled << " Gaussians\n";
        std::cout << "============================================================\n\n";
    }
    
    // Filter impossible targets
    targets.erase(std::remove_if(targets.begin(), targets.end(),
                  [&](size_t t) { return t >= cloud.size(); }), targets.end());
    
    if (targets.empty()) {
        std::cerr << "No valid targets after culling.\n";
        return 1;
    }
    
    // Setup checkpoints
    size_t lowest_target = targets.back();
    std::vector<size_t> intermediate_targets(targets.begin(), targets.end() - 1);
    
    autolod::CheckpointConfig checkpoint;
    checkpoint.output_path = output_path;
    checkpoint.targets = intermediate_targets;
    
    std::cout << "\n============================================================\n";
    std::cout << "Reducing " << cloud.size() << " Gaussians\n";
    std::cout << "Targets:";
    for (size_t t : targets) {
        float pct = 100.0f * t / original_count;
        std::cout << " " << t << " (" << std::fixed << std::setprecision(1) << pct << "%)";
    }
    std::cout << "\n";
    
    std::cout << "Fast Approx.: " << (params.use_bhattacharyya ? 0 : 1)
              << ", SH resampling: " << params.use_resampling
              << ", Scale boost: " << params.scale_boost
              << ", Opacity boost: " << params.opacity_boost
              << ", Coverage Aware: " << params.coverage_aware << std::endl;
    
    std::cout << "============================================================\n\n";

    // Reduce
    std::cout << "Starting reduction..." << std::endl;
    GaussianCloud reduced = autolod::reduce_cloud(
        std::move(cloud),
        lowest_target,
        params,
        &checkpoint,
        [](const GaussianCloud& c, const std::string& path) {
            ply::save(c, path);
        }
    );
    
    // Save final result
    std::string base = output_path;
    size_t dot = base.rfind('.');
    if (dot != std::string::npos) base = base.substr(0, dot);
    
    std::string final_path = base + "_lod" + std::to_string(checkpoint.lod_counter) 
                           + "_" + std::to_string(reduced.size()) + ".ply";
    
    std::cout << "Saving final (" << reduced.size() << ") to " << final_path << "...\n";
    ply::save(reduced, final_path);
    
    // Copy to requested output
    if (final_path != output_path) {
        ply::save(reduced, output_path);
        std::cout << "Copied to " << output_path << "\n";
    }
    
    std::cout << "\nDone!\n";
    return 0;
}
