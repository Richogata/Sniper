# -*- coding: utf-8 -*-
"""Démo du flux de prospection réel : recherche DuckDuckGo + aperçu email."""
from __future__ import annotations

import importlib.util
import sys

import streamlit as st


def _out(msg: str) -> None:
    print(msg.encode("ascii", "backslashreplace").decode("ascii"))


# 1) Charger le module app.py sans exécuter main()
spec = importlib.util.spec_from_file_location("app", "app.py")
app = importlib.util.module_from_spec(spec)
# Neutraliser les widgets Streamlit hors runtime (toast notamment)
st.toast = lambda *a, **k: None
st.rerun = lambda *a, **k: None
spec.loader.exec_module(app)

# 2) Recherche réelle DuckDuckGo — mode Local Web-Design Hunter, Lomé/Togo
_out("==> Recherche DuckDuckGo : mode 'Local Web-Design Hunter' — Lomé, Togo (région wt-wt) ...")
df = app.search_leads(
    app.MODE_WEB, "Lomé", "Togo", "wt-wt", max_results=10,
    progress_cb=lambda p: _out(f"    progression {p * 100:.0f}%"),
)
_out("")
_out(f"==> {len(df)} lead(s) trouvée(s)")
if df.empty:
    _out("    (aucune lead — DuckDuckGo peut bloquer les requêtes automatisées)")
else:
    cols = ["name", "website", "email", "phone", "flag"]
    for i, (_, r) in enumerate(df.iterrows(), 1):
        _out(f"  {i}. {r['name'][:42]:42s} | {str(r['website'])[:38]:38s} | "
             f"email={r['email'] or '-':28s} | tel={r['phone'] or '-'} | {r['flag']}")

    # 3) Aperçu de l'email de prospection pour la 1re lead
    first = df.iloc[0]
    _out("")
    _out("==> APERÇU DE L'EMAIL DE PROSPECTION (1re lead) — modèle par défaut du mode Web-Design")
    subj = app.DEFAULT_TEMPLATES[app.MODE_WEB]["subject"]
    body = app.DEFAULT_TEMPLATES[app.MODE_WEB]["body"]
    audit = ("Constat : votre établissement n'apparaît pas dans les premières recherches Google à "
             "Lomé. La diaspora togolaise (France, USA, Allemagne) réserve et commande en ligne : "
             "sans présence web, elle se tourne vers vos concurrents.")
    payment = app.payment_block(app.MODE_WEB, "", app.DEFAULT_AFRICA_PAYMENT)
    msg = app.fill_template(body, first, "Scriba & Co", "Lomé Togo", app.MODE_WEB,
                            audit=audit, payment=payment)
    _out(f"  Objet : {subj}")
    _out(f"  ----")
    for line in msg.splitlines():
        _out(f"  {line}")
    _out("")
    _out(f"==> Lien WhatsApp pour la 1re lead : {app.wa_link(first['phone'], app.fill_template(app.DEFAULT_WA[app.MODE_WEB], first, 'Scriba & Co', 'Lomé Togo', app.MODE_WEB)) if first['phone'] else '(pas de numéro trouvé)'}")
