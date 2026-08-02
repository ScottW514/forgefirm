#!/bin/bash
# Cross-compiles grblHAL-glowforge (the canonical driver repo) for the
# factory board, borrowing the Yocto cross toolchain from the ulfius work
# directory. Run from PowerShell: wsl -d forge-yocto -- bash <path>.
set -e
TC=/home/builder/dev/openglow-forgefirm/forgefirm/build/tmp/work/cortexa9t2hf-neon-fslc-linux-gnueabi/ulfius/2.7.15
export PATH="$TC/recipe-sysroot-native/usr/bin:$TC/recipe-sysroot-native/usr/bin/arm-fslc-linux-gnueabi:$PATH"
cd /home/builder/dev/openglow-forgefirm/grblHAL-glowforge
rm -rf build-arm
cmake -B build-arm \
  -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=arm \
  -DCMAKE_C_COMPILER=arm-fslc-linux-gnueabi-gcc \
  -DCMAKE_BUILD_TYPE=None \
  "-DCMAKE_C_FLAGS=--sysroot=$TC/recipe-sysroot -mthumb -mfpu=neon -mfloat-abi=hard -mcpu=cortex-a9 -O1 -g" \
  "-DCMAKE_EXE_LINKER_FLAGS=--sysroot=$TC/recipe-sysroot" \
  > /tmp/cmake-gf.log 2>&1
cmake --build build-arm -j8 > /tmp/gfbuild.log 2>&1 || { tail -30 /tmp/gfbuild.log; exit 1; }
echo BUILD-OK
file build-arm/grblHAL_glowforge 2>/dev/null || ls build-arm/
