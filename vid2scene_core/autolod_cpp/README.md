# 3DGS AutoLOD - C++ Version

High-performance Gaussian splatting LOD reducer compiled to native binary.

## Setup

### 1. Download Eigen (header-only)
```bash
cd include
curl -sL https://gitlab.com/libeigen/eigen/-/archive/5.0.0/eigen-5.0.0.tar.gz | tar xz
mv eigen-5.0.0/Eigen Eigen
rm -rf eigen-5.0.0
```

### 2. Build
```bash
mkdir build && cd build
cmake ..
make -j$(nproc)
```

### 3. Run
```bash
./autolod input.ply output.ply -r 50
./autolod input.ply output.ply -r 75,50,25  # Multiple LOD levels
./autolod input.ply output.ply -n 1000000   # Absolute count
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-r, --reduction` | Target percentage(s) | 50 |
| `-n, --target-count` | Absolute count(s) | - |
| `--fast` | Simple distance metric | off |
| `--min-opacity` | Cull threshold | 0.005 |
| `--opacity-boost` | Opacity factor | 1.0 |
| `--scale-boost` | Scale factor | 1.1 |
| `--no-coverage` | Disable coverage scaling | off |

## Distribution

Ship only the compiled binary:
```
autolod           # Linux/macOS
autolod.exe       # Windows
```

No source code visible to customers.
