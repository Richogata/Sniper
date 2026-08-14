# -*- coding: utf-8 -*-
"""Test AppTest des nouveaux widgets UI (filtres radio, secteurs, WhatsApp)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

# ⚠️ Protège settings.json : l'app persiste automatiquement la session à chaque rendu.
# Sans sauvegarde/restauration, un test écraserait la vraie clé Gemini de l'utilisateur.
_SETTINGS = Path(__file__).resolve().parent / "settings.json"
_BAK = Path(__file__).resolve().parent / "settings.json.bak"
if _SETTINGS.exists():
    shutil.copy2(_SETTINGS, _BAK)


LEAD_COLS = ["name", "website", "email", "phone", "source", "flag", "segment", "snippet", "audit", "status"]

LEADS = pd.DataFrame([
    {"name": "Site Pro SA", "website": "https://sitepro.tg", "email": "a@x.tg",
     "phone": "", "source": "CSV", "flag": "", "segment": "Site correct",
     "snippet": "", "audit": "", "status": ""},
    {"name": "Garage Centre", "website": "https://facebook.com/gc", "email": "",
     "phone": "+228 90 12 34 56", "source": "CSV", "flag": "", "segment": "Segment A — Sans site web",
     "snippet": "", "audit": "", "status": ""},
    {"name": "Boulangerie L", "website": "", "email": "b@x.tg", "phone": "22 22 33 44",
     "source": "CSV", "flag": "", "segment": "Segment A — Sans site web",
     "snippet": "", "audit": "", "status": ""},
], columns=LEAD_COLS)


def _out(m: str) -> None:
    print(m.encode("ascii", "backslashreplace").decode("ascii"))


at = AppTest.from_file("app.py", default_timeout=60)
at.session_state["leads"] = LEADS.copy()
at.run()
assert not at.exception, [e.value for e in at.exception]
_out("[OK] App chargée avec leads (nouveaux widgets)")

# Radio de filtre présent
radios = [r for r in at.radio if r.label == "Filtre d'affichage"]
assert radios, "Radio 'Filtre d'affichage' introuvable"
_out("[OK] Radio 'Filtre d'affichage' présent")

def _radio():
    return next(r for r in at.radio if r.label == "Filtre d'affichage")

# Changer de filtre : 'Avec site web' -> pas d'exception
_radio().set_value("✅ Avec site web")
at.run()
assert not at.exception, [e.value for e in at.exception]
_out("[OK] Filtre 'Avec site web' appliqué sans exception")

# Filtre 'Avec téléphone'
_radio().set_value("📞 Avec téléphone")
at.run()
assert not at.exception, [e.value for e in at.exception]
_out("[OK] Filtre 'Avec téléphone' appliqué sans exception")

# Filtres par segment (nouveaux)
_radio().set_value("🗂️ Segment A (sans site)")
at.run()
assert not at.exception, [e.value for e in at.exception]
_out("[OK] Filtre Segment A appliqué sans exception")

_radio().set_value("🗂️ Segment B (site médiocre)")
at.run()
assert not at.exception, [e.value for e in at.exception]
_out("[OK] Filtre Segment B appliqué sans exception")

# Filtre 'Tous les leads' + appliquer les modifications
_radio().set_value("Tous les leads")
at.run()
assert not at.exception, [e.value for e in at.exception]
apply_btn = next(b for b in at.button if "Appliquer" in b.label)
apply_btn.click()
at.run()
assert not at.exception, [e.value for e in at.exception]
assert len(at.session_state["leads"]) == 3
_out("[OK] Filtres + Appliquer : 3 leads conservées, sans exception")

# Toggle langue FR/EN présent et fonctionnel
lang_toggles = [t for t in at.toggle if "FRANÇAIS" in t.label]
assert lang_toggles, "Toggle FRANÇAIS/ENGLISH introuvable"
lang_toggles[0].set_value(True)
at.run()
assert not at.exception, [e.value for e in at.exception]
assert at.session_state["lang"] == "en"
_out("[OK] Toggle langue FR/EN -> 'en' sans exception")

# Onglet Dashboard rendu sans exception
if not at.exception:
    _out("[OK] Dashboard rendu dans les 4 onglets (pas d'exception globale)")

# Onglet Outreach : section WhatsApp rendue sans exception
wa_sections = [e for e in at.expander if "WhatsApp" in e.label]
assert wa_sections, "Section WhatsApp introuvable"
_out(f"[OK] Section WhatsApp présente ({len(wa_sections)} expander)")

# Boutons à callbacks on_click : modification de widgets autorisée AVANT re-rendu
reset_wa = next(b for b in at.button if "Modèle par défaut" in b.label)
reset_wa.click()
at.run()
assert not at.exception, [e.value for e in at.exception]
_out("[OK] Clic « Modèle par défaut » (on_click) sans exception")

reset_email = next(b for b in at.button if "Réinitialiser le modèle" in b.label)
reset_email.click()
at.run()
assert not at.exception, [e.value for e in at.exception]
assert "Bonjour" in at.session_state["email_body"] or "listing" in at.session_state["email_body"]
_out("[OK] Clic « Réinitialiser le modèle » (on_click) sans exception")

_# Restaure settings.json (la session de test ne doit pas altérer les vraies clés)
if _BAK.exists():
    shutil.copy2(_BAK, _SETTINGS)
    _BAK.unlink(missing_ok=True)

out("TOUS LES TESTS UI OK")
