#!/bin/bash
# Build script for AutoLOD WASM (both 32-bit and 64-bit versions)
# Run from: vid2scene_core/autolod_cpp/

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_DIR="$SCRIPT_DIR/../../vid2scene_server/video_processor/static"
SIMPLEOMP_DIR="$SCRIPT_DIR/../simpleomp"

echo "========================================"
echo "AutoLOD WASM Build Script"
echo "========================================"
echo ""

# Check for Emscripten
if ! command -v emcmake &> /dev/null; then
    echo "ERROR: Emscripten not found. Please run 'source /path/to/emsdk/emsdk_env.sh' first."
    exit 1
fi

# =============================================
# Build SimpleOMP libraries
# =============================================
echo ""
echo "========================================"
echo "Building SimpleOMP libraries"
echo "========================================"

cd "$SIMPLEOMP_DIR"

# Build 64-bit version (MEMORY64)
echo "Building SimpleOMP (64-bit/MEMORY64)..."
make clean || true
make all

# Build compat version (no MEMORY64, Safari compatible)
echo "Building SimpleOMP (32-bit/compat)..."
make compat

# Copy to autolod lib directory
echo "Copying SimpleOMP libraries to autolod_cpp/lib/"
mkdir -p "$SCRIPT_DIR/lib"
cp "$SIMPLEOMP_DIR/dist/libsimpleomp.a" "$SCRIPT_DIR/lib/"
cp "$SIMPLEOMP_DIR/dist/libsimpleomp_compat.a" "$SCRIPT_DIR/lib/"

# =============================================
# Build 32-bit WASM (Safari compatible)
# =============================================
echo ""
echo "========================================"
echo "Building 32-bit WASM (Safari compatible)"
echo "========================================"

mkdir -p "$SCRIPT_DIR/build-wasm32"
cd "$SCRIPT_DIR/build-wasm32"

emcmake cmake .. -DWASM_MEMORY64=OFF
emmake make -j$(nproc)

# Copy to static directory
echo "Copying 32-bit build to $STATIC_DIR/autolod/"
mkdir -p "$STATIC_DIR/autolod"
cp 3dgs_autolod.js "$STATIC_DIR/autolod/"
cp 3dgs_autolod.wasm "$STATIC_DIR/autolod/"

# =============================================
# Build 64-bit WASM (large file support)
# =============================================
echo ""
echo "========================================"
echo "Building 64-bit WASM (MEMORY64 - large files)"
echo "========================================"

mkdir -p "$SCRIPT_DIR/build-wasm64"
cd "$SCRIPT_DIR/build-wasm64"

emcmake cmake .. -DWASM_MEMORY64=ON
emmake make -j$(nproc)

# Copy to static directory
echo "Copying 64-bit build to $STATIC_DIR/autolod64/"
mkdir -p "$STATIC_DIR/autolod64"
cp 3dgs_autolod.js "$STATIC_DIR/autolod64/"
cp 3dgs_autolod.wasm "$STATIC_DIR/autolod64/"

# Ensure worker.js exists in both directories
if [ ! -f "$STATIC_DIR/autolod/autolod_worker.js" ]; then
    echo "WARNING: autolod_worker.js not found in autolod/"
fi
if [ ! -f "$STATIC_DIR/autolod64/autolod_worker.js" ]; then
    echo "Copying autolod_worker.js to autolod64/"
    cp "$STATIC_DIR/autolod/autolod_worker.js" "$STATIC_DIR/autolod64/"
fi

echo ""
echo "========================================"
echo "Build complete!"
echo "========================================"
echo ""
echo "32-bit build: $STATIC_DIR/autolod/"
echo "64-bit build: $STATIC_DIR/autolod64/"
echo ""
echo "Test at:"
echo "  /autolod/   - Standard (faster, Safari compatible)"
echo "  /autolod64/ - 64-bit (supports files >1GB, Chrome/Firefox only)"
