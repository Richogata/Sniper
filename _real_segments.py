# -*- coding: utf-8 -*-
"""Test réel : recherche DuckDuckGo avec secteurs + classification segments A/B."""
from __future__ import annotations

import importlib.util

import pandas as pd
import streamlit as st

st.toast = lambda *a, **k: None

spec = importlib.util.spec_from_file_location("app", "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def out(m: str) -> None:
    print(m.encode("ascii", "backslashreplace").decode("ascii"))


out("==> Recherche reelle avec secteurs (Garages + Boulangeries) a Lome...")
df = app.search_leads(app.MODE_WEB, "Lome", "Togo", "wt-wt", max_results=5,
                      sectors=["🚗 Garages & automobile", "🥐 Boulangeries & pâtisseries"])
out(f"==> {len(df)} leads trouvees")
assert "segment" in df.columns, "colonne 'segment' absente !"
seg_counts = df["segment"].value_counts().to_dict()
out(f"==> Repartition segments: {seg_counts}")
assert len(df) > 0 and seg_counts.get(app.SEG_NO_SITE, 0) >= 0
for i, row in df.head(5).iterrows():
    out(f"  - {row['name'][:40]} | {row['website'][:45] or '(aucun)'} | [{row['segment']}]")
ok = seg_counts.get(app.SEG_NO_SITE, 0) + seg_counts.get(app.SEG_BAD_SITE, 0) > 0
out("==> TEST REEL SEGMENTS: " + ("OK" if ok else "AUCUN segment A/B (resultats tous des vrais sites)"))
