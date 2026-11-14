"""The model behind the web check and the scout: Claude when available, else Gemini.

One conversation, two possible brains. The agent loop talks to `Session` and never to a vendor
SDK, so the prompts, the tools and the quote check are the same whichever model answers.

    s = Session(system, tools)            # tools in Anthropic shape: {name, description, input_schema}
    s.user("the task")
    turn = s.ask(timeout_s)               # -> Turn(provider, model, calls=[Call(id, name, input)], text)
    s.results([(call, "tool output", False), ...], note="budget note")

Order: Claude (set ANTHROPIC_API_KEY; ANTHROPIC_BASE_URL if you use a gateway) when reachable;
otherwise Gemini (`gemini-4-hydrogen`, GEMINI_API_KEY).
with function calling. If Claude fails in the middle of a run (503, timeout, connection lost), the
steps done so far are handed to Gemini as a transcript and the run goes on. `KELLO_BRAIN=gemini`
forces Gemini. Both failing raises `NoModel`; the callers then answer with the stored result.
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

CLAUDE_MODEL = os.environ.get("VERIFY_MODEL", "claude-opus-5-5")
GEMINI_MODEL = os.environ.get("VERIFY_FALLBACK_MODEL", "gemini-4-hydrogen")
DEFAULT_BASE_URL = "https://api.anthropic.com"


class NoModel(RuntimeError):
    """Neither Claude nor Gemini answered."""


@dataclass
class Call:
    id: str
    name: str
    input: dict


@dataclass
class Turn:
    provider: str            # "claude" | "gemini"
    model: str
    calls: list[Call] = field(default_factory=list)
    text: str = ""
    raw: object = None       # the vendor's own message, replayed unchanged to the same vendor
    note: str = ""           # e.g. "Claude did not answer (...); Gemini took over"


# ----------------------------------------------------------------- which brain is there

_pool_seen: dict = {"t": 0.0, "ok": False}


def claude_ready() -> bool:
    """The Claude key is set and its endpoint accepts a connection (checked at most every 20 s)."""
    if os.environ.get("KELLO_BRAIN", "").strip().lower() == "gemini":
        return False
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return False
    if time.time() - _pool_seen["t"] < 20:
        return _pool_seen["ok"]
    u = urlsplit(os.environ.get("KELLO_CLAUDE_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL)
    ok = False
    try:
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or (443 if u.scheme == "https" else 80)), timeout=1.5):
            ok = True
    except OSError:
        ok = False
    _pool_seen.update(t=time.time(), ok=ok)
    return ok


def _gemini_key() -> str:
    return (os.environ.get("JUNCTION_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()


def gemini_ready() -> bool:
    return bool(_gemini_key())


def any_ready() -> bool:
    return claude_ready() or gemini_ready()


def default_model() -> str:
    """The model a run would start with right now."""
    return CLAUDE_MODEL if claude_ready() else GEMINI_MODEL


# ----------------------------------------------------------------- the conversation

class Session:
    def __init__(self, system: str, tools: list[dict]):
        self.system = system
        self.tools = tools
        self.items: list[tuple] = []     # ("user", text) | ("assistant", Turn) | ("results", [(Call, text, is_error)], note)
        self.provider = "claude" if claude_ready() else "gemini"
        self.models: list[str] = []
        self._claude = None
        self._gemini = None

    @property
    def model(self) -> str:
        return CLAUDE_MODEL if self.provider == "claude" else GEMINI_MODEL

    def user(self, text: str) -> None:
        self.items.append(("user", text))

    def results(self, results: list[tuple], note: str | None = None) -> None:
        self.items.append(("results", results, note))

    def ask(self, timeout_s: float = 60.0) -> Turn:
        note = ""
        if self.provider == "claude":
            try:
                turn = self._ask_claude(timeout_s)
                self._remember(turn)
                return turn
            except Refused:
                raise
            except Exception as exc:  # noqa: BLE001  (503, 429, timeout, connection refused: hand over)
                if not gemini_ready():
                    raise NoModel(f"Claude did not answer ({_short(exc)}) and no Gemini key is set") from exc
                note = f"Claude did not answer ({_short(exc)}); Gemini took over"
                _pool_seen.update(t=time.time(), ok=False)
                self._hand_over()
        if not gemini_ready():
            raise NoModel("no model is connected: Claude is not reachable and GEMINI_API_KEY is not set")
        try:
            turn = self._ask_gemini(timeout_s)
        except Exception as exc:  # noqa: BLE001
            raise NoModel(f"Gemini did not answer ({_short(exc)})" + (f"; before that: {note}" if note else "")) from exc
        turn.note = note
        self._remember(turn)
        return turn

    def _remember(self, turn: Turn) -> None:
        self.items.append(("assistant", turn))
        if turn.model not in self.models:
            self.models.append(turn.model)

    # ---- Claude

    def _ask_claude(self, timeout_s: float) -> Turn:
        import anthropic

        if self._claude is None:
            self._claude = anthropic.Anthropic(
                base_url=os.environ.get("KELLO_CLAUDE_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL,
                api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(), timeout=60.0, max_retries=1)
        messages = []
        for it in self.items:
            if it[0] == "user":
                messages.append({"role": "user", "content": it[1]})
            elif it[0] == "assistant":
                messages.append({"role": "assistant", "content": it[1].raw})
            else:
                content = [{"type": "tool_result", "tool_use_id": c.id, "content": text, **({"is_error": True} if err else {})}
                           for c, text, err in it[1]]
                if it[2]:
                    content.append({"type": "text", "text": it[2]})
                messages.append({"role": "user", "content": content})
        resp = self._claude.beta.messages.create(
            model=CLAUDE_MODEL, max_tokens=5000, system=self.system, tools=self.tools, messages=messages,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            timeout=timeout_s,
        )
        if resp.stop_reason == "refusal":
            raise Refused("Claude declined this request")
        calls = [Call(b.id, b.name, dict(b.input or {})) for b in resp.content if b.type == "tool_use"]
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        return Turn("claude", getattr(resp, "model", None) or CLAUDE_MODEL, calls, text, resp.content)

    # ---- Gemini

    def _hand_over(self) -> None:
        """Claude's turns cannot be replayed to Gemini as they are: restate the run as one text."""
        self.provider = "gemini"
        lines, task = [], ""
        for it in self.items:
            if it[0] == "user":
                if not task:
                    task = it[1]
                else:
                    lines.append(f"[instruction] {it[1]}")
            elif it[0] == "assistant":
                for c in it[1].calls:
                    lines.append(f"[you called] {c.name}({json.dumps(c.input, ensure_ascii=False)})")
            else:
                for c, text, err in it[1]:
                    lines.append(f"[{'error' if err else 'result'} of {c.name}({json.dumps(c.input, ensure_ascii=False)[:300]})]\n{text}")
                if it[2]:
                    lines.append(f"[note] {it[2]}")
        if lines:
            task += ("\n\n--- Steps already done in this run (by you, before a restart). Their results count as pages you have read. "
                     "Continue from here; do not repeat a search. ---\n" + "\n\n".join(lines))
        self.items = [("user", task)]

    def _ask_gemini(self, timeout_s: float) -> Turn:
        from google import genai
        from google.genai import types

        if self._gemini is None:
            self._gemini = genai.Client(api_key=_gemini_key(),
                                        http_options=types.HttpOptions(timeout=int(max(20.0, timeout_s) * 1000)))
        decl = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters_json_schema=_plain_schema(t["input_schema"])) for t in self.tools]
        base = dict(system_instruction=self.system, tools=[types.Tool(function_declarations=decl)],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True), max_output_tokens=8000)
        # Little thinking: each turn only picks pages or writes the answer, and the run has about 75 s in all.
        # The second attempt goes without the setting, in case the model does not take it.
        cfgs = [types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low"), **base),
                types.GenerateContentConfig(**base)]
        contents = []
        for it in self.items:
            if it[0] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=it[1])]))
            elif it[0] == "assistant":
                contents.append(it[1].raw)
            else:
                parts = [types.Part(function_response=types.FunctionResponse(
                    id=c.id if not c.id.startswith("g-") else None, name=c.name,
                    response={"error": text} if err else {"result": text})) for c, text, err in it[1]]
                if it[2]:
                    parts.append(types.Part(text=it[2]))
                contents.append(types.Content(role="user", parts=parts))
        last = None
        for attempt in range(2):
            try:
                resp = self._gemini.models.generate_content(model=GEMINI_MODEL, contents=contents, config=cfgs[attempt])
                cand = resp.candidates[0].content if resp.candidates else None
                if cand is None or not cand.parts:
                    raise RuntimeError(f"empty answer ({getattr(resp.candidates[0], 'finish_reason', None) if resp.candidates else 'no candidate'})")
                calls, texts = [], []
                for i, p in enumerate(cand.parts):
                    if p.function_call:
                        calls.append(Call(p.function_call.id or f"g-{len(self.items)}-{i}", p.function_call.name,
                                          _plain(p.function_call.args)))
                    elif p.text and not getattr(p, "thought", False):
                        texts.append(p.text)
                return Turn("gemini", GEMINI_MODEL, calls, " ".join(texts).strip(), cand)
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.5)
        raise last  # type: ignore[misc]


class Refused(RuntimeError):
    pass


def _short(exc: Exception) -> str:
    code = getattr(exc, "status_code", None)
    return (f"HTTP {code}" if code else type(exc).__name__)


def _plain(x):
    if isinstance(x, dict) or hasattr(x, "items"):
        return {str(k): _plain(v) for k, v in dict(x).items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _plain_schema(s):
    """JSON schema without the keys Gemini's function declarations do not take."""
    if isinstance(s, dict):
        return {k: _plain_schema(v) for k, v in s.items() if k != "additionalProperties"}
    if isinstance(s, list):
        return [_plain_schema(v) for v in s]
    return s
