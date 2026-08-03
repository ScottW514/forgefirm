/*
 * vpu_jpeg.h - hardware JPEG encoding on the i.MX6 CODA960 VPU
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 *
 * Thin wrapper around the mainline coda V4L2 mem2mem JPEG encoder: the
 * caller writes planar YUV420 directly into the encoder's OUTPUT buffer
 * (vpu_jpeg_planes) and gets back a malloc'd JFIF JPEG.
 */
#ifndef FORGECTRL_VPU_JPEG_H
#define FORGECTRL_VPU_JPEG_H

#include <stddef.h>
#include <stdint.h>

typedef struct vpu_jpeg vpu_jpeg_t;

/* Locate the CODA JPEG encoder video node, configure it for w x h YUV420
 * -> JPEG at the given quality (5..100), and map one buffer per queue.
 * Returns NULL if no encoder exists or setup fails. */
vpu_jpeg_t *vpu_jpeg_open(int w, int h, int quality);

/* Planes of the mapped OUTPUT buffer for direct fill. */
void vpu_jpeg_planes(vpu_jpeg_t *v, uint8_t **y, uint8_t **u, uint8_t **vv,
                     int *y_stride, int *uv_stride);

/* Encode the currently-filled OUTPUT buffer. On success *jpeg is malloc'd
 * (caller frees) and 0 is returned. */
int vpu_jpeg_encode(vpu_jpeg_t *v, uint8_t **jpeg, size_t *len);

void vpu_jpeg_close(vpu_jpeg_t *v);

#endif
