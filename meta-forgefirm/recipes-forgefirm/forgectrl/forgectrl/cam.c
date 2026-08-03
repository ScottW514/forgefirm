/*
 * cam.c - persistent Glowforge camera capture engine
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 *
 * Pipeline model (mainline imx-media): both OV5648 sensors feed one
 * video-mux -> MIPI CSI-2 -> IPU CSI path to the 'ipu1_csi0 capture' video
 * node. Camera selection is which mux sink link is enabled; sensor controls
 * live on the sensor subdev; illumination is the per-camera LED driven via
 * sysfs. Links and pad formats are configured with media-ctl / v4l2-ctl
 * (the same sequences python3-gfhardware uses for one-shot grabs), then the
 * capture node is held open and streamed continuously.
 *
 * Threading: a control mutex serializes engine start/stop/switch; the
 * engine lock covers frame data and counters. The worker thread only ever
 * takes the engine lock, so control paths may join it while holding the
 * control mutex.
 */
#define _GNU_SOURCE
#include "cam.h"
#include "debayer.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <jpeglib.h>    /* requires stdio.h first (FILE) */
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <unistd.h>

#define CAM_W  2592
#define CAM_H  1944
#define HALF_W (CAM_W / 2)
#define HALF_H (CAM_H / 2)
#define HFLIP  1          /* factory image orientation (see debayer.h) */

#define N_BUFS          4
#define DQ_TIMEOUT_S    2   /* select() timeout per frame; also the idle tick */
#define MAX_DQ_TIMEOUTS 3   /* consecutive timeouts -> engine gives up */
#define IDLE_STOP_S     10  /* no clients/snapshots for this long -> teardown */
#define SNAP_TIMEOUT_S  15
#define CLIENT_WAIT_S   5
#define SWITCH_GRACE_S  3   /* wait this long for clients to drain on switch */

#define CAPTURE_ENTITY "ipu1_csi0 capture"
#define MBUS_FMT       "SBGGR8_1X8/2592x1944 field:none"

struct camdef {
    const char *name;
    int         bus;       /* I2C bus: sensor entity resolved by <bus>-0036 */
    int         muxpad;    /* video-mux sink pad */
    const char *lamp;      /* sysfs illumination attribute */
    int         exposure;  /* 1/16-line units, frame-length ceiling ~31600 */
    int         gain;
};

static const struct camdef camdefs[2] = {
    [CAM_LID]  = { "lid",  0, 0, "/sys/glowforge/pic/lid_led",    24000,  50 },
    [CAM_HEAD] = { "head", 3, 1, "/sys/glowforge/head/white_led", 24000, 200 },
};

struct buffer {
    void  *start;
    size_t length;
};

static struct {
    /* control path (start/stop/switch) - taken before lock, never by the
     * worker thread */
    pthread_mutex_t ctl;

    /* engine state */
    pthread_mutex_t lock;
    pthread_cond_t  frame_cv;   /* new stream frame published */
    pthread_cond_t  snap_cv;    /* snapshot request completed */
    pthread_t       tid;
    int             tid_valid;
    int             running;    /* worker alive and capturing */
    int             stop_flag;
    cam_id_t        cam;        /* camera the pipeline is configured for
                                 * RIGHT NOW (a borrow flips it briefly) */
    cam_id_t        home_cam;   /* camera the engine serves for streaming -
                                 * what arbitration must compare against */
    int             clients;
    struct timespec last_activity;

    /* published stream frame (half-res JPEG) */
    uint8_t        *stream_jpg;
    size_t          stream_len;
    size_t          stream_cap;
    uint64_t        seq;
    double          fps;

    /* one pending snapshot request at a time (control mutex serializes).
     * snap_cam may differ from the streaming camera: the worker then
     * "borrows" the mux - pauses the stream, switches, grabs one frame,
     * switches back (stream clients see a few-second freeze). */
    int             snap_pending;   /* 1 = requested, 2 = done, 3 = failed */
    cam_id_t        snap_cam;
    int             snap_full;
    int             snap_quality;
    uint8_t        *snap_jpg;       /* malloc'd result, taken by requester */
    size_t          snap_len;

    /* capture resources (worker/start/teardown only) */
    int             fd;
    struct buffer   bufs[N_BUFS];
    int             n_bufs;
    int             streaming;
    int             lamp_prev;      /* -1 = unknown, restore to 0 */

    /* config */
    int             stream_quality;
    int             lamp_level;
} eng = {
    .ctl = PTHREAD_MUTEX_INITIALIZER,
    .lock = PTHREAD_MUTEX_INITIALIZER,
    .frame_cv = PTHREAD_COND_INITIALIZER,
    .snap_cv = PTHREAD_COND_INITIALIZER,
    .fd = -1,
    .lamp_prev = -1,
    .stream_quality = 75,
    .lamp_level = 132,
};

const char *cam_name(cam_id_t cam)
{
    return camdefs[cam].name;
}

/* ------------------------------------------------------------------ util */

static void now_ts(struct timespec *ts)
{
    clock_gettime(CLOCK_MONOTONIC, ts);
}

static double ts_diff(const struct timespec *a, const struct timespec *b)
{
    return (double)(a->tv_sec - b->tv_sec) +
           (double)(a->tv_nsec - b->tv_nsec) / 1e9;
}

static int xioctl(int fd, unsigned long req, void *arg)
{
    int r;
    do {
        r = ioctl(fd, req, arg);
    } while (r == -1 && errno == EINTR);
    return r;
}

/* Run a shell command, logging and returning nonzero on failure. */
static int run(const char *fmt, ...)
{
    char cmd[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(cmd, sizeof(cmd), fmt, ap);
    va_end(ap);
    int rc = system(cmd);
    if (rc == -1 || !WIFEXITED(rc) || WEXITSTATUS(rc) != 0) {
        fprintf(stderr, "cam: command failed (%d): %s\n", rc, cmd);
        return -1;
    }
    return 0;
}

/* Run a command and capture its first line of output. */
static int run_read(char *out, size_t outlen, const char *fmt, ...)
{
    char cmd[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(cmd, sizeof(cmd), fmt, ap);
    va_end(ap);
    FILE *p = popen(cmd, "r");
    if (!p)
        return -1;
    out[0] = '\0';
    if (!fgets(out, (int)outlen, p)) {
        pclose(p);
        return -1;
    }
    int rc = pclose(p);
    out[strcspn(out, "\r\n")] = '\0';
    if (rc == -1 || !WIFEXITED(rc) || WEXITSTATUS(rc) != 0 || !out[0]) {
        fprintf(stderr, "cam: command failed: %s\n", cmd);
        return -1;
    }
    return 0;
}

static int sysfs_read_int(const char *path, int *val)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    int ok = fscanf(f, "%d", val) == 1;
    fclose(f);
    return ok ? 0 : -1;
}

static int sysfs_write_int(const char *path, int val)
{
    FILE *f = fopen(path, "w");
    if (!f)
        return -1;
    int ok = fprintf(f, "%d", val) > 0;
    fclose(f);
    return ok ? 0 : -1;
}

/* --------------------------------------------------- pipeline configure */

/* Resolve the sensor media entity on an I2C bus (e.g. "ov5648 0-0036") by
 * its address suffix, so OV5648 and OV8856 (HD model) both match. */
static int sensor_entity(int bus, char *out, size_t outlen)
{
    char needle[16];
    snprintf(needle, sizeof(needle), " %d-0036", bus);

    FILE *p = popen("media-ctl -p", "r");
    if (!p)
        return -1;
    char line[512];
    int found = 0;
    while (fgets(line, sizeof(line), p)) {
        char *e = strstr(line, "entity ");
        if (!e)
            continue;
        char *colon = strchr(e, ':');
        char *hit = strstr(line, needle);
        if (!colon || !hit || hit < colon)
            continue;
        char *start = colon + 2;
        char *end = hit + strlen(needle);
        if (end <= start || (size_t)(end - start) >= outlen)
            continue;
        memcpy(out, start, (size_t)(end - start));
        out[end - start] = '\0';
        found = 1;
        break;
    }
    pclose(p);
    return found ? 0 : -1;
}

/* Route the selected sensor through the video-mux to the capture node and
 * set the raw-Bayer format on every pad of the active path. Exactly one
 * mux sink link may be enabled, so the other camera's link (if that sensor
 * exists) is disabled first. */
static int configure_pipeline(cam_id_t cam, const char *sensor,
                              const char *other_sensor)
{
    const struct camdef *c = &camdefs[cam];
    const struct camdef *o = &camdefs[cam == CAM_LID ? CAM_HEAD : CAM_LID];

    if (other_sensor[0] &&
        run("media-ctl -l '\"%s\":0 -> \"video-mux\":%d [0]'",
            other_sensor, o->muxpad))
        return -1;

    if (run("media-ctl -l '\"%s\":0 -> \"video-mux\":%d [1]'",
            sensor, c->muxpad) ||
        run("media-ctl -l '\"video-mux\":2 -> \"imx6-mipi-csi2\":0 [1]'") ||
        run("media-ctl -l '\"imx6-mipi-csi2\":1 -> \"ipu1_csi0_mux\":0 [1]'") ||
        run("media-ctl -l '\"ipu1_csi0_mux\":5 -> \"ipu1_csi0\":0 [1]'") ||
        run("media-ctl -l '\"ipu1_csi0\":2 -> \"" CAPTURE_ENTITY "\":0 [1]'"))
        return -1;

    if (run("media-ctl -V '\"%s\":0 [fmt:" MBUS_FMT "]'", sensor) ||
        run("media-ctl -V '\"video-mux\":%d [fmt:" MBUS_FMT "]'", c->muxpad) ||
        run("media-ctl -V '\"video-mux\":2 [fmt:" MBUS_FMT "]'") ||
        run("media-ctl -V '\"imx6-mipi-csi2\":0 [fmt:" MBUS_FMT "]'") ||
        run("media-ctl -V '\"imx6-mipi-csi2\":1 [fmt:" MBUS_FMT "]'") ||
        run("media-ctl -V '\"ipu1_csi0_mux\":0 [fmt:" MBUS_FMT "]'") ||
        run("media-ctl -V '\"ipu1_csi0_mux\":5 [fmt:" MBUS_FMT "]'") ||
        run("media-ctl -V '\"ipu1_csi0\":0 [fmt:" MBUS_FMT "]'") ||
        run("media-ctl -V '\"ipu1_csi0\":2 [fmt:" MBUS_FMT "]'"))
        return -1;
    return 0;
}

/* Manual exposure/gain/white-balance on the sensor subdev (factory values).
 * The auto-clusters must go manual before the manual values take effect.
 * The sensor flips stay off: HFLIP breaks imx-media CSI capture, so the
 * factory mirror is applied in software (debayer). */
static int configure_sensor(const char *sensor, const struct camdef *c)
{
    char subdev[64];
    if (run_read(subdev, sizeof(subdev), "media-ctl -e '%s'", sensor))
        return -1;
    if (run("v4l2-ctl -d %s -c auto_exposure=1 -c gain_automatic=0"
            " -c white_balance_automatic=0", subdev))
        return -1;
    if (run("v4l2-ctl -d %s -c exposure=%d -c gain=%d -c red_balance=1100"
            " -c blue_balance=1400 -c horizontal_flip=0 -c vertical_flip=0",
            subdev, c->exposure, c->gain))
        return -1;
    return 0;
}

/* ------------------------------------------------------- jpeg encoding */

static int jpeg_encode_rgb(const uint8_t *rgb, int w, int h, int quality,
                           int fast, uint8_t **out, size_t *outlen)
{
    struct jpeg_compress_struct ci;
    struct jpeg_error_mgr jerr;
    unsigned char *buf = NULL;
    unsigned long buflen = 0;

    ci.err = jpeg_std_error(&jerr);
    jpeg_create_compress(&ci);
    jpeg_mem_dest(&ci, &buf, &buflen);
    ci.image_width = (JDIMENSION)w;
    ci.image_height = (JDIMENSION)h;
    ci.input_components = 3;
    ci.in_color_space = JCS_RGB;
    jpeg_set_defaults(&ci);
    jpeg_set_quality(&ci, quality, TRUE);
    if (fast)
        ci.dct_method = JDCT_FASTEST;
    jpeg_start_compress(&ci, TRUE);
    while (ci.next_scanline < ci.image_height) {
        JSAMPROW row = (JSAMPROW)(rgb + (long)ci.next_scanline * w * 3);
        jpeg_write_scanlines(&ci, &row, 1);
    }
    jpeg_finish_compress(&ci);
    jpeg_destroy_compress(&ci);
    *out = buf;
    *outlen = (size_t)buflen;
    return 0;
}

/* --------------------------------------------------- capture start/stop */

/* Release every capture resource and restore the lamp. Safe to call from
 * any state; called by the worker on exit and by a failed start. */
static void release_capture(void)
{
    if (eng.streaming) {
        enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        xioctl(eng.fd, VIDIOC_STREAMOFF, &type);
        eng.streaming = 0;
    }
    for (int i = 0; i < eng.n_bufs; i++) {
        if (eng.bufs[i].start) {
            munmap(eng.bufs[i].start, eng.bufs[i].length);
            eng.bufs[i].start = NULL;
        }
    }
    eng.n_bufs = 0;
    if (eng.fd >= 0) {
        close(eng.fd);
        eng.fd = -1;
    }
    if (eng.lamp_prev >= 0) {
        sysfs_write_int(camdefs[eng.cam].lamp, eng.lamp_prev);
        eng.lamp_prev = -1;
    }
}

/* Configure the media graph and sensor, light the lamp, and bring up the
 * V4L2 capture node streaming. Called with ctl held, engine not running. */
static int start_capture(cam_id_t cam, char *err, size_t errlen)
{
    const struct camdef *c = &camdefs[cam];
    char sensor[64], other[64] = "";

    if (sensor_entity(c->bus, sensor, sizeof(sensor))) {
        snprintf(err, errlen, "no camera sensor on i2c-%d", c->bus);
        return -1;
    }
    (void)sensor_entity(camdefs[cam == CAM_LID ? CAM_HEAD : CAM_LID].bus,
                        other, sizeof(other));

    if (configure_pipeline(cam, sensor, other)) {
        snprintf(err, errlen, "media pipeline configuration failed");
        return -1;
    }
    if (configure_sensor(sensor, c)) {
        snprintf(err, errlen, "sensor configuration failed");
        return -1;
    }

    char dev[64];
    if (run_read(dev, sizeof(dev), "media-ctl -e '" CAPTURE_ENTITY "'")) {
        snprintf(err, errlen, "cannot resolve capture video node");
        return -1;
    }

    pthread_mutex_lock(&eng.lock);
    eng.cam = cam;
    pthread_mutex_unlock(&eng.lock);

    /* Scene lighting for the duration; the previous level is restored at
     * teardown (raw register write - instant, no fade). */
    if (sysfs_read_int(c->lamp, &eng.lamp_prev))
        eng.lamp_prev = 0;
    sysfs_write_int(c->lamp, eng.lamp_level);

    eng.fd = open(dev, O_RDWR | O_NONBLOCK, 0);
    if (eng.fd < 0) {
        snprintf(err, errlen, "open %s: %s", dev, strerror(errno));
        release_capture();
        return -1;
    }

    struct v4l2_format fmt = {0};
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = CAM_W;
    fmt.fmt.pix.height = CAM_H;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_SBGGR8;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(eng.fd, VIDIOC_S_FMT, &fmt) < 0) {
        snprintf(err, errlen, "S_FMT: %s", strerror(errno));
        release_capture();
        return -1;
    }

    struct v4l2_requestbuffers req = {0};
    req.count = N_BUFS;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    if (xioctl(eng.fd, VIDIOC_REQBUFS, &req) < 0 || req.count < 2) {
        snprintf(err, errlen, "REQBUFS: %s (device busy?)", strerror(errno));
        release_capture();
        return -1;
    }

    for (eng.n_bufs = 0; eng.n_bufs < (int)req.count; eng.n_bufs++) {
        struct v4l2_buffer buf = {0};
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = (unsigned)eng.n_bufs;
        if (xioctl(eng.fd, VIDIOC_QUERYBUF, &buf) < 0) {
            snprintf(err, errlen, "QUERYBUF: %s", strerror(errno));
            release_capture();
            return -1;
        }
        eng.bufs[eng.n_bufs].length = buf.length;
        eng.bufs[eng.n_bufs].start = mmap(NULL, buf.length,
                                          PROT_READ | PROT_WRITE, MAP_SHARED,
                                          eng.fd, buf.m.offset);
        if (eng.bufs[eng.n_bufs].start == MAP_FAILED) {
            eng.bufs[eng.n_bufs].start = NULL;
            snprintf(err, errlen, "mmap: %s", strerror(errno));
            release_capture();
            return -1;
        }
    }

    for (int i = 0; i < eng.n_bufs; i++) {
        struct v4l2_buffer buf = {0};
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = (unsigned)i;
        if (xioctl(eng.fd, VIDIOC_QBUF, &buf) < 0) {
            snprintf(err, errlen, "QBUF: %s", strerror(errno));
            release_capture();
            return -1;
        }
    }

    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(eng.fd, VIDIOC_STREAMON, &type) < 0) {
        snprintf(err, errlen, "STREAMON: %s", strerror(errno));
        release_capture();
        return -1;
    }
    eng.streaming = 1;
    return 0;
}

/* ---------------------------------------------------------- worker loop */

/* Encode the pending snapshot request from a raw frame and deliver the
 * result (success or failure) to the waiter. */
static void deliver_snap(const uint8_t *raw, uint8_t *rgb_half,
                         uint8_t **prgb_full)
{
    uint8_t *jpg = NULL;
    size_t len = 0;
    int ok;

    pthread_mutex_lock(&eng.lock);
    int full = eng.snap_full;
    int q = eng.snap_quality;
    pthread_mutex_unlock(&eng.lock);

    if (full) {
        if (!*prgb_full)
            *prgb_full = malloc((size_t)CAM_W * CAM_H * 3);
        ok = *prgb_full != NULL;
        if (ok) {
            debayer_bggr_bilinear(raw, *prgb_full, CAM_W, CAM_H, HFLIP);
            ok = jpeg_encode_rgb(*prgb_full, CAM_W, CAM_H, q, 0,
                                 &jpg, &len) == 0;
        }
    } else {
        debayer_bggr_half(raw, rgb_half, CAM_W, CAM_H, HFLIP);
        ok = jpeg_encode_rgb(rgb_half, HALF_W, HALF_H, q, 0,
                             &jpg, &len) == 0;
    }

    pthread_mutex_lock(&eng.lock);
    free(eng.snap_jpg);
    eng.snap_jpg = ok ? jpg : NULL;
    eng.snap_len = ok ? len : 0;
    eng.snap_pending = ok ? 2 : 3;
    now_ts(&eng.last_activity);
    pthread_cond_broadcast(&eng.snap_cv);
    pthread_mutex_unlock(&eng.lock);
}

/* Mark a pending snapshot failed (only if not already delivered). */
static void fail_snap(void)
{
    pthread_mutex_lock(&eng.lock);
    if (eng.snap_pending == 1) {
        eng.snap_pending = 3;
        pthread_cond_broadcast(&eng.snap_cv);
    }
    pthread_mutex_unlock(&eng.lock);
}

/* Capture one frame from the currently-started pipeline and feed it to
 * deliver_snap. Used by the borrow path. */
static int grab_one_snap(uint8_t *rgb_half, uint8_t **prgb_full)
{
    for (int tries = 0; tries < MAX_DQ_TIMEOUTS; tries++) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(eng.fd, &fds);
        struct timeval tv = { .tv_sec = DQ_TIMEOUT_S };
        int r = select(eng.fd + 1, &fds, NULL, NULL, &tv);
        if (r == -1 && errno == EINTR) {
            tries--;
            continue;
        }
        if (r <= 0)
            continue;
        struct v4l2_buffer buf = {0};
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        if (xioctl(eng.fd, VIDIOC_DQBUF, &buf) < 0) {
            if (errno == EAGAIN || errno == EIO)
                continue;
            return -1;
        }
        deliver_snap(eng.bufs[buf.index].start, rgb_half, prgb_full);
        xioctl(eng.fd, VIDIOC_QBUF, &buf);
        return 0;
    }
    return -1;
}

static void *worker(void *arg)
{
    (void)arg;
    uint8_t *rgb_half = malloc((size_t)HALF_W * HALF_H * 3);
    uint8_t *rgb_full = NULL;   /* allocated on first full-res snapshot */
    int dq_timeouts = 0;
    struct timespec fps_t0;
    now_ts(&fps_t0);
    uint64_t fps_frames = 0;

    if (!rgb_half) {
        fprintf(stderr, "cam: worker OOM\n");
        goto out;
    }

    for (;;) {
        struct timespec now;
        now_ts(&now);
        pthread_mutex_lock(&eng.lock);
        int stop = eng.stop_flag;
        int clients = eng.clients;
        int snap = eng.snap_pending == 1 && eng.snap_cam == eng.home_cam;
        int borrow = eng.snap_pending == 1 && eng.snap_cam != eng.home_cam;
        cam_id_t borrow_cam = eng.snap_cam;
        cam_id_t orig_cam = eng.home_cam;
        int idle = clients == 0 && !snap && !borrow &&
                   ts_diff(&now, &eng.last_activity) > IDLE_STOP_S;
        pthread_mutex_unlock(&eng.lock);

        if (stop || idle)
            break;

        /* Cross-camera snapshot: borrow the mux - pause the stream,
         * switch, grab one frame, switch back. Stream clients just see
         * the frame gap (a few seconds). */
        if (borrow) {
            char berr[128];
            release_capture();
            if (start_capture(borrow_cam, berr, sizeof(berr)) == 0) {
                if (grab_one_snap(rgb_half, &rgb_full))
                    fail_snap();
                release_capture();
            } else {
                fprintf(stderr, "cam: borrow start failed: %s\n", berr);
                fail_snap();
            }
            if (start_capture(orig_cam, berr, sizeof(berr))) {
                fprintf(stderr, "cam: restore after borrow failed: %s\n",
                        berr);
                break;  /* engine dies; streams end; reconnect heals */
            }
            continue;
        }

        /* Wait for a frame */
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(eng.fd, &fds);
        struct timeval tv = { .tv_sec = DQ_TIMEOUT_S };
        int r = select(eng.fd + 1, &fds, NULL, NULL, &tv);
        if (r == -1 && errno == EINTR)
            continue;
        if (r <= 0) {
            if (r == 0 && ++dq_timeouts >= MAX_DQ_TIMEOUTS) {
                fprintf(stderr, "cam: %d consecutive frame timeouts, "
                        "stopping engine\n", dq_timeouts);
                break;
            }
            if (r == -1) {
                fprintf(stderr, "cam: select: %s\n", strerror(errno));
                break;
            }
            continue;
        }

        struct v4l2_buffer buf = {0};
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        if (xioctl(eng.fd, VIDIOC_DQBUF, &buf) < 0) {
            if (errno == EAGAIN || errno == EIO)
                continue;
            fprintf(stderr, "cam: DQBUF: %s\n", strerror(errno));
            break;
        }
        dq_timeouts = 0;
        const uint8_t *raw = eng.bufs[buf.index].start;

        /* Snapshot request rides on the same raw frame */
        if (snap)
            deliver_snap(raw, rgb_half, &rgb_full);

        /* Stream frame */
        if (clients > 0) {
            uint8_t *jpg = NULL;
            size_t len = 0;
            debayer_bggr_half(raw, rgb_half, CAM_W, CAM_H, HFLIP);
            if (jpeg_encode_rgb(rgb_half, HALF_W, HALF_H, eng.stream_quality,
                                1, &jpg, &len) == 0) {
                pthread_mutex_lock(&eng.lock);
                free(eng.stream_jpg);
                eng.stream_jpg = jpg;
                eng.stream_len = len;
                eng.seq++;
                fps_frames++;
                struct timespec t;
                now_ts(&t);
                double dt = ts_diff(&t, &fps_t0);
                if (dt >= 2.0) {
                    eng.fps = (double)fps_frames / dt;
                    fps_frames = 0;
                    fps_t0 = t;
                }
                pthread_cond_broadcast(&eng.frame_cv);
                pthread_mutex_unlock(&eng.lock);
            }
        }

        if (xioctl(eng.fd, VIDIOC_QBUF, &buf) < 0) {
            fprintf(stderr, "cam: QBUF: %s\n", strerror(errno));
            break;
        }
    }

out:
    release_capture();
    free(rgb_half);
    free(rgb_full);
    pthread_mutex_lock(&eng.lock);
    eng.running = 0;
    /* fail any waiter: stream clients see running==0, a pending snapshot
     * is marked failed */
    if (eng.snap_pending == 1)
        eng.snap_pending = 3;
    pthread_cond_broadcast(&eng.frame_cv);
    pthread_cond_broadcast(&eng.snap_cv);
    pthread_mutex_unlock(&eng.lock);
    return NULL;
}

/* ------------------------------------------------------- engine control */

/* With ctl held: make the engine run on `cam`. Fails if clients hold the
 * other camera. */
static int ensure_engine(cam_id_t cam, char *err, size_t errlen)
{
    for (;;) {
        pthread_mutex_lock(&eng.lock);
        int running = eng.running;
        /* Compare against the HOME camera: during a snapshot borrow the
         * pipeline (eng.cam) is briefly on the other sensor, and a stream
         * request racing that window must not attach to it. */
        cam_id_t cur = eng.home_cam;
        int clients = eng.clients;
        int tid_valid = eng.tid_valid;
        pthread_mutex_unlock(&eng.lock);

        if (running && cur == cam)
            return 0;

        if (running && cur != cam) {
            if (clients > 0) {
                /* Grace: a client that just disconnected releases its pin
                 * only when the MHD send fails on the next frame - absorb
                 * that (page navigations) instead of failing instantly. */
                struct timespec t0, t;
                now_ts(&t0);
                do {
                    usleep(100 * 1000);
                    pthread_mutex_lock(&eng.lock);
                    clients = eng.clients;
                    pthread_mutex_unlock(&eng.lock);
                    now_ts(&t);
                } while (clients > 0 && ts_diff(&t, &t0) < SWITCH_GRACE_S);
                if (clients > 0) {
                    snprintf(err, errlen,
                             "camera busy: %d client(s) streaming %s",
                             clients, camdefs[cur].name);
                    return -1;
                }
            }
            pthread_mutex_lock(&eng.lock);
            eng.stop_flag = 1;
            pthread_mutex_unlock(&eng.lock);
            /* worker notices at the next tick (<= DQ_TIMEOUT_S) */
        }

        if (tid_valid) {
            pthread_join(eng.tid, NULL);
            pthread_mutex_lock(&eng.lock);
            eng.tid_valid = 0;
            eng.stop_flag = 0;
            pthread_mutex_unlock(&eng.lock);
            continue;   /* re-evaluate from a clean state */
        }

        /* cold start */
        pthread_mutex_lock(&eng.lock);
        eng.home_cam = cam;
        pthread_mutex_unlock(&eng.lock);
        if (start_capture(cam, err, errlen))
            return -1;
        pthread_mutex_lock(&eng.lock);
        eng.running = 1;
        eng.stop_flag = 0;
        eng.seq = 0;
        eng.fps = 0;
        now_ts(&eng.last_activity);
        if (pthread_create(&eng.tid, NULL, worker, NULL)) {
            eng.running = 0;
            pthread_mutex_unlock(&eng.lock);
            release_capture();
            snprintf(err, errlen, "worker thread creation failed");
            return -1;
        }
        eng.tid_valid = 1;
        pthread_mutex_unlock(&eng.lock);
        return 0;
    }
}

void cam_engine_init(void)
{
    const char *v;
    if ((v = getenv("FORGECTRL_STREAM_Q")) != NULL) {
        int q = atoi(v);
        if (q >= 1 && q <= 100)
            eng.stream_quality = q;
    }
    if ((v = getenv("FORGECTRL_LAMP")) != NULL) {
        int l = atoi(v);
        if (l >= 0 && l <= 1023)
            eng.lamp_level = l;
    }
}

void cam_engine_shutdown(void)
{
    pthread_mutex_lock(&eng.ctl);
    pthread_mutex_lock(&eng.lock);
    int tid_valid = eng.tid_valid;
    eng.stop_flag = 1;
    pthread_mutex_unlock(&eng.lock);
    if (tid_valid) {
        pthread_join(eng.tid, NULL);
        pthread_mutex_lock(&eng.lock);
        eng.tid_valid = 0;
        pthread_mutex_unlock(&eng.lock);
    }
    pthread_mutex_unlock(&eng.ctl);
}

/* ------------------------------------------------------------ snapshots */

int cam_snapshot(cam_id_t cam, int full, int quality,
                 uint8_t **jpeg, size_t *len, char *err, size_t errlen)
{
    pthread_mutex_lock(&eng.ctl);

    /* If the engine is streaming the OTHER camera for active clients,
     * don't switch it - post the request and let the worker borrow the
     * mux for one frame. Otherwise make the engine run on `cam`. */
    pthread_mutex_lock(&eng.lock);
    int streaming_other = eng.running && eng.home_cam != cam &&
                          eng.clients > 0;
    pthread_mutex_unlock(&eng.lock);

    if (!streaming_other && ensure_engine(cam, err, errlen)) {
        pthread_mutex_unlock(&eng.ctl);
        return -1;
    }

    pthread_mutex_lock(&eng.lock);
    eng.snap_pending = 1;
    eng.snap_cam = cam;
    eng.snap_full = full;
    eng.snap_quality = quality;
    now_ts(&eng.last_activity);

    struct timespec deadline;
    clock_gettime(CLOCK_REALTIME, &deadline);
    deadline.tv_sec += SNAP_TIMEOUT_S;
    int rc = 0;
    while (eng.snap_pending == 1) {
        if (pthread_cond_timedwait(&eng.snap_cv, &eng.lock, &deadline)
            == ETIMEDOUT) {
            rc = ETIMEDOUT;
            break;
        }
    }
    if (rc == 0 && eng.snap_pending == 2) {
        *jpeg = eng.snap_jpg;
        *len = eng.snap_len;
        eng.snap_jpg = NULL;
        eng.snap_len = 0;
        eng.snap_pending = 0;
    } else {
        if (eng.snap_pending == 1 || eng.snap_pending == 3)
            snprintf(err, errlen, rc == ETIMEDOUT ?
                     "snapshot timed out" : "snapshot capture failed");
        eng.snap_pending = 0;
        rc = -1;
    }
    now_ts(&eng.last_activity);
    pthread_mutex_unlock(&eng.lock);
    pthread_mutex_unlock(&eng.ctl);
    return rc == 0 ? 0 : -1;
}

/* --------------------------------------------------------- stream client */

struct cam_client {
    uint64_t last_seq;
    uint8_t *buf;
    size_t   cap;
};

cam_client_t *cam_client_open(cam_id_t cam, char *err, size_t errlen)
{
    pthread_mutex_lock(&eng.ctl);
    if (ensure_engine(cam, err, errlen)) {
        pthread_mutex_unlock(&eng.ctl);
        return NULL;
    }
    cam_client_t *c = calloc(1, sizeof(*c));
    if (!c) {
        pthread_mutex_unlock(&eng.ctl);
        snprintf(err, errlen, "out of memory");
        return NULL;
    }
    pthread_mutex_lock(&eng.lock);
    eng.clients++;
    now_ts(&eng.last_activity);
    pthread_mutex_unlock(&eng.lock);
    pthread_mutex_unlock(&eng.ctl);
    return c;
}

long cam_client_next(cam_client_t *c, const uint8_t **jpeg)
{
    pthread_mutex_lock(&eng.lock);
    int timeouts = 0;
    while (eng.running && eng.seq <= c->last_seq) {
        struct timespec deadline;
        clock_gettime(CLOCK_REALTIME, &deadline);
        deadline.tv_sec += CLIENT_WAIT_S;
        if (pthread_cond_timedwait(&eng.frame_cv, &eng.lock, &deadline)
            == ETIMEDOUT && ++timeouts >= 2)
            break;
    }
    if (!eng.running || eng.seq <= c->last_seq) {
        pthread_mutex_unlock(&eng.lock);
        return -1;
    }
    if (c->cap < eng.stream_len) {
        uint8_t *nb = realloc(c->buf, eng.stream_len);
        if (!nb) {
            pthread_mutex_unlock(&eng.lock);
            return -1;
        }
        c->buf = nb;
        c->cap = eng.stream_len;
    }
    memcpy(c->buf, eng.stream_jpg, eng.stream_len);
    long len = (long)eng.stream_len;
    c->last_seq = eng.seq;
    now_ts(&eng.last_activity);
    pthread_mutex_unlock(&eng.lock);
    *jpeg = c->buf;
    return len;
}

void cam_client_close(cam_client_t *c)
{
    if (!c)
        return;
    pthread_mutex_lock(&eng.lock);
    if (eng.clients > 0)
        eng.clients--;
    now_ts(&eng.last_activity);
    pthread_mutex_unlock(&eng.lock);
    free(c->buf);
    free(c);
}

/* --------------------------------------------------------------- status */

void cam_get_status(struct cam_status *st)
{
    pthread_mutex_lock(&eng.lock);
    st->running = eng.running;
    st->cam = eng.home_cam;
    st->clients = eng.clients;
    st->seq = eng.seq;
    st->fps = eng.fps;
    pthread_mutex_unlock(&eng.lock);
}
