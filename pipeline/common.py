"""Shared helpers for the Kello data pipeline.

Every download is saved under data/raw/<source>/ and registered in the source
registry with the exact URL / API call and a retrieval timestamp. Downloaded
content is only ever parsed as data (json / csv), never executed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
PARTS = RAW / "_parts"

UA = "kello-data-pipeline/0.1"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")

USE_CACHE = os.environ.get("KELLO_CACHE") == "1"

AREA_IDS = [f"{i:02d}" for i in range(1, 22)] + ["90", "91"]
HUS_AREAS = ["01", "02", "03", "04", "90"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_areas() -> list[dict]:
    return json.loads((PROC / "areas.json").read_text())


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:120]


class FetchError(RuntimeError):
    pass


def fetch(url: str, source_dir: str, name: str | None = None, *, post_json=None,
          headers: dict | None = None, timeout: int = 120, retries: int = 3) -> tuple[bytes, str]:
    """GET (or POST json) a URL, save the body under data/raw/<source_dir>/ and
    return (content, retrieved_at). With KELLO_CACHE=1 an existing raw file is reused."""
    d = RAW / source_dir
    d.mkdir(parents=True, exist_ok=True)
    if name is None:
        h = hashlib.sha1((url + json.dumps(post_json, sort_keys=True)).encode()).hexdigest()[:10]
        name = _slug(url.split("//", 1)[-1])[-80:] + "_" + h
    path = d / name
    meta = d / (name + ".meta.json")
    if USE_CACHE and path.exists() and meta.exists():
        return path.read_bytes(), json.loads(meta.read_text())["retrieved_at"]
    hdr = {"User-Agent": UA, "Accept": "*/*"}
    hdr.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            if post_json is not None:
                r = requests.post(url, json=post_json, headers=hdr, timeout=timeout)
            else:
                r = requests.get(url, headers=hdr, timeout=timeout)
            if r.status_code == 200:
                ts = now_iso()
                path.write_bytes(r.content)
                meta.write_text(json.dumps({"url": url, "post_json": post_json, "retrieved_at": ts,
                                            "status": 200, "bytes": len(r.content)}, ensure_ascii=False))
                return r.content, ts
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404):
                break
        except requests.RequestException as e:  # network error: retry
            last = repr(e)
        time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{url} -> {last}")


class Out:
    """Collects indicator rows, sources and catalog entries for one pipeline part."""

    def __init__(self, part: str):
        self.part = part
        self.rows: list[dict] = []
        self.sources: dict[str, dict] = {}
        self.catalog: dict[str, dict] = {}
        self.extra: dict[str, object] = {}
        self.problems: list[str] = []

    def source(self, sid: str, *, title: str, publisher: str, url: str, api_call: str,
               retrieved_at: str | None, licence: str, notes: str = "", verified: bool = True):
        self.sources[sid] = {"title": title, "publisher": publisher, "url": url, "api_call": api_call,
                             "retrieved_at": retrieved_at, "licence": licence, "notes": notes,
                             "verified": verified}

    def define(self, key: str, *, label_en: str, label_fi: str, unit: str, definition_en: str,
               direction: str, step: str | None):
        """direction: higher_is_worse | higher_is_better | context. step: pathway step id or None."""
        assert direction in ("higher_is_worse", "higher_is_better", "context"), direction
        assert step in (None, "patient", "primary", "referral", "diagnosis", "treatment", "outcome"), step
        self.catalog[key] = {"label_en": label_en, "label_fi": label_fi, "unit": unit,
                             "definition_en": definition_en, "direction": direction, "pathway_step": step}

    def add(self, area_id: str, indicator: str, value, period, source_id: str, *,
            note: str | None = None, sex: str | None = None):
        if value is None:
            return
        c = self.catalog[indicator]
        assert source_id in self.sources, source_id
        assert area_id in AREA_IDS or area_id == "FI", area_id
        row = {"area_id": area_id, "indicator": indicator, "label_en": c["label_en"],
               "label_fi": c["label_fi"], "value": value, "unit": c["unit"], "period": str(period),
               "source_id": source_id, "kind": "measured"}
        if sex:
            row["sex"] = sex
        if note:
            row["note"] = note
        self.rows.append(row)

    def save(self):
        PARTS.mkdir(parents=True, exist_ok=True)
        (PARTS / f"{self.part}.json").write_text(json.dumps(
            {"rows": self.rows, "sources": self.sources, "catalog": self.catalog,
             "extra": self.extra, "problems": self.problems}, ensure_ascii=False))


def num(x):
    """Parse a number that may be a string, '..', '', None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return x
    s = str(x).strip().replace(",", ".")
    if s in ("", ".", "..", "...", "-"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() and "." not in s else f


def jsonstat2_records(js: dict) -> list[dict]:
    """Flatten a json-stat2 dataset (PxWeb) into [{dim_code: category_code, ..., 'value': v}]."""
    ids = js["id"]
    sizes = js["size"]
    cats = []
    for d in ids:
        idx = js["dimension"][d]["category"]["index"]
        if isinstance(idx, dict):
            codes = sorted(idx, key=idx.get)
        else:
            codes = list(idx)
        cats.append(codes)
    out = []
    values = js["value"]
    n = len(values)
    for flat in range(n):
        rem = flat
        rec = {}
        for d, size, codes in zip(reversed(ids), reversed(sizes), reversed(cats)):
            rec[d] = codes[rem % size]
            rem //= size
        rec["value"] = values[flat]
        out.append(rec)
    return out


def thl_records(js: dict) -> list[dict]:
    """Flatten a THL pivot json-stat 1.x cube into [{dim: sid, dim+'_label': label, 'value': v}]."""
    ds = js["dataset"]
    ids = ds["dimension"]["id"]
    sizes = ds["dimension"]["size"]
    cats, labels = [], []
    for d in ids:
        c = ds["dimension"][d]["category"]
        codes = sorted(c["index"], key=c["index"].get)
        cats.append(codes)
        labels.append(c["label"])
    out = []
    for k, v in ds["value"].items():
        rem = int(k)
        rec = {}
        for d, size, codes, lab in zip(reversed(ids), reversed(sizes), reversed(cats), reversed(labels)):
            code = codes[rem % size]
            rec[d] = code
            rec[d + "_label"] = lab[code]
            rem //= size
        rec["value"] = num(v)
        out.append(rec)
    return out


def thl_dimensions(text: str) -> dict[str, list[dict]]:
    """Parse a THL '.dimensions.json' (JSONP wrapper) into {dim_id: [flat nodes]}."""
    body = text[text.index("(") + 1:text.rindex(")")]
    dims = json.loads(body)
    out = {}

    def walk(n, depth, acc, parent):
        acc.append({"sid": n.get("sid"), "label": n.get("label"), "stage": n.get("stage"),
                    "code": n.get("code"), "depth": depth, "parent": parent})
        for ch in n.get("children", []):
            walk(ch, depth + 1, acc, n.get("sid"))

    for d in dims:
        acc: list[dict] = []
        for ch in d["children"]:
            walk(ch, 0, acc, None)
        out[d["id"]] = acc
    return out
