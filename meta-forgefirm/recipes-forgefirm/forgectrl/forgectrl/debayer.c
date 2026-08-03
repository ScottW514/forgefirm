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

void debayer_bggr_half_yuv420_scalar(const uint8_t *raw, int w, int h,
                                     int hflip, uint8_t *yp, int y_stride,
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

#ifdef __ARM_NEON
#include <arm_neon.h>

/* Store 16 luma bytes at column x, mirrored when hflip (the vector is
 * byte-reversed and lands at the mirrored block position). */
static inline void store16_flip(uint8_t *row, int x, int ow, int hflip,
                                uint8x16_t v)
{
    if (!hflip) {
        vst1q_u8(row + x, v);
    } else {
        uint8x16_t r = vrev64q_u8(v);
        r = vextq_u8(r, r, 8);          /* swap halves: full 16-byte reverse */
        vst1q_u8(row + (ow - 16 - x), r);
    }
}

static inline void store8_flip(uint8_t *row, int x, int n, int hflip,
                               uint8x8_t v)
{
    if (!hflip)
        vst1_u8(row + x, v);
    else
        vst1_u8(row + (n - 8 - x), vrev64_u8(v));
}

/* Y = (77R + 150G + 29B + 128) >> 8 for 16 pixels. */
static inline uint8x16_t luma16(uint8x16_t R, uint8x16_t G, uint8x16_t B)
{
    const uint8x8_t cR = vdup_n_u8(77), cG = vdup_n_u8(150),
                    cB = vdup_n_u8(29);
    uint16x8_t lo = vmull_u8(vget_low_u8(R), cR);
    lo = vmlal_u8(lo, vget_low_u8(G), cG);
    lo = vmlal_u8(lo, vget_low_u8(B), cB);
    uint16x8_t hi = vmull_u8(vget_high_u8(R), cR);
    hi = vmlal_u8(hi, vget_high_u8(G), cG);
    hi = vmlal_u8(hi, vget_high_u8(B), cB);
    return vcombine_u8(vrshrn_n_u16(lo, 8), vrshrn_n_u16(hi, 8));
}

/* 4-superpixel block sums (vertical add then horizontal pair-add) for one
 * 16-column pair of rows -> 8 lanes of u32 split across two quads. */
static inline void block_sums(uint8x16_t a, uint8x16_t b,
                              int32x4_t *q0, int32x4_t *q1)
{
    uint16x8_t lo = vaddl_u8(vget_low_u8(a), vget_low_u8(b));
    uint16x8_t hi = vaddl_u8(vget_high_u8(a), vget_high_u8(b));
    *q0 = vreinterpretq_s32_u32(vpaddlq_u16(lo));
    *q1 = vreinterpretq_s32_u32(vpaddlq_u16(hi));
}

/* ((cr*rs + cg*gs + cb*bs + 512) >> 10) + 128, clamped to 0..255. */
static inline uint16x4_t chroma4(int32x4_t rs, int32x4_t gs, int32x4_t bs,
                                 int cr, int cg, int cb)
{
    int32x4_t acc = vmulq_n_s32(rs, cr);
    acc = vmlaq_n_s32(acc, gs, cg);
    acc = vmlaq_n_s32(acc, bs, cb);
    acc = vaddq_s32(acc, vdupq_n_s32(512));
    acc = vshrq_n_s32(acc, 10);
    acc = vaddq_s32(acc, vdupq_n_s32(128));
    return vqmovun_s32(acc);            /* clamps < 0 */
}

static void debayer_bggr_half_yuv420_neon(const uint8_t *raw, int w, int h,
                                          int hflip,
                                          uint8_t *yp, int y_stride,
                                          uint8_t *up, uint8_t *vp,
                                          int uv_stride)
{
    const int ow = w / 2;
    const int oh = h / 2;
    const int uvw = ow / 2;

    for (int y2 = 0; y2 < oh / 2; y2++) {
        const uint8_t *r0 = raw + (size_t)(4 * y2) * w;     /* B G ... */
        const uint8_t *r1 = r0 + w;                         /* G R ... */
        const uint8_t *r2 = r1 + w;
        const uint8_t *r3 = r2 + w;
        uint8_t *ya = yp + (size_t)(2 * y2) * y_stride;
        uint8_t *yb = ya + y_stride;
        uint8_t *ur = up + (size_t)y2 * uv_stride;
        uint8_t *vr = vp + (size_t)y2 * uv_stride;

        for (int x = 0; x < ow; x += 16) {
            /* superpixel row A: raw rows r0/r1 */
            uint8x16x2_t ea = vld2q_u8(r0 + 2 * x);  /* [0]=B  [1]=G1 */
            uint8x16x2_t oa = vld2q_u8(r1 + 2 * x);  /* [0]=G2 [1]=R  */
            uint8x16_t Ba = ea.val[0];
            uint8x16_t Ga = vrhaddq_u8(ea.val[1], oa.val[0]);
            uint8x16_t Ra = oa.val[1];
            store16_flip(ya, x, ow, hflip, luma16(Ra, Ga, Ba));

            /* superpixel row B: raw rows r2/r3 */
            uint8x16x2_t eb = vld2q_u8(r2 + 2 * x);
            uint8x16x2_t ob = vld2q_u8(r3 + 2 * x);
            uint8x16_t Bb = eb.val[0];
            uint8x16_t Gb = vrhaddq_u8(eb.val[1], ob.val[0]);
            uint8x16_t Rb = ob.val[1];
            store16_flip(yb, x, ow, hflip, luma16(Rb, Gb, Bb));

            /* chroma from the 2x2 superpixel blocks of both rows */
            int32x4_t rs0, rs1, gs0, gs1, bs0, bs1;
            block_sums(Ra, Rb, &rs0, &rs1);
            block_sums(Ga, Gb, &gs0, &gs1);
            block_sums(Ba, Bb, &bs0, &bs1);

            uint16x8_t cb = vcombine_u16(chroma4(rs0, gs0, bs0, -43, -85, 128),
                                         chroma4(rs1, gs1, bs1, -43, -85, 128));
            uint16x8_t cr = vcombine_u16(chroma4(rs0, gs0, bs0, 128, -107, -21),
                                         chroma4(rs1, gs1, bs1, 128, -107, -21));
            store8_flip(ur, x / 2, uvw, hflip, vqmovn_u16(cb));
            store8_flip(vr, x / 2, uvw, hflip, vqmovn_u16(cr));
        }
    }
}
#endif /* __ARM_NEON */

void debayer_bggr_half_yuv420(const uint8_t *raw, int w, int h, int hflip,
                              uint8_t *yp, int y_stride,
                              uint8_t *up, uint8_t *vp, int uv_stride)
{
#ifdef __ARM_NEON
    static int no_neon = -1;
    if (no_neon < 0)
        no_neon = getenv("FORGECTRL_NO_NEON") != NULL;
    if (!no_neon && w % 32 == 0 && h % 4 == 0) {
        debayer_bggr_half_yuv420_neon(raw, w, h, hflip, yp, y_stride,
                                      up, vp, uv_stride);
        return;
    }
#endif
    debayer_bggr_half_yuv420_scalar(raw, w, h, hflip, yp, y_stride,
                                    up, vp, uv_stride);
}
