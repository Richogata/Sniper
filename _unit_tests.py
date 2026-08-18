# -*- coding: utf-8 -*-
"""Tests unitaires des fonctionnalités ajoutées : secteurs combinables,
filtres de leads, lien WhatsApp, OpenAI (mocké), retry Gemini (mocké)."""
from __future__ import annotations

import importlib.util
import smtplib
import sys

import pandas as pd
import streamlit as st

st.toast = lambda *a, **k: None
st.rerun = lambda *a, **k: None

spec = importlib.util.spec_from_file_location("app", "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

# Référence à la VRAIE gemini_generate : les tests 27/28 la remplacent par un mock,
# le test 38 (bascule de modèles) doit restaurer la fonction d'origine.
_ORIG_GEMINI_GENERATE = app.gemini_generate


def out(msg: str) -> None:
    print(msg.encode("ascii", "backslashreplace").decode("ascii"))


# 1) build_queries avec secteurs combinés (2 requêtes immo + 4 coiffure = 6)
qs = app.build_queries(app.MODE_WEB, "Lome", "Togo",
                       ["🏠 Agences immobilières", "💇 Coiffure & beauté"])
assert len(qs) == 6, qs
assert all("{city}" not in q and "lome" in q.lower() for q in qs)
assert any("coiffeur lome togo" in q.lower() for q in qs)
assert any("barber shop lome togo" in q.lower() for q in qs)
out(f"[OK] build_queries secteurs combinés: {len(qs)} requêtes")

# 2) sans secteurs -> fallback QUERIES
qs2 = app.build_queries(app.MODE_WEB, "Lome", "Togo")
assert len(qs2) == len(app.QUERIES[app.MODE_WEB])
out("[OK] build_queries fallback")

# 3) has_website
assert app.has_website("https://maison.tg")
assert not app.has_website("")
assert not app.has_website("https://facebook.com/abc")
assert not app.has_website("https://www.google.com/maps/place/x")
out("[OK] has_website")

# 3bis) classify_segment (Segments A / B)
assert app.classify_segment("") == app.SEG_NO_SITE
assert app.classify_segment("https://facebook.com/x") == app.SEG_NO_SITE
assert app.classify_segment("https://monagence.wordpress.com") == app.SEG_BAD_SITE
assert app.classify_segment("https://site.gq") == app.SEG_BAD_SITE
assert app.classify_segment("https://maison.tg") == app.SEG_OK
out("[OK] classify_segment (A / B / correct)")

# 4) apply_lead_filter (avec segments)
df = pd.DataFrame([
    {"name": "A", "website": "https://a.tg", "email": "a@x.tg", "phone": "",
     "segment": app.SEG_OK},
    {"name": "B", "website": "https://facebook.com/b", "email": "", "phone": "+228 90",
     "segment": app.SEG_NO_SITE},
    {"name": "C", "website": "", "email": "c@x.tg", "phone": "",
     "segment": app.SEG_NO_SITE},
])
assert app.apply_lead_filter(df, "✅ Avec site web").tolist() == [True, False, False]
assert app.apply_lead_filter(df, "⚠️ Sans site web").tolist() == [False, True, True]
assert app.apply_lead_filter(df, "📧 Avec email").tolist() == [True, False, True]
assert app.apply_lead_filter(df, "📞 Avec téléphone").tolist() == [False, True, False]
assert app.apply_lead_filter(df, "🗂️ Segment A (sans site)").tolist() == [False, True, True]
assert app.apply_lead_filter(df, "🗂️ Segment B (site médiocre)").tolist() == [False, False, False]
assert app.apply_lead_filter(df, "Tous les leads").all()
out("[OK] apply_lead_filter (avec segments)")

# 4bis) audit_prompt : segments + langue FR/EN + techniques AIDA/PAS
p1 = app.audit_prompt(app.MODE_WEB, "Garage X", "Lomé Togo", segment=app.SEG_NO_SITE, lang="fr")
assert "PAS" in p1 and "diaspora" in p1 and "français" in p1
p2 = app.audit_prompt(app.MODE_WEB, "Boul Y", "Lomé Togo", snippet="ancien site",
                      segment=app.SEG_BAD_SITE, lang="en", website="https://b.wordpress.com")
assert "AIDA" in p2 and "English" in p2 and "wordpress.com" in p2
p3 = app.audit_prompt(app.MODE_WEB, "Café Z", "Lomé Togo", segment=app.SEG_OK, lang="en")
assert "AIDA" in p3 and "English" in p3
out("[OK] audit_prompt segment + langue + AIDA/PAS")

# 4ter) body_to_html : email HTML clair et lisible (fond blanc, texte sombre)
html = app.body_to_html("Bonjour {LeadName},\n\nCeci est un test.")
assert html.startswith("<div") and "background:#f4f4f2" in html and "Bonjour" in html
assert "#0d0d0f" not in html  # plus de fond sombre (illisible dans Gmail)
assert "color:#222222" in html  # texte sombre sur fond clair
out("[OK] body_to_html (email HTML clair, lisible, anti-spam friendly)")

# 5) wa_link
link = app.wa_link("+228 90 12 34 56", "Bonjour {LeadName}")
assert "wa.me/22890123456" in link
out("[OK] wa_link")

# 6) openai_generate avec client mock
class FakeMsg:
    content = "Texte ameliore"

class FakeChoice:
    message = FakeMsg()

class FakeResp:
    choices = [FakeChoice()]

class FakeCompletions:
    def create(self, **kw):
        assert kw["model"] == "gpt-4o-mini"
        return FakeResp()

class FakeClient:
    def __init__(self, api_key):
        pass
    chat = type("C", (), {"completions": FakeCompletions()})()

app._OpenAI = FakeClient
out2 = app.openai_generate("sk-x", "gpt-4o-mini", "prompt")
assert out2 == "Texte ameliore"
out("[OK] openai_generate (mock)")

# 7) gemini retry : 2x 429 puis succès
calls = {"n": 0}

class FakeGenResp:
    text = "audit ok"

def _maybe(**kw):
    calls["n"] += 1
    if calls["n"] < 3:
        raise Exception("429 RESOURCE_EXHAUSTED")
    return FakeGenResp()

class FakeGenClient:
    def __init__(self, api_key):
        pass
    models = type("M", (), {"generate_content": staticmethod(_maybe)})()

app._genai = type("G", (), {"Client": FakeGenClient})()
app._GENAI_STATE = "new"
app.time.sleep = lambda s: None  # accélère
out3 = app.gemini_generate("k", "gemini-2.5-flash", "p", max_retries=4, base_wait=0.001)
assert out3 == "audit ok" and calls["n"] == 3
out("[OK] gemini_generate retry 429 -> succès")

# 8) _lang_templates / _lang_wa : modèles FR/EN selon le toggle instantané
subj_en, body_en = app._lang_templates(app.MODE_WEB, "en")
assert "{LeadName}" in subj_en and "Hello" in body_en and "diaspora" in body_en.lower()
subj_fr, body_fr = app._lang_templates(app.MODE_WEB, "fr")
assert "{LeadName}" in subj_fr and "Bonjour" in body_fr and "diaspora" in body_fr.lower()
wa_en = app._lang_wa(app.MODE_WEB, "en")
assert "Hello" in wa_en and "diaspora" in wa_en.lower()
wa_fr = app._lang_wa(app.MODE_WEB, "fr")
assert "Bonjour" in wa_fr and "diaspora" in wa_fr.lower()
wa_en_copy = app._lang_wa(app.MODE_COPY, "en")
assert "Hello" in wa_en_copy and "copywriting" in wa_en_copy.lower()
out("[OK] _lang_templates / _lang_wa (bascule FR/EN instantanée)")

# 9) _swap_msg_defaults : bascule si non personnalisé, préservé sinon, copy préservé
app.st.session_state["email_subject"] = app.DEFAULT_TEMPLATES[app.MODE_WEB]["subject"]
app.st.session_state["email_body"] = app.DEFAULT_TEMPLATES[app.MODE_WEB]["body"]
app.st.session_state["wa_msg"] = app.DEFAULT_WA[app.MODE_WEB]
assert app._swap_msg_defaults(app.MODE_WEB, "fr", "en") is True
assert app.st.session_state["email_subject"] == app.DEFAULT_TEMPLATES_EN[app.MODE_WEB]["subject"]
assert app.st.session_state["email_body"] == app.DEFAULT_TEMPLATES_EN[app.MODE_WEB]["body"]
assert app.st.session_state["wa_msg"] == app.EN_WA[app.MODE_WEB]
# email personnalisé -> préservé ; WA non personnalisé -> basculé
app.st.session_state["email_subject"] = "Objet custom"
app.st.session_state["email_body"] = "Corps custom"
app.st.session_state["wa_msg"] = app.EN_WA[app.MODE_WEB]
assert app._swap_msg_defaults(app.MODE_WEB, "en", "fr") is True
assert app.st.session_state["email_subject"] == "Objet custom"
assert app.st.session_state["wa_msg"] == app.DEFAULT_WA[app.MODE_WEB]
# mode Copywriting : emails intacts (template_lang prioritaire), WA basculé
app.st.session_state["email_subject"] = app.DEFAULT_COPY_LANGS["fr"][0]
app.st.session_state["email_body"] = app.DEFAULT_COPY_LANGS["fr"][1]
app.st.session_state["wa_msg"] = app.DEFAULT_WA[app.MODE_COPY]
assert app._swap_msg_defaults(app.MODE_COPY, "fr", "en") is True
assert app.st.session_state["email_subject"] == app.DEFAULT_COPY_LANGS["fr"][0]
assert app.st.session_state["wa_msg"] == app.EN_WA[app.MODE_COPY]
out("[OK] _swap_msg_defaults (bascule / préservation / mode Copy)")

# 10) _is_bad_credentials : détection de l'erreur Gmail 535 (BadCredentials)
assert app._is_bad_credentials(
    Exception("(535, b'5.7.8 Username and Password not accepted. BadCredentials gsmtp')"))
assert app._is_bad_credentials(Exception("535 5.7.8 Password not accepted"))
assert not app._is_bad_credentials(Exception("socket.timeout: timed out"))
assert not app._is_bad_credentials(Exception("404 model not found"))
out("[OK] _is_bad_credentials (535 vs autres erreurs)")

# 11) test_smtp_connection : succès + échec 535 (SMTP mocké, aucun réseau)
app._logins = None
app._fail_login = False

class FakeSMTP_SSL:
    def __init__(self, host, port, context=None, timeout=30):
        assert host == "smtp.gmail.com" and port == 465

    def __enter__(self):
        if app._fail_login:
            raise app.smtplib.SMTPAuthenticationError(535, b"5.7.8 BadCredentials gsmtp")
        return self

    def __exit__(self, *a):
        return False

    def login(self, sender, password):
        app._logins = (sender, password)

_orig_smtp_ssl = app.smtplib.SMTP_SSL
app.smtplib.SMTP_SSL = FakeSMTP_SSL
ok, msg = app.test_smtp_connection("me@gmail.com", "abcd efgh")
assert ok and app._logins == ("me@gmail.com", "abcd efgh")
out("[OK] test_smtp_connection succès (SMTP mocké)")

app._fail_login = True
ok2, msg2 = app.test_smtp_connection("me@gmail.com", "wrong")
assert not ok2 and "535" in msg2 and "mot de passe d'application" in msg2.lower()
out("[OK] test_smtp_connection 535 -> message d'aide")

ok3, msg3 = app.test_smtp_connection("", "")
assert not ok3 and "Renseignez" in msg3
out("[OK] test_smtp_connection champs vides")

app.smtplib.SMTP_SSL = _orig_smtp_ssl  # restaure le module stdlib (aucune fuite)
out("[OK] smtplib.SMTP_SSL restauré après les tests")

# 12) body_to_html avec contenu enrichi (images cid, CTA, vidéo)
html_rich = app.body_to_html("Bonjour {LeadName}",
                             image_cids=["img_0", "img_1"],
                             cta={"url": "https://exemple.tg/offre", "label": "Voir l'offre"},
                             video="https://youtube.com/watch?v=abc")
assert "cid:img_0" in html_rich and "cid:img_1" in html_rich
assert "https://exemple.tg/offre" in html_rich and "l&#x27;offre" in html_rich  # apostrophe échappée
assert "Voir" in html_rich and "Regarder la vidéo" in html_rich and "youtube.com" in html_rich
assert html_rich.index("cid:img_0") < html_rich.index("Bonjour")
html_plain = app.body_to_html("Bonjour")
assert "cid:" not in html_plain and "Regarder la vidéo" not in html_plain
out("[OK] body_to_html contenu enrichi (image/CTA/vidéo)")

# 13) _outreach_targets : sélection ✓ prioritaire > filtre actif > toutes
app.st.session_state["leads_filter"] = "Tous les leads"
df_t = pd.DataFrame([
    {"name": "A", "website": "https://a.tg", "email": "a@x.tg", "phone": "",
     "segment": app.SEG_OK},
    {"name": "B", "website": "https://facebook.com/b", "email": "", "phone": "+228 90",
     "segment": app.SEG_NO_SITE},
    {"name": "C", "website": "", "email": "c@x.tg", "phone": "",
     "segment": app.SEG_NO_SITE},
])
edit_t = df_t.copy()
edit_t[app.SEL_COL] = [True, False, True]
app.st.session_state["leads_edit"] = edit_t
app.st.session_state["leads_filter"] = "Tous les leads"
tgt, d1 = app._outreach_plan(df_t)
assert list(tgt["name"]) == ["A", "C"], tgt["name"].tolist()
assert "sélectionnée" in d1
# l'index d'origine est conservé
assert list(tgt.index) == [0, 2]
# aucune sélection mais filtre Segment A actif -> B et C
edit_t[app.SEL_COL] = False
app.st.session_state["leads_edit"] = edit_t
app.st.session_state["leads_filter"] = "🗂️ Segment A (sans site)"
tgt2, d2 = app._outreach_plan(df_t)
assert list(tgt2["name"]) == ["B", "C"], tgt2["name"].tolist()
assert "Segment A" in d2
# aucune sélection ni filtre -> toutes
app.st.session_state["leads_filter"] = "Tous les leads"
tgt3, d3 = app._outreach_plan(df_t)
assert list(tgt3["name"]) == ["A", "B", "C"]
assert "toutes les leads" in d3
app.st.session_state.pop("leads_edit", None)
out("[OK] _outreach_plan (sélection > filtre > toutes)")

# 14) v6 — analyze_ai_html : absence IA + form/contact -> Cible Prioritaire IA
r = app.analyze_ai_html(
    "<html><body><h1>Cabinet X</h1><form><input></form><p>Contactez-nous</p></body></html>")
assert r["target"] is True, r
assert "chatbot" in r["missing"] and "ai" in r["missing"]
assert r["has_form"] is True and r["has_contact"] is True
r2 = app.analyze_ai_html("<html><body><p>Notre chatbot IA et notre assistant AI répondent via Intercom et Crisp.</p></body></html>")
assert r2["target"] is False and not r2["missing"], r2
# faux positif français : « j'ai » (ai en minuscules) ne doit PAS compter comme de l'IA
r3 = app.analyze_ai_html("<html><body><p>Bonjour, j'ai une question. Merci.</p></body></html>")
assert "ai" in r3["missing"] and "ia" in r3["missing"], r3
out("[OK] analyze_ai_html (Cible Prioritaire IA + faux positifs français)")

# 15) audit_ai_batch (monkeypatch du scan réseau)
app.audit_ai_website = lambda url: {"missing": ["chatbot"], "has_form": True,
                                    "has_contact": True, "target": True,
                                    "detail": "scan ok"}
dfa = pd.DataFrame([{"name": "A", "website": "https://a.tg"},
                    {"name": "B", "website": "https://b.tg"}])
dfr = app.audit_ai_batch(dfa, max_workers=2)
assert (dfr["ai_target"] == app.AI_TARGET_YES).all(), dfr
assert (dfr["ai_audit"] == "scan ok").all()
assert list(dfr.index) == [0, 1]  # index d'origine conservé
out("[OK] audit_ai_batch (parallèle, colonnes ai_target/ai_audit)")

# 16) v6 — settings.json : persistance + sauvegarde instantanée (fichier temporaire)
import os as _os
import tempfile as _tmp

_tmp_path = _os.path.join(_tmp.gettempdir(), "scriba_test_settings_v6.json")
app.SETTINGS_FILE = _tmp_path  # type: ignore[assignment]
app.st.session_state.pop("_settings_hash", None)
app.st.session_state["agency"] = "Test & Co"
app.st.session_state["gemini_key"] = "AIza-test"
app.st.session_state["country"] = "Togo"
app.persist_settings()
loaded = app.load_settings()
assert loaded.get("agency") == "Test & Co"
assert loaded.get("gemini_key") == "AIza-test"
assert loaded.get("country") == "Togo"
with open(_tmp_path, encoding="utf-8") as f:
    _first = f.read()
app.persist_settings()  # rien n'a changé -> aucune écriture
with open(_tmp_path, encoding="utf-8") as f:
    assert f.read() == _first
app.st.session_state["agency"] = "Nouveau Nom"
app.persist_settings()  # changement -> écriture immédiate
assert app.load_settings()["agency"] == "Nouveau Nom"
_os.remove(_tmp_path)
out("[OK] settings.json (persistance + sauvegarde instantanée, idempotente)")

# 17) v6 — is_mobile_phone : indicatifs mobiles par pays
assert app.is_mobile_phone("+33 6 12 34 56 78")
assert not app.is_mobile_phone("+33 1 42 34 56 78")
assert app.is_mobile_phone("+228 90 12 34 56")   # Togo mobile 9x
assert not app.is_mobile_phone("+228 22 12 34 56")  # Togo fixe 2x
assert app.is_mobile_phone("+221 77 123 45 67")  # Sénégal mobile 7x
assert not app.is_mobile_phone("+221 33 123 45 67")
assert app.is_mobile_phone("+212 6 61 23 45 67")  # Maroc mobile 6/7
assert app.is_mobile_phone("+1 514 123 4567")    # Québec
assert not app.is_mobile_phone("")
assert not app.is_mobile_phone("22 22 33 44")
out("[OK] is_mobile_phone (mobiles FR/AF/QC vs fixes)")

# 18) v6 — tone_for_country + parse sortie Gemini (OBJET/CORPS)
assert "formel" in app.tone_for_country("France")
assert "chaleureux" in app.tone_for_country("Togo")
assert "chaleureux" in app.tone_for_country("Québec") or "professionnel" in app.tone_for_country("Québec")
assert "courtois" in app.tone_for_country("Allemagne")  # pays inconnu -> défaut
subj, body = app._parse_gen_email("OBJET: Sujet test\nCORPS:\nBonjour {LeadName},\n\nMerci.")
assert subj == "Sujet test" and "Bonjour {LeadName}" in body and "{LeadName}" in body
subj2, body2 = app._parse_gen_email("Ligne 1\nLigne 2\nLigne 3")
assert subj2 == "Ligne 1" and "Ligne 2" in body2
out("[OK] tone_for_country + _parse_gen_email")

# 19) v6 — payment_block selon le pays (Afrique -> split local, EU -> IBAN)
p1 = app.payment_block(app.MODE_COPY, "FR761234", "", country="France")
assert "IBAN" in p1 and "SEPA" in p1
p2 = app.payment_block(app.MODE_COPY, "FR761234", "", country="Togo")
assert "T-Money" in p2 or "FCFA" in p2
p3 = app.payment_block(app.MODE_AI, "", "Plan 50/50", country="Togo")
assert "Plan 50/50" in p3
p4 = app.payment_block(app.MODE_AI, "FR761234", "", country="France")
assert "IBAN" in p4
out("[OK] payment_block pays-conscient (Afrique / EU)")

# 20) v6 — apply_lead_filter : Cible Prioritaire IA + ICP 3-20 employés
df_ai = pd.DataFrame([
    {"name": "A", "website": "https://a.tg", "email": "", "phone": "",
     "segment": app.SEG_OK, "ai_target": app.AI_TARGET_YES, "employees": "8"},
    {"name": "B", "website": "https://b.tg", "email": "", "phone": "",
     "segment": app.SEG_OK, "ai_target": "", "employees": "45"},
    {"name": "C", "website": "", "email": "", "phone": "",
     "segment": app.SEG_NO_SITE, "ai_target": "", "employees": "12"},
])
assert app.apply_lead_filter(df_ai, "🎯 Cible Prioritaire IA").tolist() == [True, False, False]
assert app.apply_lead_filter(df_ai, "🏢 ICP 3-20 employés (IA)").tolist() == [True, False, True]
assert app.apply_lead_filter(df_ai, "Tous les leads").all()
# sans colonne v6 (données héritées) -> aucun crash, masque vide pour le filtre IA
assert app.apply_lead_filter(df_ai.drop(columns=["ai_target"]), "🎯 Cible Prioritaire IA").tolist() \
    == [False, False, False]
out("[OK] apply_lead_filter (Cible Prioritaire IA + ICP 3-20)")

# 21) v6 — audit_prompt : mode IA (ICP + faille) sans casser les modes existants
pa = app.audit_prompt(app.MODE_AI, "PME X", "Lomé Togo", segment=app.SEG_NO_SITE, lang="fr",
                      faille="aucun chatbot détecté")
assert "ICP" in pa and "3 à 20 employés" in pa and "aucun chatbot détecté" in pa
pc = app.audit_prompt(app.MODE_COPY, "Agence Y", "Paris France", segment=app.SEG_NO_SITE, lang="fr")
assert "ICP" not in pc  # ligne ICP réservée au mode AI
out("[OK] audit_prompt mode AI (ICP + faille)")

# 22) v6 — search_linkedin_profiles : filtrage des URL (sans réseau, DDGS mocké)
class FakeResults:
    def text(self, query, region="wt-wt", max_results=10):
        assert "site:linkedin.com/in/" in query and "Lomé" in query
        return [
            {"title": "Jean Dupont - Gérant - Agence X | LinkedIn",
             "href": "https://fr.linkedin.com/in/jeandupont"},
            {"title": "Autre résultat", "href": "https://exemple.tg/page"},
            {"title": "Marie K - Fondatrice | LinkedIn",
             "href": "https://www.linkedin.com/in/mariek"},
        ]

app.DDGS = lambda: FakeResults()
profils = app.search_linkedin_profiles("gérant", "Lomé", "Togo", region="wt-wt", max_results=5)
assert len(profils) == 2, profils
assert all("linkedin.com/in/" in p["url"] for p in profils)
assert "Jean Dupont" in profils[0]["name"]
assert "LinkedIn" not in profils[0]["name"]  # suffixe nettoyé
out("[OK] search_linkedin_profiles (Dorking + filtre URL + nettoyage nom)")

# 23) v7 — analyze_ai_html : extrait titre/meta/texte réels + nouveaux fournisseurs
r = app.analyze_ai_html(
    "<html><head><title>Cabinet Test | Lomé</title>"
    "<meta name='description' content='Soins dentaires à Lomé.'></head>"
    "<body><p>Nous soignons vos dents depuis 2005. Contactez-nous.</p>"
    "<form><input type='email'></form></body></html>")
assert r["title"] == "Cabinet Test | Lomé"
assert "Soins dentaires à Lomé" in r["meta"]
assert "soignons vos dents" in r["text"]
assert r["target"] is True  # pas d'IA + form + contact
# nouveau fournisseur Tawk.to détecté dans les scripts
r_tawk = app.analyze_ai_html(
    "<html><body><script src='https://embed.tawk.to/abc123/default'></script>"
    "<p>Bienvenue</p></body></html>")
assert "Tawk.to" in r_tawk["signals"], r_tawk["signals"]
assert r_tawk["target"] is False
# phrase IA écrite en toutes lettres (intelligence artificielle) = indice IA
r_ph = app.analyze_ai_html(
    "<html><body><p>Nous utilisons l'intelligence artificielle pour vous répondre plus vite.</p></body></html>")
assert r_ph["target"] is False  # « intelligence artificielle » = a de l'IA
out("[OK] analyze_ai_html enrichi (titre/meta/texte + Tawk + phrase IA explicite)")

# 24) v7 — audit_ai_website : fallback sans 'signals' (erreur réseau) sans crash
# (restaure d'abord la vraie fonction : le test 15 l'avait remplacée par un lambda)
_orig_audit_ai_website = app.audit_ai_website
import app as _app_mod  # noqa: E402  (le module réel est déjà chargé sous le nom « app »)
app.audit_ai_website = _app_mod.audit_ai_website
app.requests.get = lambda *a, **k: (_ for _ in ()).throw(Exception("boom réseau"))
base = app.audit_ai_website("https://exemple.tg")
assert "signals" in base and base["signals"] == []
assert base["target"] is False and base["detail"]
out("[OK] audit_ai_website : erreur réseau -> fallback complet (signals présent)")

# 25) v7 — fetch_snippet : contenu réel (titre + meta + paragraphes)
class FakeRespS:
    status_code = 200
    text = ("<html><head><title>Agence Test</title>"
            "<meta name='description' content='Agence immobilière à Paris.'></head>"
            "<body><p>Nous vendons des biens de prestige depuis 2010.</p>"
            "<p>Contactez-nous dès aujourd'hui.</p></body></html>")
app.requests.get = lambda *a, **k: FakeRespS()
snip = app.fetch_snippet("https://agence.test")
assert "Agence Test" in snip and "Agence immobilière à Paris" in snip
assert "vendons des biens" in snip
out("[OK] fetch_snippet : titre + meta + paragraphes réels")

# 26) v7 — _parse_gen_email : variantes markdown / anglaises / espaces
s1, b1 = app._parse_gen_email("**OBJET:** Sujet en gras\n**CORPS:**\nBonjour {LeadName}")
assert s1 == "Sujet en gras" and "Bonjour {LeadName}" in b1
s2, b2 = app._parse_gen_email("Subject: Hello there\nBody:\nThis is the body.")
assert s2 == "Hello there" and "This is the body." in b2
s3, b3 = app._parse_gen_email("Sujet : Avec espaces\nCorps :\nDu contenu")
assert s3 == "Avec espaces" and "Du contenu" in b3
out("[OK] _parse_gen_email : markdown **OBJET:** + variantes Subject/Body + espaces")

# 27) v7 — personalize_email / personalize_wa : prompts incluent le contenu réel
class FakeGenResp2:
    text = "OBJET: {LeadName} test\nCORPS:\nBonjour {LeadName},\n\nMerci."

app.gemini_generate = lambda *a, **k: FakeGenResp2().text
lead_p = pd.Series({"name": "Cabinet X", "website": "https://x.tg", "email": "x@x.tg",
                    "phone": "+228 90 00 00 00", "snippet": "Cabinet dentaire à Lomé.",
                    "employees": "8", "ai_audit": "aucun chatbot"})
subj_p, body_p = app.personalize_email(
    app.MODE_AI, "Agence", "Lomé", "Togo", "fr", lead_p,
    audit="Audit IA : pas de chatbot.", faille="aucun chatbot détecté", api_key="k")
assert subj_p == "{LeadName} test" and "{LeadName}" in body_p
wa_p = app.personalize_wa(app.MODE_AI, "Agence", "Lomé", "Togo", "fr", lead_p,
                          faille="aucun chatbot", api_key="k")
assert wa_p and "{LeadName}" in wa_p
out("[OK] personalize_email / personalize_wa (prompt avec contenu réel + faille)")

# 28) v7 — _gen_both_gemini_cb : email + WhatsApp en un clic (Gemini mocké)
def _fake_gen_both(api_key, model, prompt, temperature=0.7, max_tokens=700,
                   max_retries=3, base_wait=5.0):
    if "WhatsApp" in prompt or "prospection WhatsApp" in prompt:
        return "Bonjour {LeadName} 👋 On en parle ?"
    return ("OBJET: {LeadName} — Sujet\nCORPS:\nBonjour {LeadName},\n\n{Audit}\n\n"
            "À très vite,\n{AgencyName}")

app.gemini_generate = _fake_gen_both
app.st.session_state["leads"] = pd.DataFrame([
    {"name": "Cabinet Test", "website": "https://cabinet.tg", "email": "c@x.tg",
     "phone": "+228 90 12 34 56", "source": "CSV", "flag": "", "segment": app.SEG_OK,
     "snippet": "Cabinet dentaire à Lomé.", "audit": "", "status": "", "linkedin": "",
     "employees": "8", "ai_target": app.AI_TARGET_YES, "ai_audit": "aucun chatbot"}])
_ed = app.st.session_state["leads"].copy()
_ed[app.SEL_COL] = [True]
app.st.session_state["leads_edit"] = _ed
app.st.session_state["leads_filter"] = "Tous les leads"
app.st.session_state["gemini_key"] = "k"
app.st.session_state["mode"] = app.MODE_AI
app.st.session_state["lang"] = "fr"
app.st.session_state["agency"] = "MaisonNova"
app.st.session_state["city"] = "Lomé"
app.st.session_state["country"] = "Togo"
app.st.session_state["audits"] = {}
app.st.session_state.pop("_out_error", None)
app._gen_both_gemini_cb()
assert not app.st.session_state.get("_out_error"), app.st.session_state.get("_out_error")
assert "{AgencyName}" in app.st.session_state["email_body"]
assert "{LeadName}" in app.st.session_state["wa_msg"]
app.st.session_state.pop("leads_edit", None)
out("[OK] _gen_both_gemini_cb : templates email + WhatsApp générés en un clic")

# 29) v7 — send_via_smtp : structure MIME réelle (alternative + related + image inline)
_sent = []

class _FakeSMTP:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, m):
        _sent.append(m)

_orig_smtp = app.smtplib.SMTP_SSL
app.smtplib.SMTP_SSL = _FakeSMTP
try:
    app.send_via_smtp("me@gmail.com", "pw", "client@x.tg", "Objet", "Bonjour",
                      html_body="<p>Bonjour</p>",
                      images=[{"maintype": "image", "subtype": "png", "data": b"x"}])
finally:
    app.smtplib.SMTP_SSL = _orig_smtp
assert len(_sent) == 1
_ctypes = [p.get_content_type() for p in _sent[0].walk()]
assert _ctypes == ["multipart/alternative", "text/plain", "multipart/related",
                   "text/html", "image/png"], _ctypes
_imgs = [p for p in _sent[0].walk() if p.get_content_type() == "image/png"]
assert _imgs and _imgs[0].get("Content-ID") == "<img_0>"
out("[OK] send_via_smtp : MIME réel valide (image inline cid:img_0)")

# 30) v7 — outreach_worker : envoi réel par lead + erreur 535 journalisée
_state = {"queue": [{"name": "A", "email": "a@x.tg", "subject": "S", "body": "B"},
                     {"name": "B", "email": "b@x.tg", "subject": "S", "body": "B"}],
          "log": [], "pos": 0, "done": False, "stopped": False,
          "stats": {"contacted": 0, "wa": 0, "mail": 0, "fail": 0, "history": []}}
_calls = []


def _fake_send(item):
    _calls.append(item["email"])
    if item["email"] == "b@x.tg":
        raise Exception("535 BadCredentials gsmtp")

app.outreach_worker(_state, app.threading.Event(), _fake_send, 0, 0)
assert _calls == ["a@x.tg", "b@x.tg"] and _state["stats"]["mail"] == 1 \
    and _state["stats"]["fail"] == 1
assert any("535" in l or "Identifiants" in l for l in _state["log"])
out("[OK] outreach_worker : envoi réel par lead, 535 journalisée")

# 31) v7 — spam_risk_warning : détection des mots déclencheurs
assert app.spam_risk_warning("Offre exceptionnelle -100% gratuit") == ["gratuit", "offre exceptionnelle", "100%"]
assert app.spam_risk_warning("Bonjour, proposition de collaboration") == []
assert "free" in app.spam_risk_warning("Get free access now")
assert "urgent" in app.spam_risk_warning("", "Réponse urgente demandée")
out("[OK] spam_risk_warning (déclencheurs FR/EN détectés)")

# 32) v7 — send_via_smtp : en-têtes anti-spam (nom d'affichage, Reply-To, List-Unsubscribe)
_sent2 = []

class _FakeSMTP2:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, m):
        _sent2.append(m)

_orig_smtp2 = app.smtplib.SMTP_SSL
app.smtplib.SMTP_SSL = _FakeSMTP2
try:
    app.send_via_smtp("me@gmail.com", "pw", "client@x.tg", "Sujet", "Corps",
                      sender_name="Mon Agence")
finally:
    app.smtplib.SMTP_SSL = _orig_smtp2
_msg2 = _sent2[0]
assert _msg2["From"] == "Mon Agence <me@gmail.com>", _msg2["From"]
assert _msg2["Reply-To"] == "me@gmail.com"
assert "unsubscribe" in _msg2["List-Unsubscribe"]
assert _msg2["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
out("[OK] send_via_smtp : en-têtes anti-spam (From nom + Reply-To + List-Unsubscribe)")

# 33) v7 — parse_gmail_accounts : compte principal + comptes additionnels
app.st.session_state["gmail_user"] = "a@gmail.com"
app.st.session_state["gmail_pass"] = "pw-a"
app.st.session_state["gmail_accounts"] = "b@gmail.com:pw-b\nc@gmail.com:pw-c\nligne sans deux-points\n"
_accs = app.parse_gmail_accounts()
assert _accs == [("a@gmail.com", "pw-a"), ("b@gmail.com", "pw-b"), ("c@gmail.com", "pw-c")], _accs
app.st.session_state["gmail_accounts"] = ""
assert app.parse_gmail_accounts() == [("a@gmail.com", "pw-a")]
app.st.session_state["gmail_user"] = ""
app.st.session_state["gmail_pass"] = ""
assert app.parse_gmail_accounts() == []
out("[OK] parse_gmail_accounts (principal + additionnels, lignes propres ignorées)")

# 34) v7 — _account_send_fn : roulement round-robin sur les comptes
app.st.session_state["gmail_user"] = "a@gmail.com"
app.st.session_state["gmail_pass"] = "pw-a"
app.st.session_state["gmail_accounts"] = "b@gmail.com:pw-b"
_sent3 = []

class _FakeSMTP3:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, m):
        _sent3.append(m["From"])

_orig_smtp3 = app.smtplib.SMTP_SSL
app.smtplib.SMTP_SSL = _FakeSMTP3
app.st.session_state["_daily_sent"] = {}
fn = app._account_send_fn("Mon Agence")
try:
    for i in range(4):
        fn({"email": f"x{i}@x.tg", "subject": "S", "body": "B"})
finally:
    app.smtplib.SMTP_SSL = _orig_smtp3
# a -> b -> a -> b (roulement)
assert _sent3 == ["Mon Agence <a@gmail.com>", "Mon Agence <b@gmail.com>",
                  "Mon Agence <a@gmail.com>", "Mon Agence <b@gmail.com>"], _sent3
# compteur quotidien incrémenté
assert app.daily_sent_count() == 4
out("[OK] _account_send_fn : roulement multi-comptes + compteur quotidien")

# 35) v7 — réchauffement : limite progressive par semaine + cap de file
app.st.session_state["warmup_enabled"] = True
app.st.session_state["warmup_start"] = app.datetime.now().date()  # semaine 0 -> 10/jour
assert app.daily_send_limit() == 10
app.st.session_state["_daily_sent"] = {str(app.datetime.now().date()): 8}
assert app.daily_remaining() == 2
_q = [{"email": f"x{i}@x.tg"} for i in range(5)]
_q2, note = app._outreach_queue_cap(_q)
assert len(_q2) == 2 and note and "Quota" in note
app.st.session_state["warmup_enabled"] = False
app.st.session_state["daily_limit"] = 0
assert app.daily_send_limit() == 0 and app.daily_remaining() == 999_999
_q3, note3 = app._outreach_queue_cap(_q)
assert len(_q3) == 5 and not note3
out("[OK] réchauffement progressif + cap de file au quota quotidien")

# 36) v7 — settings : la date warmup_start est sérialisée en ISO (pas de crash JSON)
import json as _json
_snap = app._settings_snapshot()
assert isinstance(_snap.get("warmup_start"), str)  # date -> ISO
_json.dumps(_snap)  # ne doit pas lever
out("[OK] _settings_snapshot : date sérialisée en ISO (JSON valide)")

# 37) v7 — _normalize_leads_index : index dupliqués (éditeur dynamique) -> RangeIndex
import pandas as _pd
leads_dup = _pd.DataFrame([
    {"name": "A", "website": "https://a.tg", "email": "a@x.tg", "segment": app.SEG_OK},
    {"name": "B", "website": "https://b.tg", "email": "", "segment": app.SEG_NO_SITE},
], index=[20, 20])  # deux leads d'index 20 -> collision de clés widgets
app.st.session_state["leads"] = leads_dup
edit_dup = leads_dup.copy()
edit_dup[app.SEL_COL] = [True, False]
app.st.session_state["leads_edit"] = edit_dup
app.st.session_state["leads_version"] = 5
app.st.session_state["edit_version"] = 5
app._normalize_leads_index()
norm = app.st.session_state["leads"]
assert norm.index.is_unique and list(norm.index) == [0, 1], norm.index
assert list(norm["name"]) == ["A", "B"]  # ordre conservé
n_edit = app.st.session_state["leads_edit"]
assert n_edit[app.SEL_COL].tolist() == [True, False]  # sélection ✓ préservée
app.st.session_state["leads_version"] = 0
app.st.session_state["edit_version"] = -1
app.st.session_state.pop("leads_edit", None)
app.st.session_state["leads"] = empty = _pd.DataFrame(columns=app.LEAD_COLS)
app._normalize_leads_index()  # vide -> aucun crash
out("[OK] _normalize_leads_index : index dupliqués réparés (clés widgets uniques)")

# 38) v7 — gemini_generate : bascule automatique 429/404 -> autre modèle
# (restaure la vraie fonction : les tests 27/28 l'avaient remplacée par un mock)
app.gemini_generate = _ORIG_GEMINI_GENERATE
_fb_calls = []

class _FakeGenRespFB:
    text = "réponse de secours"

class _FakeGenClientFB:
    def __init__(self, api_key):
        pass

    class models:
        @staticmethod
        def generate_content(model, contents, config=None):
            _fb_calls.append(model)
            if model == "gemini-3.6-flash":
                raise Exception("429 RESOURCE_EXHAUSTED quota")
            if model == "gemini-2.5-flash":
                raise Exception("404 NOT_FOUND")
            return _FakeGenRespFB()

app._genai = type("G", (), {"Client": _FakeGenClientFB})()
app._GENAI_STATE = "new"
app.time.sleep = lambda s: None
app.st.toast = lambda *a, **k: None
_fb = app.gemini_generate("k", "gemini-3.6-flash", "p", max_retries=1, base_wait=0.001)
assert _fb == "réponse de secours"
assert "gemini-3.5-flash" in _fb_calls  # a sauté 3.6 (429) et 2.5 (404)
# modèle sans erreur -> réponse directe, pas de fallback
_fb_calls.clear()
_fb2 = app.gemini_generate("k", "gemini-3.5-flash", "p", max_retries=1, base_wait=0.001)
assert _fb2 == "réponse de secours" and len(_fb_calls) == 1
out("[OK] gemini_generate : bascule automatique 429/404 -> modèle de secours")

# 39) v7 — coercition de types des settings (settings.json en clair) :
# "true"/"" -> bool, "" -> int, sinon crash des widgets ('str' object
# cannot be interpreted as an integer) sur déploiement/session partagée
app.st.session_state["warmup_enabled"] = ""          # corrompu : str vide
app.st.session_state["lang_en"] = "true"             # str au lieu de bool
app.st.session_state["daily_limit"] = ""             # str vide au lieu de int
app.st.session_state["warmup_start"] = "2026-08-14"  # ISO str -> date
app.init_session()
assert app.st.session_state["warmup_enabled"] is False, app.st.session_state["warmup_enabled"]
assert app.st.session_state["lang_en"] is True
assert app.st.session_state["daily_limit"] == 200
assert app.st.session_state["warmup_start"].__class__.__name__ == "date"
# boot vierge (aucun fichier de settings) -> défauts sains, pas de crash
_orig_sf = app.SETTINGS_FILE
app.SETTINGS_FILE = app.Path("_no_such_settings_regression.json")  # type: ignore[assignment]
app.st.session_state.pop("warmup_enabled", None)
app.st.session_state.pop("daily_limit", None)
app.st.session_state.pop("warmup_start", None)
app.init_session()
assert app.st.session_state["warmup_enabled"] is False
assert app.st.session_state["daily_limit"] == 200
app.SETTINGS_FILE = _orig_sf
out("[OK] coercition de types settings (bool/int/date) + défauts boot vierge")

# 40) _bulk_parse_emails_from_excel : détection colonne email + noms + doublons
import io as _io
import pandas as _pd_bulk

# Cas 1 : colonne "Email" explicite + colonne "Nom"
df1 = _pd_bulk.DataFrame({"Nom": ["Alice", "Bob", "Charlie"], "Email": ["alice@test.com", "bob@test.com", "charlie@test.com"]})
buf1 = _io.BytesIO()
df1.to_excel(buf1, index=False)
buf1.seek(0)
buf1.name = "test.xlsx"
result1 = app._bulk_parse_emails_from_excel(buf1)
assert len(result1) == 3, f"Expected 3, got {len(result1)}"
assert result1.iloc[0]["email"] == "alice@test.com"
assert result1.iloc[0]["name"] == "Alice"
out("[OK] _bulk_parse_emails_from_excel : colonne Email + Nom")

# Cas 2 : email trouvé automatiquement dans la 1ère colonne
df2 = _pd_bulk.DataFrame({"col1": ["alice@test.com", "bob@test.com"]})
buf2 = _io.BytesIO()
df2.to_excel(buf2, index=False)
buf2.seek(0)
buf2.name = "test.xlsx"
result2 = app._bulk_parse_emails_from_excel(buf2)
assert len(result2) == 2
assert result2.iloc[0]["email"] == "alice@test.com"
out("[OK] _bulk_parse_emails_from_excel : détection auto colonne email")

# Cas 3 : doublons → dédupliqués
df3 = _pd_bulk.DataFrame({"mail": ["dup@test.com", "dup@test.com", "unique@test.com"]})
buf3 = _io.BytesIO()
df3.to_excel(buf3, index=False)
buf3.seek(0)
buf3.name = "test.xlsx"
result3 = app._bulk_parse_emails_from_excel(buf3)
assert len(result3) == 2, f"Expected 2 deduplicated, got {len(result3)}"
out("[OK] _bulk_parse_emails_from_excel : doublons dédupliqués")

# Cas 4 : CSV
df4 = _pd_bulk.DataFrame({"Email": ["csv1@test.com", "csv2@test.com"]})
buf4 = _io.BytesIO()
df4.to_csv(buf4, index=False)
buf4.seek(0)
buf4.name = "test.csv"
result4 = app._bulk_parse_emails_from_excel(buf4)
assert len(result4) == 2
out("[OK] _bulk_parse_emails_from_excel : CSV")

# Cas 5 : email dans une cellule avec du texte
df5 = _pd_bulk.DataFrame({"info": ["Contact: hello@world.com", "N/A", "test@email.org"]})
buf5 = _io.BytesIO()
df5.to_excel(buf5, index=False)
buf5.seek(0)
buf5.name = "test.xlsx"
result5 = app._bulk_parse_emails_from_excel(buf5)
assert len(result5) == 2, f"Expected 2, got {len(result5)}"
assert result5.iloc[0]["email"] == "hello@world.com"
out("[OK] _bulk_parse_emails_from_excel : email extrait de cellule texte")

# 41) bulk_mass_worker : envoi avec erreur ignorée + quota
import threading as _thr
_stats = {"sent": 0, "failed": 0, "errors": []}
_state = {
    "queue": [
        {"email": "a@test.com", "name": "A", "subject": "s1", "body": "b1"},
        {"email": "bad@test.com", "name": "Bad", "subject": "s2", "body": "b2"},
        {"email": "c@test.com", "name": "C", "subject": "s3", "body": "b3"},
    ],
    "total_in_file": 3,
    "log": [],
    "pos": 0,
    "done": False,
    "stopped": False,
    "quota": 500,
    "stats": _stats,
}
_call_count = [0]
def _mock_send(item):
    _call_count[0] += 1
    if item["email"] == "bad@test.com":
        raise smtplib.SMTPRecipientsRefused(550, b"Invalid")

_stop = _thr.Event()
app.bulk_mass_worker(_state, _stop, _mock_send, 0, 0)
assert _state["done"] is True
assert _state["stats"]["sent"] == 2  # a@test.com + c@test.com
assert _state["stats"]["failed"] == 1  # bad@test.com
assert len(_state["stats"]["errors"]) == 1
assert _state["stats"]["errors"][0]["email"] == "bad@test.com"
assert _call_count[0] == 3  # les 3 ont été tentés
out("[OK] bulk_mass_worker : erreur ignorée, envoi continue")

# 42) bulk_mass_worker : arrêt par quota
app.st.session_state["_daily_sent"] = {}  # reset compteur quotidien
daily_key = str(app.datetime.now().date())
app.st.session_state["_daily_sent"][daily_key] = 0  # compteur propre
_stats2 = {"sent": 0, "failed": 0, "errors": []}
_state2 = {
    "queue": [{"email": f"u{i}@t.com", "name": f"U{i}", "subject": "s", "body": "b"} for i in range(10)],
    "total_in_file": 10,
    "log": [],
    "pos": 0,
    "done": False,
    "stopped": False,
    "quota": 3,  # simulate quota at 3
    "stats": _stats2,
}
def _mock_send_inc(item):
    """Mock qui incrémente le compteur quotidien (comme _account_send_fn)."""
    with app._DAILY_LOCK:
        _ds = app.st.session_state.setdefault("_daily_sent", {})
        _ds[daily_key] = int(_ds.get(daily_key, 0)) + 1
app.bulk_mass_worker(_state2, _thr.Event(), _mock_send_inc, 0, 0)
assert _state2["stats"]["sent"] == 3, f"sent={_state2['stats']['sent']}"
assert _state2["pos"] == 3
assert any("Quota" in l for l in _state2["log"])
out("[OK] bulk_mass_worker : arrêt automatique au quota")

# 43) bulk_mass_worker : arrêt manuel (stop_event)
_stats3 = {"sent": 0, "failed": 0, "errors": []}
_stop3 = _thr.Event()
_state3 = {
    "queue": [{"email": f"u{i}@t.com", "name": f"U{i}", "subject": "s", "body": "b"} for i in range(5)],
    "total_in_file": 5,
    "log": [],
    "pos": 0,
    "done": False,
    "stopped": False,
    "quota": 999,
    "stats": _stats3,
}
_n = [0]
def _mock_stop(item):
    _n[0] += 1
    if _n[0] == 2:
        _stop3.set()
app.bulk_mass_worker(_state3, _stop3, _mock_stop, 0, 0)
assert _state3["stopped"] is True
assert _state3["pos"] == 2  # arrêt après 2 envois
out("[OK] bulk_mass_worker : arrêt manuel (stop_event)")

# 44) _generate_tracking_id : ID unique par destinataire
id1 = app._generate_tracking_id("test@example.com", 12345)
id2 = app._generate_tracking_id("test@example.com", 12345)
id3 = app._generate_tracking_id("other@example.com", 12345)
assert isinstance(id1, str) and len(id1) == 12
assert id1 != id2  # même email, même campagne → IDs différents (uuid)
assert id1 != id3  # emails différents → IDs différents
out("[OK] _generate_tracking_id : ID unique par destinataire")

# 45) _generate_tracking_pixel_html : pixel vide si pas de base_url, sinon HTML
assert app._generate_tracking_pixel_html("abc123", "") == ""
pixel = app._generate_tracking_pixel_html("abc123", "https://example.com")
assert 'img src=' in pixel
assert 'abc123' in pixel
assert 'track=open' in pixel
out("[OK] _generate_tracking_pixel_html : vide si pas de base_url, pixel sinon")

# 46) _wrap_link_for_tracking : lien wrappé avec base_url
wrapped = app._wrap_link_for_tracking("https://target.com", "abc123", "https://track.com")
assert "track.com" in wrapped
assert "abc123" in wrapped
assert "target.com" in wrapped
assert wrapped == app._wrap_link_for_tracking("https://target.com", "abc123", "https://track.com")
out("[OK] _wrap_link_for_tracking : lien wrappé correctement")

# 47) _wrap_link_for_tracking : pas de wrapping sans base_url
assert app._wrap_link_for_tracking("https://target.com", "abc123", "") == "https://target.com"
out("[OK] _wrap_link_for_tracking : pas de wrapping sans base_url")

# 48) _campaign_create : tracking_id ajouté à chaque destinataire
camp = app._campaign_create(
    subject="Test", body="Body", html="<p>Body</p>",
    recipients=[{"email": "a@test.com", "name": "A"},
                {"email": "b@test.com", "name": "B"}],
    scheduled_at="")
assert camp["total"] == 2
for r in camp["recipients"]:
    assert "tracking_id" in r
    assert r["status"] == app.TRACK_PENDING
    assert r["sent_at"] == ""
    assert r["error"] == ""
    assert isinstance(r["clicked_links"], list)
# Nettoyage : retirer la campagne test
camps = app._load_campaigns()
camps = [c for c in camps if c.get("id") != camp["id"]]
app._save_campaigns(camps)
out("[OK] _campaign_create : tracking_id + statut par destinataire")

# 49) _campaign_create : statut scheduled si date future
camp2 = app._campaign_create(
    subject="Test2", body="Body2", html="<p>Body2</p>",
    recipients=[{"email": "c@test.com", "name": "C"}],
    scheduled_at="2099-01-01T12:00:00")
assert camp2["recipients"][0]["status"] == app.TRACK_SCHEDULED
assert camp2["state"] == app.CAMP_PLANNED
# Nettoyage
camps = app._load_campaigns()
camps = [c for c in camps if c.get("id") != camp2["id"]]
app._save_campaigns(camps)
out("[OK] _campaign_create : scheduled → TRACK_SCHEDULED + CAMP_PLANNED")

# 50) _update_recipient_status_raw : mise à jour dans le fichier
camp3 = app._campaign_create(
    subject="Test3", body="Body3", html="<p>Body3</p>",
    recipients=[{"email": "d@test.com", "name": "D"},
                {"email": "e@test.com", "name": "E"}],
    scheduled_at="")
app._update_recipient_status_raw(camp3["id"], "d@test.com", app.TRACK_SENT)
camps = app._load_campaigns()
for c in camps:
    if c.get("id") == camp3["id"]:
        for r in c["recipients"]:
            if r["email"] == "d@test.com":
                assert r["status"] == app.TRACK_SENT
                assert r["sent_at"] != ""
            elif r["email"] == "e@test.com":
                assert r["status"] == app.TRACK_PENDING
        assert c["sent"] == 1
        assert c["failed"] == 0
        break
# Nettoyage
camps = [c for c in camps if c.get("id") != camp3["id"]]
app._save_campaigns(camps)
out("[OK] _update_recipient_status_raw : statut mis à jour")

# 51) _update_recipient_status_raw : détection bounce
app._update_recipient_status_raw(camp3["id"], "e@test.com", app.TRACK_BOUNCED, error="550 mailbox not found")
camps = app._load_campaigns()
for c in camps:
    if c.get("id") == camp3["id"]:
        for r in c["recipients"]:
            if r["email"] == "e@test.com":
                assert r["status"] == app.TRACK_BOUNCED
                assert r["error"] == "550 mailbox not found"
        assert c["bounced"] == 1
        break
# Nettoyage final
camps = [c for c in camps if c.get("id") != camp3["id"]]
app._save_campaigns(camps)
out("[OK] _update_recipient_status_raw : bounce détecté")

# 52) _enrich_html_with_tracking : pixel + liens wrappés
html_orig = '<p><a href="https://example.com">Lien</a></p></div>'
html_tracked = app._enrich_html_with_tracking(html_orig, "abc123", "https://track.com")
assert 'track.com' in html_tracked
assert 'abc123' in html_tracked
assert 'pixel' not in html_tracked.lower() or 'img_' in html_tracked
out("[OK] _enrich_html_with_tracking : pixel + liens wrappés")

# 53) _enrich_html_with_tracking : rien si pas de base_url
html_same = app._enrich_html_with_tracking(html_orig, "abc123", "")
assert html_same == html_orig
out("[OK] _enrich_html_with_tracking : pas de modification sans base_url")

out("TOUS LES TESTS UNITAIRES OK")
