#!/usr/bin/python3
"""
gfhome - one-shot Glowforge web-service homing for ForgeFIRM

Connects the machine to the Glowforge web service just long enough for
the service to run its camera-based homing sequence (settings report ->
hunt (Z/lens) -> lid image -> move to the home corner -> lid image),
then parks the lens at the hall-sensor reference, disconnects, and
exits. All three axes end at the factory home position: X/Y at the
back-left home corner, Z at the top-of-travel hall trigger.

The grblHAL-glowforge controller invokes this for $H when
homing_mode = gfcloud is set in /data/forgefirm.conf, releasing
/dev/glowforge for the duration of the run. It can also be run by hand
(with the controller stopped or its homing session active). The same
shared config supplies optional identity overrides (gf_serial /
gf_password; the fuse identity is the fallback), managed from the
forgectrl UI. The service hostname is always derived from whichever
serial is in effect - it is never set independently.

The service ends the sequence silently - there is no completion
message - so the run is considered homed once a hunt and at least one
motion have completed and the service has been quiet for --quiet
seconds.

Exit codes: 0 = homed, 1 = configuration/connection failure,
2 = homing did not complete.

(C) Copyright 2026
Scott Wiederhold, s.e.wiederhold@gmail.com
SPDX-License-Identifier: MIT
"""
import argparse
import json
import logging
import os
import queue
import shutil
import signal
import sys
import time
from pathlib import Path
from queue import Queue

from gfutilities.configuration import parse, get_cfg, log_level
from gfutilities.service.authentication import authenticate_machine
from gfutilities.service.dispatch import dispatch_action, PULS_ACTIONS
from gfutilities.service.websocket import get_session, ws_connect

import ffmachine

CONF = '/data/etc/gfhome.conf'
CONF_SAMPLE = '/etc/gfhome.conf.sample'

logging.basicConfig(format='(%(levelname)s) %(module)s:%(funcName)s %(message)s')
logger = logging.getLogger('openglow')


def load_config(path: str) -> bool:
    if path == CONF and not Path(CONF).is_file() and Path(CONF_SAMPLE).is_file():
        Path(CONF).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CONF_SAMPLE, CONF)
    if not Path(path).is_file():
        logger.error('config file %s not found', path)
        return False
    parse(path)
    if not get_cfg('SERVICE.SERVER_URL'):
        logger.error('config %s has no SERVICE section', path)
        return False
    if get_cfg('LOGGING.FILE'):
        Path(get_cfg('LOGGING.FILE')).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(get_cfg('LOGGING.FILE'))
        fh.setLevel(log_level(get_cfg('LOGGING.LEVEL')))
        fh.setFormatter(logging.Formatter(
            '%(asctime)s (%(levelname)s) %(module)s:%(funcName)s %(message)s'))
        logger.addHandler(fh)
    logger.setLevel(logging.DEBUG)
    return True


def home(machine, args) -> int:
    q_rx: Queue = Queue()
    q_tx: Queue = Queue()

    session = get_session()
    if not authenticate_machine(session):
        logger.error('sign-in to %s failed', get_cfg('SERVICE.SERVER_URL'))
        return 1

    # No session passed: homing is a single short connect that never needs
    # a reconnect token refresh.
    ws = ws_connect(q_rx, q_tx)
    if not ws:
        logger.error('web socket connection failed')
        return 1

    result = 2
    try:
        machine.start(session, q_tx)

        from gfhardware._common import InputSwitch
        switches = machine._sw_thread.all_switches()
        if not switches[InputSwitch.SW_DOORS]:
            logger.error('lid is open - close it and re-home')
            return 2
        if not switches[InputSwitch.SW_ESTOP]:
            logger.error('e-stop is tripped')
            return 2

        t0 = time.monotonic()
        last_activity = t0
        in_flight = ''
        done = set()

        while True:
            now = time.monotonic()
            if now - t0 > args.timeout:
                logger.error('homing timed out after %ds (completed: %s)',
                             args.timeout, sorted(done) or 'nothing')
                return 2
            if 'hunt' not in done and now - t0 > args.start_timeout:
                logger.error('service did not start homing within %ds',
                             args.start_timeout)
                return 2

            busy = bool(machine.running_action_id)
            if busy:
                last_activity = now
            elif in_flight:
                logger.info('%s completed', in_flight)
                done.add(in_flight)
                in_flight = ''

            if ('hunt' in done and 'motion' in done and not busy
                    and now - last_activity >= args.quiet):
                logger.info('homing complete (service quiet %.0fs)', args.quiet)
                result = 0
                break

            try:
                msg = json.loads(q_rx.get(timeout=0.5))
            except queue.Empty:
                continue
            except ValueError:
                logger.warning('unparseable service message')
                continue
            last_activity = time.monotonic()
            logger.info('service action: %s (%s)',
                        msg.get('action_type'), msg.get('status'))
            # Homing borrows the service only for camera homing; a print must
            # never run inside a homing session (allow_print=False).
            result = dispatch_action(machine, msg, allow_print=False)
            if result in PULS_ACTIONS:
                in_flight = result
    finally:
        if result == 0:
            # Deterministic Z: the hunt file leaves the lens wherever its
            # pattern ends; re-reference against the hall sensor so the
            # controller can trust top-of-travel.
            try:
                from gfhardware.z_axis import ZAxis
                ZAxis.home()
            except Exception:
                logger.exception('final Z reference failed')
                result = 2
        ws.shutdown()
        try:
            machine.stop()
        except Exception:
            logger.exception('machine shutdown failed')
    return result


def main() -> int:
    try:
        # The controller exports its own $H budget minus a margin, so
        # the runner always gives up before the controller kills it.
        timeout_default = max(30, int(os.environ.get('GFHOME_TIMEOUT_S', 240)))
    except ValueError:
        timeout_default = 240

    ap = argparse.ArgumentParser(description='ForgeFIRM one-shot Glowforge cloud homing')
    ap.add_argument('-c', '--config', default=CONF, help='config file (default %s)' % CONF)
    ap.add_argument('--timeout', type=int, default=timeout_default,
                    help='overall time budget in seconds (default %d)' % timeout_default)
    ap.add_argument('--start-timeout', type=int, default=120,
                    help='max seconds to wait for the service to begin homing (default 120)')
    ap.add_argument('--quiet', type=int, default=10,
                    help='silence after the last action that means done (default 10)')
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))

    if not load_config(args.config):
        return 1

    ffmachine.apply_identity_overrides()

    # Machine() reads the OCOTP identity and head info; it fails cleanly
    # when the controller still owns /dev/glowforge.
    try:
        machine = ffmachine.build_machine()
    except Exception:
        logger.exception('machine init failed (is the motion controller '
                         'still holding /dev/glowforge?)')
        return 1

    rc = home(machine, args)
    logger.info('exit %d (%s)', rc, 'homed' if rc == 0 else 'not homed')
    return rc


if __name__ == '__main__':
    sys.exit(main())
