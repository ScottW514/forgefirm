/*
 * debayer.c - BGGR raw-Bayer to RGB conversion for the Glowforge cameras
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 *
 * BGGR tile layout (row 0 topmost):
 *   even rows:  B G B G ...
 *   odd  rows:  G R G R ...
 */
#include <stddef.h>

#include "debayer.h"

static inline int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

void debayer_bggr_bilinear(const uint8_t *raw, uint8_t *rgb,
                           int w, int h, int hflip)
{
    /* Border pixels use clamped neighbor coordinates; the interior uses the
     * same expressions with the clamps folding to identity. Per-pixel clamp
     * cost is acceptable: full resolution is only used for snapshots. */
    for (int y = 0; y < h; y++) {
        const int yn = clampi(y - 1, 0, h - 1) * w;
        const int yc = y * w;
        const int ys = clampi(y + 1, 0, h - 1) * w;
        uint8_t *out_row = rgb + (long)y * w * 3;
        for (int x = 0; x < w; x++) {
            const int xw = clampi(x - 1, 0, w - 1);
            const int xe = clampi(x + 1, 0, w - 1);
            unsigned r, g, b;
            if ((y & 1) == 0) {
                if ((x & 1) == 0) {         /* B site */
                    b = raw[yc + x];
                    g = (raw[yc + xw] + raw[yc + xe] +
                         raw[yn + x] + raw[ys + x] + 2) >> 2;
                    r = (raw[yn + xw] + raw[yn + xe] +
                         raw[ys + xw] + raw[ys + xe] + 2) >> 2;
                } else {                    /* G site on a B row */
                    g = raw[yc + x];
                    b = (raw[yc + xw] + raw[yc + xe] + 1) >> 1;
                    r = (raw[yn + x] + raw[ys + x] + 1) >> 1;
                }
            } else {
                if ((x & 1) == 0) {         /* G site on an R row */
                    g = raw[yc + x];
                    r = (raw[yc + xw] + raw[yc + xe] + 1) >> 1;
                    b = (raw[yn + x] + raw[ys + x] + 1) >> 1;
                } else {                    /* R site */
                    r = raw[yc + x];
                    g = (raw[yc + xw] + raw[yc + xe] +
                         raw[yn + x] + raw[ys + x] + 2) >> 2;
                    b = (raw[yn + xw] + raw[yn + xe] +
                         raw[ys + xw] + raw[ys + xe] + 2) >> 2;
                }
            }
            uint8_t *px = out_row + (long)(hflip ? w - 1 - x : x) * 3;
            px[0] = (uint8_t)r;
            px[1] = (uint8_t)g;
            px[2] = (uint8_t)b;
        }
    }
}

void debayer_bggr_half_yuv420(const uint8_t *raw, int w, int h, int hflip,
                              uint8_t *yp, int y_stride,
                              uint8_t *up, uint8_t *vp, int uv_stride)
{
    const int ow = w / 2;       /* luma dimensions */
    const int oh = h / 2;
    const int uvw = ow / 2;

    /* JFIF full-range ITU-R 601, x256 fixed point:
     *   Y  =  0.299 R + 0.587 G + 0.114 B          ->  77 150  29
     *   Cb = -0.169 R - 0.331 G + 0.500 B + 128    -> -43 -85 128
     *   Cr =  0.500 R - 0.419 G - 0.081 B + 128    -> 128 -107 -21 */
    for (int y2 = 0; y2 < oh / 2; y2++) {
        uint8_t *yrow0 = yp + (size_t)(2 * y2) * y_stride;
        uint8_t *yrow1 = yrow0 + y_stride;
        uint8_t *urow = up + (size_t)y2 * uv_stride;
        uint8_t *vrow = vp + (size_t)y2 * uv_stride;
        for (int x2 = 0; x2 < uvw; x2++) {
            int rs = 0, gs = 0, bs = 0;
            for (int sy = 0; sy < 2; sy++) {
                const int row = 2 * y2 + sy;
                const uint8_t *quad_row = raw + (size_t)(2 * row) * w;
                uint8_t *yrow = sy ? yrow1 : yrow0;
                for (int sx = 0; sx < 2; sx++) {
                    const int col = 2 * x2 + sx;
                    const uint8_t *q = quad_row + 2 * col;
                    const int b = q[0];
                    const int g = (q[1] + q[w] + 1) >> 1;
                    const int r = q[w + 1];
                    rs += r;
                    gs += g;
                    bs += b;
                    yrow[hflip ? ow - 1 - col : col] =
                        (uint8_t)((77 * r + 150 * g + 29 * b + 128) >> 8);
                }
            }
            const int cx = hflip ? uvw - 1 - x2 : x2;
            int cb = ((-43 * rs - 85 * gs + 128 * bs + 512) >> 10) + 128;
            int cr = ((128 * rs - 107 * gs - 21 * bs + 512) >> 10) + 128;
            urow[cx] = (uint8_t)(cb < 0 ? 0 : (cb > 255 ? 255 : cb));
            vrow[cx] = (uint8_t)(cr < 0 ? 0 : (cr > 255 ? 255 : cr));
        }
    }
}

void debayer_bggr_half(const uint8_t *raw, uint8_t *rgb,
                       int w, int h, int hflip)
{
    const int ow = w / 2;
    const int oh = h / 2;
    for (int y = 0; y < oh; y++) {
        const uint8_t *row_b = raw + (long)(2 * y) * w;     /* B G ... */
        const uint8_t *row_r = row_b + w;                   /* G R ... */
        uint8_t *out_row = rgb + (long)y * ow * 3;
        for (int x = 0; x < ow; x++) {
            const int xi = 2 * x;
            uint8_t *px = out_row + (long)(hflip ? ow - 1 - x : x) * 3;
            px[0] = row_r[xi + 1];                              /* R */
            px[1] = (uint8_t)((row_b[xi + 1] + row_r[xi] + 1) >> 1); /* G */
            px[2] = row_b[xi];                                  /* B */
        }
    }
}
