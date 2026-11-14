"""Search hints per wellbeing services county: the names a Finnish page would actually use.

These are hints for writing queries and for recognising a local page, not facts shown to the
user: brand names, site domains and hospitals were written from general knowledge and are only
used to find pages; everything shown comes from a page that was read.

    hints("21") -> {id, name_fi, name_en, short_fi, brand, site, hospitals, city, yta, uni_hospital,
                    uni_city, uni_site, local_terms}
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# id: (brand, site, hospitals, main city, lowercase stems that mark a page as local, acronyms)
_C = {
    "01": ("Itä-Uudenmaan hyvinvointialue", "itauusimaa.fi", ["Porvoon sairaala"], "Porvoo", ["itä-uusimaa", "itä-uudenmaa", "porvoo"], []),
    "02": ("Keusote", "keusote.fi", ["Hyvinkään sairaala"], "Hyvinkää", ["keski-uusimaa", "keski-uudenmaa", "keusote", "hyvinkää"], []),
    "03": ("LUVN", "luvn.fi", ["Jorvin sairaala", "Lohjan sairaala"], "Espoo", ["länsi-uusimaa", "länsi-uudenmaa", "espoo", "jorvi", "lohja"], ["LUVN"]),
    "04": ("VAKE", "vakehyva.fi", ["Peijaksen sairaala"], "Vantaa", ["vantaan ja keravan", "vantaa", "kerava", "peijas"], ["VAKE"]),
    "05": ("Varha", "varha.fi", ["Tyks", "Turun yliopistollinen keskussairaala"], "Turku", ["varsinais-suom", "varha", "turun ", "turku"], ["Tyks", "TYKS"]),
    "06": ("Satakunnan hyvinvointialue", "sata.fi", ["Satasairaala"], "Pori", ["satakun", "satasairaala", "porin ", "porissa"], []),
    "07": ("Oma Häme", "omahame.fi", ["Kanta-Hämeen keskussairaala", "Assi-sairaala"], "Hämeenlinna", ["kanta-häme", "oma häme", "hämeenlinna"], []),
    "08": ("Pirha", "pirha.fi", ["Tays", "Tampereen yliopistollinen sairaala"], "Tampere", ["pirkanmaa", "pirha", "tampere"], ["Tays", "TAYS"]),
    "09": ("Päijät-Hämeen hyvinvointialue", "paijatha.fi", ["Päijät-Hämeen keskussairaala"], "Lahti", ["päijät-häme", "päijät-sote", "lahden ", "lahti"], []),
    "10": ("Kymenhva", "kymenhva.fi", ["Kymenlaakson keskussairaala"], "Kotka", ["kymenlaakso", "kymenhva", "kymsote", "kouvola", "kotka"], []),
    "11": ("Ekhva", "ekhva.fi", ["Etelä-Karjalan keskussairaala"], "Lappeenranta", ["etelä-karjala", "ekhva", "eksote", "lappeenran"], []),
    "12": ("Eloisa", "etelasavonha.fi", ["Mikkelin keskussairaala", "Savonlinnan keskussairaala"], "Mikkeli", ["etelä-savo", "eloisa", "mikkeli", "savonlinna"], []),
    "13": ("Pohjois-Savon hyvinvointialue", "pshyvinvointialue.fi", ["KYS", "Kuopion yliopistollinen sairaala"], "Kuopio", ["pohjois-savo", "kuopio"], ["KYS"]),
    "14": ("Siun sote", "siunsote.fi", ["Pohjois-Karjalan keskussairaala"], "Joensuu", ["pohjois-karjala", "siun sote", "joensuu"], []),
    "15": ("Hyvaks", "hyvaks.fi", ["Sairaala Nova"], "Jyväskylä", ["keski-suom", "hyvaks", "sairaala nova", "jyväskylä"], []),
    "16": ("Hyvaep", "hyvaep.fi", ["Seinäjoen keskussairaala"], "Seinäjoki", ["etelä-pohjanmaa", "hyvaep", "seinäjo"], []),
    "17": ("Pohjanmaan hyvinvointialue", "pohjanmaanhyvinvointi.fi", ["Vaasan keskussairaala"], "Vaasa", ["pohjanmaan hyvinvointialue", "österbottens välfärdsområde", "vaasa"], []),
    "18": ("Soite", "soite.fi", ["Keski-Pohjanmaan keskussairaala"], "Kokkola", ["keski-pohjanmaa", "soite", "kokkola"], []),
    "19": ("Pohde", "pohde.fi", ["OYS", "Oulun yliopistollinen sairaala"], "Oulu", ["pohjois-pohjanmaa", "pohde", "pohtee", "oulun ", "oulussa"], ["OYS"]),
    "20": ("Kainuun hyvinvointialue", "kainuu.fi", ["Kainuun keskussairaala"], "Kajaani", ["kainuu", "kajaani"], []),
    "21": ("Lapha", "lapha.fi", ["Lapin keskussairaala", "Länsi-Pohjan keskussairaala"], "Rovaniemi", ["lapin hyvinvointialue", "lapha", "lapin keskussairaala", "länsi-pohja", "rovaniem", "lapissa", "lappi"], []),
    "90": ("Helsingin kaupunki", "hel.fi", ["HUS", "Meilahden sairaala"], "Helsinki", ["helsingin", "helsinki", "meilah"], ["HUS"]),
    "91": ("ÅHS", "ahs.ax", ["Ålands centralsjukhus"], "Mariehamn", ["åland", "ahvenanmaa", "mariehamn"], ["ÅHS"]),
}
# collaborative area -> (university hospital, city, site, lowercase stems, acronyms)
_Y = {
    "HUS": ("HUS Helsingin yliopistollinen sairaala", "Helsinki", "hus.fi", ["helsingin yliopistolli", "etelä-suomen yhteistyöalue"], ["HUS"]),
    "TYKS": ("Tyks Turun yliopistollinen keskussairaala", "Turku", "varha.fi", ["turun yliopistolli", "länsi-suomen yhteistyöalue", "varha"], ["Tyks", "TYKS"]),
    "TAYS": ("Tays Tampereen yliopistollinen sairaala", "Tampere", "pirha.fi", ["tampereen yliopistolli", "sisä-suomen yhteistyöalue", "pirha"], ["Tays", "TAYS"]),
    "KYS": ("KYS Kuopion yliopistollinen sairaala", "Kuopio", "pshyvinvointialue.fi", ["kuopion yliopistolli", "itä-suomen yhteistyöalue"], ["KYS"]),
    "OYS": ("OYS Oulun yliopistollinen sairaala", "Oulu", "pohde.fi", ["oulun yliopistolli", "pohjois-suomen yhteistyöalue", "pohde", "pohtee"], ["OYS"]),
    "ALAND": ("Tyks Turun yliopistollinen keskussairaala", "Turku", "varha.fi", ["ålands hälso"], ["Tyks", "TYKS"]),
}

# every site a university hospital publishes its care pathways on (seen in search results)
_YSITES = {"HUS": ["hus.fi"], "TYKS": ["tyks.fi", "varha.fi"], "TAYS": ["tays.fi", "pirha.fi"],
           "KYS": ["kys.fi", "pshyvinvointialue.fi"], "OYS": ["oys.fi", "pohde.fi"], "ALAND": ["tyks.fi", "varha.fi"]}

_areas: list[dict] | None = None


def areas() -> list[dict]:
    global _areas
    if _areas is None:
        _areas = json.loads((ROOT / "data" / "processed" / "areas.json").read_text(encoding="utf-8"))
    return _areas


def hints(area_id: str | None) -> dict | None:
    """Names and sites for one county; None for the whole country or an unknown id."""
    if not area_id or area_id == "FI":
        return None
    a = next((x for x in areas() if x["id"] == area_id), None)
    if a is None or area_id not in _C:
        return None
    brand, site, hospitals, city, local, acr = _C[area_id]
    uni, uni_city, uni_site, yterms, yacr = _Y.get(a.get("yta") or "", ("", "", "", [], []))
    return {
        "id": area_id, "name_fi": a["name_fi"], "name_en": a["name_en"], "short_fi": a.get("short_fi"),
        "short_en": a.get("short_en"), "brand": brand, "site": site, "hospitals": hospitals, "city": city,
        "yta": a.get("yta"), "yta_name_fi": a.get("yta_name_fi"), "uni_hospital": uni, "uni_city": uni_city,
        "uni_site": uni_site, "uni_sites": _YSITES.get(a.get("yta") or "", [uni_site] if uni_site else []),
        "uni_short": uni.split(" ")[0] if uni else "",
        "local_terms": sorted(set(local) | set(acr)),
        "yta_terms": sorted(set(yterms) | set(yacr)),
    }


def mentions(text: str, terms: list[str]) -> list[str]:
    """Which of the terms the text mentions. Lowercase terms are stems matched anywhere,
    case-insensitively; terms with capitals are acronyms (HUS, OYS, Tyks) matched with their
    case at the start of a word, so "KYS" does not match "kysely"."""
    import re

    text = text or ""
    low = text.lower()
    out = []
    for t in terms:
        if t != t.lower():
            if re.search(r"(?<![A-Za-zÅÄÖåäö])" + re.escape(t), text):
                out.append(t)
        elif t in low:
            out.append(t)
    return out
