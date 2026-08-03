/*
 * vpu_jpeg.c - hardware JPEG encoding on the i.MX6 CODA960 VPU
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 *
 * V4L2 mem2mem, single-planar API against the mainline coda driver: one
 * MMAP buffer on each queue, synchronous QBUF/DQBUF per frame. The node
 * is found by personality (driver "coda", JPEG on the capture side,
 * YUV420 accepted on the output side), never by number - coda registers
 * four nodes and the numbering depends on probe order.
 */
#include "vpu_jpeg.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define ENCODE_TIMEOUT_MS 1000

struct vpu_jpeg {
    int      fd;
    int      w, h;
    int      bpl;           /* OUTPUT luma stride from S_FMT */
    uint8_t *out;           /* mapped OUTPUT (YUV420) buffer */
    size_t   out_size;
    uint8_t *cap;           /* mapped CAPTURE (JPEG) buffer */
    size_t   cap_size;
};

static int xioctl(int fd, unsigned long req, void *arg)
{
    int r;
    do {
        r = ioctl(fd, req, arg);
    } while (r == -1 && errno == EINTR);
    return r;
}

/* Is this node the coda JPEG encoder? (JPEG capture, YUV420 output) */
static int is_jpeg_encoder(int fd)
{
    struct v4l2_capability cap = {0};
    if (xioctl(fd, VIDIOC_QUERYCAP, &cap) < 0 ||
        strcmp((const char *)cap.driver, "coda") != 0 ||
        !(cap.device_caps & V4L2_CAP_VIDEO_M2M))
        return 0;

    struct v4l2_fmtdesc fd0 = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE };
    if (xioctl(fd, VIDIOC_ENUM_FMT, &fd0) < 0 ||
        fd0.pixelformat != V4L2_PIX_FMT_JPEG)
        return 0;

    for (unsigned i = 0; ; i++) {
        struct v4l2_fmtdesc fo = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT,
                                   .index = i };
        if (xioctl(fd, VIDIOC_ENUM_FMT, &fo) < 0)
            return 0;
        if (fo.pixelformat == V4L2_PIX_FMT_YUV420)
            return 1;
    }
}

static int find_encoder(void)
{
    for (int i = 0; i < 32; i++) {
        char path[32];
        snprintf(path, sizeof(path), "/dev/video%d", i);
        int fd = open(path, O_RDWR | O_NONBLOCK, 0);
        if (fd < 0)
            continue;
        if (is_jpeg_encoder(fd))
            return fd;
        close(fd);
    }
    return -1;
}

static int map_one(int fd, enum v4l2_buf_type type, uint8_t **mem,
                   size_t *size)
{
    struct v4l2_requestbuffers req = { .count = 1, .type = type,
                                       .memory = V4L2_MEMORY_MMAP };
    if (xioctl(fd, VIDIOC_REQBUFS, &req) < 0 || req.count < 1)
        return -1;
    struct v4l2_buffer buf = { .type = type, .memory = V4L2_MEMORY_MMAP,
                               .index = 0 };
    if (xioctl(fd, VIDIOC_QUERYBUF, &buf) < 0)
        return -1;
    *mem = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED,
                fd, buf.m.offset);
    if (*mem == MAP_FAILED) {
        *mem = NULL;
        return -1;
    }
    *size = buf.length;
    return 0;
}

vpu_jpeg_t *vpu_jpeg_open(int w, int h, int quality)
{
    vpu_jpeg_t *v = calloc(1, sizeof(*v));
    if (!v)
        return NULL;
    v->fd = find_encoder();
    if (v->fd < 0)
        goto fail;

    struct v4l2_format fo = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT };
    fo.fmt.pix.width = (unsigned)w;
    fo.fmt.pix.height = (unsigned)h;
    fo.fmt.pix.pixelformat = V4L2_PIX_FMT_YUV420;
    fo.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(v->fd, VIDIOC_S_FMT, &fo) < 0 ||
        fo.fmt.pix.width != (unsigned)w ||
        fo.fmt.pix.height != (unsigned)h) {
        fprintf(stderr, "vpu: S_FMT output rejected %dx%d\n", w, h);
        goto fail;
    }
    v->w = w;
    v->h = h;
    v->bpl = (int)fo.fmt.pix.bytesperline;

    struct v4l2_format fc = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE };
    fc.fmt.pix.width = (unsigned)w;
    fc.fmt.pix.height = (unsigned)h;
    fc.fmt.pix.pixelformat = V4L2_PIX_FMT_JPEG;
    if (xioctl(v->fd, VIDIOC_S_FMT, &fc) < 0)
        goto fail;

    struct v4l2_control q = { .id = V4L2_CID_JPEG_COMPRESSION_QUALITY,
                              .value = quality };
    xioctl(v->fd, VIDIOC_S_CTRL, &q);    /* best effort */

    if (map_one(v->fd, V4L2_BUF_TYPE_VIDEO_OUTPUT, &v->out, &v->out_size) ||
        map_one(v->fd, V4L2_BUF_TYPE_VIDEO_CAPTURE, &v->cap, &v->cap_size))
        goto fail;

    enum v4l2_buf_type t = V4L2_BUF_TYPE_VIDEO_OUTPUT;
    if (xioctl(v->fd, VIDIOC_STREAMON, &t) < 0)
        goto fail;
    t = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(v->fd, VIDIOC_STREAMON, &t) < 0)
        goto fail;
    return v;

fail:
    vpu_jpeg_close(v);
    return NULL;
}

void vpu_jpeg_planes(vpu_jpeg_t *v, uint8_t **y, uint8_t **u, uint8_t **vv,
                     int *y_stride, int *uv_stride)
{
    *y = v->out;
    *u = v->out + (size_t)v->bpl * v->h;
    *vv = *u + (size_t)(v->bpl / 2) * (v->h / 2);
    *y_stride = v->bpl;
    *uv_stride = v->bpl / 2;
}

int vpu_jpeg_encode(vpu_jpeg_t *v, uint8_t **jpeg, size_t *len)
{
    struct v4l2_buffer cb = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
                              .memory = V4L2_MEMORY_MMAP, .index = 0 };
    struct v4l2_buffer ob = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT,
                              .memory = V4L2_MEMORY_MMAP, .index = 0 };
    ob.bytesused = (unsigned)v->out_size;

    if (xioctl(v->fd, VIDIOC_QBUF, &cb) < 0 ||
        xioctl(v->fd, VIDIOC_QBUF, &ob) < 0)
        return -1;

    struct pollfd pfd = { .fd = v->fd, .events = POLLIN };
    int pr;
    do {
        pr = poll(&pfd, 1, ENCODE_TIMEOUT_MS);
    } while (pr == -1 && errno == EINTR);
    if (pr <= 0)
        return -1;

    if (xioctl(v->fd, VIDIOC_DQBUF, &cb) < 0)
        return -1;
    xioctl(v->fd, VIDIOC_DQBUF, &ob);

    uint8_t *out = malloc(cb.bytesused);
    if (!out)
        return -1;
    memcpy(out, v->cap, cb.bytesused);
    *jpeg = out;
    *len = cb.bytesused;
    return 0;
}

void vpu_jpeg_close(vpu_jpeg_t *v)
{
    if (!v)
        return;
    if (v->fd >= 0) {
        enum v4l2_buf_type t = V4L2_BUF_TYPE_VIDEO_OUTPUT;
        xioctl(v->fd, VIDIOC_STREAMOFF, &t);
        t = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        xioctl(v->fd, VIDIOC_STREAMOFF, &t);
    }
    if (v->out)
        munmap(v->out, v->out_size);
    if (v->cap)
        munmap(v->cap, v->cap_size);
    if (v->fd >= 0)
        close(v->fd);
    free(v);
}
