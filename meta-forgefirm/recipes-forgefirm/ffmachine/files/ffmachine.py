"""
ffmachine - shared ForgeFIRM hardware-machine glue for the Glowforge
web-service clients: the gfhome one-shot homing runner and the gfcloud
full-cloud daemon both drive the same hardware Machine with captures
routed through forgectrl, and honour the same shared-config identity
overrides. Config-file parsing and logging stay in each client.

(C) Copyright 2026
Scott Wiederhold, s.e.wiederhold@gmail.com
SPDX-License-Identifier: MIT
"""
import logging
import os

from gfutilities.configuration import get_cfg, set_cfg

logger = logging.getLogger('openglow')

# The shared machine config (identity overrides, homing/controller mode),
# managed from the forgectrl UI. Override the path with GFHOME_CONF.
MACHINE_CONF = os.environ.get('GFHOME_CONF', '/data/forgefirm.conf')

_HOSTNAME_ALPHABET = 'BCDFGHJKMQRTVWXY2346789'


def hostname_for(serial) -> str:
    """The factory serial -> hostname encoding (base 23 over the consonant
    alphabet, up to six characters, split XXX-YYY) - the same derivation
    gfhardware applies to the fuse serial."""
    enc = ''
    serial = int(serial)
    while serial > 0 and len(enc) < 6:
        enc = _HOSTNAME_ALPHABET[serial % 23] + enc
        serial //= 23
    return '{}-{}'.format(enc[:3], enc[3:])


def apply_identity_overrides(machine_conf: str = MACHINE_CONF) -> None:
    """Identity overrides from the shared machine config (set in the
    forgectrl UI): non-empty gf_serial / gf_password beat the OCOTP fuse
    identity - Machine.__init__ sets its fuse values with keep_value, so
    whatever is in the config store first wins. The hostname is never
    overridden independently: it derives from the serial, so a serial
    override re-derives it."""
    keys = {}
    try:
        with open(machine_conf) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                keys[k.strip()] = v.strip()
    except OSError:
        return
    for key, cfg in (('gf_serial', 'MACHINE.SERIAL'),
                     ('gf_password', 'MACHINE.PASSWORD')):
        if keys.get(key):
            set_cfg(cfg, keys[key])
            logger.info('identity override: %s from %s', cfg, machine_conf)
    if keys.get('gf_serial'):
        try:
            set_cfg('MACHINE.HOSTNAME', hostname_for(keys['gf_serial']))
            logger.info('identity override: MACHINE.HOSTNAME derived '
                        'from gf_serial')
        except ValueError:
            logger.warning('gf_serial is not numeric; hostname left at '
                           'the fuse derivation')


def build_machine():
    """Build the hardware Machine with captures routed through forgectrl.

    forgectrl owns the imx-media pipeline whenever it serves a stream
    (LightBurn typically keeps one open), so direct V4L2 grabs fail busy.
    Its snapshot endpoint delivers the same factory-configured
    full-resolution JPEG, works during an active stream (mux borrow), and
    takes a per-shot lamp override - head captures request lamp=0 because
    added white light washes out the measure-laser dot the cloud's focus
    analysis needs. Direct capture remains the fallback when the daemon is
    unreachable.
    """
    import requests
    from gfhardware import Machine
    from gfhardware.leds import head_all_led_off, set_head_led_from_pulse
    from gfutilities.service.websocket import img_upload

    class ForgectrlMachine(Machine):

        @staticmethod
        def _snapshot(cam: str, lamp: int = None) -> bytes:
            url = '%s/cam/snapshot?cam=%s&res=full' % (
                get_cfg('FORGECTRL.URL') or 'http://127.0.0.1:8080', cam)
            if lamp is not None:
                url += '&lamp=%d' % lamp
            rsp = requests.get(url, timeout=45)
            rsp.raise_for_status()
            if not rsp.content.startswith(b'\xff\xd8'):
                raise ValueError('forgectrl returned a non-JPEG body')
            return rsp.content

        def _save_sent(self, img: bytes, msg: dict) -> None:
            if get_cfg('LOGGING.SAVE_SENT_IMAGES'):
                with open('%s/%s.jpeg' % (get_cfg('LOGGING.DIR'), msg['id']),
                          'wb') as f:
                    f.write(img)

        def _lid_image(self, msg: dict) -> None:
            logger.info('capturing Lid Image via forgectrl')
            try:
                img = self._snapshot('lid')
            except Exception:
                logger.exception('forgectrl snapshot failed; direct capture')
                return super()._lid_image(msg)
            logger.info('uploading Lid Image')
            img_upload(self._session, img, msg)
            self._save_sent(img, msg)

        def _head_image(self, msg: dict, settings: dict = None) -> None:
            logger.info('capturing Head Image via forgectrl')
            if settings and settings.get('HCil') is not None:
                set_head_led_from_pulse(settings['HCil'])
            try:
                img = self._snapshot('head', lamp=0)
            except Exception:
                logger.exception('forgectrl snapshot failed; direct capture')
                return super()._head_image(msg, settings)
            head_all_led_off()
            logger.info('uploading Head Image')
            img_upload(self._session, img, msg)
            self._save_sent(img, msg)

    return ForgectrlMachine()
