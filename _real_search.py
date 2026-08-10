# -*- coding: utf-8 -*-
"""Test réel de la recherche sectorielle DuckDuckGo (réseau requis)."""
from __future__ import annotations

import importlib.util

import streamlit as st

st.toast = lambda *a, **k: None

spec = importlib.util.spec_from_file_location("app", "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def out(msg: str) -> None:
    print(msg.encode("ascii", "backslashreplace").decode("ascii"))


SECTEURS = ["🚗 Garages & automobile", "🥐 Boulangeries & pâtisseries"]
out(f"==> Recherche réelle : secteurs {SECTEURS} — Lomé, Togo (wt-wt)")
qs = app.build_queries(app.MODE_WEB, "Lomé", "Togo", SECTEURS)
out(f"    Requêtes générées ({len(qs)}) :")
for q in qs:
    out(f"      - {q}")

df = app.search_leads(app.MODE_WEB, "Lomé", "Togo", "wt-wt", max_results=5,
                      sectors=SECTEURS,
                      progress_cb=lambda p: None)
out(f"==> {len(df)} lead(s) trouvée(s)")
if df.empty:
    out("    (aucun résultat — possible blocage temporaire de DuckDuckGo)")
else:
    for i, (_, r) in enumerate(df.iterrows(), 1):
        out(f"  {i}. {str(r['name'])[:40]:40s} | {str(r['website'])[:36]:36s} | "
            f"tel={r['phone'] or '-'} | {r['flag']}")
out("TEST RÉEL TERMINÉ")
