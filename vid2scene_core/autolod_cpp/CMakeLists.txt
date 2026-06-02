cmake_minimum_required(VERSION 3.14)
project(3dgs_autolod VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Eigen (header-only)
include_directories(${CMAKE_SOURCE_DIR}/include)

# Source files - use main.cpp for all builds
add_executable(3dgs_autolod
    src/main.cpp
    src/autolod.cpp
)

# Platform-specific configuration
if(EMSCRIPTEN)
    # ==================== WASM BUILD (Emscripten) ====================
    message(STATUS "Building for WebAssembly with Emscripten")
    
    # Option for large file support (MEMORY64 mode - Chrome/Firefox only)
    option(WASM_MEMORY64 "Enable MEMORY64 for large file support (Chrome/Firefox only)" OFF)
    
    if(WASM_MEMORY64)
        message(STATUS "MEMORY64 mode enabled - will support files up to 16GB")
        message(STATUS "NOTE: This build will NOT work in Safari!")
        
        # Compiler flags with MEMORY64
        target_compile_options(3dgs_autolod PRIVATE
            -O3
            -ffast-math
            -fopenmp
            -pthread
            -sMEMORY64=1
        )
        
        # Link SimpleOMP library (MEMORY64 version)
        target_link_libraries(3dgs_autolod PRIVATE
            ${CMAKE_SOURCE_DIR}/lib/libsimpleomp.a
        )
        
        # Emscripten link flags for MEMORY64
        target_link_options(3dgs_autolod PRIVATE
            -fopenmp
            -pthread
            -sPROXY_TO_PTHREAD
            -sPTHREAD_POOL_SIZE=navigator.hardwareConcurrency
            -sWASM=1
            -sALLOW_MEMORY_GROWTH=1
            -sINITIAL_MEMORY=1GB
            -sMAXIMUM_MEMORY=16GB
            -sMEMORY64=1
            -sEXPORTED_RUNTIME_METHODS=['FS','callMain','WORKERFS']
            -sMODULARIZE=1
            -sEXPORT_NAME='AutoLOD'
            -sINVOKE_RUN=0
            -sFORCE_FILESYSTEM=1
            -sNO_DISABLE_EXCEPTION_CATCHING
            -lworkerfs.js
        )
    else()
        message(STATUS "WASM32 mode (Safari compatible) - max 2GB memory")
        
        # Compiler flags without MEMORY64
        target_compile_options(3dgs_autolod PRIVATE
            -O3
            -ffast-math
            -fopenmp
            -pthread
        )
        
        # Link SimpleOMP library (WASM32 version needed!)
        # Note: rebuild simpleomp without -sMEMORY64=1 for this build
        target_link_libraries(3dgs_autolod PRIVATE
            ${CMAKE_SOURCE_DIR}/lib/libsimpleomp_compat.a
        )
        
        # Emscripten link flags for WASM32 (Safari compatible)
        target_link_options(3dgs_autolod PRIVATE
            -fopenmp
            -pthread
            -sPROXY_TO_PTHREAD
            -sPTHREAD_POOL_SIZE=navigator.hardwareConcurrency
            -sWASM=1
            -sALLOW_MEMORY_GROWTH=1
            -sINITIAL_MEMORY=256MB
            -sMAXIMUM_MEMORY=2GB
            -sEXPORTED_RUNTIME_METHODS=['FS','callMain','WORKERFS']
            -sMODULARIZE=1
            -sEXPORT_NAME='AutoLOD'
            -sINVOKE_RUN=0
            -sFORCE_FILESYSTEM=1
            -sNO_DISABLE_EXCEPTION_CATCHING
            -lworkerfs.js
        )
    endif()
    
    set(CMAKE_EXECUTABLE_SUFFIX ".js")


elseif(MSVC)
    # ==================== WINDOWS BUILD (MSVC) ====================
    find_package(OpenMP REQUIRED)
    
    target_compile_options(3dgs_autolod PRIVATE
        /O2           # Optimize for speed
        /fp:fast      # Fast floating point
        /W4           # Warning level 4
        /MT           # Static link MSVC runtime (no redistributable needed)
    )
    set(CMAKE_BUILD_TYPE Release)
    
    target_link_libraries(3dgs_autolod PRIVATE OpenMP::OpenMP_CXX)

else()
    # ==================== LINUX/MACOS BUILD (GCC/Clang) ====================
    find_package(OpenMP REQUIRED)
    
    target_compile_options(3dgs_autolod PRIVATE
        -O3
        -march=native
        -ffast-math
        -Wall
        -Wextra
    )
    set(CMAKE_BUILD_TYPE Release)
    
    # Static link only OpenMP runtime (libgomp) for portability
    # libgomp has GPL runtime exception, so no licensing concerns
    target_link_options(3dgs_autolod PRIVATE 
        "LINKER:-Bstatic,-lgomp,-Bdynamic"
    )
    
    target_link_libraries(3dgs_autolod PRIVATE OpenMP::OpenMP_CXX)
endif()

# Installation (native builds only)
if(NOT EMSCRIPTEN)
    install(TARGETS 3dgs_autolod DESTINATION bin)
endif()
