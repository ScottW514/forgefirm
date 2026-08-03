/*
 * debayer.c - BGGR raw-Bayer to RGB conversion for the Glowforge cameras
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 *
 * BGGR tile layout (row 0 topmost):
 *   even rows:  B G B G ...
 *   odd  rows:  G R G R ...
 */
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
