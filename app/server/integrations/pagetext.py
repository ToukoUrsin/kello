"""Turn a scraped page into text an agent can quote from.

    extract_main(html, url)   -> {title, text}   main content only: no nav, cookie banner, footer
    pdf_text(data)            -> {title, text, pages}   PyMuPDF, with [page N] markers
    jats_text(xml)            -> {title, text}   Europe PMC full text
    best_passages(text, terms, budget) -> the passages that match the question, in page order

Headings (`## `), list items (`- `), table rows (`a | b | c`) and numbers are kept.
"""

from __future__ import annotations

import math
import re

# Dropped whatever they hold (when small): banners, dialogs, forms around the content.
_HARD = re.compile(
    r"cookie|consent|gdpr|cmp-|onetrust|cybot|skip-?link|skiplink|skip-to|visually-hidden|sr-only|newsletter|"
    r"modal|popup|search-form|searchform|language-switch|lang-switch|feedback|chat-|chatbot|share-|social-|some-share",
    re.I,
)
# Dropped only when most of their text is links: a class such as "layout--with-sidebar" or
# "content-menu" often wraps the article itself (Tyks waiting-time tables sit in one).
_SOFT = re.compile(
    r"breadcrumb|murupolku|navbar|nav-|-nav\b|\bnav\b|menu|sidebar|site-header|site-footer|page-footer|footer|share|"
    r"social|related|toolbar|print-|pager|pagination|tags|toc\b",
    re.I,
)
_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "template", "nav", "footer", "form",
              "button", "select", "input", "dialog", "canvas", "video", "audio", "picture", "source", "link", "meta")
_DROP_ROLES = {"navigation", "banner", "contentinfo", "search", "dialog", "alertdialog", "menu", "menubar",
               "complementary", "toolbar"}
_HEAD = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "#### ", "h6": "#### "}
_BLOCK = {"p", "div", "section", "article", "main", "ul", "ol", "dl", "dt", "dd", "blockquote", "figure",
          "figcaption", "details", "summary", "header", "address", "pre", "tr", "hr", "body", "center", "fieldset"}
_GENERIC_TITLE = re.compile(r"^\s*(skip to|siirry|hyppää|ota yhteyttä|etusivu|home|menu|valikko|\*|404\b)", re.I)


def _ws(s: str) -> str:
    s = (s or "").replace("\u00ad", "").replace("\u200b", "").replace("\ufeff", "").replace("\u00a0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", s).strip()


def _inline(node) -> str:
    from bs4 import NavigableString, Tag

    parts = []
    for c in node.children:
        if isinstance(c, NavigableString):
            parts.append(str(c))
        elif isinstance(c, Tag):
            if c.name == "br":
                parts.append(" ")
            elif c.name in ("sup", "sub"):
                parts.append(c.get_text())
            else:
                parts.append(_inline(c))
    return "".join(parts)


def _table(t) -> str:
    rows = []
    cap = t.find("caption")
    if cap:
        rows.append("Table: " + _ws(cap.get_text(" ")))
    for tr in t.find_all("tr"):
        cells = [_ws(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows[:400])


def _render(node, out: list[str], buf: list[str]) -> None:
    from bs4 import NavigableString, Tag

    def flush():
        s = _ws("".join(buf))
        buf.clear()
        if s:
            out.append(s)

    for c in node.children:
        if isinstance(c, NavigableString):
            if type(c).__name__ in ("Comment", "Doctype", "CData", "ProcessingInstruction", "Declaration"):
                continue
            buf.append(str(c))
            continue
        if not isinstance(c, Tag):
            continue
        name = c.name
        if name in _HEAD:
            flush()
            s = _ws(c.get_text(" "))
            if s:
                out.append(_HEAD[name] + s)
        elif name == "table":
            flush()
            s = _table(c)
            if s:
                out.append(s)
        elif name == "li":
            flush()
            sub_out: list[str] = []
            sub_buf: list[str] = []
            _render(c, sub_out, sub_buf)
            tail = _ws("".join(sub_buf))
            if tail:
                sub_out.append(tail)
            if sub_out:
                out.append("- " + sub_out[0])
                out.extend(sub_out[1:])
        elif name == "br":
            buf.append(" ")
        elif name in _BLOCK:
            flush()
            _render(c, out, buf)
            flush()
        else:
            _render(c, out, buf)


def _link_share(el, n: int) -> float:
    if not n:
        return 1.0
    return sum(len(a.get_text(" ", strip=True)) for a in el.find_all("a")) / n


def _is_boiler(el, total: int) -> bool:
    attrs = el.attrs or {}
    if attrs.get("role") in _DROP_ROLES:
        return True
    n = len(el.get_text(" ", strip=True))
    if attrs.get("aria-hidden") == "true" or "hidden" in attrs:
        # decorative icons are hidden, but so are collapsed accordion and tab panels, which hold
        # the real content on hospital pages (HUS care pathway): keep hidden blocks that carry text
        return n < 40
    if el.name == "aside":
        return _link_share(el, n) >= 0.5
    ident = " ".join([attrs.get("id") or ""] + list(attrs.get("class") or []))
    if not ident:
        return False
    if _HARD.search(ident):
        # a wrapper that holds most of the page is not boilerplate, whatever its class says
        return n < max(1500, total * 0.25)
    if _SOFT.search(ident):
        return _link_share(el, n) >= 0.5
    return False


def extract_main(html: str, url: str = "") -> dict:
    """Main content of an HTML page as plain text with light structure, plus its real title."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "lxml")
    title = ""
    for sel, attr in (("meta[property='og:title']", "content"), ("meta[name='citation_title']", "content"),
                      ("meta[name='twitter:title']", "content")):
        m = soup.select_one(sel)
        if m and _ws(m.get(attr, "")):
            title = _ws(m.get(attr))
            break
    if not title and soup.title:
        title = _ws(soup.title.get_text(" "))
    desc = ""
    m = soup.select_one("meta[name='description'], meta[property='og:description']")
    if m:
        desc = _ws(m.get("content", ""))
    published = ""
    for sel in ("meta[property='article:published_time']", "meta[name='citation_publication_date']",
                "meta[name='dcterms.issued']", "meta[name='DC.date']", "meta[name='date']",
                "meta[property='article:modified_time']"):
        m = soup.select_one(sel)
        if m and _ws(m.get("content", "")):
            published = _ws(m.get("content"))[:25]
            break
    if not published:
        t = soup.find("time")
        if t is not None:
            published = _ws(t.get("datetime") or t.get_text(" "))[:25]

    for t in soup.find_all(("script", "style", "noscript", "svg", "template")):
        t.decompose()
    links = _links(soup, url)
    body = soup.body or soup
    # Pick the main block BEFORE dropping navigation: some sites nest everything, <main> included,
    # inside an unclosed <header> or <nav>, and dropping those first would drop the page.
    whole = len(body.get_text(" ", strip=True))
    first, first_len = None, 0
    for sel in ("main", "[role=main]", "#main-content", "#main", "#content", "article"):
        for cand in body.select(sel)[:6]:
            n = len(cand.get_text(" ", strip=True))
            if n > first_len:
                first, first_len = cand, n
    if first is not None and first_len >= 200 and first is not body:
        body = first.extract()
    for t in body.find_all(_DROP_TAGS):
        t.decompose()
    total = len(body.get_text(" ", strip=True))
    # <header> holds the article headline when it sits inside main/article; the site header does not.
    for h in body.find_all("header"):
        if not h.find_parent(["main", "article"]):
            h.decompose()
    for el in list(body.find_all(True)):
        if el.parent is None or el.name in ("main", "article", "body", "html"):
            continue
        try:
            if _is_boiler(el, total):
                el.decompose()
        except Exception:
            continue

    best, best_len = body, 0
    for sel in ("main", "[role=main]", "article", "#main-content", "#main", "#content", ".main-content",
                ".content", ".article", ".post", ".entry-content"):
        for cand in body.select(sel)[:6]:
            n = len(cand.get_text(" ", strip=True))
            if n > best_len:
                best, best_len = cand, n
    remaining = len(body.get_text(" ", strip=True))
    root = best if best_len >= max(400, remaining * 0.35) else body

    out: list[str] = []
    buf: list[str] = []
    _render(root, out, buf)
    tail = _ws("".join(buf))
    if tail:
        out.append(tail)
    # drop exact repeats (menus rendered twice for mobile) and lone link words at the very top
    seen, blocks = set(), []
    for b in out:
        k = b.lower()
        if len(b) < 200 and k in seen:
            continue
        seen.add(k)
        blocks.append(b)
    text = "\n\n".join(blocks)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if not published:  # Finnish public sites print "Päivitetty 7.4.2026" at the foot of the page
        m = re.search(r"(?:Päivitetty|Julkaistu|Updated|Published)\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})", text)
        if m:
            published = m.group(1)
    h1 = next((b[2:] for b in blocks if b.startswith("# ")), "")
    if not title or _GENERIC_TITLE.search(title):
        title = h1 or title
    elif h1 and 8 <= len(h1) <= 200 and h1 != title:
        # some CMSs garble <title> ("keuhkopussn msotelioom"); the visible headline is the real one
        import difflib
        if 0.6 <= difflib.SequenceMatcher(None, h1.lower(), title.lower()[: len(h1) + 10]).ratio() < 1.0 and len(title) <= len(h1) + 3:
            title = h1
    if not title:
        title = next((b.lstrip("# -") for b in blocks if len(b) > 8), "")[:140]
    if desc and desc.lower() not in text.lower()[:3000]:
        text = desc + "\n\n" + text
    return {"title": title[:300], "text": text, "published": published, "links": links}


def _links(soup, url: str, limit: int = 400) -> list[dict]:
    """Every link of the page (menus included): the page an agent needs is often one click away
    from the hub page that the search engine returned."""
    from urllib.parse import urljoin

    out, seen = [], {(url or "").split("#")[0].rstrip("/")}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(url or "", href).split("#")[0]
        key = full.rstrip("/")
        if not full.startswith(("http://", "https://")) or key in seen:
            continue
        seen.add(key)
        text = _ws(a.get_text(" ", strip=True))[:120]
        out.append({"url": full, "text": text})
        if len(out) >= limit:
            break
    return out


def matching_links(links: list[dict], terms: list[str] | str, n: int = 8) -> list[dict]:
    """The links whose text or address shares the most stems with `terms` (best first, none if no overlap)."""
    want = set(stems(terms) if isinstance(terms, str) else terms)
    scored = []
    for i, l in enumerate(links or []):
        path = re.sub(r"[/_\-\.]+", " ", l["url"].split("//", 1)[-1])
        got = set(stems(l.get("text", "") + " " + path))
        hit = len(want & got)
        if hit:
            scored.append((-hit, i, l))
    return [l for _, _, l in sorted(scored)[:n]]


def pdf_text(data: bytes, max_pages: int = 400) -> dict:
    import pymupdf as fitz

    doc = fitz.open(stream=data, filetype="pdf")
    parts = []
    for i, page in enumerate(doc, start=1):
        if i > max_pages:
            break
        t = page.get_text("text") or ""
        t = re.sub(r"[ \t]+\n", "\n", t)
        t = re.sub(r"(?<![.:!?\n])\n(?=[a-zåäö(])", " ", t)  # join lines broken mid-sentence
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        if t:
            parts.append(f"[page {i}]\n{t}")
    meta = doc.metadata or {}
    title = _ws(meta.get("title") or "")
    title = re.sub(r"^(PowerPoint Presentation|PowerPoint-esitys|Microsoft Word -|Microsoft PowerPoint -)\s*", "", title, flags=re.I)
    if not title or len(title) < 6 or title.lower().endswith((".indd", ".docx", ".doc", ".pdf")):
        first = parts[0].split("\n", 1)[1] if parts else ""
        title = _ws(" ".join(first.split("\n")[:3]))[:160]
    created = meta.get("creationDate") or ""
    m = re.search(r"D:(\d{4})(\d{2})(\d{2})", created)
    return {"title": title, "text": "\n\n".join(parts), "pages": doc.page_count,
            "published": f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""}


def jats_text(xml: str) -> dict:
    """Europe PMC full-text XML (JATS) -> title + text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xml, "lxml-xml")
    title = _ws(soup.find("article-title").get_text(" ")) if soup.find("article-title") else ""
    out = []
    j = soup.find("journal-title")
    y = soup.find("pub-date")
    if j:
        out.append(_ws(j.get_text(" ")) + (" " + _ws(y.find("year").get_text()) if y and y.find("year") else ""))
    for ab in soup.find_all("abstract"):
        out.append("## Abstract")
        out.append(_ws(ab.get_text(" ")))
    body = soup.find("body")
    if body:
        for el in body.find_all(["title", "p", "table-wrap"]):
            if el.find_parent("table-wrap") and el.name != "table-wrap":
                continue
            if el.name == "title":
                out.append("## " + _ws(el.get_text(" ")))
            elif el.name == "table-wrap":
                rows = [_ws(x.get_text(" ")) for x in el.find_all(["label", "caption"])]
                for tr in el.find_all("tr"):
                    rows.append(" | ".join(_ws(c.get_text(" ")) for c in tr.find_all(["th", "td"])))
                out.append("\n".join(r for r in rows if r))
            else:
                out.append(_ws(el.get_text(" ")))
    year = _ws(y.find("year").get_text()) if y and y.find("year") else ""
    return {"title": title, "text": "\n\n".join(o for o in out if o), "published": year}


# ----------------------------------------------------------------- passage ranking

_WORD = re.compile(r"[a-zåäöéü0-9][a-zåäöéü0-9\-]{2,}", re.I)
_STOP = set("""ja on ei että tai sekä kuin myös ovat oli joka jotka tämä nämä sen niin mutta vain kun jos
the and for with that this from are was were has have its not does how what which into than them their is in of to by an
measure today much many this use used using does lead people among""".split())


def stems(text: str) -> list[str]:
    """Crude stems that survive Finnish inflection: lowercase, first 6 letters of longer words."""
    out = []
    for w in _WORD.findall((text or "").lower()):
        if w in _STOP:
            continue
        out.append(w[:6] if len(w) > 6 and not w[0].isdigit() else w)
    return out


def _split_passages(text: str, target: int = 900) -> list[str]:
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    passages, cur, cur_len = [], [], 0
    for b in blocks:
        if len(b) > target * 2 and "|" not in b[:200]:  # a very long paragraph: cut at sentence ends
            pieces, piece = [], ""
            for sent in re.split(r"(?<=[.!?])\s+", b):
                if len(piece) + len(sent) > target and piece:
                    pieces.append(piece)
                    piece = sent
                else:
                    piece = (piece + " " + sent).strip()
            if piece:
                pieces.append(piece)
        else:
            pieces = [b]
        for p in pieces:
            starts_section = p.startswith("#") or p.startswith("[page ")
            if cur and (cur_len + len(p) > target or (starts_section and cur_len > 200)):
                passages.append("\n\n".join(cur))
                cur, cur_len = [], 0
            cur.append(p)
            cur_len += len(p)
    if cur:
        passages.append("\n\n".join(cur))
    return passages


def best_passages(text: str, terms: list[str] | str, budget: int = 5000, lead: int = 500) -> dict:
    """Keep the passages that best match `terms` (BM25 on crude stems), in page order.

    Returns {text, kept, total, chars_total}. The top of the page is always kept (`lead`
    characters) so the reader knows what the page is; gaps are marked with a line "[...]".
    """
    if isinstance(terms, str):
        terms = stems(terms)
    q = list(dict.fromkeys(terms))
    if len(text) <= budget:
        return {"text": text, "kept": 1, "total": 1, "chars_total": len(text)}
    passages = _split_passages(text)
    toks = [stems(p) for p in passages]
    n = len(passages)
    avg = (sum(len(t) for t in toks) / n) if n else 1.0
    df = {t: sum(1 for tk in toks if t in tk) for t in q}
    scores = []
    for tk in toks:
        s = 0.0
        if tk:
            ln = len(tk)
            for t in q:
                f = tk.count(t)
                if not f:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * ln / avg))
        scores.append(s)
    for i, p in enumerate(passages):  # numbers and tables are what a decision-maker needs
        if scores[i] > 0 and (re.search(r"\d[\d.,]*\s?(%|prosent|päivä|vrk|days|per |€|eur)", p, re.I) or " | " in p):
            scores[i] *= 1.25
    order = sorted(range(n), key=lambda i: -scores[i])
    keep = {0}
    used = min(len(passages[0]), lead)
    for i in order:
        if scores[i] <= 0:
            break
        if i in keep:
            continue
        if used + len(passages[i]) > budget:
            if used > budget * 0.6:
                break
            continue
        keep.add(i)
        used += len(passages[i])
    parts, prev = [], -1
    for i in sorted(keep):
        if i != prev + 1:
            parts.append("[...]")
        p = passages[i]
        if i == 0 and len(keep) > 1 and scores[0] <= 0 and len(p) > lead:
            p = p[:lead].rsplit(" ", 1)[0] + " [...]"
        parts.append(p)
        prev = i
    if prev != n - 1:
        parts.append("[...]")
    return {"text": "\n\n".join(parts), "kept": len(keep), "total": n, "chars_total": len(text)}
