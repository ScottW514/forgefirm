/*
 * main.c - forgectrl: ForgeFIRM system control daemon
 * Copyright (c) 2026 Scott Wiederhold <s.e.wiederhold@gmail.com>
 * SPDX-License-Identifier: MIT
 *
 * HTTP service (ulfius) exposing the Glowforge cameras as MJPEG:
 *
 *   GET /                        index page with a live view
 *   GET /?action=stream          mjpg-streamer-compatible stream (lid)
 *   GET /?action=snapshot        mjpg-streamer-compatible snapshot (lid)
 *   GET /cam/stream?cam=lid|head            multipart MJPEG, 1296x972
 *   GET /cam/snapshot?cam=&res=full|half&q= single JPEG (default full res)
 *   GET /cam/status                         JSON engine status
 *
 * The two cameras share the hardware mux, so streaming clients pin the
 * selection; requests for the other camera return 409 until they leave.
 * Environment: FORGECTRL_PORT (8080), FORGECTRL_STREAM_Q (75),
 * FORGECTRL_LAMP (132).
 *
 * ulfius runs libmicrohttpd in thread-per-connection mode, so each stream
 * callback may block waiting for the next frame.
 */
#define _GNU_SOURCE
#include "cam.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ulfius.h>
#include <unistd.h>

#define DEFAULT_PORT 8080
#define BOUNDARY     "forgectrl-frame"
#define SNAP_Q_DEF   75

static volatile sig_atomic_t quit = 0;

static void on_signal(int sig)
{
    (void)sig;
    quit = 1;
}

/* ------------------------------------------------------------- helpers */

static cam_id_t parse_cam(const struct _u_request *req, int *ok)
{
    const char *v = u_map_get(req->map_url, "cam");
    *ok = 1;
    if (!v || !strcmp(v, "lid"))
        return CAM_LID;
    if (!strcmp(v, "head"))
        return CAM_HEAD;
    *ok = 0;
    return CAM_LID;
}

static int reply_error(struct _u_response *res, unsigned status,
                       const char *msg)
{
    ulfius_set_string_body_response(res, status, msg);
    ulfius_add_header_to_response(res, "Content-Type", "text/plain");
    return U_CALLBACK_CONTINUE;
}

/* ------------------------------------------------------------ streaming */

struct stream_ctx {
    cam_client_t *cl;
    uint8_t      *chunk;    /* current multipart chunk being drained */
    size_t        chunk_cap;
    size_t        chunk_len;
    size_t        off;
};

static ssize_t stream_cb(void *cls, uint64_t pos, char *buf, size_t max)
{
    (void)pos;
    struct stream_ctx *sc = cls;

    if (sc->off >= sc->chunk_len) {
        const uint8_t *jpg;
        long len = cam_client_next(sc->cl, &jpg);
        if (len < 0)
            return U_STREAM_END;

        char head[128];
        int headlen = snprintf(head, sizeof(head),
                               "--" BOUNDARY "\r\n"
                               "Content-Type: image/jpeg\r\n"
                               "Content-Length: %ld\r\n\r\n", len);
        size_t need = (size_t)headlen + (size_t)len + 2;
        if (sc->chunk_cap < need) {
            uint8_t *nb = realloc(sc->chunk, need);
            if (!nb)
                return U_STREAM_ERROR;
            sc->chunk = nb;
            sc->chunk_cap = need;
        }
        memcpy(sc->chunk, head, (size_t)headlen);
        memcpy(sc->chunk + headlen, jpg, (size_t)len);
        memcpy(sc->chunk + headlen + len, "\r\n", 2);
        sc->chunk_len = need;
        sc->off = 0;
    }

    size_t n = sc->chunk_len - sc->off;
    if (n > max)
        n = max;
    memcpy(buf, sc->chunk + sc->off, n);
    sc->off += n;
    return (ssize_t)n;
}

static void stream_free_cb(void *cls)
{
    struct stream_ctx *sc = cls;
    cam_client_close(sc->cl);
    free(sc->chunk);
    free(sc);
}

static int do_stream(cam_id_t cam, struct _u_response *res)
{
    char err[256];
    cam_client_t *cl = cam_client_open(cam, err, sizeof(err));
    if (!cl)
        return reply_error(res, strstr(err, "busy") ? 409 : 503, err);

    struct stream_ctx *sc = calloc(1, sizeof(*sc));
    if (!sc) {
        cam_client_close(cl);
        return reply_error(res, 500, "out of memory");
    }
    sc->cl = cl;

    ulfius_add_header_to_response(res, "Content-Type",
        "multipart/x-mixed-replace; boundary=" BOUNDARY);
    ulfius_add_header_to_response(res, "Cache-Control", "no-store");
    ulfius_set_stream_response(res, 200, stream_cb, stream_free_cb,
                               U_STREAM_SIZE_UNKNOWN, 64 * 1024, sc);
    return U_CALLBACK_CONTINUE;
}

static int do_snapshot(cam_id_t cam, int full, int quality,
                       struct _u_response *res)
{
    uint8_t *jpg = NULL;
    size_t len = 0;
    char err[256];
    if (cam_snapshot(cam, full, quality, &jpg, &len, err, sizeof(err)))
        return reply_error(res, strstr(err, "busy") ? 409 : 503, err);
    ulfius_set_binary_body_response(res, 200, (const char *)jpg, len);
    ulfius_add_header_to_response(res, "Content-Type", "image/jpeg");
    ulfius_add_header_to_response(res, "Cache-Control", "no-store");
    free(jpg);
    return U_CALLBACK_CONTINUE;
}

/* ------------------------------------------------------------ callbacks */

static int cb_stream(const struct _u_request *req, struct _u_response *res,
                     void *user_data)
{
    (void)user_data;
    int ok;
    cam_id_t cam = parse_cam(req, &ok);
    if (!ok)
        return reply_error(res, 400, "cam must be 'lid' or 'head'");
    return do_stream(cam, res);
}

static int cb_snapshot(const struct _u_request *req, struct _u_response *res,
                       void *user_data)
{
    (void)user_data;
    int ok;
    cam_id_t cam = parse_cam(req, &ok);
    if (!ok)
        return reply_error(res, 400, "cam must be 'lid' or 'head'");

    int full = 1;
    const char *v = u_map_get(req->map_url, "res");
    if (v) {
        if (!strcmp(v, "half"))
            full = 0;
        else if (strcmp(v, "full"))
            return reply_error(res, 400, "res must be 'full' or 'half'");
    }
    int quality = SNAP_Q_DEF;
    if ((v = u_map_get(req->map_url, "q")) != NULL) {
        quality = atoi(v);
        if (quality < 1 || quality > 100)
            return reply_error(res, 400, "q must be 1..100");
    }
    return do_snapshot(cam, full, quality, res);
}

static int cb_status(const struct _u_request *req, struct _u_response *res,
                     void *user_data)
{
    (void)req;
    (void)user_data;
    struct cam_status st;
    cam_get_status(&st);
    char body[256];
    snprintf(body, sizeof(body),
             "{\"running\":%s,\"cam\":\"%s\",\"clients\":%d,"
             "\"frames\":%llu,\"fps\":%.1f,"
             "\"stream\":{\"width\":1296,\"height\":972},"
             "\"snapshot\":{\"width\":2592,\"height\":1944}}",
             st.running ? "true" : "false", cam_name(st.cam), st.clients,
             (unsigned long long)st.seq, st.fps);
    ulfius_set_string_body_response(res, 200, body);
    ulfius_add_header_to_response(res, "Content-Type", "application/json");
    return U_CALLBACK_CONTINUE;
}

static const char index_html[] =
    "<!DOCTYPE html><html><head><title>ForgeFIRM camera</title>"
    "<style>body{font-family:sans-serif;background:#111;color:#ddd;"
    "text-align:center}img{max-width:95%;border:1px solid #444}"
    "a{color:#8cf}</style></head><body>"
    "<h2>ForgeFIRM camera</h2>"
    "<p><a href=\"/cam/stream?cam=lid\">lid stream</a> | "
    "<a href=\"/cam/snapshot?cam=lid\">lid snapshot</a> | "
    "<a href=\"/cam/stream?cam=head\">head stream</a> | "
    "<a href=\"/cam/snapshot?cam=head\">head snapshot</a> | "
    "<a href=\"/cam/status\">status</a></p>"
    "<img src=\"/cam/stream?cam=lid\" alt=\"lid camera stream\">"
    "</body></html>";

/* "/" serves the index, plus the mjpg-streamer-compatible
 * ?action=stream / ?action=snapshot aliases many clients expect. */
static int cb_root(const struct _u_request *req, struct _u_response *res,
                   void *user_data)
{
    (void)user_data;
    const char *action = u_map_get(req->map_url, "action");
    if (action) {
        if (!strcmp(action, "stream"))
            return do_stream(CAM_LID, res);
        if (!strcmp(action, "snapshot"))
            return do_snapshot(CAM_LID, 1, SNAP_Q_DEF, res);
        return reply_error(res, 400, "unknown action");
    }
    ulfius_set_string_body_response(res, 200, index_html);
    ulfius_add_header_to_response(res, "Content-Type", "text/html");
    return U_CALLBACK_CONTINUE;
}

/* ------------------------------------------------------------------ main */

int main(void)
{
    unsigned port = DEFAULT_PORT;
    const char *v = getenv("FORGECTRL_PORT");
    if (v && atoi(v) > 0 && atoi(v) < 65536)
        port = (unsigned)atoi(v);

    /* Stay well below the motion feeder (SCHED_FIFO) and the controller;
     * best effort. */
    (void)nice(5);

    cam_engine_init();

    struct _u_instance inst;
    if (ulfius_init_instance(&inst, port, NULL, NULL) != U_OK) {
        fprintf(stderr, "forgectrl: ulfius init failed\n");
        return 1;
    }
    ulfius_add_endpoint_by_val(&inst, "GET", "/", NULL, 0, &cb_root, NULL);
    ulfius_add_endpoint_by_val(&inst, "GET", "/cam/stream", NULL, 0,
                               &cb_stream, NULL);
    ulfius_add_endpoint_by_val(&inst, "GET", "/cam/snapshot", NULL, 0,
                               &cb_snapshot, NULL);
    ulfius_add_endpoint_by_val(&inst, "GET", "/cam/status", NULL, 0,
                               &cb_status, NULL);

    if (ulfius_start_framework(&inst) != U_OK) {
        fprintf(stderr, "forgectrl: cannot start HTTP on port %u\n", port);
        ulfius_clean_instance(&inst);
        return 1;
    }
    fprintf(stderr, "forgectrl: listening on port %u\n", port);

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);
    while (!quit)
        pause();

    fprintf(stderr, "forgectrl: shutting down\n");
    ulfius_stop_framework(&inst);
    ulfius_clean_instance(&inst);
    cam_engine_shutdown();
    return 0;
}
