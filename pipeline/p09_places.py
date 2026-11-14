"""Where people live: every municipality with its population, its county and its distance to the nearest university hospital.

Same inputs and method as p07_distance.py (run that first: this reads the files it saved under data/raw/):
municipality polygon centroid (Statistics Finland 1:4.5M boundaries 2026), great-circle distance x 1.3 road
factor to the nearest of the five university hospitals (OpenStreetMap Nominatim), population 31 Dec of the
latest year (Statistics Finland 11ra). Writes data/processed/places.json, which the map view draws.

    python pipeline/p09_places.py
"""
from __future__ import annotations

import json

from common import PROC, RAW, jsonstat2_records
from p07_distance import HOSPITALS, ROAD_FACTOR, centroid, haversine

NAMES = {"HUS": ("Helsinki University Hospital", "Helsinki"), "TYKS": ("Turku University Hospital", "Turku"),
         "TAYS": ("Tampere University Hospital", "Tampere"), "KYS": ("Kuopio University Hospital", "Kuopio"),
         "OYS": ("Oulu University Hospital", "Oulu")}


def run() -> dict:
    hospitals = []
    for code in HOSPITALS:
        res = json.loads((RAW / "osm" / f"nominatim_{code}.json").read_text())
        hospitals.append({"id": code, "name_en": NAMES[code][0], "city": NAMES[code][1],
                          "lat": round(float(res[0]["lat"]), 4), "lon": round(float(res[0]["lon"]), 4)})
    feats = json.loads((RAW / "geo" / "kunta4500k_2026.json").read_text())["features"]
    k2h = {x["sourceLocalId"].split("/")[-1]: x["targetLocalId"].split("/")[-1]
           for x in json.loads((RAW / "statfin" / "kunta2026_hva2026.json").read_text())}
    pop_raw = json.loads((RAW / "statfin" / "11ra_kunta_pop.json").read_text())
    recs = jsonstat2_records(pop_raw)
    acode = next(k for k in recs[0] if k.lower().startswith("alue"))
    year = next(str(r[k]) for r in recs[:1] for k in r if k.startswith("timeperiod") or k.lower().startswith("vuosi"))
    pop = {r[acode][2:]: int(r["value"]) for r in recs if r["value"]}
    places, skipped = [], []
    for f in feats:
        ku = f["properties"]["kunta"]
        area, p = k2h.get(ku), pop.get(ku)
        if area is None or p is None:
            skipped.append(ku)
            continue
        lat, lon = centroid(f["geometry"])
        km, code = min((haversine(lat, lon, h["lat"], h["lon"]) * ROAD_FACTOR, h["id"]) for h in hospitals)
        places.append({"id": ku, "name": f["properties"]["nimi"], "area_id": area, "lat": round(lat, 4), "lon": round(lon, 4),
                       "population": p, "km": round(km, 1), "nearest": code})
    places.sort(key=lambda x: x["id"])
    out = {
        "hospitals": hospitals, "places": places, "population_year": year, "road_factor": ROAD_FACTOR,
        "method_en": (f"Each municipality is placed at the centre of its area (Statistics Finland boundaries 2026). Distance is the "
                      f"straight line to the nearest of the five university hospitals x {ROAD_FACTOR} as a road factor: an approximation, "
                      f"not a routed drive. Population 31 Dec {year}, Statistics Finland."),
        "sources": ["statfin_geo_kunta4500k_2026", "statfin_11ra_municipal_pop", "statfin_kunta_hva_2026", "osm_nominatim_university_hospitals"],
        "skipped": skipped,
    }
    (PROC / "places.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    o = run()
    print(len(o["places"]), "municipalities;", sum(p["population"] for p in o["places"]), "people; skipped", o["skipped"])
