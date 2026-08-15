"""logs.* - unified logging: the log tree, tail, and the sanitized export."""
import gzip
import io
import tarfile

from ..catalog import test

_LOG_COVERS = [("forgectrl", "src/logs.*"), ("forgectrl", "src/fflog.*"), ("forgectrl", "src/sanitize.*"),
               ("forgectrl", "src/main.c")]


@test("logs.tree-tail-export", title="Log tree, tail, and sanitized export", subsystem="logs",
      kind="auto", est_min=1,
      covers=_LOG_COVERS, requires=["forgectrl.auth"],
      description="/logs lists the loggers with their levels and files, /logs/tail returns the "
                  "forgectrl logger's tail, and POST /logs/export streams a sanitized tar.gz "
                  "bundle that contains no panel token.")
def tree_tail_export(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    st, body = fc.get("/logs")
    ctx.log("GET /logs -> %s", st)
    ctx.check(st == 200 and isinstance(body, dict), "GET /logs -> %s", st)
    loggers = body.get("loggers") or []
    names = [l.get("name") for l in loggers] if isinstance(loggers, list) else list(loggers)
    ev["loggers"] = names
    ctx.log("loggers: %s", names)
    ctx.check("forgectrl" in names, "/logs lacks the forgectrl logger: %s", names)

    st, tail = fc.get("/logs/tail", params={"name": "forgectrl", "lines": "20"})
    ctx.log("GET /logs/tail?name=forgectrl -> %s", st)
    ctx.check(st == 200, "GET /logs/tail -> %s %s", st, tail if isinstance(tail, dict) else "")
    st, tail = fc.get("/logs/tail", params={"name": "no-such-logger"})
    ctx.check(st == 404, "unknown logger -> %s, expected 404", st)

    st, data = fc.post("/logs/export", raw=True)
    ctx.log("POST /logs/export -> %s (%d bytes)", st, len(data) if data else 0)
    ctx.check(st == 200, "POST /logs/export -> %s", st)
    ev["export_bytes"] = len(data)
    try:
        raw = gzip.decompress(data)
        tf = tarfile.open(fileobj=io.BytesIO(raw))
        members = tf.getnames()
    except (OSError, tarfile.TarError, EOFError) as e:
        ctx.fail("export is not a readable tar.gz: %s", e)
    ev["members"] = len(members)
    ctx.log("bundle: %d members, e.g. %s", len(members), members[:5])
    ctx.check(members, "empty bundle")
    ctx.check(any(m.endswith("README.txt") for m in members), "sanitized bundle lacks README.txt")
    token = fc.token
    if token:
        leaked = []
        for m in tf.getmembers():
            if m.isfile():
                content = tf.extractfile(m).read()
                if token.encode() in content:
                    leaked.append(m.name)
        ev["token_leaks"] = leaked
        ctx.check(not leaked, "the sanitized bundle contains the panel token: %s", leaked)
