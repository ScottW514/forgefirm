/*
 * debayer.h - BGGR raw-Bayer to RGB conversion for the Glowforge cameras
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 */
#ifndef FORGECTRL_DEBAYER_H
#define FORGECTRL_DEBAYER_H

#include <stdint.h>

/* Full-resolution bilinear demosaic of a BGGR frame. rgb must hold w*h*3
 * bytes. hflip mirrors the output horizontally (the factory image
 * orientation: the sensor HFLIP register breaks imx-media CSI capture, so
 * the mirror is applied in software). */
void debayer_bggr_bilinear(const uint8_t *raw, uint8_t *rgb,
                           int w, int h, int hflip);

/* Half-resolution demosaic: each 2x2 BGGR quad becomes one RGB pixel
 * (greens averaged) - no interpolation. Output is (w/2)x(h/2); rgb must
 * hold (w/2)*(h/2)*3 bytes. */
void debayer_bggr_half(const uint8_t *raw, uint8_t *rgb,
                       int w, int h, int hflip);

/* Half-resolution demosaic straight to planar YUV420 (JFIF full-range,
 * ITU-R 601) for the VPU JPEG encoder: luma per 2x2 BGGR quad at
 * (w/2)x(h/2), chroma averaged per 2x2 luma block at (w/4)x(h/4).
 * w/2 and h/2 must be even. Strides are in bytes. */
void debayer_bggr_half_yuv420(const uint8_t *raw, int w, int h, int hflip,
                              uint8_t *yp, int y_stride,
                              uint8_t *up, uint8_t *vp, int uv_stride);

#endif
