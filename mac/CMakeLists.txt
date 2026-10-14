# Build with the Retro68 68k toolchain:
#   mkdir build && cd build
#   cmake .. -DCMAKE_TOOLCHAIN_FILE=<Retro68-build>/toolchain/m68k-apple-macos/cmake/retro68.toolchain.cmake
#   make
cmake_minimum_required(VERSION 3.9)
project(BrainSCSI C)

add_application(BrainSCSI
    src/main.c
    src/link.c
    TYPE "APPL"
    CREATOR "BrSC"
)

# Small and fast for an 8 MHz 68000.
set_target_properties(BrainSCSI PROPERTIES COMPILE_OPTIONS "-Os")
