#!/bin/bash
set -e
TC=/home/builder/dev/openglow-forgefirm/forgefirm/build/tmp/work/cortexa9t2hf-neon-fslc-linux-gnueabi/ulfius/2.7.15
SP="$(cd "$(dirname "$0")" && pwd)"
"$TC/recipe-sysroot-native/usr/bin/arm-fslc-linux-gnueabi/arm-fslc-linux-gnueabi-gcc" \
  --sysroot="$TC/recipe-sysroot" \
  -mthumb -mfpu=neon -mfloat-abi=hard -mcpu=cortex-a9 \
  -O2 -Wall -Wextra -o "$SP/feeder" "$SP/feeder.c"
echo FEEDER-OK
