"""Distance from where people live to the nearest university hospital.

Method: for every municipality, great-circle distance from the centroid of its polygon
(Statistics Finland 1:4.5M generalised boundaries) to the nearest of the five university
hospitals (coordinates geocoded with OpenStreetMap Nominatim), multiplied by 1.3 as a
road-distance factor, then population-weighted (year-end 2025 population) to the county.
"""
from __future__ import annotations

import json
import math
import time

from common import Out, fetch, FetchError, jsonstat2_records, AREA_IDS

HOSPITALS = {"HUS": "Meilahden tornisairaala, Helsinki", "TYKS": "Turun yliopistollinen keskussairaala, Turku",
             "TAYS": "Tampereen yliopistollinen sairaala, Tampere", "KYS": "Kuopion yliopistollinen sairaala, Kuopio",
             "OYS": "Oulun yliopistollinen sairaala, Oulu"}
CITY_BOX = {"HUS": (60.1, 60.3, 24.8, 25.1), "TYKS": (60.4, 60.5, 22.2, 22.4), "TAYS": (61.4, 61.6, 23.7, 23.9),
            "KYS": (62.8, 63.0, 27.5, 27.8), "OYS": (64.9, 65.1, 25.4, 25.6)}
ROAD_FACTOR = 1.3
WFS = ("https://geo.stat.fi/geoserver/tilastointialueet/wfs?service=WFS&version=2.0.0&request=GetFeature"
       "&typeName=tilastointialueet:kunta4500k_2026&outputFormat=application/json&srsName=EPSG:4326")
CORR = ("https://data.stat.fi/api/classifications/v2/correspondenceTables/"
        "kunta_1_20260101%23hyvinvointialue_1_20260101/maps?content=data&meta=max&lang=fi&format=json")
PX = "https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin/vaerak/11ra.px"


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def ring_centroid(ring):
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if a == 0:
        return ring[0][0], ring[0][1], 0.0
    return cx / (3 * a), cy / (3 * a), abs(a) / 2


def centroid(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    sx = sy = sa = 0.0
    for poly in polys:
        x, y, a = ring_centroid(poly[0])
        sx += x * a
        sy += y * a
        sa += a
    return sy / sa, sx / sa  # lat, lon


def run() -> Out:
    out = Out("p07_distance")
    try:
        hosp, calls, ts = {}, [], None
        for code, q in HOSPITALS.items():
            url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=fi&q=" + q.replace(" ", "+")
            raw, ts = fetch(url, "osm", f"nominatim_{code}.json")
            res = json.loads(raw)
            lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
            b = CITY_BOX[code]
            if not (b[0] <= lat <= b[1] and b[2] <= lon <= b[3]):
                raise FetchError(f"geocode for {code} outside expected city: {lat},{lon} {res[0].get('display_name')}")
            hosp[code] = (lat, lon, res[0].get("display_name"))
            calls.append(url)
            time.sleep(1.1)
        out.source("osm_nominatim_university_hospitals", title="Coordinates of the five Finnish university hospitals (OpenStreetMap Nominatim geocoder)",
                   publisher="OpenStreetMap contributors", url="https://nominatim.openstreetmap.org/", api_call="GET " + " ; ".join(calls),
                   retrieved_at=ts, licence="ODbL 1.0",
                   notes="; ".join(f"{c}: {v[0]:.4f},{v[1]:.4f} ({v[2]})" for c, v in hosp.items()))
        raw, gts = fetch(WFS, "geo", "kunta4500k_2026.json")
        feats = json.loads(raw)["features"]
        out.source("statfin_geo_kunta4500k_2026", title="Municipal boundaries 2026, 1:4,500,000 (WFS)", publisher="Statistics Finland",
                   url="https://geo.stat.fi/geoserver/tilastointialueet/wfs", api_call=f"GET {WFS}", retrieved_at=gts, licence="CC BY 4.0",
                   notes="Polygon centroids used as municipality locations.")
        raw, cts = fetch(CORR, "statfin", "kunta2026_hva2026.json")
        k2h = {x["sourceLocalId"].split("/")[-1]: x["targetLocalId"].split("/")[-1] for x in json.loads(raw)}
        out.source("statfin_kunta_hva_2026", title="Correspondence table: municipalities 2026 - wellbeing services counties 2026", publisher="Statistics Finland",
                   url="https://stat.fi/en/luokitukset/corrmaps/kunta_1_20260101%23hyvinvointialue_1_20260101", api_call=f"GET {CORR}",
                   retrieved_at=cts, licence="CC BY 4.0", notes="")
        mraw, _ = fetch(PX, "statfin", "vaerak_11ra.px.meta.px.json")
        m = {v["code"]: v for v in json.loads(mraw)["variables"]}
        acode = next(c for c in m if c.startswith("alue"))
        kus = [v for v in m[acode]["values"] if v.startswith("KU")]
        year = m["timeperiod_y"]["values"][-1]
        body = {"query": [{"code": acode, "selection": {"filter": "item", "values": kus}},
                          {"code": "contentscode", "selection": {"filter": "item", "values": ["vaerak-vaesto"]}},
                          {"code": "timeperiod_y", "selection": {"filter": "item", "values": [year]}}],
                "response": {"format": "json-stat2"}}
        raw, pts = fetch(PX, "statfin", "11ra_kunta_pop.json", post_json=body)
        mpop = {r[acode][2:]: r["value"] for r in jsonstat2_records(json.loads(raw)) if r["value"]}
        out.source("statfin_11ra_municipal_pop", title=f"11ra -- Population 31 Dec {year} by municipality", publisher="Statistics Finland",
                   url="https://pxdata.stat.fi/PxWeb/pxweb/fi/StatFin/StatFin__vaerak/statfin_vaerak_pxt_11ra.px/",
                   api_call=f"POST {PX} (all KUxxx areas, contentscode=vaerak-vaesto, year={year}; body in data/raw/statfin/11ra_kunta_pop.json.meta.json)",
                   retrieved_at=pts, licence="CC BY 4.0", notes="Population weights for the distance indicator.")
    except (FetchError, ValueError, KeyError, IndexError, StopIteration) as e:
        out.problems.append(f"distance: {e!r}")
        out.save()
        return out

    method = (f"Population-weighted mean over municipalities of great-circle distance from municipality polygon centroid to the nearest of the five "
              f"university hospitals (HUS Meilahti, TYKS, TAYS, KYS, OYS), x {ROAD_FACTOR} road factor; population 31 Dec {year}. "
              "Geometric approximation, not routed travel distance.")
    out.define("km_to_university_hospital", label_en="Distance to nearest university hospital (population-weighted, approx. road km)",
               label_fi="Etäisyys lähimpään yliopistosairaalaan (väestöpainotettu, arvioitu tiekilometri)", unit="km", direction="higher_is_worse", step="referral",
               definition_en=method)
    out.define("pop_over_100km_from_university_hospital_pct", label_en="Population living over 100 km (approx. road) from a university hospital",
               label_fi="Yli 100 km päässä yliopistosairaalasta asuvan väestön osuus (arvio)", unit="%", direction="higher_is_worse", step="referral",
               definition_en="Share of county population in municipalities whose centroid is more than 100 km (great-circle x 1.3) from the nearest university hospital.")
    acc = {}
    missing = []
    for f in feats:
        ku = f["properties"]["kunta"]
        area, p = k2h.get(ku), mpop.get(ku)
        if area is None or p is None:
            missing.append(ku)
            continue
        lat, lon = centroid(f["geometry"])
        km, code = min((haversine(lat, lon, h[0], h[1]) * ROAD_FACTOR, c) for c, h in hosp.items())
        for a in (area, "FI"):
            s = acc.setdefault(a, {"w": 0, "km": 0.0, "far": 0, "near": {}})
            s["w"] += p
            s["km"] += km * p
            s["far"] += p if km > 100 else 0
            s["near"][code] = s["near"].get(code, 0) + p
    if missing:
        out.problems.append(f"distance: {len(missing)} municipalities without mapping or population: {missing[:10]}")
    src = "osm_nominatim_university_hospitals"
    for a in AREA_IDS + ["FI"]:
        if a not in acc:
            continue
        s = acc[a]
        near = max(s["near"], key=s["near"].get)
        note = (f"method: population-weighted municipal centroid great-circle distance x {ROAD_FACTOR}; nearest for most residents: {near}; "
                "inputs: OSM Nominatim hospital coordinates, Statistics Finland municipal boundaries 2026 and population " + year)
        out.add(a, "km_to_university_hospital", round(s["km"] / s["w"], 1), year, src, note=note)
        out.add(a, "pop_over_100km_from_university_hospital_pct", round(s["far"] / s["w"] * 100, 1), year, src, note=note)
    out.problems.append("distance: nearest radiotherapy unit not computed (no citable public list of radiotherapy units located in the time available)")
    out.save()
    return out


if __name__ == "__main__":
    o = run()
    print(len(o.rows), "rows;", o.problems)
    for r in o.rows:
        if r["indicator"] == "km_to_university_hospital":
            print(r["area_id"], r["value"], r["note"][80:130])
