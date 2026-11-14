#!/usr/bin/env python
"""Drive the local Claude Science app (claude-science 0.1.72) from a script.

Claude Science has no public API. This talks to the same local HTTP API the web app uses
(http://127.0.0.1:<port>/api/...), authenticated with a session cookie minted from a
single-use `claude-science url` nonce. Route names were read from the web bundle
(/assets/index-*.js, the `"frames.createEmpty": e => Lt("/frames", ...)` table).

    python science/drive.py status
    python science/drive.py signin-url             # prints a claude.ai URL (valid 10 min)
    python science/drive.py signin-code '<code>'   # code shown after Authorize
    python science/drive.py --project kello --prompt-file p.md --out science/out/<name>/
    python science/drive.py collect --frame <root_frame_id> --out science/out/<name>/

Permission cards are answered from a fixed allowlist (see POLICY below); anything else is
denied and logged to <out>/approvals.jsonl. The sandbox and approvals are never bypassed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SESSION_DIR = HERE / ".session"          # local-app cookie only; never the Claude account token
WORK_ROOT = HERE / "work"                # the only host folders a card may be granted
CLI = os.environ.get("CLAUDE_SCIENCE_BIN", str(Path.home() / ".local/bin/claude-science"))

# ---- POLICY: what a permission card may be approved for ---------------------------------
ALLOWED_HOSTS = {
    "canapi.iarc.who.int", "nordcan.iarc.who.int", "sotkanet.fi", "pxdata.stat.fi", "sampo.thl.fi",
    "pypi.org", "files.pythonhosted.org",
    "conda.anaconda.org", "repo.anaconda.com", "anaconda.org",
    "cran.r-project.org", "cloud.r-project.org",
}
ALLOWED_HOST_SUFFIXES = (".pypi.org", ".anaconda.org", ".conda.io")
LOCAL_EXEC_TOOLS = {"python", "r", "bash", "manage_environments", "install_packages"}
TERMINAL = {"completed", "failed", "cancelled", "error", "aborted", "stopped", "interrupted", "timed_out"}


def host_allowed(target: str) -> bool:
    h = re.sub(r"^[a-z]+://", "", (target or "").strip().lower()).split("/")[0].split(":")[0]
    return bool(h) and "*" not in h and (h in ALLOWED_HOSTS or h.endswith(ALLOWED_HOST_SUFFIXES))


def decide(req: dict) -> tuple[bool, dict, str]:
    """Return (approve, extra response fields, reason) for one pending input request."""
    kind = req.get("kind")
    if kind == "network":
        ok = host_allowed(req.get("target", ""))
        # the app only honours a domain approval given at "always" scope (revocable in Settings)
        return ok, {"scope": "always"} if ok else {}, f"network {req.get('target')!r} {'in' if ok else 'NOT in'} allowlist"
    if kind == "local_exec":
        tool = req.get("tool")
        ok = tool in LOCAL_EXEC_TOOLS and not req.get("shared_env")
        return ok, {"scope": "conversation"} if ok else {}, f"local_exec tool={tool!r}"
    if kind == "host":
        try:
            target = Path(req.get("target", "")).resolve()
            ok = target == WORK_ROOT or WORK_ROOT in target.parents
        except Exception:
            ok = False
        return ok, {"mode": req.get("requested_mode") or "ro", "scope": "always"} if ok else {}, f"host folder {req.get('target')!r}"
    if kind == "usage_checkpoint":
        # "Keep going" inside the plan's own limit is fine; continuing on paid usage credits is not ours to approve.
        ok = req.get("boundary") != "overage"
        return ok, {}, f"usage checkpoint claim={req.get('claim')!r} boundary={req.get('boundary')!r}"
    # ask / host_delete / artifact_delete / mcp_tool / customize_mutation / remote_exec /
    # remote_read / credential_access / contact_email / usage_checkpoint / anything new
    return False, {}, f"kind {kind!r} is not in the allowlist"


# ---- local app session ------------------------------------------------------------------
def cli(*args: str) -> str:
    return subprocess.run([CLI, *args], capture_output=True, text=True, timeout=60).stdout


def daemon_status() -> dict:
    try:
        return json.loads(cli("status"))
    except Exception:
        return {"running": False}


class App:
    def __init__(self) -> None:
        st = daemon_status()
        if not st.get("running"):
            sys.exit("claude-science is not running. Start it: "
                     "claude-science serve --no-browser --detached --port 8780")
        self.base = f"http://localhost:{st['port']}"
        self.version = st.get("version")
        self.http = httpx.Client(base_url=self.base, timeout=120, follow_redirects=False)
        self._load_cookies()
        if self.http.get("/api/me").status_code != 200:
            self._mint_session()

    def _load_cookies(self) -> None:
        f = SESSION_DIR / "cookies.json"
        if f.exists():
            for k, v in json.loads(f.read_text()).items():
                self.http.cookies.set(k, v, domain="localhost.local", path="/")   # how httpx stores localhost

    def _save_cookies(self) -> None:
        SESSION_DIR.mkdir(exist_ok=True)
        (SESSION_DIR / ".gitignore").write_text("*\n")
        f = SESSION_DIR / "cookies.json"
        f.write_text(json.dumps({c.name: c.value for c in self.http.cookies.jar}))  # last value wins
        f.chmod(0o600)

    def _mint_session(self) -> None:
        """`claude-science url` -> single-use nonce -> operon_auth + operon_csrf cookies."""
        pkce = self._cookie("operon_pkce")                    # sign-in state must survive a new session
        self.http.cookies.clear()
        if pkce:
            self.http.cookies.set("operon_pkce", pkce, domain="localhost.local", path="/")
        url = cli("url").strip().splitlines()[0]
        nonce = url.split("nonce=")[1]
        self.http.get(url)
        r = self.http.post("/api/auth/nonce", json={"nonce": nonce}, headers={"Origin": self.base})
        if self.http.get("/api/me").status_code != 200:
            sys.exit(f"could not open a local session (nonce exchange -> {r.status_code})")
        self._save_cookies()

    def call(self, method: str, path: str, **kw):
        headers = dict(kw.pop("headers", {}))
        retried = kw.pop("_retried", False)
        if method != "GET":
            headers["x-operon-csrf"] = self._cookie("operon_csrf")
            headers["Origin"] = self.base
        r = self.http.request(method, "/api" + path, headers=headers, **kw)
        if not retried and (r.status_code == 401 or (r.status_code == 403 and "csrf" in r.text)):
            self._mint_session()                          # new nonce -> fresh auth + CSRF cookies
            headers.pop("x-operon-csrf", None)
            return self.call(method, path, headers=headers, _retried=True, **kw)
        return r

    def _cookie(self, name: str) -> str:
        vals = [c.value for c in self.http.cookies.jar if c.name == name]
        return vals[-1] if vals else ""

    def get(self, path: str, **kw):
        r = self.call("GET", path, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict | None = None):
        r = self.call("POST", path, json=body or {})
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code} {r.text[:400]}")
        return r.json() if r.content else {}

    def auth(self) -> dict:
        return self.get("/auth/status")


# ---- commands ---------------------------------------------------------------------------
def cmd_status(app: App, _a) -> int:
    a = app.auth()
    me = app.get("/me")
    print(json.dumps({"version": app.version, "base": app.base, "signed_in": a.get("authenticated"),
                      "email": me.get("email"), "subscription": a.get("subscription_type"),
                      "skip_approvals": a.get("dangerously_skip_approvals"),
                      "sandbox_active": daemon_status().get("daemon", {}).get("sandbox_active")}, indent=2))
    return 0 if a.get("authenticated") else 2


def cmd_signin_url(app: App, _a) -> int:
    """Paste-code sign-in: the URL can be opened in ANY browser signed in to claude.ai."""
    d = app.get("/auth/login", params={"provider": "claude_ai", "redirect": "/", "mode": "paste"})
    app._save_cookies()                                   # keeps operon_pkce (10 min)
    (SESSION_DIR / "signin_state.json").write_text(json.dumps({"state": d["state"], "at": time.time()}))
    print(d["authorize_url"])
    print("\nOpen it within 10 minutes, click Authorize, copy the code it shows, then run:\n"
          "  python science/drive.py signin-code '<code>'", file=sys.stderr)
    return 0


def cmd_signin_code(app: App, a) -> int:
    st = json.loads((SESSION_DIR / "signin_state.json").read_text())
    r = app.post("/auth/exchange", {"provider": "claude_ai", "code": a.code.strip(),
                                    "state": st["state"], "redirect": "/"})
    (SESSION_DIR / "signin_state.json").unlink(missing_ok=True)
    if r.get("restart_pending"):
        print("daemon is restarting to apply the sign-in ...", file=sys.stderr)
        time.sleep(15)
        app = App()
    return cmd_status(app, a)


def ensure_project(app: App, name: str) -> str:
    for p in app.get("/projects", params={"limit": 200})["projects"]:
        if p["name"] == name or p["project_id"] == name:
            return p["project_id"]
    p = app.post("/projects", {"name": name, "description": "Kello: where Finnish lung cancer patients lose time"})
    return p.get("project_id") or p["project"]["project_id"]


def walk(frame: dict):
    yield frame
    for c in frame.get("children") or []:
        if isinstance(c, dict):
            yield from walk(c)


def cmd_run(app: App, a) -> int:
    if not app.auth().get("authenticated"):
        print("Not signed in to a Claude account. Run `python science/drive.py signin-url`.", file=sys.stderr)
        return 2
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    prompt = Path(a.prompt_file).read_text()
    (out / "prompt.md").write_text(prompt)
    pid = ensure_project(app, a.project)
    if a.frame:                                           # pick up a session that is already running
        root = a.frame
    else:
        body = {"input_data": {"request": prompt}}
        if a.model:
            body["model"] = a.model
        res = app.post(f"/projects/{pid}/request", body)
        root = res.get("root_frame_id") or res.get("frame_id") or res.get("id")
    if not root:
        raise RuntimeError("no frame id in response")
    print(f"session {root} in project {pid}: {app.base}/projects/{pid}/frames/{root}", file=sys.stderr)
    (out / "session.json").write_text(json.dumps({"project_id": pid, "root_frame_id": root, "app": app.base,
                                                  "claude_science_version": app.version}, indent=2))
    log = (out / "approvals.jsonl").open("a")
    answered: set[str] = set()
    deadline = time.time() + a.timeout
    status, last = "processing", ""
    while time.time() < deadline:
        frame = app.get(f"/frames/{root}", params={"include_children": "true"})
        status = frame.get("status")
        if status != last:
            print(f"[{time.strftime('%H:%M:%S')}] {status}", file=sys.stderr)
            last = status
        for f in walk(frame):
            if f.get("status") == "awaiting_plan_approval" and f["id"] not in answered:
                answered.add(f["id"])
                log.write(json.dumps({"frame": f["id"], "kind": "plan", "approved": True}) + "\n")
                app.post(f"/frames/{f['id']}/approve-plan", {})
            for req in (f.get("output_data") or {}).get("pending_input_requests") or []:
                key = f"{req.get('requestId')}:{req.get('tool_id')}"
                if key in answered:
                    continue
                answered.add(key)
                ok, extra, why = decide(req)
                resp = {"requestId": req.get("requestId"), "approved": ok,
                        "action": ("answer" if ok else "cancel") if req.get("kind") == "ask"
                        else ("allow" if ok else "deny"), **extra}
                if req.get("tool_id"):
                    resp["tool_id"] = req["tool_id"]
                if not ok and req.get("kind") == "usage_checkpoint":
                    resp["held_by_user"] = True
                log.write(json.dumps({"at": time.strftime("%FT%T"), "frame": f["id"], "request": req,
                                      "approved": ok, "why": why}, default=str) + "\n")
                log.flush()
                print(f"  card {req.get('kind')}: {'ALLOW' if ok else 'DENY'} ({why})", file=sys.stderr)
                try:
                    app.post(f"/frames/{f['id']}/resolve-input", {"responses": [resp]})
                except RuntimeError as e:                 # one bad card must not end the run
                    print(f"  card answer rejected: {e}", file=sys.stderr)
        if status in TERMINAL:
            break
        time.sleep(3)
    else:
        print("timed out; leaving the session running", file=sys.stderr)
    collect(app, root, out)
    return 0 if status == "completed" else 1


EXT = {"python": "py", "r": "R", "bash": "sh"}


def collect(app: App, root: str, out: Path) -> None:
    """Copy artifacts plus their provenance (code, environment, execution log) into out/."""
    out.mkdir(parents=True, exist_ok=True)
    for d in ("artifacts", "provenance", "code"):
        (out / d).mkdir(exist_ok=True)
    arts = app.get(f"/frames/{root}/artifacts")
    manifest = []
    for art in arts:
        name = art["filename"].replace("/", "_")
        r = app.call("GET", f"/artifacts/versions/{art['version_id']}")
        r.raise_for_status()
        (out / "artifacts" / name).write_bytes(r.content)
        lin = app.call("GET", f"/artifacts/{art['id']}/lineage")
        lineage = lin.json() if lin.status_code == 200 else {}
        (out / "provenance" / f"{name}.lineage.json").write_text(json.dumps(lineage, indent=1))
        code = lineage.get("code")
        if code:
            (out / "code" / f"{name}.{EXT.get(lineage.get('language') or '', 'txt')}").write_text(
                code if isinstance(code, str) else json.dumps(code, indent=1))
        manifest.append({"filename": name, "artifact_id": art["id"], "version_id": art["version_id"],
                         "version_number": art.get("version_number"), "content_type": art.get("content_type"),
                         "sha256": hashlib.sha256(r.content).hexdigest(), "app_checksum": art.get("checksum"),
                         "language": lineage.get("language"), "has_code": bool(code),
                         "has_environment": bool(lineage.get("environment_snapshot")),
                         "created_at": art.get("created_at")})
    for path, fn in ((f"/frames/{root}/export", "session_export.json"),
                     (f"/frames/{root}/execution-log?limit=500", "execution_log.json")):
        r = app.call("GET", path)
        if r.status_code == 200:
            (out / fn).write_bytes(r.content)
    exp = out / "session_export.json"
    if exp.exists():                                       # last assistant text = the answer
        frames = json.loads(exp.read_text()).get("frames") or []
        msgs = (frames[0].get("messages") or []) if frames else []
        texts = ["\n".join(b.get("text", "") for b in m["content"] if isinstance(b, dict) and b.get("type") == "text")
                 if isinstance(m.get("content"), list) else str(m.get("content"))
                 for m in msgs if m.get("role") == "assistant"]
        texts = [t for t in texts if t.strip()]
        if texts:
            ans = texts[-1]
            for m in manifest:                             # {{artifact:<id>}} -> the file we just saved
                for key in (m["version_id"], m["artifact_id"]):
                    ans = ans.replace("{{artifact:%s}}" % key, "artifacts/" + m["filename"])
            (out / "answer.md").write_text(ans)
    (out / "manifest.json").write_text(json.dumps({"root_frame_id": root, "collected_at": time.strftime("%FT%T%z"),
                                                   "claude_science_version": app.version,
                                                   "artifacts": manifest}, indent=1))
    print(f"collected {len(manifest)} artifacts into {out}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "status", "signin-url", "signin-code", "collect"])
    ap.add_argument("code", nargs="?", help="signin-code: the code claude.ai showed")
    ap.add_argument("--project", default="kello")
    ap.add_argument("--prompt-file")
    ap.add_argument("--out")
    ap.add_argument("--frame", help="collect, or run: root frame id of an existing session")
    ap.add_argument("--model", help="e.g. claude-opus-5-5 (default: the app's selection)")
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args()
    app = App()
    if a.command == "status":
        return cmd_status(app, a)
    if a.command == "signin-url":
        return cmd_signin_url(app, a)
    if a.command == "signin-code":
        if not a.code:
            ap.error("signin-code needs the code")
        return cmd_signin_code(app, a)
    if a.command == "collect":
        if not (a.frame and a.out):
            ap.error("collect needs --frame and --out")
        collect(app, a.frame, Path(a.out).resolve())
        return 0
    if not (a.prompt_file and a.out):
        ap.error("run needs --prompt-file and --out")
    return cmd_run(app, a)


if __name__ == "__main__":
    sys.exit(main())
