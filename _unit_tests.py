# -*- coding: utf-8 -*-
"""Tests unitaires des fonctionnalités ajoutées : secteurs combinables,
filtres de leads, lien WhatsApp, OpenAI (mocké), retry Gemini (mocké)."""
from __future__ import annotations

import importlib.util
import sys

import pandas as pd
import streamlit as st

st.toast = lambda *a, **k: None
st.rerun = lambda *a, **k: None

spec = importlib.util.spec_from_file_location("app", "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


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

# 4ter) body_to_html : email HTML Luxe
html = app.body_to_html("Bonjour {LeadName},\n\nCeci est un test.")
assert html.startswith("<div") and "c9a45c" in html and "Bonjour" in html
out("[OK] body_to_html (email HTML Luxe)")

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

out("TOUS LES TESTS UNITAIRES OK")
