"""The append-only result log (JSONL) and the export helpers.

One JSON object per line under the data directory (default
/data/forgetest/results.jsonl, override FORGETEST_DATA). Records:

  campaign    {"id","manifest_sha","catalog_hash","image"}   a campaign opened
  result      {"campaign","test","result","fingerprint","manifest_sha",
               "image","duration_s","evidence","answers","log","message"}
  invalidate  {"reason"}       manual invalidate-all (full campaign required)
  reset       {"reason"}       explicit campaign reset
  export      {"artifact_sha256","authorized","campaign"}

Every record carries "t" (type) and "ts" (UTC, ISO 8601, seconds).
The file is only ever appended; a corrupt line is skipped, counted, and
reported, never repaired in place.
"""
import json
import os
import threading
import time

DEFAULT_DATA_DIR = "/data/forgetest"


def now_ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def data_dir():
    return os.environ.get("FORGETEST_DATA") or DEFAULT_DATA_DIR


class Log:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "results.jsonl")
        self._lock = threading.Lock()
        self.corrupt = 0

    def append(self, rec):
        rec = dict(rec)
        rec.setdefault("ts", now_ts())
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        return rec

    def read(self):
        recs = []
        self.corrupt = 0
        if not os.path.exists(self.path):
            return recs
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                self.corrupt += 1
                continue
            if isinstance(rec, dict) and "t" in rec:
                recs.append(rec)
            else:
                self.corrupt += 1
        return recs

    def raw(self):
        if not os.path.exists(self.path):
            return ""
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as f:
                return f.read()
