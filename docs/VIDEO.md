# Video and the cameras

The machine has two cameras — one in the lid looking down at the bed, one in the
print head looking at the material under the lens — and ForgeFIRM serves both
over plain HTTP from the web control panel: **MJPEG** for anything that can read
a stream of JPEGs, and an **H.264** live stream for clients that decode video
(the panel uses it when the browser can). There is no app, no cloud relay, and
no proprietary protocol.

One rule governs all of it: **the cameras only capture with the lid closed**
(§2). Everything else here assumes that condition is met.

This page explains what you get, how to point a client at it, what the sensors
are physically capable of versus what ForgeFIRM actually sends and why, and what
you can change.

- For sender setup in general, see [Connecting LightBurn](LIGHTBURN.md).
- The cloud mode described in §8 is documented in
  [Cloud mode](https://github.com/ScottW514/python3-gfhardware/blob/master/forgefirm-app/docs/CLOUD.md).

---

## 1. What the hardware is

The two cameras carry the same kind of sensor and feed one shared path into the
board. A **hardware MIPI switch** (the factory `CAM_SEL` line) selects which of
them reaches the board's single camera receiver, so **exactly one camera can be
capturing at any moment**. That is a property of the board, not a software
limit — there is no configuration in which both stream at once.

| | Lid camera | Head camera |
|---|---|---|
| Sees | the whole bed, from above | the material directly under the lens |
| Its lamp | the lid LED strip | the white LED in the print head |
| Used for | bed view, camera-referenced homing, LightBurn's camera overlay | focus and material inspection (cloud mode's distance measurement) |

The lid lens is a wide fisheye, which matters for how you use the image (§5.5).

Which sensor is fitted depends on the machine. Standard machines carry a **5 MP
OV5648**; "HD" machines carry an **8 MP OV8856**. ForgeFIRM reads which one
bound and configures itself accordingly — one firmware image covers both — and
reports it in `/cam/status` and on the panel's Status tab.

---

## 2. Privacy: the cameras only work with the lid closed

**Neither camera captures anything while the lid is open.** Not the live view,
not a snapshot, and not an image requested by the Glowforge service in cloud
mode. Close the lid and everything works; open it and the sensors stop.

The reason is where the lid camera points. It is mounted in the lid, so raising
the lid swings it up to face the room — and in cloud mode the shutter is not
yours to press: the service asks for images on its own schedule, whenever it is
connected. The rule removes the question. The enclosure being shut is the
condition for an image to exist at all.

**What the rule covers**

- **Both cameras.** The head camera is gated too, so this is one rule to
  remember rather than a rule with an exception you have to trust.
- **Every way in:** the panel, `/cam/stream`, `/cam/snapshot`, the
  mjpg-streamer aliases, LightBurn, and cloud mode's image actions.
- **Capture already running.** Opening the lid stops a live stream within
  about a frame and shuts the sensor down; it does not merely block new
  requests.
- **The lamps.** A refused capture never raises them, so an attempt with the
  lid open leaves no trace.

**How it behaves**

| Situation | What happens |
|---|---|
| Snapshot requested with the lid open | `409` and a message naming the lid; no image data |
| Stream requested with the lid open | `409`; the stream never opens |
| Lid opened while a stream is running | the stream ends cleanly and the pipeline is torn down |
| Lid state unreadable | treated as open — capture refused |
| Cloud service asks for an image with the lid open | refused, and reported back to the service as a failed action rather than left hanging |
| Lid closed again | everything works immediately; nothing to restart |

`GET /cam/status` reports it: **`capture_allowed`** is false whenever the lid is
open, and **`stopped_by_lid`** records that the last capture ended because the
lid opened rather than going idle. The panel's Status tab says *lid open — the
cameras are off* rather than showing a stream error.

**Where the check comes from.** The lid signal is the same one the hardware
safety chain uses to gate the beam — the series combination of both lid
switches, not a software flag — and the check **fails closed**: if the lid
state cannot be read at all, the cameras stay dark. That direction is proven by
a unit test in CI; the end-to-end behavior is an acceptance test run on real
hardware.

**One thing it costs.** The factory firmware ran the cloud's focus *hunt* with
the lid open, and part of a hunt is a head capture. Those captures are now
refused, so a hunt attempted with the lid open fails instead of completing.
Close the lid before letting the app focus or print.

**What it is not.** This is a rule enforced by the two programs that own the
sensors, not a hardware cut-off: the sensor rails stay powered, and anyone with
root on the machine could bypass it. It protects you from the Glowforge
service, from other software on your network, and from a stream you forgot was
running — not from someone who already controls the board. There is
deliberately no setting to turn it off.

---

## 3. Watching it

**In the panel.** Open `http://<machine>:8080/` and go to the **Status** tab.
The *Lid camera* card shows a still by default with **Live** and **Refresh**
buttons; **Live** switches the same frame to the running stream.

**From another program.** The endpoints are:

| URL | What it returns |
|---|---|
| `/cam/stream?cam=lid` | continuous MJPEG (`multipart/x-mixed-replace`) |
| `/cam/stream?cam=head` | the same, from the head camera |
| `/cam/h264?cam=lid` | continuous H.264 as fragmented MP4 (see §5.6): the same picture in a fraction of the bytes, for clients that decode video |
| `/cam/snapshot?cam=lid` | one full-resolution JPEG |
| `/cam/snapshot?cam=lid&res=half` | one half-resolution JPEG (much faster) |
| `/cam/status` | JSON: which sensor, which camera, frame rate, frame sizes, whether the lid currently permits capture |
| `/?action=stream` | the lid stream again, under the name mjpg-streamer clients expect |
| `/?action=snapshot` | one full-resolution lid JPEG, same aliasing |

The `?action=` pair exists because a lot of software — print-server dashboards,
camera widgets, anything written against mjpg-streamer — assumes those exact
URLs. Point such a client at `http://<machine>:8080/` and it will work.

Every one of them answers **`409`** with the lid open (§2), so a client that
checks status codes can tell "close the lid" apart from "the camera is broken".

**Access.** Reading the camera needs no token. It does need a request that
addresses the machine by IP address (or `localhost`) and, from a browser, one
that is not cross-site — that is what stops a hostile page in another tab from
reaching into your machine. It is not protection against other people on your
LAN. Anything that *changes* machine state does need the panel's token. In
practice: paste the URL into any local client and it works.

---

## 4. What you actually get

| | 5 MP machine (OV5648) | 8 MP machine (OV8856) |
|---|---|---|
| Sensor frame captured | 2592 × 1944 | 3264 × 2448 |
| Live stream | 1296 × 972 | 1632 × 1224 |
| Full snapshot | 2592 × 1944 | 3264 × 2448 |
| Half snapshot | 1296 × 972 | 1632 × 1224 |
| Stream formats | MJPEG (quality 75 by default) and H.264 (~1.5 Mbit/s by default) | same |
| Frame rate | **15 fps** sustained | not yet measured (§10) |

Measured on a 5 MP machine: 15.0 fps with a viewer attached, which is the rate
the sensor itself produces in this mode — the machine is not the bottleneck.
The daemon uses about 41 % of one CPU with one viewer, and LightBurn can watch
the stream while jogging from the same session without disturbing motion. A
full-resolution still takes about 2.4 s to produce (2.7 s if the camera has to
be started first), because 5 megapixels of demosaicing and JPEG encoding happen
on the machine's CPU.

The stream frame is not a resampled copy of the full frame. Each 2 × 2 group of
sensor pixels becomes exactly one output pixel, which is why the stream is
precisely half the capture in each axis and why it is cheap enough to run
continuously.

The 41 % figure is the NEON demosaic feeding the hardware JPEG encoder. When
the GPU demosaic and the H.264 stream carry the load instead (§5.6), the
stream's CPU cost drops to bookkeeping; those two paths are newer than the
figure above and their own numbers will be measured on the bench the same way.

---

## 5. What the sensor can do versus what ForgeFIRM sends

This is where expectations usually come unstuck: the sensors are more capable
on paper than the video you get. Each difference below is deliberate and has a
reason.

| | The sensor can | ForgeFIRM sends | Why |
|---|---|---|---|
| Live resolution | full frame | half in each axis | CPU and bandwidth; §5.1 |
| Frame rate (5 MP) | 30 fps in reduced modes | 15 fps | the full-field mode runs at 15 fps; §5.1 |
| Resolution (8 MP) | 3280 × 2464 | 3264 × 2448 | the widest frame the board's camera receiver can take; §5.2 |
| Bit depth | 10 bits per pixel | 8 bits | JPEG is 8-bit, and 8-bit is what makes §5.2 fit |
| Exposure / color | auto exposure and auto white balance | fixed values | a bed image has to look the same frame to frame; §5.4 |
| Lens | — | no correction applied | correction belongs in the client; §5.5 |
| Encoding | — | MJPEG and H.264, nothing recorded | §5.6 |
| Mirroring | a mirror register | mirrored in software instead | the register breaks capture on this board; §5.7 |

### 5.1 Resolution and frame rate on a 5 MP machine

The OV5648 offers several modes, and they are not simply "the same picture,
smaller":

| Mode | Rate | Field of view |
|---|---|---|
| 2592 × 1944 | 15 fps | the whole sensor |
| 1920 × 1080 | 15 fps | a crop from the middle |
| 1600 × 1200 | 15 fps | a crop from the middle |
| 1280 × 960 | 30 fps | the whole sensor, every other pixel |
| 1280 × 720 | 30 fps | a crop, every other pixel |
| 640 × 480 | 30 fps | the whole sensor, every fourth pixel |

ForgeFIRM runs the **2592 × 1944** mode. The cropped modes are unusable for a
bed camera — they would show the middle of the bed and cut off the corners. That
leaves the full-frame mode at 15 fps or the skipped 1280 × 960 mode at 30 fps.

The camera runs **one mode at a time**, and the live stream and the snapshots
come from the same frames: that is what lets a snapshot be delivered while a
stream is running, and it is why the picture does not stutter or re-expose when
you take one. Choosing 1280 × 960 would double the frame rate and permanently
give up full-resolution stills — and full resolution is exactly what bed
alignment, camera calibration and cloud mode need. Full stills win; 15 fps is
the price.

The stream is halved to 1296 × 972 rather than sent at full size because
demosaicing and encoding 5 megapixels 15 times a second is far beyond this
CPU, and because a 5 MP live view of the bed is of no practical use — it is a
positioning aid, not a photograph.

### 5.2 8 MP ("HD") machines: a few rows short of the full array

The OV8856's largest frame is 3280 × 2464. ForgeFIRM captures **3264 × 2448**,
which is 16 columns and 16 rows less — the whole field of view, edge to edge,
just without the last few pixels of margin.

Getting there is not free, and it explains why §5.3 matters. The sensor can
send its full frame over the two data lanes this board wires, but at 10 bits
per pixel that means running the link at **1.44 Gbit/s per lane**, and the
i.MX6's camera receiver tops out at **1 Gbit/s per lane** — it has no timing
setting for anything faster, so it refuses the mode outright. Asking the sensor
for 8-bit pixels instead cuts a fifth off every sample and lets the same frame
travel at half the rate, which the receiver takes comfortably. That is how an
HD machine gets its full resolution, and it costs nothing, because the
delivered JPEG was going to be 8-bit anyway.

The result is about 15 frames per second off the sensor, and roughly the same
bytes per second across the bus as a 5 MP machine at its own full frame.

### 5.3 Ten bits in, eight bits out

Both sensors can emit 10 bits per pixel. ForgeFIRM asks both for 8 instead, and
the delivered image is 8 bits per channel because that is what JPEG is.

Two bits would buy nothing without a tone curve to spend them on, and there is
no tone curve (§5.4) — while asking for 8 halves the data crossing the bus,
which is what keeps the stream cheap on a 5 MP machine and what makes full
resolution reachable at all on an 8 MP one (§5.2).

### 5.4 Exposure, gain and color are fixed

There is no auto-exposure and no auto white balance. Exposure, gain and the
color balance are set to fixed values when the camera starts, matching what the
factory firmware used, and they are not adjustable from the panel.

That is deliberate. A bed camera is a measuring instrument: camera-referenced
homing, LightBurn's overlay, and cloud mode's alignment all compare images to
known geometry, and an image whose brightness and color shift between frames —
as the head moves through the frame, or as the laser flashes — is worse than a
consistently imperfect one.

ForgeFIRM also applies **no gamma, tone curve, sharpening or noise reduction**.
The JPEG is the sensor's data, demosaiced and encoded. Compared with a phone
photo the result looks flat. That is expected; it is not a fault, and it does
not affect how well the image works for alignment.

One consequence on 8 MP machines: that sensor's driver publishes no color
balance controls at all, so those images will be less color-correct than a
5 MP machine's until the exposure and gain are commissioned on real hardware.

### 5.5 The lens is not corrected

The lid lens is a wide fisheye and the image has heavy barrel distortion —
straight bed edges bow. ForgeFIRM sends the image as the lens sees it and does
not attempt to flatten it.

Correction belongs where the calibration lives: **LightBurn's camera
calibration** pass measures your particular machine's lens and applies the
correction on the host, which is more accurate than a fixed correction baked
into the firmware and costs the machine's CPU nothing. Run that calibration
before trusting the camera overlay for placement.

### 5.6 Two streams, one picture: MJPEG and H.264. Nothing is recorded.

The same live picture is served two ways, and **the machine never writes video
to disk**.

**MJPEG** (`/cam/stream`) is the universal one: every frame is a complete
JPEG, so a viewer can join or leave at any moment, a dropped frame costs
nothing, and browsers, LightBurn and mjpg-streamer clients consume it with no
plugin. It stays, unchanged, and it is what anything that cannot decode video
should use.

**H.264** (`/cam/h264`) exists because bytes on this machine are not free.
MJPEG re-sends the whole scene fifteen times a second, roughly 9 Mbit/s, and
the WiFi transmit path runs on the machine's single CPU core, where measured
cost is about 7 % of the core per MB/s sent. A bed camera's scene barely
changes between frames, which is exactly what an inter-frame codec exploits:
the H.264 stream carries the same picture in roughly 1.5 Mbit/s and gives most
of that CPU back. It arrives as fragmented MP4, the form a browser's Media
Source Extensions accept, with the codec named in an `X-H264-Codec` response
header; the panel's **Live** button uses it automatically where the browser
can and falls back to MJPEG where it cannot. Latency is a beat behind MJPEG
(under a second), which is why LightBurn keeps consuming the MJPEG stream.

Both encoders are hardware: JPEG frames come from the CODA960's JPEG unit and
H.264 from its BIT processor, two independent engines, so serving both at once
does not double any cost that matters. The demosaic that feeds them runs as
fragment shaders on the SoC's GC880 GPU when the image ships the GL stack
(reported as `"convert": "gpu"` in `/cam/status`), reading the sensor frame
and writing the encoder's buffer directly, so a stream frame never crosses the
CPU at all; without the GPU it falls back to the NEON demosaic. (Stills are
still demosaiced and encoded on the CPU, which is most of why a
full-resolution one takes a couple of seconds.)

One more consumer of nothing: with a frame-rate cap set (`FORGECTRL_STREAM_FPS`
of 1 or more), the cap is programmed into the CSI receiver's frame-skip
hardware, and skipped frames are dropped before they are ever written to
memory. `/cam/status` reports `"hw_fps_skip": true` when that is in effect.

If you want a recording, record the stream on the computer watching it. The
machine stores its firmware, settings and logs on a small internal flash device
and has no recording feature to fill it with.

### 5.7 The mirror is applied in software

The image is mirrored horizontally to match the orientation the factory
software produced. The sensors have a mirror register that would do this for
free, but setting it breaks the board's capture path — frames stop completing
altogether — so the flip is done while the image is being demosaiced instead.
The cost is negligible and the result is identical.

---

## 6. Lighting

Each camera has its own lamp, and ForgeFIRM drives them around captures:

- **While capturing**, the relevant lamp is raised to a fixed working level and
  restored when the camera goes idle.
- **At rest**, the lid lamp sits at the `lid_lamp_idle` setting (0–255, default
  236) — the bed light you normally see. It is asserted when the daemon starts,
  when you change the setting, and whenever a controller starts.
- **Per shot**, `/cam/snapshot` accepts `lamp=0..1023` to override the level for
  that one image; a few frames are discarded afterward so the image you get was
  actually exposed under the light you asked for.

In cloud mode the cloud client drives the lid lamp for as long as it runs, and
ForgeFIRM re-asserts your idle level the next time a controller starts.

---

## 7. Sharing one camera path

Because only one camera can capture at a time, requests have to be arbitrated.
The rule is **the newest request wins**, on the assumption that one person is
standing at the machine:

- **A new stream preempts the current one.** Existing viewers' streams end
  cleanly — their picture freezes on the last frame — rather than being torn
  mid-frame.
- **A snapshot of the other camera borrows the path.** The stream pauses, the
  mux switches, one frame is taken, and it switches back; viewers see a gap of
  a second or two. Snapshots do not fail because someone else is watching.
- **The camera shuts down after 10 seconds** with nobody watching and no
  snapshot pending, so other software on the machine can use it — and
  immediately, whoever is watching, if the lid opens (§2).

---

## 8. Who else uses the cameras

- **Camera-referenced homing** (`$H`) takes a lid image and has the Glowforge
  service work out where the head is. This is the factory homing method, so it
  needs a service session; it is the one part of GRBL mode that does.
- **Cloud mode** captures both cameras on demand through the same snapshot
  endpoint, so it obeys the same arbitration as everything else.
- **LightBurn** consumes the lid stream for its camera overlay while it drives
  motion over the Grbl connection; the two coexist.

---

## 9. When something looks wrong

**No picture at all, and a 409 mentioning the lid.** Working as intended: the
lid is open (§2). Close it. `/cam/status` shows `capture_allowed: false` while
that is the case. If the lid *is* shut and you still see this, one of the two
lid switches is not making — the same condition that would stop the laser
firing, so it is worth investigating rather than working around.

**A black or nearly black picture.** The scene is not lit: the exposure is
fixed, so the camera cannot compensate. Check `lid_lamp_idle`, and remember
snapshots can carry their own `lamp=` level.

**The stream stops on its own.** Either the lid opened (§2 — the panel says
so), or someone else — another browser tab, LightBurn, the panel — asked for
the other camera, or for a stream, and preempted yours. Reload; the panel does
this automatically and says which it was.

**"camera switch timed out".** A viewer would not let go within the grace
period. Close the other viewer and retry.

**A snapshot returns 503.** The camera could not start. The usual cause is
another process holding the capture device; the daemon's log names the failing
step.

**`/cam/status` reports `"sensor": "unknown"`.** No camera was found on that
bus, or a sensor bound that this firmware has no profile for. On an HD machine
see §9.

**The picture is bowed / placement is off.** Expected without calibration; see
§5.5.

---

## 10. Status of 8 MP ("HD") machines

Everything an 8 MP machine needs is in the firmware: the kernel patches for the
OV8856 — including the 8-bit full-resolution mode §5.2 depends on — the
device-tree entries, and a capture path that picks its geometry and sensor
controls from whichever sensor bound.

**None of it has run on an 8 MP machine.** No such unit has been available to
test against, so treat 8 MP support as untested rather than working: whether
the receiver locks onto the full-resolution mode, and what exposure and gain
the sensor actually wants, can only be settled on that hardware. Frame-rate and
CPU figures in §4 are from a 5 MP machine and do not carry over — an HD machine
demosaics 60 % more pixels per frame. Reports from anyone with an HD machine
are welcome.

The 5 MP path is hardware-validated and in daily use.

---

## See also

- [Connecting LightBurn](LIGHTBURN.md) — sender setup and the camera overlay
- [Motion and laser drive](MOTION.md) — what the machine does while you watch
- [Cooling and airflow](COOLING.md)
- [Laser safety](SAFETY.md)
