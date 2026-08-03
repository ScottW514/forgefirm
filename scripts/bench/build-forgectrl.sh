#!/bin/bash
# Cross-compiles forgectrl (the canonical repo, ../../../forgectrl -> synced
# to ~/dev/openglow-forgefirm/forgectrl) for the factory board, borrowing the
# Yocto cross toolchain + sysroot from the forgectrl recipe work directory
# (which carries ulfius and libjpeg). If that path ages out after a clean,
# regenerate it with: bitbake forgectrl. Run from PowerShell:
#   wsl -d forge-yocto -- bash <path>/build-forgectrl.sh
set -e
TC=/home/builder/dev/openglow-forgefirm/forgefirm/build/tmp/work/cortexa9t2hf-neon-fslc-linux-gnueabi/forgectrl/0.1.0
export PATH="$TC/recipe-sysroot-native/usr/bin:$TC/recipe-sysroot-native/usr/bin/arm-fslc-linux-gnueabi:$PATH"
cd /home/builder/dev/openglow-forgefirm/forgectrl
rm -rf build-arm
cmake -B build-arm \
  -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=arm \
  -DCMAKE_C_COMPILER=arm-fslc-linux-gnueabi-gcc \
  -DCMAKE_BUILD_TYPE=None \
  "-DCMAKE_C_FLAGS=--sysroot=$TC/recipe-sysroot -mthumb -mfpu=neon -mfloat-abi=hard -mcpu=cortex-a9 -O2 -g" \
  "-DCMAKE_EXE_LINKER_FLAGS=--sysroot=$TC/recipe-sysroot" \
  > /tmp/cmake-fc.log 2>&1
cmake --build build-arm -j8 > /tmp/fcbuild.log 2>&1 || { tail -30 /tmp/fcbuild.log; exit 1; }
echo BUILD-OK
file build-arm/forgectrl 2>/dev/null || ls build-arm/
