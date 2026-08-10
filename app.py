# -*- coding: utf-8 -*-
"""
====================================================================
  SCRIBA OMNISCIENT PROSPECTOR — v1.0
  Tableau de bord Streamlit de prospection automatisée
  ------------------------------------------------------------------
  3 modèles d'affaires depuis un seul dashboard :
    1) European Copywriting Sniper   -> agences immobilières (EU)
    2) Local Web-Design Hunter       -> PME sans site (local / Afrique)
    3) Local SEO Visibility          -> fiches Google Maps faibles

  Stack : Streamlit · Google GenAI (Gemini) · Pandas · Requests ·
          BeautifulSoup · ddgs (DuckDuckGo) · smtplib · Composio

  Lancement :  streamlit run app.py
====================================================================
"""

from __future__ import annotations

import random
import re
import smtplib
import ssl
import threading
import time
import webbrowser
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import quote

import inspect

import pandas as pd
import requests
import streamlit as st

# ------------------------------------------------------------------
#  Imports optionnels (dégradation gracieuse si non installés)
# ------------------------------------------------------------------

try:  # recherche DuckDuckGo (nouveau paquet, l'ancien est déprécié)
    from ddgs import DDGS
    _DDGS_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        _DDGS_AVAILABLE = True
    except ImportError:
        DDGS = None
        _DDGS_AVAILABLE = False

try:  # Gemini — nouveau SDK unifié google-genai
    from google import genai as _genai
    from google.genai import types as _genai_types
    _GENAI_STATE = "new"
except Exception:
    try:  # ancien SDK google-generativeai
        import google.generativeai as _genai_legacy
        _GENAI_STATE = "legacy"
    except Exception:
        _genai_legacy = None
        _GENAI_STATE = None

try:
    from composio import Composio as _Composio
    _COMPOSIO_AVAILABLE = True
except ImportError:
    _COMPOSIO_AVAILABLE = False

try:  # OpenAI — fournisseur IA OPTIONNEL (amélioration d'emails / messages)
    from openai import OpenAI as _OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OpenAI = None
    _OPENAI_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    _BS4_AVAILABLE = False

# ------------------------------------------------------------------
#  Constantes
# ------------------------------------------------------------------

MODE_COPY = "European Copywriting Sniper"
MODE_WEB = "Local Web-Design Hunter"
MODE_SEO = "Local SEO Visibility"
MODES = [MODE_COPY, MODE_WEB, MODE_SEO]

MODE_INFO = {
    MODE_COPY: {
        "emoji": "🖋️",
        "label": "🖋️ European Copywriting Sniper",
        "desc": "Cible les agences immobilières — réécriture d'annonces en style luxe, emails avec IBAN Grey.co.",
    },
    MODE_WEB: {
        "emoji": "🌍",
        "label": "🌍 Local Web-Design Hunter",
        "desc": "Cible les PME sans site web — argumentaire diaspora, WhatsApp, paiement T-Money / Flooz.",
    },
    MODE_SEO: {
        "emoji": "📍",
        "label": "📍 Local SEO Visibility",
        "desc": "Cible les fiches Google Maps faibles — QR code + avis 5 étoiles, WhatsApp, paiement local.",
    },
}

GEMINI_MODELS = [
    "gemini-3.6-flash",   # dernier modèle stable -> DÉFAUT (le plus susceptible d'être dispo)
    "gemini-3.5-flash",
    "gemini-2.5-flash",   # toujours supporté (compromis coût/performance)
    "gemini-2.5-pro",
    # NB : gemini-2.0-flash retiré de la liste — modèle arrêté par Google (404 NOT_FOUND)
]

LEAD_COLS = ["name", "website", "email", "phone", "source", "flag", "segment", "snippet", "audit", "status"]

# --- Segments de prospection ciblée (architecture des leads) ---
SEG_NO_SITE = "Segment A — Sans site web"
SEG_BAD_SITE = "Segment B — Site médiocre"
SEG_OK = "Site correct"
SEGMENTS = [SEG_NO_SITE, SEG_BAD_SITE, SEG_OK]

# Langue de génération des messages IA (toggle instantané FRANÇAIS / ENGLISH)
LANGS = {"fr": "FRANÇAIS", "en": "ENGLISH"}

# Colonne de sélection des lignes (Streamlit >= 1.49 : `selection_mode` a été retiré
# de st.data_editor, on utilise une colonne checkbox à la place).
SEL_COL = "✓ Sélection"

DEFAULT_AFRICA_PAYMENT = "10 000 FCFA (acompte) / 40 000 FCFA (solde à la livraison) — par T-Money ou Flooz"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

USER_ID = "scriba-prospector-local"

PLACEHOLDERS = ("{AgencyName} · {LeadName} · {LeadWebsite} · {LeadEmail} · "
                "{Location} · {Mode} · {Audit} · {PaymentPlan}")

# --- requêtes DuckDuckGo par mode ---------------------------------
QUERIES = {
    MODE_COPY: [
        "agence immobilière {city} {country}",
        "real estate agency {city} {country}",
        "immobilienmakler {city} {country}",
        "agence immobilière de luxe {city} {country}",
    ],
    MODE_WEB: [
        "restaurant {city} {country}",
        "coiffeur {city} {country}",
        "boutique {city} {country}",
        "petite entreprise {city} {country}",
        "garage auto {city} {country}",
    ],
    MODE_SEO: [
        "meilleur restaurant {city} {country} avis",
        "hôtel {city} {country} avis clients",
        "pharmacie {city} {country} horaires",
        "salon de coiffure {city} {country} avis",
    ],
}

# --- modèles OpenAI (fournisseur OPTIONNEL) -----------------------
OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
    "o3-mini",
]

# --- secteurs ciblables par mode (combinables dans la recherche) --
SECTORS = {
    MODE_COPY: [
        {"label": "🏠 Agences immobilières (toutes)", "queries": [
            "agence immobilière {city} {country}",
            "real estate agency {city} {country}",
            "immobilienmakler {city} {country}",
        ]},
        {"label": "✨ Immobilier de luxe", "queries": [
            "agence immobilière de luxe {city} {country}",
            "luxury real estate agency {city} {country}",
        ]},
        {"label": "🔑 Location & gestion locative", "queries": [
            "agence location {city} {country}",
            "gestion locative {city} {country}",
            "property management {city} {country}",
        ]},
        {"label": "🏷️ Transaction & vente", "queries": [
            "agence vente immobilière {city} {country}",
            "real estate sales {city} {country}",
        ]},
        {"label": "🏗️ Promoteurs & immobilier neuf", "queries": [
            "promoteur immobilier {city} {country}",
            "immobilier neuf {city} {country}",
            "new build property {city} {country}",
        ]},
    ],
    MODE_WEB: [
        {"label": "🍽️ Restaurants & cafés", "queries": [
            "restaurant {city} {country}", "café {city} {country}", "bar {city} {country}",
        ]},
        {"label": "🏠 Agences immobilières", "queries": [
            "agence immobilière {city} {country}", "real estate agency {city} {country}",
        ]},
        {"label": "💇 Coiffure & beauté", "queries": [
            "coiffeur {city} {country}", "salon de coiffure {city} {country}",
            "salon de beauté {city} {country}", "barber shop {city} {country}",
        ]},
        {"label": "🛍️ Boutiques & commerces", "queries": [
            "boutique {city} {country}", "magasin {city} {country}", "shop {city} {country}",
        ]},
        {"label": "🚗 Garages & automobile", "queries": [
            "garage auto {city} {country}", "garage automobile {city} {country}",
            "mécanicien {city} {country}", "car workshop {city} {country}",
        ]},
        {"label": "🏨 Hôtels & hébergement", "queries": [
            "hôtel {city} {country}", "hotel {city} {country}", "auberge {city} {country}",
        ]},
        {"label": "🏥 Santé (cliniques, pharmacies)", "queries": [
            "clinique {city} {country}", "pharmacie {city} {country}",
            "cabinet médical {city} {country}",
        ]},
        {"label": "🎓 Éducation & formation", "queries": [
            "école {city} {country}", "centre de formation {city} {country}",
            "école de formation {city} {country}",
        ]},
        {"label": "💪 Fitness & sports", "queries": [
            "salle de sport {city} {country}", "fitness {city} {country}",
            "club de sport {city} {country}",
        ]},
        {"label": "🥐 Boulangeries & pâtisseries", "queries": [
            "boulangerie {city} {country}", "pâtisserie {city} {country}",
        ]},
        {"label": "✈️ Voyages & tourisme", "queries": [
            "agence de voyage {city} {country}", "travel agency {city} {country}",
        ]},
        {"label": "💻 Services informatiques", "queries": [
            "service informatique {city} {country}", "bureau informatique {city} {country}",
            "photocopie {city} {country}",
        ]},
    ],
    MODE_SEO: [
        {"label": "🍽️ Restaurants (avis Google)", "queries": [
            "meilleur restaurant {city} {country} avis",
            "restaurant {city} {country} avis clients",
        ]},
        {"label": "🏨 Hôtels (avis Google)", "queries": [
            "hôtel {city} {country} avis clients", "hotel {city} {country} reviews",
        ]},
        {"label": "💊 Pharmacies & horaires", "queries": [
            "pharmacie {city} {country} horaires", "pharmacy {city} {country} hours",
        ]},
        {"label": "💇 Coiffeurs (avis Google)", "queries": [
            "salon de coiffure {city} {country} avis", "coiffeur {city} {country} avis",
        ]},
        {"label": "🚗 Garages (avis Google)", "queries": [
            "garage auto {city} {country} avis", "garage {city} {country} review",
        ]},
        {"label": "🏥 Cliniques & cabinets", "queries": [
            "clinique {city} {country} avis", "cabinet médical {city} {country} avis",
        ]},
        {"label": "💪 Salles de sport", "queries": [
            "salle de sport {city} {country} avis", "fitness {city} {country} avis",
        ]},
        {"label": "🎓 Écoles & formations", "queries": [
            "école {city} {country} avis", "centre de formation {city} {country} avis",
        ]},
    ],
}

DIRECTORY_HINTS = [
    "facebook", "instagram", "tiktok", "linkedin", "youtube", "wikipedia",
    "yelp", "tripadvisor", "google.com", "google.fr", "maps.google",
    "pagesjaunes", "trustpilot", "annuaire", "cylex", "hotfrog",
    "twitter", "x.com", "gmb", "googleusercontent",
    "petitfute", "trip", "booking", "restaurantguru", "menulist",
]

# Signaux d'un site « médiocre » (Segment B) : plateformes gratuites, constructeurs
# amateurs, domaines gratuits — en général un site sans soin, faible en conversion.
BAD_SITE_HINTS = [
    "wordpress.com", "blogspot", "wixsite", "wix.com", "jimdo", "weebly",
    "webnode", "godaddysites", "site123", "webador", "tilda", "carrd",
    "canva.site", "netlify.app", "github.io", "000webhostapp", "yolasite",
    "strikingly", "mystrikingly", "bizsite", "freewebsite",
    ".tk", ".ml", ".ga", ".cf", ".gq",
]

# --- modèles d'emails par défaut ----------------------------------
DEFAULT_COPY_LANGS = {
    "fr": (
        "{AgencyName} — Vos annonces méritent une plume de luxe",
        (
            "Bonjour {LeadName},\n\n"
            "En immobilier, la première impression se joue dans les mots. Une annonce qui raconte un "
            "art de vivre — plutôt qu'une simple liste de pièces — se négocie plus haut, souvent "
            "plusieurs milliers d'euros au-dessus du prix plancher.\n\n"
            "{Audit}\n\n"
            "Chez {AgencyName}, nous réécrivons vos annonces dans un registre « luxe » : vocabulaire "
            "sensoriel, rythme de lecture, émotion, le tout aligné sur votre positionnement à {Location}. "
            "Si vous souhaitez un exemple gratuit sur l'une de vos propriétés, répondez simplement à ce "
            "message.\n\nÀ très vite,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    ),
    "en": (
        "{AgencyName} — Your listings deserve a luxury pen",
        (
            "Hello {LeadName},\n\n"
            "In real estate, the first impression is made of words. A listing that tells a "
            "lifestyle — rather than a mere list of rooms — commands a higher price, often "
            "several thousand euros above the floor price.\n\n"
            "{Audit}\n\n"
            "At {AgencyName}, we rewrite your listings in a luxury register: sensory vocabulary, "
            "rhythm, emotion — aligned with your positioning in {Location}. Reply to this email "
            "for a free example on one of your properties.\n\n"
            "Best regards,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    ),
    "de": (
        "{AgencyName} — Ihre Anzeigen verdienen eine Luxus-Feder",
        (
            "Guten Tag {LeadName},\n\n"
            "Im Immobilienbereich entscheidet der erste Eindruck in Worten. Eine Anzeige, die "
            "einen Lebensstil erzählt — statt nur eine Liste von Räumen — erzielt höhere Preise, "
            "oft mehrere tausend Euro über dem Mindestpreis.\n\n"
            "{Audit}\n\n"
            "Bei {AgencyName} schreiben wir Ihre Anzeigen im Luxus-Stil um: sensorische Sprache, "
            "Rhythmus, Emotion — abgestimmt auf Ihre Positionierung in {Location}. Antworten Sie "
            "auf diese E-Mail für ein kostenloses Beispiel.\n\n"
            "Mit freundlichen Grüßen,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    ),
}

DEFAULT_TEMPLATES = {
    MODE_COPY: {
        "subject": "{AgencyName} — Vos annonces méritent une plume de luxe",
        "body": (
            "Bonjour {LeadName},\n\n"
            "En immobilier, la première impression se joue dans les mots. Une annonce qui raconte un "
            "art de vivre — plutôt qu'une simple liste de pièces — se négocie plus haut, souvent "
            "plusieurs milliers d'euros au-dessus du prix plancher.\n\n"
            "{Audit}\n\n"
            "Chez {AgencyName}, nous réécrivons vos annonces dans un registre « luxe » : vocabulaire "
            "sensoriel, rythme de lecture, émotion, le tout aligné sur votre positionnement à {Location}. "
            "Si vous souhaitez un exemple gratuit sur l'une de vos propriétés, répondez simplement à ce "
            "message.\n\nÀ très vite,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    },
    MODE_WEB: {
        "subject": "{LeadName} — Vos clients de la diaspora ne vous trouvent pas",
        "body": (
            "Bonjour {LeadName},\n\n"
            "Votre établissement à {Location} travaille bien — mais aujourd'hui, une grande partie de vos "
            "clients potentiels (notamment la diaspora) commence par une recherche en ligne. S'ils ne "
            "vous trouvent pas, ils vont chez le concurrent.\n\n"
            "{Audit}\n\n"
            "Chez {AgencyName}, nous créons des sites simples, rapides et élégants — optimisés mobile, "
            "en français, avec vos horaires, vos photos et un bouton WhatsApp. Devis gratuit sous 48 h, "
            "sans engagement.\n\nÀ très vite,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    },
    MODE_SEO: {
        "subject": "{LeadName} — Votre fiche Google Maps sous-exploitée",
        "body": (
            "Bonjour {LeadName},\n\n"
            "Vos clients vous trouvent déjà sur Google Maps — mais combien de ces visites deviennent des "
            "clients ? Sans avis récents et sans lien direct vers votre activité, la fiche perd jusqu'à "
            "80 % de son potentiel.\n\n"
            "{Audit}\n\n"
            "Chez {AgencyName}, nous installons un QR code à votre comptoir et accompagnons vos clients "
            "vers des avis 5 étoiles. Résultat : plus de visibilité locale, plus d'appels, plus de "
            "ventes. Première optimisation offerte.\n\nÀ très vite,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    },
}

DEFAULT_WA = {
    MODE_COPY: (
        "Bonjour {LeadName} 👋\nJe suis {AgencyName}, spécialiste de la rédaction immobilière. "
        "Vos annonces méritent un style « luxe » qui se négocie plus haut. Un exemple gratuit sur "
        "l'une de vos propriétés à {Location} ?"
    ),
    MODE_WEB: (
        "Bonjour {LeadName} 👋\nJe vous ai trouvé à {Location}. Saviez-vous que vos clients de la "
        "diaspora ne peuvent pas vous trouver en ligne ? Un site simple + bouton WhatsApp = plus de "
        "réservations. Chez {AgencyName}, devis gratuit sous 48 h. On en parle ?"
    ),
    MODE_SEO: (
        "Bonjour {LeadName} 👋\nJe vous propose d'augmenter votre chiffre d'affaires : un QR code sur "
        "votre comptoir + des avis 5 étoiles Google. Plus de visibilité = plus de clients chaque "
        "semaine. Chez {AgencyName}, la première optimisation est offerte. On en discute ?"
    ),
}

# --- modèles par défaut EN (toggle FRANÇAIS / ENGLISH) ----------------
# Le toggle bascule instantanément la langue de génération : audits IA,
# emails et messages WhatsApp (modèles par défaut, non personnalisés).
DEFAULT_TEMPLATES_EN = {
    MODE_WEB: {
        "subject": "{LeadName} — Your diaspora clients can't find you online",
        "body": (
            "Hello {LeadName},\n\n"
            "Your business in {Location} works hard — but today, most of your potential clients "
            "(especially the diaspora) start with an online search. If they can't find you, they "
            "go to a competitor who shows up.\n\n"
            "{Audit}\n\n"
            "At {AgencyName}, we build simple, fast and elegant websites — mobile-first, in French, "
            "with your opening hours, your photos and a WhatsApp button. Free quote within 48h, "
            "no commitment.\n\n"
            "Best regards,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    },
    MODE_SEO: {
        "subject": "{LeadName} — Your Google Maps profile is underused",
        "body": (
            "Hello {LeadName},\n\n"
            "Your customers already find you on Google Maps — but how many of those visits become "
            "clients? Without recent reviews and a direct link to your activity, the profile loses "
            "up to 80% of its potential.\n\n"
            "{Audit}\n\n"
            "At {AgencyName}, we install a QR code at your counter and guide your customers to "
            "5-star reviews. Result: more local visibility, more calls, more sales. First "
            "optimization offered.\n\n"
            "Best regards,\n{AgencyName}\n\n—\n{PaymentPlan}"
        ),
    },
}

EN_WA = {
    MODE_COPY: (
        "Hello {LeadName} 👋\nI'm {AgencyName}, a real-estate copywriting specialist. Your "
        "listings deserve a « luxury » style that negotiates higher. A free example on one of "
        "your properties in {Location}?"
    ),
    MODE_WEB: (
        "Hello {LeadName} 👋\nI found your business in {Location}. Did you know your diaspora "
        "clients can't find you online? A simple website + WhatsApp button = more bookings. At "
        "{AgencyName}, free quote within 48h. Shall we talk?"
    ),
    MODE_SEO: (
        "Hello {LeadName} 👋\nI can help you increase revenue: a QR code at your counter + "
        "5-star Google reviews. More visibility = more customers every week. At {AgencyName}, "
        "the first optimization is free. Interested?"
    ),
}


# ------------------------------------------------------------------
#  Petits utilitaires
# ------------------------------------------------------------------


def rerun() -> None:
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()


def empty_leads() -> pd.DataFrame:
    return pd.DataFrame(columns=LEAD_COLS)


def lead_key(row: pd.Series | dict) -> str:
    name = str(row.get("name", "") or "").strip().lower()
    site = str(row.get("website", "") or "").strip().lower()
    return f"{name}|{site}"


def _norm(v) -> str:
    """Normalise une valeur de cellule (NaN -> chaîne vide)."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def clean_name(title: str) -> str:
    t = re.split(r"\s*[|\-–—]\s*", title or "")[0]
    t = re.sub(r"\s*·.*$", "", t).strip()
    return (t[:80] or "Sans nom")


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def extract_contact(text: str, want_phone: bool = False) -> tuple[str, str]:
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text or "")
    email = emails[0] if emails else ""
    phone = ""
    if want_phone:
        cands = re.findall(r"\+?\d{1,3}(?:[\s.\-]?\d{2,4}){2,5}", text or "")
        for c in cands:
            digits = re.sub(r"\D", "", c)
            if 7 <= len(digits) <= 15:
                phone = c.strip()
                break
    return email, phone


def classify_flag(url: str, mode: str) -> str:
    u = (url or "").lower()
    is_directory = any(h in u for h in DIRECTORY_HINTS)
    if mode == MODE_COPY:
        return "Agence immobilière"
    if mode == MODE_WEB:
        return "⚠️ Probablement sans site pro" if is_directory else "Site détecté"
    return "⚠️ Fiche Google Maps à améliorer ?" if is_directory else "Site présent"


def has_website(url) -> bool:
    """True si l'URL ressemble à un vrai site pro (pas un annuaire / réseau social)."""
    u = (url or "").lower()
    return bool(u) and not any(h in u for h in DIRECTORY_HINTS)


def classify_segment(website) -> str:
    """Segment ciblé d'une lead (architecture des leads) :
    - Segment A [NO_SITE]  : aucune présence web pro (annuaire / réseau social seulement) ;
    - Segment B [BAD_SITE] : site présent mais « médiocre » (plateforme gratuite, domaine free) ;
    - Site correct         : vrai site professionnel.
    """
    u = (website or "").lower()
    if not u or any(h in u for h in DIRECTORY_HINTS):
        return SEG_NO_SITE
    if any(h in u for h in BAD_SITE_HINTS):
        return SEG_BAD_SITE
    return SEG_OK


FILTER_OPTIONS = ["Tous les leads", "✅ Avec site web", "⚠️ Sans site web",
                  "📧 Avec email", "📞 Avec téléphone",
                  "🗂️ Segment A (sans site)", "🗂️ Segment B (site médiocre)"]


def apply_lead_filter(df: pd.DataFrame, opt: str) -> pd.Series:
    """Masque booléen selon le filtre d'affichage choisi."""
    if opt == "✅ Avec site web":
        return df["website"].map(has_website)
    if opt == "⚠️ Sans site web":
        return ~df["website"].map(has_website)
    if opt == "📧 Avec email":
        return df["email"].astype(str).str.strip() != ""
    if opt == "📞 Avec téléphone":
        return df["phone"].astype(str).str.strip() != ""
    if opt == "🗂️ Segment A (sans site)":
        return df["segment"].astype(str).str.startswith("Segment A")
    if opt == "🗂️ Segment B (site médiocre)":
        return df["segment"].astype(str).str.startswith("Segment B")
    return pd.Series(True, index=df.index)


def _outreach_plan(leads: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """(Leads ciblées par l'onglet Outreach, description de leur origine).
    Priorité : filtre d'affichage actif (Discovery) → sélection explicite (✓) → toutes.
    Le filtre appliqué dans l'outil définit donc TOUJOURS les destinataires : si vous
    affichez uniquement « ⚠️ Sans site web », seuls ces leads seront contactés.
    L'index d'origine est conservé (les indices restent valides partout).
    NB : invariant d'alignement — `leads_edit` est toujours reconstruit depuis `leads`
    (mêmes lignes, même ordre) quand `leads_version` change ; on s'appuie dessus pour
    aligner la sélection par position (iloc)."""
    if leads.empty:
        return leads, "aucune lead"
    opt = st.session_state.get("leads_filter", "Tous les leads")
    if opt != "Tous les leads":
        filtered = leads[apply_lead_filter(leads, opt)]
        return filtered, f"filtre « {opt} » actif dans Discovery ({len(filtered)} leads)"
    edit = st.session_state.get("leads_edit")
    if (edit is not None and not edit.empty and SEL_COL in edit.columns
            and len(edit) == len(leads)):
        sel = edit[SEL_COL].fillna(False).astype(bool)
        if bool(sel.any()):
            return (leads.iloc[sel.values],
                    f"{int(sel.sum())} lead(s) sélectionnée(s) (✓ dans Discovery)")
    return leads, "toutes les leads (aucune sélection, aucun filtre)"


def build_queries(mode: str, city: str, country: str,
                  sectors: list[str] | None = None) -> list[str]:
    """Construit les requêtes DuckDuckGo : union des requêtes des secteurs choisis,
    ou requêtes par défaut du mode si aucun secteur n'est précisé."""
    if sectors:
        queries = [q for s in SECTORS[mode] if s["label"] in sectors for q in s["queries"]]
    else:
        queries = QUERIES[mode]
    return [q.format(city=city.strip() or "ville", country=country.strip() or "pays")
            for q in queries]


def fetch_snippet(url: str, max_chars: int = 900) -> str:
    """Extrait léger (meta description / premier <p>) — pas de rendu JS."""
    if not url or not _BS4_AVAILABLE:
        return ""
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": UA}, allow_redirects=True)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"].strip()[:max_chars]
        p = soup.find("p")
        if p:
            return p.get_text(" ", strip=True)[:max_chars]
    except Exception:
        pass
    return ""


# ------------------------------------------------------------------
#  Recherche DuckDuckGo
# ------------------------------------------------------------------


def search_leads(mode: str, city: str, country: str, region: str, max_results: int,
                 progress_cb=None, sectors: list[str] | None = None) -> pd.DataFrame:
    if not _DDGS_AVAILABLE:
        raise RuntimeError("Librairie de recherche absente — installez `ddgs` (pip install ddgs).")

    rows: list[dict] = []
    seen: set[str] = set()
    want_phone = mode in (MODE_WEB, MODE_SEO)
    queries = build_queries(mode, city, country, sectors)

    for qi, q in enumerate(queries):
        results: list[dict] = []
        try:
            results = DDGS().text(q, region=region, max_results=max_results)
        except Exception as exc:  # noqa: BLE001
            st.toast(f"Requête ignorée (« {q} ») : {exc}")
        for r in results or []:
            url = normalize_url(r.get("href") or "")
            title = r.get("title") or ""
            if not url:
                continue
            name = clean_name(title)
            key = lead_key({"name": name, "website": url})
            if key in seen:
                continue
            seen.add(key)
            email, phone = extract_contact(r.get("body"), want_phone)
            rows.append({
                "name": name,
                "website": url,
                "email": email,
                "phone": phone,
                "source": "DuckDuckGo",
                "flag": classify_flag(url, mode),
                "segment": classify_segment(url),
                "snippet": "",
                "audit": "",
                "status": "",
            })
        if progress_cb:
            progress_cb((qi + 1) / len(queries))

    return pd.DataFrame(rows, columns=LEAD_COLS) if rows else empty_leads()


def parse_csv_leads(uploaded) -> pd.DataFrame:
    """Mapping souple des colonnes d'un export Instant Data Scraper."""
    df = pd.read_csv(uploaded)
    df = df.where(pd.notna(df), "")
    low = {c: str(c).lower() for c in df.columns}

    def pick(names: list[str]) -> str | None:
        for col in df.columns:
            if any(n in low[col] for n in names):
                return col
        return None

    name_c = pick(["name", "nom", "business", "company", "title", "entreprise"])
    url_c = pick(["website", "url", "site", "link", "lien", "href", "web"])
    email_c = pick(["email", "mail", "courriel"])
    phone_c = pick(["phone", "tel", "whatsapp", "mobile", "téléphone"])

    name_c = name_c or df.columns[0]
    rows: list[dict] = []
    for _, row in df.iterrows():
        email = _norm(row[email_c]) if email_c else ""
        phone = _norm(row[phone_c]) if phone_c else ""
        website = normalize_url(_norm(row[url_c]) if url_c else "")
        rows.append({
            "name": _norm(row[name_c]) or "Sans nom",
            "website": website,
            "email": email,
            "phone": phone,
            "source": "CSV",
            "flag": "",
            "segment": classify_segment(website),
            "snippet": "",
            "audit": "",
            "status": "",
        })
    return pd.DataFrame(rows, columns=LEAD_COLS)


# ------------------------------------------------------------------
#  Gemini (google-genai + fallback legacy)
# ------------------------------------------------------------------


def _is_rate_limit(exc: Exception) -> bool:
    """Détecte un 429 / RESOURCE_EXHAUSTED (limite de débit ou quota Gemini)."""
    if getattr(exc, "code", None) == 429:
        return True
    s = str(exc).upper()
    return ("429" in s or "RESOURCE_EXHAUSTED" in s
            or "RATE LIMIT" in s or "TOO MANY REQUESTS" in s or "QUOTA" in s)


def _is_not_found(exc: Exception) -> bool:
    """Détecte un 404 — modèle inexistant, arrêté par Google ou non autorisé."""
    if getattr(exc, "code", None) == 404:
        return True
    s = str(exc).upper()
    return "404" in s or "NOT_FOUND" in s or "MODEL NOT FOUND" in s


def gemini_available_models(api_key: str) -> list[str]:
    """Liste réelle des modèles Gemini du compte supportant generateContent.

    Interroge l'API (client.models.list) ; si l'appel échoue (pas de clé, réseau…),
    renvoie une liste vide et l'interface retombe sur GEMINI_MODELS.
    """
    names: list[str] = []
    try:
        if _GENAI_STATE == "new":
            client = _genai.Client(api_key=api_key)
            for m in client.models.list():
                name = (getattr(m, "name", "") or "")
                if "gemini" not in name.lower():
                    continue
                methods = getattr(m, "supported_generation_methods", None)
                if methods is None or "generateContent" in methods:
                    names.append(name.replace("models/", ""))
    except Exception:  # noqa: BLE001
        pass
    preferred = [m for m in GEMINI_MODELS if m in names]
    rest = sorted(m for m in names if m not in preferred)
    return preferred + rest


@st.cache_data(ttl=300, show_spinner=False)
def _available_models_cached(api_key: str) -> list[str]:
    """Version mise en cache (5 min) de gemini_available_models."""
    return gemini_available_models(api_key)


def gemini_generate(api_key: str, model: str, prompt: str,
                    temperature: float = 0.7, max_tokens: int = 700,
                    max_retries: int = 3, base_wait: float = 5.0) -> str:
    """Appel Gemini avec nouvelle tentative automatique sur 429 / 5xx.

    Backoff exponentiel : ~5s, ~12s, ~27s avant d'abandonner. Un 429 persistant
    après ces essais signifie en général un quota QUOTIDIEN épuisé (plan gratuit).
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            if _GENAI_STATE == "new":
                client = _genai.Client(api_key=api_key)
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=_genai_types.GenerateContentConfig(
                        temperature=temperature, max_output_tokens=max_tokens,
                    ),
                )
                return (resp.text or "").strip()
            if _GENAI_STATE == "legacy":
                _genai_legacy.configure(api_key=api_key)
                return _genai_legacy.GenerativeModel(model).generate_content(prompt).text.strip()
            raise RuntimeError("SDK Gemini absent — installez `google-genai` (pip install google-genai).")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= max_retries or not _is_rate_limit(exc):
                raise
            wait = base_wait * (2 ** attempt) + random.uniform(0, 2.0)
            try:
                st.toast(f"⏳ Limite API Gemini (429) — nouvel essai dans {wait:.0f}s "
                         f"({attempt + 1}/{max_retries})…")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def openai_generate(api_key: str, model: str, prompt: str,
                    temperature: float = 0.7, max_tokens: int = 700) -> str:
    """Génération de texte via OpenAI (fournisseur OPTIONNEL — amélioration d'emails/messages)."""
    if not _OPENAI_AVAILABLE:
        raise RuntimeError("Paquet `openai` absent — pip install openai")
    client = _OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def audit_prompt(mode: str, name: str, location: str, snippet: str = "",
                 segment: str = SEG_NO_SITE, lang: str = "fr", website: str = "") -> str:
    """Argumentaire IA personnalisé selon le segment (A: sans site / B: site médiocre),
    avec techniques de copywriting (AIDA / PAS), ton prestigieux et langue FR/EN."""
    en = lang != "fr"
    L = lambda fr_t, en_t: en_t if en else fr_t  # noqa: E731

    service = {
        MODE_COPY: L("réécriture d'annonces immobilières en style « luxe »",
                     "luxury real-estate listing rewriting"),
        MODE_WEB: L("création d'un site web moderne (mobile, WhatsApp, référencement local)",
                    "modern website design (mobile, WhatsApp, local SEO)"),
        MODE_SEO: L("QR code + avis Google 5 étoiles + fiche Maps optimisée",
                    "QR code + 5-star Google reviews + optimized Maps profile"),
    }[mode]

    if segment == SEG_NO_SITE:
        angle = L(
            f"« {name} » ({location}) n'a AUCUN site web professionnel (au mieux une page "
            "d'annuaire ou de réseau social). Démontre ce que cela coûte réellement : invisibilité "
            "dans les recherches, clients locaux perdus au profit des concurrents visibles, et "
            "surtout perte de confiance de la diaspora — ces clients à l'étranger qui cherchent, "
            "comparent, réservent et paient en ligne avant de venir ou de faire venir leurs proches.",
            f"« {name} » ({location}) has NO professional website (at best a directory or social "
            "page). Demonstrate the real cost: invisibility in search, local clients lost to visible "
            "competitors, and above all lost diaspora trust — clients abroad who search, compare, "
            "book and pay online before travelling or sending relatives.",
        )
    elif segment == SEG_BAD_SITE:
        angle = L(
            f"« {name} » ({location}) a un site web MAIS il est médiocre. Analyse-le avec "
            f"précision à partir de son URL ({website or 'non fournie'}) et de l'extrait "
            f"« {snippet or 'aucun'} » : esthétique datée, structure confuse, absence d'appel à "
            "l'action, mauvaise adaptation mobile, lenteur, faible conversion. Critique de façon "
            "incisive mais élégante, puis décris la refonte idéale qui transformerait les visiteurs "
            "en clients.",
            f"« {name} » ({location}) HAS a website but it is mediocre. Analyse it precisely from "
            f"its URL ({website or 'not provided'}) and the snippet « {snippet or 'none'} »: dated "
            "aesthetics, confusing structure, missing call-to-action, poor mobile adaptation, slow "
            "speed, low conversion. Critique incisively yet elegantly, then describe the ideal "
            "redesign that would turn visitors into customers.",
        )
    else:
        angle = L(
            f"« {name} » ({location}) a déjà un bon site. Propose une montée en gamme premium "
            "convaincante : positionnement, présence éditoriale, génération de leads qualifiés, "
            "sans dévaloriser l'existant.",
            f"« {name} » ({location}) already has a good website. Offer a compelling premium "
            "upgrade: positioning, editorial presence, qualified lead generation — without "
            "devaluing what already exists.",
        )

    technique = (
        L("Structure PAS : Problème → Agitation → Solution",
          "PAS structure: Problem → Agitate → Solve")
        if segment == SEG_NO_SITE else
        L("Structure AIDA : Attention → Intérêt → Désir → Action",
          "AIDA structure: Attention → Interest → Desire → Action")
    )

    snippet_line = (
        L(f"Appuie-toi sur cet extrait du site : « {snippet} »\n",
          f"Base your analysis on this site excerpt: « {snippet} »\n")
        if (snippet and segment == SEG_BAD_SITE) else ""
    )

    return L(
        "Tu es un copywriter senior de très haut niveau. Rédige un argumentaire de vente "
        "PERSONNALISÉ — jamais générique — pour ce prospect. Contraintes impératives :\n"
        f"· Technique de copywriting : {technique}.\n"
        "· Ton prestigieux, esthétique, très professionnel et sobre (zéro émoticône).\n"
        "· Chaque phrase doit être spécifique à ce prospect (nom, lieu, situation réelle).\n"
        "· N'invente AUCUN chiffre précis si tu n'as pas de données ; reste qualitatif et élégant.\n"
        "· Structure ta réponse en 3 parties : (1) accroche, (2) démonstration, (3) appel à "
        "l'action.\n"
        f"· Ta solution : {service}.\n\n"
        f"Prospect : {angle}\n"
        f"Extrait fourni : « {snippet or 'aucun'} »\n"
        "Réponds en français, ton premium.\n",
        "You are a senior, world-class copywriter. Write a PERSONALIZED sales argument — never "
        "generic — for this prospect. Mandatory constraints:\n"
        f"· Copywriting technique: {technique}.\n"
        "· Prestigious, aesthetic, highly professional, sober tone (zero emoji).\n"
        "· Every sentence must be specific to this prospect (name, place, real situation).\n"
        "· Do NOT invent precise figures without data; stay qualitative and elegant.\n"
        "· Structure your answer in 3 parts: (1) hook, (2) demonstration, (3) call to action.\n"
        f"· Your solution: {service}.\n\n"
        f"Prospect: {angle}\n"
        f"Provided excerpt: « {snippet or 'none'} »\n"
        "Answer in English, premium tone.\n",
    )


# ------------------------------------------------------------------
#  Envoi d'emails : smtplib + Composio
# ------------------------------------------------------------------


def body_to_html(text: str, image_cids: list[str] | None = None,
                 cta: dict | None = None, video: str = "") -> str:
    """Convertit le corps (texte brut) en email HTML « Luxe » (fond sombre, laiton),
    avec contenu enrichi optionnel : images (pièces jointes inline cid), bouton CTA, vidéo."""
    import html as _html

    def _richify(block: str) -> str:
        """Échappe le texte puis convertit les liens markdown [texte](url) et images
        ![alt](url) en HTML, utilisables directement dans le corps du template.
        L'échappement se fait AVANT l'insertion des <br> (sinon ils seraient affichés
        littéralement « &lt;br&gt; » dans l'email)."""
        block = _html.escape(block)
        block = block.replace("\n", "<br>")
        block = re.sub(
            r"!\[([^\]]*)\]\((https?://[^)\s]+)\)",
            lambda m: (f'<img src="{m.group(2)}" alt="{m.group(1)}" '
                       'style="max-width:100%;height:auto;border-radius:10px;'
                       'margin:0 0 18px 0;display:block;"/>'),
            block)
        block = re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            lambda m: (f'<a href="{m.group(2)}" '
                       'style="color:#D9A441;text-decoration:underline;'
                       f'font-family:Helvetica,Arial,sans-serif;">{m.group(1)}</a>'),
            block)
        return block

    paras = []
    for block in re.split(r"\n\s*\n", text or ""):
        if block.strip():
            paras.append(
                f'<p style="margin:0 0 16px 0;line-height:1.7;">{_richify(block)}</p>')
    body = "\n".join(paras) or "<p></p>"

    rich: list[str] = []
    for cid in image_cids or []:
        rich.append(
            f'<img src="cid:{cid}" alt="" style="max-width:100%;height:auto;'
            'border-radius:10px;margin:0 0 18px 0;display:block;"/>')
    if cta and cta.get("url"):
        rich.append(
            f'<a href="{_html.escape(str(cta["url"]))}" style="display:inline-block;'
            'background:linear-gradient(135deg,#EEC06A,#A87F2F);color:#161006;'
            'text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;'
            'font-family:Helvetica,Arial,sans-serif;margin:6px 0 20px 0;">'
            f'{_html.escape(str(cta.get("label") or "En savoir plus"))}</a>')
    if video and str(video).strip():
        rich.append(
            f'<a href="{_html.escape(str(video))}" style="display:inline-block;'
            'border:1px solid #c9a45c;color:#c9a45c;text-decoration:none;'
            'padding:12px 26px;border-radius:8px;font-weight:700;'
            'font-family:Helvetica,Arial,sans-serif;margin:0 0 20px 0;">'
            '▶️ Regarder la vidéo</a>')
    rich_html = "\n".join(rich)

    return (
        "<div style=\"background:#0d0d0f;padding:32px;font-family:Georgia,'Times New Roman',serif;\">"
        "<div style=\"max-width:640px;margin:0 auto;background:#16161a;border:1px solid #3a341f;"
        "border-radius:12px;padding:36px;\">"
        "<div style=\"color:#c9a45c;font-size:13px;letter-spacing:3px;text-transform:uppercase;"
        "margin-bottom:18px;\">Scriba Omniscient · Prospection</div>"
        f"{rich_html}{body}"
        "<div style=\"margin-top:24px;padding-top:18px;border-top:1px solid #2a2a30;"
        "color:#8a8a93;font-size:12px;font-family:Helvetica,Arial,sans-serif;\">"
        "Message professionnel envoyé dans le cadre d'une prospection B2B. Si vous n'êtes pas le "
        "bon interlocuteur, répondez « STOP » pour ne plus être recontacté.</div>"
        "</div></div>"
    )


def send_via_smtp(sender: str, password: str, to: str, subject: str, body: str,
                  html_body: str | None = None,
                  images: list[dict] | None = None) -> str:
    """Envoie un email Gmail via smtplib. `images` = liste de dicts
    {maintype, subtype, data} attachées en inline (cid: img_0, img_1, …)."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    for i, img in enumerate(images or []):
        msg.add_related(img["data"], maintype=img.get("maintype", "image"),
                        subtype=img.get("subtype", "png"), cid=f"img_{i}")
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
        server.login(sender, password)
        server.send_message(msg)
    return "ok"


SMTP_HINT = ("💡 Identifiants Gmail refusés (535). Utilisez un MOT DE PASSE D'APPLICATION "
             "(jamais votre mot de passe normal) — https://myaccount.google.com/apppasswords. "
             "Vérifiez : validation en 2 étapes activée, code collé SANS espaces, bonne adresse. "
             "Alternative : canal « composio (Gmail OAuth) » dans l'onglet Outreach.")


def _is_bad_credentials(exc: Exception) -> bool:
    """Détecte l'erreur Gmail 535 « Username and Password not accepted » (BadCredentials)."""
    s = str(exc).upper()
    return ("535" in s and ("BADCREDENTIALS" in s
                             or "PASSWORD NOT ACCEPTED" in s
                             or "USERNAME AND PASSWORD NOT ACCEPTED" in s))


def test_smtp_connection(sender: str, password: str) -> tuple[bool, str]:
    """Tente une connexion SMTP Gmail (sans envoyer de mail). Retourne (ok, message)."""
    if not sender or not password:
        return False, "Renseignez d'abord votre adresse Gmail et le mot de passe d'application."
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
            server.login(sender, password)
        return True, "Connexion Gmail réussie ✓ — les envois smtplib fonctionneront."
    except smtplib.SMTPAuthenticationError as exc:
        if _is_bad_credentials(exc):
            return False, f"Identifiants refusés (535). {SMTP_HINT}"
        return False, f"Authentification refusée : {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Connexion impossible : {exc}"


@st.cache_data(ttl=120, show_spinner=False)
def _composio_status_cached(api_key: str) -> tuple[bool, str]:
    return composio_status(api_key)


def composio_status(api_key: str) -> tuple[bool, str]:
    if not api_key:
        return False, "Clé Composio absente → utiliser smtplib."
    if not _COMPOSIO_AVAILABLE:
        return False, "`composio` non installé → utiliser smtplib."
    try:
        comp = _Composio(api_key=api_key)
        accounts = comp.connected_accounts.list(user_ids=[USER_ID], statuses=["ACTIVE"])
        for acc in accounts:
            if getattr(acc, "toolkit", "") == "gmail":
                return True, "Compte Gmail Composio actif ✓"
        return False, ("Aucun compte Gmail Composio actif. Connectez le toolkit gmail "
                       f"(user_id={USER_ID}) sur composio.dev puis relancez.")
    except Exception as exc:  # noqa: BLE001
        return False, f"Erreur Composio : {exc}"


def send_via_composio(api_key: str, to: str, subject: str, body: str) -> str:
    comp = _Composio(api_key=api_key)
    comp.actions.execute(
        action="GMAIL_SEND_EMAIL",
        params={"to": to, "subject": subject, "body_text": body},
        user_id=USER_ID,
    )
    return "ok"


# ------------------------------------------------------------------
#  Modèles / paiement
# ------------------------------------------------------------------


def payment_block(mode: str, iban: str, africa_payment: str) -> str:
    if mode == MODE_COPY:
        if iban.strip():
            return (f"Paiement sécurisé par virement SEPA — IBAN (Grey.co) : {iban.strip()}. "
                    "Facture professionnelle fournie.")
        return ("Paiement sécurisé par virement SEPA via Grey.co (IBAN communiqué sur demande). "
                "Facture professionnelle fournie.")
    return (f"Paiement flexible en 2 tranches : {africa_payment.strip() or DEFAULT_AFRICA_PAYMENT}. "
            "Réduction si paiement comptant.")


def fill_template(template: str, lead: pd.Series | dict, agency: str, location: str,
                  mode: str, audit: str = "", payment: str = "") -> str:
    """Remplace les placeholders {…} du modèle par les infos du client.

    Placeholders fixes : {AgencyName} {LeadName} {LeadWebsite} {LeadEmail} {Location}
    {Mode} {Audit} {PaymentPlan} {City} {Country}.
    Placeholders dynamiques : TOUTE accolade correspondant à une colonne de la lead
    (nom, email, téléphone, site, segment, source, extrait, statut…), insensible à la
    casse — ex. {Phone} ou {phone} → numéro du client. Placeholder inconnu → laissé
    tel quel · champ vide → « … » pour les champs nominatifs.
    """
    s = template
    # 1) Placeholders dynamiques : n'importe quelle colonne de la lead (insensible à la casse)
    for col in LEAD_COLS:
        if col == "audit":  # {Audit} est réservé à l'argumentaire IA (fixé ci-dessous)
            continue
        v = str(lead.get(col, "") or "")
        if not v and col == "name":  # champ nominatif vide -> « … » (comme {LeadName})
            v = "…"
        # lambda : évite que le contenu de `v` soit interprété comme une backreference
        s = re.sub(r"\{" + re.escape(col) + r"\}", lambda m: v, s, flags=re.I)
    # 2) Placeholders fixes (priorité finale)
    parts = (location or "").strip().split()
    values = {
        "AgencyName": agency or "…",
        "LeadName": str(lead.get("name", "") or "…"),
        "LeadWebsite": str(lead.get("website", "") or ""),
        "LeadEmail": str(lead.get("email", "") or ""),
        "Location": location or "…",
        "Mode": MODE_INFO[mode]["emoji"] + " " + mode,
        "Audit": audit,
        "PaymentPlan": payment,
        "City": parts[0] if parts else "",
        "Country": parts[-1] if len(parts) > 1 else "",
    }
    for k, v in values.items():
        s = s.replace("{" + k + "}", v)
    return s


# ------------------------------------------------------------------
#  WhatsApp
# ------------------------------------------------------------------


def wa_link(phone: str, message: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"https://wa.me/{digits}?text={quote(message)}"


# ------------------------------------------------------------------
#  Campagne d'envoi (thread + arrêt réactif)
# ------------------------------------------------------------------


def _track(stats: dict, channel: str, ok: bool, name: str, detail: str = "") -> None:
    """Compte une action de contact dans un dict de stats (sûr depuis un thread)."""
    stats["contacted"] += 1
    if channel == "WhatsApp":
        stats["wa"] += int(ok)
    else:
        stats["mail"] += int(ok)
    stats["fail"] += int(not ok)
    stats["history"].insert(0, {
        "Heure": datetime.now().strftime("%H:%M:%S"),
        "Lead": str(name)[:40],
        "Canal": channel,
        "Statut": "✓" if ok else "✗",
        "Détail": detail,
    })
    del stats["history"][200:]


def _merge_stats(state_stats: dict) -> None:
    """Fusionne les stats d'un worker (thread) dans le dashboard de session."""
    s = st.session_state["campaign_stats"]
    s["contacted"] += state_stats["contacted"]
    s["wa"] += state_stats["wa"]
    s["mail"] += state_stats["mail"]
    s["fail"] += state_stats["fail"]
    s["history"] = state_stats["history"] + s["history"]
    del s["history"][200:]


def outreach_worker(state: dict, stop_event: threading.Event, send_fn,
                    min_delay: int, max_delay: int) -> None:
    total = len(state["queue"])
    for i, item in enumerate(state["queue"]):
        if stop_event.is_set():
            break
        state["log"].append(f"→ [{i + 1}/{total}] {item['name']} · {item['email']}")
        try:
            send_fn(item)
            state["log"].append("   ✓ envoyé")
            _track(state["stats"], "Email", True, item["name"], "email envoyé")
        except Exception as exc:  # noqa: BLE001
            state["log"].append(f"   ✗ échec : {exc}")
            if _is_bad_credentials(exc) and not any("Identifiants Gmail refusés" in l
                                                     for l in state["log"]):
                state["log"].append("   " + SMTP_HINT)
            _track(state["stats"], "Email", False, item["name"], str(exc)[:80])
        state["pos"] = i + 1
        if i < total - 1 and not stop_event.is_set():
            end = time.time() + random.uniform(min_delay, max_delay)
            while time.time() < end:
                if stop_event.is_set():
                    break
                time.sleep(1)
    state["stopped"] = stop_event.is_set() and state["pos"] < total
    state["done"] = True


def one_click_worker(state: dict, stop_event: threading.Event, email_fn,
                     min_delay: int, max_delay: int) -> None:
    """Moteur hybride « One-Click Multi-Send » :
    - téléphone + email -> WhatsApp (lien wa.me ouvert, prêt à envoyer) + email envoyé ;
    - téléphone seul    -> WhatsApp uniquement ;
    - email seul        -> Email Only (bascule automatique).
    Délai humain (90 s par défaut) entre chaque lead."""
    total = len(state["queue"])
    for i, item in enumerate(state["queue"]):
        if stop_event.is_set():
            break
        name = item["name"]
        # 1) WhatsApp — ouvre wa.me avec le message 100 % personnalisé et encodé
        if item.get("wa_link"):
            try:
                webbrowser.open(item["wa_link"])
                state["log"].append(f"📲 [{i + 1}/{total}] {name} — WhatsApp ouvert (prêt à envoyer)")
                _track(state["stats"], "WhatsApp", True, name, "lien wa.me ouvert")
            except Exception as exc:  # noqa: BLE001
                state["log"].append(f"   ✗ WhatsApp : {exc}")
                _track(state["stats"], "WhatsApp", False, name, str(exc)[:80])
        # 2) Email — envoi via smtp (si l'adresse existe)
        if item.get("email"):
            try:
                email_fn(item)
                state["log"].append(f"📧 [{i + 1}/{total}] {name} — email envoyé ✓")
                _track(state["stats"], "Email", True, name, "email envoyé")
            except Exception as exc:  # noqa: BLE001
                state["log"].append(f"   ✗ email : {exc}")
                if _is_bad_credentials(exc) and not any("Identifiants Gmail refusés" in l
                                                         for l in state["log"]):
                    state["log"].append("   " + SMTP_HINT)
                _track(state["stats"], "Email", False, name, str(exc)[:80])
        elif not item.get("wa_link"):
            state["log"].append(f"⚠️ [{i + 1}/{total}] {name} — aucun canal disponible")
        state["pos"] = i + 1
        if i < total - 1 and not stop_event.is_set():
            end = time.time() + random.uniform(min_delay, max_delay)
            while time.time() < end:
                if stop_event.is_set():
                    break
                time.sleep(1)
    state["stopped"] = stop_event.is_set() and state["pos"] < total
    state["done"] = True


# ------------------------------------------------------------------
#  CSS — design « Obsidienne & Laiton » (frontend-design)
# ------------------------------------------------------------------


def premium_css() -> str:
    return """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..700;1,9..144,300..700&family=Manrope:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root{
  --bg:#0B0E14; --bg2:#10141D; --panel:#141926; --panel2:#1B2231;
  --line:#243047; --line2:#2F3C55;
  --gold:#D9A441; --goldhi:#F2C96B; --golddeep:#A87F2F;
  --text:#E9E5DC; --muted:#98A0B3; --dim:#6B7488;
  --green:#3DDC84; --red:#FF6B6B; --blue:#6FB1FC;
  --mono:'JetBrains Mono',monospace; --serif:'Fraunces',serif; --sans:'Manrope',sans-serif;
}

html, body, .stApp{ font-family:var(--sans); color:var(--text); }

[data-testid="stAppViewContainer"]{
  background:
    radial-gradient(1200px 520px at 50% -8%, rgba(217,164,65,.10), transparent 62%),
    radial-gradient(ellipse at 50% 118%, rgba(0,0,0,.5), transparent 58%),
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.045'/%3E%3C/svg%3E"),
    linear-gradient(180deg, var(--bg) 0%, #0A0D13 100%);
}
[data-testid="stHeader"]{ background:transparent; }
[data-testid="stToolbar"]{ color:var(--muted); }

::selection{ background:rgba(217,164,65,.35); color:#fff; }
::-webkit-scrollbar{ width:10px; height:10px; }
::-webkit-scrollbar-track{ background:transparent; }
::-webkit-scrollbar-thumb{ background:var(--line2); border-radius:8px; }
::-webkit-scrollbar-thumb:hover{ background:var(--golddeep); }

/* ---------- Typo ---------- */
h1,h2,h3{ font-family:var(--serif); font-weight:580; letter-spacing:-.01em; color:var(--text); }
h1{ background:linear-gradient(120deg,#F6E3B4 0%, var(--gold) 55%, var(--golddeep) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
h2{ border-left:3px solid var(--gold); padding-left:.6rem; }
h4,h5,h6{ font-family:var(--mono); text-transform:uppercase; letter-spacing:.14em; font-size:.78rem; color:var(--gold); }

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#0C1017 0%, #0A0D13 100%);
  border-right:1px solid var(--line);
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"]{ padding-top:1.2rem; }
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] label p{
  font-family:var(--mono); font-size:.68rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--dim) !important; margin-bottom:.35rem;
}
[data-testid="stSidebar"] h3{ font-family:var(--mono); font-size:.8rem; letter-spacing:.18em;
  text-transform:uppercase; color:var(--gold); margin-top:1.4rem; }

.side-brand{ display:flex; align-items:center; gap:.7rem; padding:.4rem .2rem .8rem; }
.side-logo{ font-size:1.9rem; line-height:1; filter:drop-shadow(0 2px 10px rgba(217,164,65,.45)); }
.side-name{ font-family:var(--serif); font-size:1.05rem; line-height:1.15; color:var(--text); }
.side-name span{ color:var(--gold); font-style:italic; }
.side-sep{ height:1px; margin:.4rem 0 1rem;
  background:linear-gradient(90deg, transparent, var(--line2) 30%, var(--golddeep) 50%, var(--line2) 70%, transparent); }

/* ---------- Brand header ---------- */
.brand{ margin:0 0 .4rem; }
.brand-eyebrow{ font-family:var(--mono); font-size:.7rem; letter-spacing:.34em;
  text-transform:uppercase; color:var(--gold); }
.brand-title{ font-family:var(--serif); font-size:2.5rem; line-height:1.04; font-weight:600;
  background:linear-gradient(120deg,#F6E3B4 0%, var(--gold) 55%, var(--golddeep) 100%);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.brand-title small{ font-family:var(--mono); font-size:.72rem; letter-spacing:.22em;
  color:var(--muted); -webkit-text-fill-color:var(--muted); }
.brand-sub{ color:var(--muted); font-size:.9rem; margin-top:.3rem; }
.brand-sub b{ color:var(--goldhi); font-weight:600; }

/* ---------- Boutons ---------- */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button{
  border-radius:10px; border:1px solid var(--line2);
  background:linear-gradient(180deg, var(--panel2) 0%, var(--panel) 100%);
  color:var(--text); font-family:var(--sans); font-weight:600; letter-spacing:.01em;
  padding:.55rem 1.05rem; transition:all .18s ease;
}
.stButton>button:hover, .stDownloadButton>button:hover{
  border-color:var(--gold); color:var(--goldhi);
  box-shadow:0 0 0 1px rgba(217,164,65,.3), 0 8px 20px -8px rgba(217,164,65,.4);
  transform:translateY(-1px);
}
.stButton>button[kind="primary"]{
  background:linear-gradient(135deg,#EEC06A 0%, var(--gold) 55%, var(--golddeep) 100%);
  color:#161006; border:none; font-weight:800;
  box-shadow:0 4px 16px -6px rgba(217,164,65,.65), inset 0 1px 0 rgba(255,255,255,.35);
}
.stButton>button[kind="primary"]:hover{
  color:#161006; filter:brightness(1.08);
  box-shadow:0 6px 24px -6px rgba(217,164,65,.8);
}
.stButton>button:disabled, .stDownloadButton>button:disabled{ opacity:.45; filter:grayscale(.4); }

/* ---------- Champs ---------- */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div{
  background:rgba(20,26,38,.72); border:1px solid var(--line2); border-radius:10px;
  transition:border-color .18s ease, box-shadow .18s ease;
}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within,
[data-baseweb="select"] > div:focus-within{
  border-color:var(--gold);
  box-shadow:0 0 0 3px rgba(217,164,65,.14);
}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea, [data-baseweb="select"] div{
  color:var(--text);
}
[data-testid="stFileUploader"]{ border:1px dashed var(--line2); border-radius:12px;
  background:rgba(20,26,38,.35); }
[data-testid="stFileUploader"]:hover{ border-color:var(--gold); }
input[type="checkbox"]{ accent-color:var(--gold); }

/* ---------- Onglets ---------- */
.stTabs [data-baseweb="tab-list"]{ gap:.25rem; border-bottom:1px solid var(--line);
  padding-bottom:.35rem; margin-bottom:1rem; }
.stTabs [data-baseweb="tab"]{
  font-family:var(--mono); font-size:.76rem; letter-spacing:.12em; text-transform:uppercase;
  color:var(--muted); padding:.45rem .9rem; border-radius:8px 8px 0 0;
  transition:color .18s ease, background .18s ease;
}
.stTabs [data-baseweb="tab"]:hover{ color:var(--goldhi); background:rgba(217,164,65,.06); }
.stTabs [data-baseweb="tab"][aria-selected="true"]{
  color:var(--goldhi); background:rgba(217,164,65,.10);
  box-shadow:inset 0 -2px 0 var(--gold);
}

/* ---------- Métriques ---------- */
[data-testid="stMetric"]{
  background:linear-gradient(180deg, rgba(255,255,255,.025), rgba(255,255,255,0) 70%),
              var(--panel);
  border:1px solid var(--line); border-radius:14px; padding:1rem 1.1rem;
}
[data-testid="stMetricLabel"]{ font-family:var(--mono); font-size:.66rem;
  letter-spacing:.16em; text-transform:uppercase; color:var(--dim); }
[data-testid="stMetricValue"]{ font-family:var(--serif); font-size:1.9rem;
  color:var(--goldhi); }
[data-testid="stMetricDelta"]{ color:var(--green); }

/* ---------- Tableaux / éditeur ---------- */
[data-testid="stDataFrame"], [data-testid="stDataEditor"]{
  border:1px solid var(--line); border-radius:12px; overflow:hidden;
}
[data-testid="stDataFrame"]{ box-shadow:0 10px 30px -18px rgba(0,0,0,.8); }

/* ---------- Expanders / alerts / captions ---------- */
[data-testid="stExpander"]{
  border:1px solid var(--line); border-radius:12px;
  background:linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,0));
}
[data-testid="stExpander"] summary{ font-family:var(--sans); font-weight:600; }
[data-testid="stCaptionContainer"]{ color:var(--muted); }
.stAlert{ border-radius:12px; border:1px solid var(--line2); }
.stAlert p{ color:var(--text); }

/* ---------- Liens / progress / divers ---------- */
a{ color:var(--gold); }
a:hover{ color:var(--goldhi); }
[data-testid="stProgress"] > div > div > div{
  background:linear-gradient(90deg, var(--golddeep), var(--gold) 50%, var(--goldhi));
}
.stCode, code{ font-family:var(--mono); }
hr{ border-color:var(--line); }
[data-testid="stSidebar"] hr{ border-color:var(--line); }

.ftr{ color:var(--dim); font-size:.75rem; text-align:center; margin:2rem 0 .4rem;
  font-family:var(--mono); letter-spacing:.08em; }
.ftr b{ color:var(--gold); }
</style>
"""


def inject_css() -> None:
    st.markdown(premium_css(), unsafe_allow_html=True)


# ------------------------------------------------------------------
#  Initialisation session
# ------------------------------------------------------------------


def init_session() -> None:
    st.session_state.setdefault("leads", empty_leads())
    st.session_state.setdefault("leads_edit", empty_leads())
    st.session_state.setdefault("leads_version", 0)
    st.session_state.setdefault("edit_version", -1)
    st.session_state.setdefault("audits", {})
    st.session_state.setdefault("mode", MODE_COPY)
    st.session_state.setdefault("prev_mode", None)
    st.session_state.setdefault("prev_lang", "fr")
    st.session_state.setdefault("prev_msg_lang", "fr")
    st.session_state.setdefault("sent_count", 0)
    st.session_state.setdefault("out_state", None)
    st.session_state.setdefault("out_stop", threading.Event())
    st.session_state.setdefault("out_thread", None)
    st.session_state.setdefault("wa_msg", "")
    st.session_state.setdefault("my_wa", "")
    st.session_state.setdefault("sectors_sel", [s["label"] for s in SECTORS[MODE_COPY]])
    st.session_state.setdefault("leads_filter", "Tous les leads")
    st.session_state.setdefault("openai_key", "")
    st.session_state.setdefault("openai_model", OPENAI_MODELS[0])
    st.session_state.setdefault("lang", "fr")
    st.session_state.setdefault("campaign_stats",
                                {"contacted": 0, "wa": 0, "mail": 0, "fail": 0, "history": []})

    # Réparation des données héritées d'une session plus ancienne (sans colonne segment)
    for dfk in ("leads", "leads_edit"):
        df = st.session_state.get(dfk)
        if df is not None and "segment" not in df.columns:
            st.session_state[dfk]["segment"] = (
                df["website"].map(classify_segment).fillna(SEG_NO_SITE))


def _lang_templates(mode: str, lang: str) -> tuple[str, str]:
    """Modèles email par défaut (objet, corps) selon le mode et la langue active.

    Mode Copywriting : le sélecteur dédié `template_lang` (fr/en/de) est prioritaire ;
    s'il n'est pas encore défini, il est initialisé sur la langue active.
    Modes Web / SEO : le toggle FRANÇAIS / ENGLISH bascule directement fr/en.
    """
    if mode == MODE_COPY:
        tlang = st.session_state.get("template_lang") \
            or (lang if lang in DEFAULT_COPY_LANGS else "fr")
        return DEFAULT_COPY_LANGS.get(tlang, DEFAULT_COPY_LANGS["fr"])
    tpl = DEFAULT_TEMPLATES_EN if lang == "en" else DEFAULT_TEMPLATES
    t = tpl[mode]
    return t["subject"], t["body"]


def _lang_wa(mode: str, lang: str) -> str:
    """Message WhatsApp par défaut selon la langue active (fr/en)."""
    return EN_WA.get(mode, DEFAULT_WA[mode]) if lang == "en" else DEFAULT_WA[mode]


def _swap_msg_defaults(mode: str, old_lang: str, new_lang: str) -> bool:
    """Bascule les modèles par défaut (email + WhatsApp) vers la nouvelle langue,
    UNIQUEMENT s'ils n'ont pas été personnalisés (encore égaux aux défauts de
    l'ancienne langue) — les messages édités à la main sont toujours préservés.

    Mode Copywriting : les emails suivent le sélecteur dédié `template_lang` ;
    seuls les messages WhatsApp sont basculés par le toggle global.
    Retourne True si au moins un modèle a été remplacé.
    """
    swapped = False
    if mode != MODE_COPY:
        cur = (st.session_state.get("email_subject", ""),
               st.session_state.get("email_body", ""))
        if cur == _lang_templates(mode, old_lang):
            st.session_state["email_subject"], st.session_state["email_body"] = \
                _lang_templates(mode, new_lang)
            swapped = True
    if st.session_state.get("wa_msg", "") == _lang_wa(mode, old_lang):
        st.session_state["wa_msg"] = _lang_wa(mode, new_lang)
        swapped = True
    return swapped


def ensure_template_defaults(mode: str) -> None:
    """Rafraîchit les modèles par défaut lors d'un changement de mode."""
    lang = st.session_state.get("lang", "fr")
    subj, bdy = _lang_templates(mode, lang)
    st.session_state["email_subject"] = subj
    st.session_state["email_body"] = bdy
    st.session_state["wa_msg"] = _lang_wa(mode, lang)


# ------------------------------------------------------------------
#  Sidebar
# ------------------------------------------------------------------


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="side-brand"><div class="side-logo">⛏️</div>'
            '<div class="side-name">SCRIBA<br>OMNISCIENT <span>Prospector</span></div></div>'
            '<div class="side-sep"></div>',
            unsafe_allow_html=True,
        )

        st.markdown("### ⚙️ Identité")
        st.text_input("Nom de l'agence", key="agency", placeholder="Scriba & Co")
        st.text_input("Clé API Gemini (moteur principal, gratuit)", type="password", key="gemini_key",
                      help="https://aistudio.google.com/apikey — audits IA et génération de textes.")
        st.text_input("📱 Votre numéro WhatsApp (international)", key="my_wa",
                      placeholder="+228 90 12 34 56",
                      help="C'est le numéro connecté à votre WhatsApp : les liens d'envoi s'ouvriront "
                           "dans votre application WhatsApp et le message partira de ce numéro. "
                           "Modifiable à tout moment.")
        with st.expander("📬 Votre adresse d'envoi (Gmail — fallback)"):
            st.text_input("Votre adresse Gmail", key="gmail_user", placeholder="vous@gmail.com")
            st.text_input("Mot de passe d'application", type="password", key="gmail_pass",
                          help="https://myaccount.google.com/apppasswords")
            if st.button("🔌 Tester la connexion Gmail", use_container_width=True):
                with st.spinner("Connexion à Gmail…"):
                    ok_t, msg_t = test_smtp_connection(st.session_state.get("gmail_user", ""),
                                                       st.session_state.get("gmail_pass", ""))
                if ok_t:
                    st.success(msg_t)
                else:
                    st.error(msg_t)
        st.text_input("Clé API Composio (optionnel)", type="password", key="composio_key",
                      help="composio.dev — Gmail via OAuth, remplace smtplib")
        if st.session_state.get("composio_key"):
            ok_c, msg_c = _composio_status_cached(st.session_state["composio_key"])
            if ok_c:
                st.success(msg_c)
            else:
                st.warning(msg_c)
        with st.expander("🧠 IA optionnelle — OpenAI (facultatif)"):
            st.caption("Optionnel : pour améliorer/réécrire vos emails et messages WhatsApp avec "
                       "OpenAI. Gemini reste le moteur principal (gratuit).")
            st.text_input("Clé API OpenAI", type="password", key="openai_key",
                          help="https://platform.openai.com/api-keys")
            st.selectbox("Modèle OpenAI", OPENAI_MODELS, index=0, key="openai_model")

        st.markdown("### 🎯 Mode")
        st.selectbox("Modèle d'affaires", MODES, key="mode",
                     format_func=lambda m: MODE_INFO[m]["label"])
        st.caption(MODE_INFO[st.session_state["mode"]]["desc"])

        st.markdown("### 🌐 Langue de génération")
        st.toggle(
            "FRANÇAIS / ENGLISH",
            value=(st.session_state.get("lang", "fr") == "en"),
            key="lang_en",
            help="Change instantanément la langue de génération des messages : audits IA, "
                 "emails et WhatsApp (modèles par défaut). Vos messages personnalisés sont "
                 "préservés. En mode Copywriting, les emails suivent le sélecteur de langue "
                 "dédié (onglet Outreach). N'affecte pas l'interface.",
        )
        lang = "en" if st.session_state.get("lang_en") else "fr"
        st.session_state["lang"] = lang
        prev_msg = st.session_state.get("prev_msg_lang", "fr")
        if lang != prev_msg:
            # Bascule instantanée : remplace les modèles UNIQUEMENT s'ils sont encore les
            # valeurs par défaut de l'ancienne langue (jamais les messages personnalisés).
            _swap_msg_defaults(st.session_state.get("mode", MODE_COPY), prev_msg, lang)
            st.session_state["prev_msg_lang"] = lang

        st.markdown("### 📍 Localisation")
        c1, c2 = st.columns(2)
        c1.text_input("Ville", key="city", placeholder="Lomé")
        c2.text_input("Pays", key="country", placeholder="Togo")

        st.markdown("### 💰 Paiement & confiance")
        st.text_input("IBAN (Grey.co) — emails EU", key="iban", placeholder="FR76 1234 …")
        st.text_area("Split T-Money / Flooz — clients Afrique",
                     value=DEFAULT_AFRICA_PAYMENT, key="africa_payment", height=70)

        if st.button("🧹 Réinitialiser la session"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            rerun()


# ------------------------------------------------------------------
#  Tab 1 — Lead Discovery & Scraper
# ------------------------------------------------------------------


def render_discovery_tab() -> None:
    st.markdown("### 🧭 Lead Discovery & Scraper")
    mode = st.session_state["mode"]

    with st.expander("🔍 Recherche DuckDuckGo (gratuit, sans navigateur)", expanded=True):
        st.markdown("**🎯 Secteurs ciblés** — combinez-en plusieurs pour élargir la recherche :")
        sector_labels = [s["label"] for s in SECTORS[mode]]
        st.multiselect("Secteurs", options=sector_labels, key="sectors_sel")
        c1, c2, c3 = st.columns([2, 2, 1])
        region = c1.selectbox("Région de recherche", ["fr-fr", "en-gb", "de-de", "wt-wt", "us-en"],
                              index=0, key="ddg_region")
        max_res = c2.number_input("Résultats par requête", 5, 50, 10, key="ddg_max")
        launch = c3.button("🔍 Lancer", type="primary", use_container_width=True)

        if launch:
            if not _DDGS_AVAILABLE:
                st.error("`ddgs` absent — `pip install ddgs` puis relancez l'app.")
            else:
                prog = st.progress(0.0, text="Prospection DuckDuckGo…")
                try:
                    df = search_leads(
                        mode, st.session_state.get("city", ""),
                        st.session_state.get("country", ""), region, int(max_res),
                        sectors=st.session_state.get("sectors_sel") or None,
                        progress_cb=lambda p: prog.progress(p, text="Prospection DuckDuckGo…"),
                    )
                    st.session_state["leads"] = df
                    st.session_state["leads_version"] += 1
                    st.toast(f"{len(df)} leads découvertes ✓", icon="🎯")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Erreur de recherche : {exc}")
                finally:
                    prog.empty()

    with st.expander("📄 Importer un CSV (Instant Data Scraper)", expanded=True):
        uploaded = st.file_uploader("Fichier CSV", type=["csv"], key="csv_up")
        if uploaded and st.button("📥 Importer le CSV", type="secondary"):
            try:
                df = parse_csv_leads(uploaded)
                if st.session_state["leads"].empty:
                    st.session_state["leads"] = df
                else:
                    st.session_state["leads"] = pd.concat(
                        [st.session_state["leads"], df], ignore_index=True)
                st.session_state["leads_version"] += 1
                st.toast(f"{len(df)} leads importées ✓", icon="📥")
            except Exception as exc:  # noqa: BLE001
                st.error(f"CSV illisible : {exc}")

    st.markdown("### 📋 Table des leads")
    leads = st.session_state["leads"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Leads", len(leads))
    c2.metric("Avec email", int((leads["email"] != "").sum()) if not leads.empty else 0)
    c3.metric("Auditées", len(st.session_state["audits"]))
    c4.metric("Envoyées", st.session_state["sent_count"])

    if leads.empty:
        st.info("Aucune lead pour l'instant — lancez une recherche ou importez un CSV.")
        return

    ver = st.session_state["leads_version"]
    if st.session_state.get("edit_version") != ver:
        edit_df = leads.copy()
        edit_df[SEL_COL] = False
        st.session_state["leads_edit"] = edit_df
        st.session_state["edit_version"] = ver

    # Filtre d'affichage — un clic pour ne voir qu'une catégorie de leads
    filter_opt = st.radio("Filtre d'affichage", FILTER_OPTIONS, index=0,
                          horizontal=True, key="leads_filter")
    full_edit = st.session_state["leads_edit"]
    mask = apply_lead_filter(full_edit, filter_opt)
    view = full_edit[mask] if filter_opt != "Tous les leads" else full_edit
    if filter_opt != "Tous les leads":
        st.caption(f"🔎 {len(view)} / {len(full_edit)} leads affichées — filtre « {filter_opt} » actif. "
                   "Remettez le filtre sur « Tous les leads » pour appliquer vos modifications.")

    sc1, sc2, sc3 = st.columns([1, 1, 3])
    if sc1.button("☑️ Tout sélectionner", use_container_width=True,
                  help="Coche TOUTES les leads affichées (ou toutes si aucun filtre) — elles "
                       "deviendront les destinataires de l'onglet Outreach."):
        full_edit.loc[mask, SEL_COL] = True  # uniquement les leads visibles par le filtre
        st.session_state["leads_edit"] = full_edit
        st.session_state.pop("leads_editor", None)  # force le widget à repartir des données
        rerun()
    if sc2.button("⬜ Tout désélectionner", use_container_width=True):
        full_edit[SEL_COL] = False
        st.session_state["leads_edit"] = full_edit
        st.session_state.pop("leads_editor", None)
        rerun()
    sel_count = (int(full_edit[SEL_COL].fillna(False).astype(bool).sum())
                 if SEL_COL in full_edit.columns else 0)
    sc3.caption(f"✅ **{sel_count} / {len(full_edit)}** lead(s) cochée(s). La colonne « Sélection » "
                "définit les destinataires de l'onglet Outreach — sinon le filtre actif, "
                "sinon toutes les leads.")

    edited = st.data_editor(
        view,
        key="leads_editor",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        height=430,
        column_config={
            SEL_COL: st.column_config.CheckboxColumn("Sélection", width="small"),
            "name": st.column_config.TextColumn("Nom", width="medium"),
            "website": st.column_config.TextColumn("Site / URL", width="medium"),
            "email": st.column_config.TextColumn("Email", width="medium"),
            "phone": st.column_config.TextColumn("Téléphone / WhatsApp", width="small"),
            "source": st.column_config.TextColumn("Source", width="small"),
            "flag": st.column_config.TextColumn("Analyse", width="medium"),
            "segment": st.column_config.SelectboxColumn("Segment", options=SEGMENTS,
                                                         width="medium"),
            "snippet": st.column_config.TextColumn("Extrait", width="small"),
            "audit": st.column_config.TextColumn("Audit", width="small"),
            "status": st.column_config.TextColumn("Statut", width="small"),
        },
    )

    # Persiste l'édition/la sélection (✓) à chaque exécution → l'onglet Outreach n'envoie
    # qu'aux leads sélectionnées (ou filtrées), jamais à toute la liste par surprise.
    if filter_opt == "Tous les leads":
        st.session_state["leads_edit"] = edited
    elif SEL_COL in edited.columns:
        # Sous filtre : on persiste UNIQUEMENT la colonne de sélection (✓) des lignes visibles
        # (les autres colonnes ne sont modifiables que sur « Tous les leads »).
        idx = [i for i in edited.index if i in full_edit.index]
        if idx:
            full_edit.loc[idx, SEL_COL] = edited.loc[idx, SEL_COL].fillna(False).astype(bool)
            st.session_state["leads_edit"] = full_edit

    b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
    filter_active = filter_opt != "Tous les leads"
    if b1.button("💾 Appliquer les modifications", use_container_width=True,
                 disabled=filter_active):
        st.session_state["leads"] = edited.drop(columns=[SEL_COL], errors="ignore").reset_index(drop=True)
        st.session_state["leads_version"] += 1
        st.toast("Modifications appliquées ✓")
        rerun()
    if filter_active:
        b1.caption("Filtre actif : passez sur « Tous les leads » avant d'appliquer.",
                   unsafe_allow_html=True)
    if b2.button("🗑️ Supprimer la sélection", use_container_width=True):
        sel_mask = (edited[SEL_COL].fillna(False).astype(bool)
                    if SEL_COL in edited.columns else pd.Series(False, index=edited.index))
        if not sel_mask.any():
            st.toast("Cochez des lignes dans la colonne « Sélection » d'abord.")
        else:
            sel_rows = edited.loc[sel_mask]
            keys = {(_norm(r.get("name")), _norm(r.get("website")), _norm(r.get("email")))
                    for _, r in sel_rows.iterrows()}
            keep = ~full_edit.apply(
                lambda r: (_norm(r.get("name")), _norm(r.get("website")), _norm(r.get("email"))) in keys,
                axis=1,
            )
            st.session_state["leads"] = full_edit.loc[keep].drop(
                columns=[SEL_COL], errors="ignore").reset_index(drop=True)
            st.session_state["leads_version"] += 1
            st.toast(f"{len(keys)} lead(s) supprimée(s) ✓")
            rerun()
    if b3.button("🧹 Vider la liste", use_container_width=True):
        st.session_state["leads"] = empty_leads()
        st.session_state["leads_version"] += 1
        rerun()
    b4.download_button(
        "⬇️ Exporter les leads (CSV)", data=leads.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"leads_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv",
        use_container_width=True,
    )


# ------------------------------------------------------------------
#  Tab 2 — AI Audit Engine
# ------------------------------------------------------------------


def _save_audit(key: str) -> None:
    st.session_state["audits"][key] = st.session_state.get(f"audit_{key}", "")


def render_audit_tab() -> None:
    st.markdown("### 🧠 AI Audit Engine")
    leads = st.session_state["leads"]
    if leads.empty:
        st.info("Aucune lead — commencez par l'onglet Discovery.")
        return

    mode = st.session_state["mode"]
    api_key = st.session_state.get("gemini_key", "")
    if not api_key:
        st.warning("Renseignez votre clé Gemini dans la barre latérale pour générer les audits.")

    # Liste dynamique : les modèles réellement disponibles sur le compte (si clé fournie),
    # sinon repli sur la liste de référence GEMINI_MODELS.
    avail: list[str] = []
    if api_key:
        avail = _available_models_cached(api_key)
    model_opts = avail or GEMINI_MODELS
    current = st.session_state.get("gemini_model")
    if current is not None and current not in model_opts:
        del st.session_state["gemini_model"]  # ancien modèle (ex. arrêté) -> remise à zéro
    model = st.selectbox("Modèle Gemini", model_opts, index=0, key="gemini_model",
                         format_func=lambda m: str(m).replace("models/", ""))
    if avail:
        st.caption(f"✅ {len(avail)} modèles détectés sur ton compte — liste rafraîchie toutes les 5 min.")
    audit_delay = st.slider(
        "⏳ Délai entre audits (s)", 0, 60, 6, key="audit_delay",
        help="Espace les appels Gemini pour rester sous la limite de débit du plan gratuit "
             "(≈10 requêtes/min). En cas de 429, l'app réessaie automatiquement avec un délai croissant.",
    )

    st.markdown("#### Sélection des leads")
    # Mêmes leads que le filtre actif dans Discovery : si un filtre est appliqué,
    # seules les leads filtrées apparaissent ici (les autres ne sont pas auditées).
    filter_opt = st.session_state.get("leads_filter", "Tous les leads")
    if filter_opt != "Tous les leads":
        audit_leads = leads[apply_lead_filter(leads, filter_opt)]
        st.caption(f"🔎 {len(audit_leads)} / {len(leads)} leads — filtre « {filter_opt} » actif "
                   "dans Discovery. Les leads hors filtre ne sont pas listées ici.")
    else:
        audit_leads = leads
    opts = list(audit_leads.index)
    selected = st.multiselect(
        "Leads à auditer",
        options=opts,
        format_func=lambda i: (f"{audit_leads.loc[i, 'name']}"
                               + (f" — {audit_leads.loc[i, 'website']}" if audit_leads.loc[i, 'website'] else "")),
        key="audit_sel",
    )
    # Sécurité : on ne garde que les leads réellement dans le filtre actif — une sélection
    # faite avant d'appliquer le filtre (ou héritée d'une ancienne session) ne doit jamais
    # permettre d'auditer des leads hors filtre.
    allowed = set(opts)
    selected = [i for i in selected if i in allowed]

    need_snippets = [i for i in selected
                     if mode == MODE_COPY or str(leads.loc[i].get("segment", "")) == SEG_BAD_SITE]
    if need_snippets:
        st.markdown("#### Extraits de sites (Copywriting / Segment B — critique IA)")
        for i in need_snippets:
            with st.expander(f"✂️ Extrait pour « {leads.loc[i, 'name']} »", expanded=False):
                col1, col2 = st.columns([3, 1])
                st.text_area(
                    "Texte / description du site", key=f"snippet_{i}", height=110,
                    placeholder="Collez un extrait (ou récupérez-le du site) : l'IA le critiquera "
                                "pour le Segment B, ou s'en inspirera en mode Copywriting.",
                )
                col2.button("🔎 Récupérer du site", key=f"fetch_{i}", on_click=_fetch_snippet_cb,
                            args=(i,))
                _flush_outcome()

    if st.button("✨ Générer les audits IA", type="primary", disabled=not selected):
        if not api_key:
            st.error("Clé Gemini manquante.")
        else:
            prog = st.progress(0.0, text="Audits en cours…")
            fallback_toasted = False
            for n, i in enumerate(selected):
                row = leads.loc[i]
                key = lead_key(row)
                seg = str(row.get("segment", "")) or SEG_NO_SITE
                snippet = ""
                if mode == MODE_COPY or seg == SEG_BAD_SITE:
                    snippet = (st.session_state.get(f"snippet_{i}", "") or "").strip()
                    if not snippet and row.get("snippet"):
                        snippet = str(row["snippet"])
                location = f"{st.session_state.get('city', '')} {st.session_state.get('country', '')}".strip()
                prompt = audit_prompt(mode, str(row["name"]), location or "…", snippet,
                                      segment=seg, lang=st.session_state.get("lang", "fr"),
                                      website=str(row.get("website", "")))
                used_model = model
                text = ""
                try:
                    text = gemini_generate(api_key, model, prompt)
                except Exception as exc:  # noqa: BLE001
                    st.session_state["audits"][key] = ""
                    if _is_rate_limit(exc):
                        st.toast(
                            f"⏳ Quota Gemini atteint (429) pour {row['name']} — après plusieurs "
                            "tentatives automatiques. Patientez ~1 min (débit) ou jusqu'à demain "
                            "(quota gratuit), puis relancez.",
                            icon="⏳",
                        )
                    elif _is_not_found(exc):
                        # 404 : bascule automatique — réessaie avec un autre modèle de la liste
                        for fb in model_opts:
                            if fb == model:
                                continue
                            try:
                                text = gemini_generate(api_key, fb, prompt)
                                used_model = fb
                                break
                            except Exception:  # noqa: BLE001
                                continue
                        if not text:
                            st.toast(
                                f"❌ Modèle « {model} » indisponible (404) pour {row['name']} — "
                                "aucun modèle de la liste n'a répondu. Vérifiez votre clé Gemini "
                                "(sidebar) ou choisissez un autre modèle.",
                                icon="🚫",
                            )
                    else:
                        st.toast(f"Échec audit {row['name']} : {exc}", icon="⚠️")
                if text:
                    st.session_state["audits"][key] = text
                    if "audit" in st.session_state["leads"].columns:
                        st.session_state["leads"].loc[i, "audit"] = "✓"
                        st.session_state["leads"].loc[i, "status"] = "auditée"
                    if used_model != model and not fallback_toasted:
                        st.toast(
                            f"🔄 « {model} » indisponible (404) — audits générés avec « {used_model} » ✓",
                            icon="🔄",
                        )
                        fallback_toasted = True
                if n < len(selected) - 1 and audit_delay > 0:
                    time.sleep(audit_delay)
                prog.progress((n + 1) / len(selected), text=f"Audit {n + 1}/{len(selected)}")
            prog.empty()
            st.session_state["leads_version"] += 1
            st.toast("Audits générés ✓", icon="✨")
            rerun()

    st.markdown("#### Résultats")
    audited = {k: v for k, v in st.session_state["audits"].items() if v}
    if not audited:
        st.caption("Aucun audit généré pour l'instant.")
        return

    for key, text in list(audited.items()):
        name, site = key.rsplit("|", 1) if "|" in key else (key, "")
        with st.expander(f"🧾 {name or key}", expanded=False):
            st.text_area("Audit (éditable)", value=text, height=260,
                         key=f"audit_{key}", on_change=_save_audit, args=(key,))
            st.caption(site or "")

    audits_md = "\n\n---\n\n".join(
        f"## {k.split('|')[0] if '|' in k else k}\n\n{v}" for k, v in audited.items())
    st.download_button(
        "⬇️ Exporter les audits (Markdown)",
        data=audits_md.encode("utf-8-sig"),
        file_name=f"audits_{datetime.now():%Y%m%d_%H%M}.md", mime="text/markdown",
    )


# ------------------------------------------------------------------
#  Callbacks (on_click) — s'exécutent AVANT le re-rendu des widgets,
#  donc ils peuvent modifier les valeurs des widgets (clé session) sans erreur.
# ------------------------------------------------------------------


def _flush_outcome() -> None:
    """Affiche les toasts / erreurs produits par les callbacks on_click."""
    toast = st.session_state.pop("_out_toast", None)
    err = st.session_state.pop("_out_error", None)
    if toast:
        st.toast(toast, icon="✍️")
    if err:
        st.error(err)


def _reset_email_tpl() -> None:
    subj, bdy = _lang_templates(st.session_state["mode"], st.session_state.get("lang", "fr"))
    st.session_state["email_subject"] = subj
    st.session_state["email_body"] = bdy


def _insert_ph_subject() -> None:
    """Insère le placeholder choisi (selectbox `insert_ph`) à la fin de l'objet."""
    ph = st.session_state.get("insert_ph", "")
    if ph:
        cur = st.session_state.get("email_subject", "") or ""
        st.session_state["email_subject"] = (cur + " {" + ph + "}").strip()


def _insert_ph_body() -> None:
    """Insère le placeholder choisi (selectbox `insert_ph`) à la fin du corps."""
    ph = st.session_state.get("insert_ph", "")
    if ph:
        cur = st.session_state.get("email_body", "") or ""
        st.session_state["email_body"] = cur + ("\n\n" if cur else "") + "{" + ph + "}"


def _reset_wa_msg() -> None:
    st.session_state["wa_msg"] = _lang_wa(st.session_state["mode"], st.session_state.get("lang", "fr"))


def _improve_email_openai() -> None:
    lang = st.session_state.get("lang", "fr")
    lang_note = ("Answer in English." if lang == "en" else "Réponds en français.")
    prompt = (
        "Tu es un rédacteur commercial senior. Améliore cet email de prospection pour le rendre "
        "plus persuasif, fluide et professionnel.\n"
        "IMPORTANT : conserve INTACT tous les placeholders entre accolades ({...}) — ils seront "
        "remplacés automatiquement par le système.\n"
        f"Langue de réponse : {lang_note}\n\n"
        f"Email à améliorer :\n\n{st.session_state.get('email_body', '')}"
    )
    try:
        st.session_state["email_body"] = openai_generate(
            st.session_state["openai_key"], st.session_state.get("openai_model"), prompt)
        st.session_state["_out_toast"] = "Email amélioré ✓"
    except Exception as exc:  # noqa: BLE001
        st.session_state["_out_error"] = f"Échec OpenAI : {exc}"


def _improve_wa_openai() -> None:
    lang = st.session_state.get("lang", "fr")
    lang_note = ("Answer in English." if lang == "en" else "Réponds en français.")
    prompt = (
        "Tu es un commercial senior expert en prospection WhatsApp. Améliore ce message pour le "
        "rendre plus convaincant et professionnel.\n"
        "IMPORTANT : conserve INTACT tous les placeholders entre accolades ({...}).\n"
        f"Langue de réponse : {lang_note}\n\n"
        f"Message à améliorer :\n\n{st.session_state.get('wa_msg', '')}"
    )
    try:
        st.session_state["wa_msg"] = openai_generate(
            st.session_state["openai_key"], st.session_state.get("openai_model"), prompt)
        st.session_state["_out_toast"] = "Message amélioré ✓"
    except Exception as exc:  # noqa: BLE001
        st.session_state["_out_error"] = f"Échec OpenAI : {exc}"


def _fetch_snippet_cb(i: int) -> None:
    site = st.session_state["leads"].loc[i, "website"]
    got = fetch_snippet(site)
    if got:
        st.session_state[f"snippet_{i}"] = got
    else:
        st.session_state["_out_error"] = "Aucun extrait exploitable sur ce site (JS ?)."


def _mark_wa(i: int) -> None:
    """Ouvre le lien wa.me d'une lead et compte le contact dans le dashboard."""
    try:
        leads = st.session_state["leads"]
        row = leads.loc[i]
        mode = st.session_state["mode"]
        wa_tpl = st.session_state.get("wa_msg") or DEFAULT_WA[mode]
        msg = fill_template(wa_tpl, row, st.session_state.get("agency", ""),
                            f"{st.session_state.get('city','')} {st.session_state.get('country','')}".strip(),
                            mode)
        webbrowser.open(wa_link(str(row["phone"]), msg))
        _track(st.session_state["campaign_stats"], "WhatsApp", True,
               str(row["name"]), "lien wa.me ouvert")
        st.session_state["_out_toast"] = "WhatsApp ouvert — contact compté ✓"
    except Exception as exc:  # noqa: BLE001
        st.session_state["_out_error"] = f"Échec WhatsApp : {exc}"


# ------------------------------------------------------------------
#  Tab 3 — Smart Outreach
# ------------------------------------------------------------------


def render_outreach_tab() -> None:
    st.markdown("### 🚀 Smart Outreach")
    leads = st.session_state["leads"]
    mode = st.session_state["mode"]

    if leads.empty:
        st.info("Aucune lead — commencez par l'onglet Discovery.")
        return

    # Destinataires = sélection ✓ de Discovery, sinon filtre actif, sinon toutes
    target, src = _outreach_plan(leads)
    st.caption(f"🎯 Destinataires : **{len(target)} / {len(leads)}** lead(s) — **{src}**.")
    if len(target) < len(leads):
        st.info("Seules les leads sélectionnées/filtrées dans Discovery seront contactées.")

    # ---------------- Email ----------------
    with st.expander("📧 Campagne email", expanded=True):
        if mode == MODE_COPY:
            langs = ["fr", "en", "de"]
            st.selectbox("Langue du modèle", langs, key="template_lang",
                         index=langs.index(st.session_state.get("template_lang", "fr")),
                         help="Change la langue du modèle (le réinitialise).")
            lang = st.session_state.get("template_lang", "fr")
            if st.session_state.get("prev_lang") != lang:
                subj, bdy = DEFAULT_COPY_LANGS.get(lang, DEFAULT_COPY_LANGS["fr"])
                st.session_state["email_subject"] = subj
                st.session_state["email_body"] = bdy
                st.session_state["prev_lang"] = lang
        subject = st.text_input("Objet de l'email", key="email_subject")
        body = st.text_area("Corps du message (placeholders)", key="email_body", height=300)
        st.caption(f"Template libre : écrivez l'objet et le corps avec les accolades "
                   f"{PLACEHOLDERS} — remplacées automatiquement par les infos du client à l'envoi. "
                   "Toute colonne de la lead fonctionne aussi en placeholder — ex. **{{Phone}}**, "
                   "**{{Segment}}**, **{{Source}}**, **{{City}}**, **{{Country}}**. "
                   "**{{Audit}}** = audit IA · **{{PaymentPlan}}** = bloc paiement · "
                   "placeholder inconnu = laissé tel quel · champ vide = « … ».")

        ph1, ph2, ph3 = st.columns([3, 1, 1])
        ph_opts = ([p.strip().strip("{} ") for p in PLACEHOLDERS.split("·")]
                   + ["Phone", "City", "Country", "Segment", "Source", "Snippet", "Status"])
        ph1.selectbox("➕ Insérer un placeholder (info du client)", ph_opts,
                      key="insert_ph",
                      help="Choisissez un placeholder puis cliquez « Dans l'objet » "
                           "ou « Dans le corps » pour l'ajouter au template — il sera "
                           "remplacé par l'info réelle du client à l'envoi.")
        ph2.button("Dans l'objet", use_container_width=True, key="ins_ph_subj",
                   on_click=_insert_ph_subject)
        ph3.button("Dans le corps", use_container_width=True, key="ins_ph_body",
                   on_click=_insert_ph_body)

        t1, t2, t3, t4 = st.columns([1, 1, 1, 2])
        t1.button("🔄 Réinitialiser le modèle", use_container_width=True, on_click=_reset_email_tpl)
        payment_on = t2.checkbox("Ajouter le bloc paiement", value=True, key="payment_on")
        preview_btn = t3.button("👁️ Prévisualiser (1ʳᵉ lead)", use_container_width=True)
        t4.button("✍️ Améliorer avec OpenAI", use_container_width=True,
                  disabled=not (bool(st.session_state.get("openai_key")) and _OPENAI_AVAILABLE),
                  help="Réécrit votre email via OpenAI (optionnel — Gemini reste le moteur "
                       "principal, gratuit).",
                  on_click=_improve_email_openai)
        _flush_outcome()

        # --- Contenu enrichi : image(s), lien CTA, vidéo -----------------------
        with st.expander("🖼️ Contenu enrichi (images · lien · vidéo)", expanded=False):
            st.caption("Dans le corps du template, vous pouvez aussi écrire directement : "
                       "**![légende](https://…/image.png)** pour afficher une image par URL, "
                       "ou **[texte du lien](https://…)** pour un lien cliquable.")
            imgs = st.file_uploader(
                "🖼️ Images à téléverser dans l'email (logo, visuel…)",
                type=["png", "jpg", "jpeg", "gif", "webp"],
                accept_multiple_files=True, key="email_images",
                help="Les images téléversées sont jointes en inline (cid) — affichées en tête "
                     "de l'email dans Gmail et la plupart des clients. Canal smtplib uniquement.")
            img_list = []
            for f in imgs or []:
                mime = (f.type or "image/png").split("/")
                img_list.append({
                    "maintype": mime[0] or "image",
                    "subtype": mime[1] if len(mime) > 1 else "png",
                    "data": f.getvalue(),
                })
            st.session_state["email_images_data"] = img_list
            if img_list:
                st.success(f"{len(img_list)} image(s) prête(s) — insérées en tête de l'email ✓")
            cr1, cr2 = st.columns(2)
            cr1.text_input("🔗 Lien du bouton (CTA)", key="email_cta_url",
                           placeholder="https://votresite.com",
                           help="Optionnel — crée un bouton doré cliquable dans l'email.")
            cr2.text_input("Texte du bouton", key="email_cta_label", value="En savoir plus")
            st.text_input("🎬 Vidéo (URL YouTube / Vimeo)", key="email_video_url",
                          placeholder="https://youtube.com/watch?v=…",
                          help="Optionnel — ajoute un lien « ▶️ Regarder la vidéo » à l'email.")

        if preview_btn and not target.empty:
            row = target.iloc[0]
            audit = st.session_state["audits"].get(lead_key(row), "")
            payment = payment_block(mode, st.session_state.get("iban", ""),
                                    st.session_state.get("africa_payment", "")) if payment_on else ""
            preview = fill_template(body, row, st.session_state.get("agency", ""),
                                    f"{st.session_state.get('city','')} {st.session_state.get('country','')}".strip(),
                                    mode, audit, payment)
            with st.expander("Aperçu (1ʳᵉ lead)", expanded=True):
                st.markdown(f"**Objet :** {subject}")
                st.divider()
                st.write(preview)

    # ---------------- Envoi ----------------
    with st.expander("✈️ Envoi séquentiel (anti-spam)", expanded=True):
        email_leads = target[target["email"] != ""]
        if email_leads.empty:
            st.warning("Aucune lead avec email. Ajoutez des emails dans l'onglet Discovery.")
        else:
            opts = list(email_leads.index)
            recipients = st.multiselect(
                "Destinataires", options=opts, default=opts,
                format_func=lambda i: f"{email_leads.loc[i,'name']} <{email_leads.loc[i,'email']}>",
                key="recipients",
            )
            recipients = [i for i in recipients if i in email_leads.index]

            c1, c2, c3 = st.columns([2, 2, 1])
            dmin, dmax = c1.slider("Délai entre envois (secondes)", 10, 300, (90, 90), step=5,
                                   help="90 secondes par défaut — délai humain anti-spam.")
            test_mode = c2.checkbox("Mode test (2–6 s)", key="test_mode",
                                    help="Pour valider le pipeline sans attendre.")
            if test_mode:
                dmin, dmax = 2, 6

            channel = c3.selectbox("Canal d'envoi",
                                   ["smtplib (Gmail App Password)", "composio (Gmail OAuth)"],
                                   key="channel")

            if channel.startswith("composio"):
                ok, msg = _composio_status_cached(st.session_state.get("composio_key", ""))
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)

            running = bool(st.session_state.get("out_thread") and st.session_state["out_thread"].is_alive())
            b1, b2 = st.columns(2)
            if b1.button("▶️ Lancer la campagne", type="primary", use_container_width=True,
                         disabled=running or not recipients):
                creds_ok = True
                if channel.startswith("composio"):
                    if not st.session_state.get("composio_key"):
                        st.error("Renseignez la clé Composio (sidebar) — puis connectez Gmail sur composio.dev.")
                        creds_ok = False
                elif not st.session_state.get("gmail_user") or not st.session_state.get("gmail_pass"):
                    st.error("Renseignez les credentials Gmail (sidebar) — ou passez en canal Composio.")
                    creds_ok = False
                if creds_ok:
                    payment = payment_block(mode, st.session_state.get("iban", ""),
                                            st.session_state.get("africa_payment", "")) if payment_on else ""
                    img_list = st.session_state.get("email_images_data") or []
                    cids = [f"img_{i}" for i in range(len(img_list))]
                    cta_url = (st.session_state.get("email_cta_url") or "").strip()
                    cta = ({"url": cta_url,
                            "label": (st.session_state.get("email_cta_label") or "").strip()
                                     or "En savoir plus"} if cta_url else None)
                    video_url = (st.session_state.get("email_video_url") or "").strip()
                    queue = []
                    for i in recipients:
                        row = email_leads.loc[i]
                        audit = st.session_state["audits"].get(lead_key(row), "")
                        q = {
                            "name": str(row["name"]),
                            "email": str(row["email"]),
                            "subject": subject,
                            "body": fill_template(body, row, st.session_state.get("agency", ""),
                                                  f"{st.session_state.get('city','')} {st.session_state.get('country','')}".strip(),
                                                  mode, audit, payment),
                        }
                        q["html"] = body_to_html(q["body"], image_cids=cids, cta=cta,
                                                  video=video_url)  # HTML « Luxe » + enrichi
                        q["images"] = img_list
                        queue.append(q)
                    if not queue:
                        st.error("Aucun destinataire.")
                    else:
                        if channel.startswith("composio"):
                            ck = st.session_state.get("composio_key", "")
                            send_fn = lambda item: send_via_composio(ck, item["email"], item["subject"], item["body"])  # noqa: E731
                        else:
                            gu = st.session_state["gmail_user"]
                            gp = st.session_state["gmail_pass"]
                            send_fn = lambda item: send_via_smtp(gu, gp, item["email"], item["subject"], item["body"], html_body=item.get("html"), images=item.get("images"))  # noqa: E731
                        state = {"queue": queue, "log": [], "pos": 0, "done": False,
                                 "stopped": False,
                                 "stats": {"contacted": 0, "wa": 0, "mail": 0, "fail": 0,
                                            "history": []}}
                        st.session_state["out_state"] = state
                        st.session_state["out_stop"] = threading.Event()
                        t = threading.Thread(target=outreach_worker,
                                             args=(state, st.session_state["out_stop"], send_fn, int(dmin), int(dmax)),
                                             daemon=True)
                        st.session_state["out_thread"] = t
                        t.start()
                        st.toast("Campagne démarrée ✓")

            if b2.button("⏹️ Stopper la campagne", use_container_width=True, disabled=not running):
                st.session_state["out_stop"].set()
                st.toast("Arrêt demandé — en attente du prochain envoi…")

            state = st.session_state.get("out_state")
            if state:
                total = len(state["queue"])
                st.progress(state["pos"] / total if total else 0.0,
                            text=f"Progression : {state['pos']}/{total}")
                if state["log"]:
                    with st.expander("📜 Journal d'envoi", expanded=True):
                        st.code("\n".join(state["log"][-80:]), language=None)
                if state["done"]:
                    if state.get("stopped"):
                        st.warning("Campagne interrompue par l'utilisateur.")
                    else:
                        st.success(f"Campagne terminée — {state['pos']}/{total} emails envoyés.")
                        st.session_state["sent_count"] += state["pos"]
                    _merge_stats(state["stats"])
                    st.session_state["out_state"] = None
                else:
                    time.sleep(2)
                    rerun()
            elif running:
                time.sleep(2)
                rerun()

    # ---------------- WhatsApp ----------------
    with st.expander("📲 WhatsApp — envoi direct aux leads", expanded=True):
        my_wa = _norm(st.session_state.get("my_wa", ""))
        if my_wa:
            st.success(f"📱 Envoi depuis votre numéro : **{my_wa}** — les liens s'ouvrent dans votre "
                       "WhatsApp et le message partira de ce numéro.")
        else:
            st.info("Renseignez votre numéro WhatsApp dans la barre latérale (Identité → 📱 Votre "
                    "numéro WhatsApp) pour confirmer votre identité d'envoi.")

        st.text_area("Message WhatsApp (placeholders)", key="wa_msg", height=150,
                     placeholder="Ex : Bonjour {LeadName} 👋 …")
        c1, c2 = st.columns([1, 3])
        c1.button("🔄 Modèle par défaut", use_container_width=True, on_click=_reset_wa_msg)
        c2.button("✍️ Améliorer le message avec OpenAI", use_container_width=True,
                  disabled=not (bool(st.session_state.get("openai_key")) and _OPENAI_AVAILABLE),
                  on_click=_improve_wa_openai)
        _flush_outcome()

        wa_tpl = st.session_state.get("wa_msg") or DEFAULT_WA[mode]
        cta_wa = (st.session_state.get("email_cta_url") or "").strip()
        if cta_wa:
            st.caption(f"🔗 Le lien CTA « {cta_wa} » sera ajouté au message — wa.me n'accepte "
                       "pas d'images/vidéos jointes (canal email uniquement).")
        wa_leads = target[target["phone"].astype(str).str.strip() != ""]
        if wa_leads.empty:
            st.warning("Aucune lead avec numéro de téléphone — ajoutez des numéros dans l'onglet "
                       "Discovery (colonne « Téléphone / WhatsApp »).")
        else:
            st.markdown(f"**{len(wa_leads)} lead(s) avec numéro** — cliquez sur « Envoyer » pour "
                        "ouvrir WhatsApp avec le message pré-rempli :")
            for i in list(wa_leads.index):
                row = wa_leads.loc[i]
                msg = fill_template(wa_tpl, row, st.session_state.get("agency", ""),
                                    f"{st.session_state.get('city','')} {st.session_state.get('country','')}".strip(),
                                    mode)
                if cta_wa:
                    msg += f"\n\n🔗 {cta_wa}"
                link = wa_link(str(row["phone"]), msg)
                with st.expander(f"📲 {row['name']} — {row['phone']}", expanded=False):
                    st.code(msg, language=None)
                    cc1, cc2 = st.columns([1, 2])
                    cc1.link_button("📲 Envoyer sur WhatsApp", link, use_container_width=True,
                                    key=f"wa_send_{i}")
                    cc2.button("✅ Ouvrir & compter l'envoi", key=f"wa_open_{i}",
                               use_container_width=True, on_click=_mark_wa, args=(i,))
            _flush_outcome()

    # ---------------- One-Click Multi-Send (hybride) ----------------
    with st.expander("⚡ One-Click Multi-Send (WhatsApp + Email)", expanded=True):
        hybrid = target[(target["phone"].astype(str).str.strip() != "")
                        | (target["email"].astype(str).str.strip() != "")]
        if hybrid.empty:
            st.warning("Aucune lead joignable (ni téléphone, ni email) — ajoutez des contacts "
                       "dans l'onglet Discovery.")
        else:
            st.caption("**Règle hybride** : téléphone + email → les deux canaux · téléphone seul → "
                       "WhatsApp · email seul → **Email Only** (bascule automatique).")
            opts = list(hybrid.index)
            sel = st.multiselect(
                "Leads à contacter", options=opts, default=opts,
                format_func=lambda i: (f"{hybrid.loc[i,'name']} — 📞 {hybrid.loc[i,'phone'] or '—'} "
                                       f"· ✉️ {hybrid.loc[i,'email'] or '—'}"),
                key="hybrid_sel",
            )
            sel = [i for i in sel if i in hybrid.index]
            if sel:
                has_ph = hybrid.loc[sel, "phone"].astype(str).str.strip().ne("")
                has_em = hybrid.loc[sel, "email"].astype(str).str.strip().ne("")
                n_both = int((has_ph & has_em).sum())
                n_ph = int(has_ph.sum())
                n_em = int(has_em.sum())
                st.caption(f"🎯 {len(sel)} lead(s) : **{n_both}** avec téléphone + email (les deux) "
                           f"· **{n_ph - n_both}** WhatsApp only · **{n_em - n_both}** Email Only.")
                c1, c2, c3 = st.columns([2, 2, 1])
                dmin, dmax = c1.slider("Délai humain entre leads (s)", 10, 300, (90, 90),
                                       step=5, key="hybrid_delay",
                                       help="90 secondes par défaut — envoi espacé anti-spam.")
                if c2.checkbox("Mode test (2–6 s)", key="hybrid_test"):
                    dmin, dmax = 2, 6
                chan = c3.selectbox("Canal email", ["smtplib (Gmail App Password)",
                                                    "composio (Gmail OAuth)"], key="hybrid_channel",
                                    help="Les images du contenu enrichi ne s'envoient qu'en smtplib.")
                running = bool(st.session_state.get("hybrid_thread")
                               and st.session_state["hybrid_thread"].is_alive())
                b1, b2 = st.columns([3, 1])
                if b1.button("🚀 Lancer le One-Click Multi-Send", type="primary",
                             use_container_width=True, disabled=running or not sel):
                    creds_ok = True
                    if n_em > 0:
                        if chan.startswith("composio"):
                            if not st.session_state.get("composio_key"):
                                st.error("Renseignez la clé Composio (sidebar) pour le canal email.")
                                creds_ok = False
                        elif not (st.session_state.get("gmail_user")
                                  and st.session_state.get("gmail_pass")):
                            st.error("Renseignez les credentials Gmail (sidebar) pour les envois "
                                     "email — ou choisissez le canal Composio.")
                            creds_ok = False
                    if creds_ok:
                        agency = st.session_state.get("agency", "")
                        loc = f"{st.session_state.get('city','')} {st.session_state.get('country','')}".strip()
                        wa_tpl_oc = st.session_state.get("wa_msg") or DEFAULT_WA[mode]
                        subj_oc = st.session_state.get("email_subject") \
                            or DEFAULT_TEMPLATES[mode]["subject"]
                        body_oc = st.session_state.get("email_body") \
                            or DEFAULT_TEMPLATES[mode]["body"]
                        payment = (payment_block(mode, st.session_state.get("iban", ""),
                                                 st.session_state.get("africa_payment", ""))
                                   if payment_on else "")
                        img_list_oc = st.session_state.get("email_images_data") or []
                        cids_oc = [f"img_{i}" for i in range(len(img_list_oc))]
                        cta_url_oc = (st.session_state.get("email_cta_url") or "").strip()
                        cta_oc = ({"url": cta_url_oc,
                                   "label": (st.session_state.get("email_cta_label") or "").strip()
                                            or "En savoir plus"} if cta_url_oc else None)
                        video_oc = (st.session_state.get("email_video_url") or "").strip()
                        queue = []
                        for i in sel:
                            row = hybrid.loc[i]
                            audit = st.session_state["audits"].get(lead_key(row), "")
                            phone = _norm(row.get("phone"))
                            email = _norm(row.get("email"))
                            item = {"name": str(row["name"]), "email": email, "wa_link": ""}
                            if phone:
                                wa_msg = fill_template(wa_tpl_oc, row, agency, loc, mode)
                                if cta_url_oc:
                                    wa_msg += f"\n\n🔗 {cta_url_oc}"
                                item["wa_link"] = wa_link(phone, wa_msg)
                            if email:
                                item["subject"] = fill_template(subj_oc, row, agency, loc, mode)
                                item["body"] = fill_template(body_oc, row, agency, loc, mode,
                                                              audit, payment)
                                item["html"] = body_to_html(item["body"], image_cids=cids_oc,
                                                            cta=cta_oc, video=video_oc)
                                item["images"] = img_list_oc
                            queue.append(item)
                        if not queue:
                            st.error("Aucune lead à contacter.")
                        else:
                            if chan.startswith("composio"):
                                ck = st.session_state.get("composio_key", "")
                                email_fn = lambda it: send_via_composio(ck, it["email"], it["subject"], it["body"])  # noqa: E731
                            else:
                                gu = st.session_state["gmail_user"]
                                gp = st.session_state["gmail_pass"]
                                email_fn = lambda it: send_via_smtp(gu, gp, it["email"], it["subject"], it["body"], html_body=it.get("html"), images=it.get("images"))  # noqa: E731
                            state = {"queue": queue, "log": [], "pos": 0, "done": False,
                                     "stopped": False,
                                     "stats": {"contacted": 0, "wa": 0, "mail": 0, "fail": 0,
                                                "history": []}}
                            st.session_state["hybrid_state"] = state
                            st.session_state["hybrid_stop"] = threading.Event()
                            t = threading.Thread(target=one_click_worker,
                                                 args=(state, st.session_state["hybrid_stop"],
                                                       email_fn, int(dmin), int(dmax)),
                                                 daemon=True)
                            st.session_state["hybrid_thread"] = t
                            t.start()
                            st.toast("One-Click Multi-Send démarré ✓")
                if b2.button("⏹️ Stopper", use_container_width=True, disabled=not running,
                             key="hybrid_stop_btn"):
                    st.session_state["hybrid_stop"].set()
                hstate = st.session_state.get("hybrid_state")
                if hstate:
                    total = len(hstate["queue"])
                    st.progress(hstate["pos"] / total if total else 0.0,
                                text=f"Progression : {hstate['pos']}/{total}")
                    if hstate["log"]:
                        with st.expander("📜 Journal One-Click", expanded=True):
                            st.code("\n".join(hstate["log"][-80:]), language=None)
                    if hstate["done"]:
                        if hstate.get("stopped"):
                            st.warning("One-Click interrompu par l'utilisateur.")
                        else:
                            st.success(f"Terminé — {hstate['pos']}/{total} leads traitées.")
                        _merge_stats(hstate["stats"])
                        st.session_state["hybrid_state"] = None
                    else:
                        time.sleep(2)
                        rerun()
                elif running:
                    time.sleep(2)
                    rerun()

    st.info(
        "**Éthique & conformité** : prospection froide autorisée sous conditions (RGPD / loi "
        "Informatique et Libertés). Utilisez les délais anti-spam, proposez un moyen de "
        "désinscription et ne sollicitez que des professionnels dans le cadre de leur activité."
    )


# ------------------------------------------------------------------
#  Tab 4 — Dashboard de campagne (stats en direct)
# ------------------------------------------------------------------


def render_dashboard_tab() -> None:
    st.markdown("### 📊 Dashboard de campagne")
    leads = st.session_state["leads"]
    stats = st.session_state["campaign_stats"]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Leads", len(leads))
    c2.metric("Contactées", stats["contacted"])
    c3.metric("WhatsApp", stats["wa"])
    c4.metric("Emails", stats["mail"])
    c5.metric("Échecs", stats["fail"])
    succ = stats["mail"] + stats["wa"]
    c6.metric("Taux de succès",
              f"{100 * succ / (succ + stats['fail']):.0f} %" if (succ + stats["fail"]) else "—")

    st.markdown("#### Répartition par segment")
    if leads.empty:
        st.info("Importez ou recherchez des leads pour voir la répartition par segment.")
    else:
        seg_counts = (leads["segment"].value_counts()
                      if "segment" in leads.columns else pd.Series(dtype=int))
        for seg in SEGMENTS:
            n = int(seg_counts.get(seg, 0))
            pct = n / len(leads) * 100 if len(leads) else 0
            st.progress(pct / 100, text=f"{seg} — {n} leads ({pct:.0f} %)")
        st.caption("🗂️ **Segment A — Sans site** : argumentaire visibilité / perte de clients locaux / "
                   "confiance diaspora (PAS). · 🗂️ **Segment B — Site médiocre** : critique IA de "
                   "l'URL / du texte (AIDA) — esthétique et conversion.")

    st.markdown("#### Historique des contacts")
    if not stats["history"]:
        st.caption("Aucun contact pour l'instant — lancez une campagne ou envoyez sur WhatsApp.")
    else:
        st.dataframe(pd.DataFrame(stats["history"]), hide_index=True,
                     use_container_width=True, height=220)
    if st.button("🧹 Vider l'historique", key="reset_stats_btn"):
        stats["history"] = []
        stats["contacted"] = stats["wa"] = stats["mail"] = stats["fail"] = 0
        st.toast("Historique vidé ✓")
        rerun()


# ------------------------------------------------------------------
#  Main
# ------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Scriba Omniscient Prospector",
        page_icon="⛏️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    init_session()

    mode = st.session_state["mode"]
    if st.session_state.get("prev_mode") != mode:
        ensure_template_defaults(mode)
        st.session_state["sectors_sel"] = [s["label"] for s in SECTORS[mode]]
        st.session_state["prev_mode"] = mode

    render_sidebar()

    agency = st.session_state.get("agency", "") or "Scriba"
    st.markdown(
        f'<div class="brand">'
        f'<div class="brand-eyebrow">Scriba Omniscient · Prospection IA</div>'
        f'<div class="brand-title">Prospector <small>V1.0</small></div>'
        f'<div class="brand-sub"><b>{agency}</b> — {MODE_INFO[mode]["emoji"]} {mode} · '
        f'{st.session_state.get("city","") or "Ville"} / {st.session_state.get("country","") or "Pays"}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="side-sep"></div>', unsafe_allow_html=True)

    _tabs_kw = {"key": "main_tabs"} if "key" in inspect.signature(st.tabs).parameters else {}
    tab1, tab2, tab3, tab4 = st.tabs(
        ["🧭 Discovery", "🧠 Audit IA", "🚀 Outreach", "📊 Dashboard"], **_tabs_kw)
    with tab1:
        render_discovery_tab()
    with tab2:
        render_audit_tab()
    with tab3:
        render_outreach_tab()
    with tab4:
        render_dashboard_tab()

    st.markdown(
        '<div class="ftr">⛏️ SCRIBA OMNISCIENT PROSPECTOR · <b>v1.1</b> · '
        'Segments A/B · IA FR/EN · One-Click Multi-Send · Dashboard</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
