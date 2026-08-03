/*
 * cam.h - persistent Glowforge camera capture engine
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 *
 * One worker thread owns the imx-media pipeline and V4L2 capture node for
 * the selected camera (lid or head - they share the video-mux, so exactly
 * one can stream at a time). The engine starts on demand, publishes the
 * latest half-resolution JPEG for stream clients, serves full-resolution
 * snapshot requests from the same raw frames, and tears the pipeline down
 * after an idle period so one-shot users (gfhardware) can still grab.
 */
#ifndef FORGECTRL_CAM_H
#define FORGECTRL_CAM_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    CAM_LID  = 0,
    CAM_HEAD = 1,
} cam_id_t;

/* Read once at startup (env overrides): stream JPEG quality and lamp level. */
void cam_engine_init(void);

/* Stop the engine (if running) and release everything. */
void cam_engine_shutdown(void);

/* Blocking snapshot from the live engine. full=1 -> 2592x1944 bilinear,
 * full=0 -> 1296x972. quality 1..100. On success *jpeg is malloc'd (caller
 * frees). If the other camera is streaming, the worker borrows the mux for
 * one frame (the stream freezes for a few seconds) - snapshots do not fail
 * busy. Returns 0, or -1 with a message in err (pipeline failure,
 * timeout). */
int cam_snapshot(cam_id_t cam, int full, int quality,
                 uint8_t **jpeg, size_t *len, char *err, size_t errlen);

/* Stream client: open makes the engine serve `cam` (starting it, or
 * preempting the current clients and switching - last request wins; the
 * preempted clients' next() returns -1 so their streams end cleanly).
 * next blocks for a frame newer than the last one returned and copies it
 * into a client-owned buffer, close releases the pin. */
typedef struct cam_client cam_client_t;

cam_client_t *cam_client_open(cam_id_t cam, char *err, size_t errlen);
/* Returns frame length (>0), or -1 when the engine stopped / timed out and
 * the stream should end. The returned pointer stays valid until the next
 * cam_client_next() or cam_client_close(). */
long cam_client_next(cam_client_t *c, const uint8_t **jpeg);
void cam_client_close(cam_client_t *c);

/* Status snapshot for /cam/status. */
struct cam_status {
    int      running;
    cam_id_t cam;
    int      clients;
    uint64_t seq;
    double   fps;
};
void cam_get_status(struct cam_status *st);

const char *cam_name(cam_id_t cam);

#endif
