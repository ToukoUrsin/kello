"""The search over the sentences the web checks quoted must answer without MongoDB Atlas: from the stored files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "server"))


def test_search_answers_from_files_without_atlas(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("JUNCTION_MONGODB_URI", raising=False)
    from integrations import mongo_store

    r = mongo_store.search("sädehoito")
    assert r["backend"] == "files"
    assert r["hits"] and r["counties"]
    for h in r["hits"]:
        assert "".join(p["t"] for p in h["parts"]) == h["quote"]      # the sentence is shown whole, word for word
        assert h["url"].startswith("http") and h["areas"]
    assert any(p["hit"] for h in r["hits"] for p in h["parts"])
    assert mongo_store.search("x")["hits"] == []                      # one letter is not a search
    s = mongo_store.stats()
    assert s["backend"] == "files" and s["quotes"] > 100 and s["checks"] > 50


def test_one_row_per_sentence_lists_every_county():
    from integrations import mongo_store

    hit = {"url": "https://example.org/a", "domain": "example.org", "title": "t", "quote": "q", "about": "context",
           "parts": [{"t": "q", "hit": False}], "intervention_name_en": "A"}
    r = mongo_store._answer("files", "q", None, [
        {**hit, "area_id": "21", "area_name_en": "Lapland wellbeing services county"},
        {**hit, "area_id": "19", "area_name_en": "North Ostrobothnia wellbeing services county", "about": "in_use"},
    ])
    assert len(r["hits"]) == 1
    assert [a["name"] for a in r["hits"][0]["areas"]] == ["Lapland", "North Ostrobothnia"]
    assert r["hits"][0]["about"] == "in_use"
