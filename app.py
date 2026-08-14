# -*- coding: utf-8 -*-
"""
====================================================================
  SCRIBA OMNISCIENT PROSPECTOR — v6
  Tableau de bord Streamlit de prospection automatisée
  ------------------------------------------------------------------
  4 modèles d'affaires depuis un seul dashboard :
    1) European Copywriting Sniper   -> agences immobilières (EU)
    2) Local Web-Design Hunter       -> PME sans site (local / Afrique)
    3) Local SEO Visibility          -> fiches Google Maps faibles
    4) AI Agency (MaisonNova)        -> PME 3-20 employés sans IA (audit web)

  v6 ajoute :
    · Persistance ZÉRO perte — settings.json (clés, emails, agence, logo)
      chargés au démarrage et sauvegardés instantanément.
    · Découverte géo-localisée — sélecteur des 10 pays francophones.
    · LinkedIn Sniper — profils décideurs via Google Dorking (site:linkedin.com/in/).
    · Audit IA des sites — scan HTML (BeautifulSoup) : absence de chatbot/IA,
      présence form/« Contact » -> marquage « Cible Prioritaire IA ».
    · Dashboard de campagnes — tableau [Nom | Pays | Source | Statut | Réponse],
      taux de clic et taux de réponse.
    · Personnalisation IA par pays (Gemini Flash) — formel en France,
      plus chaleureux au Togo, etc.

  Stack : Streamlit · Google GenAI (Gemini) · Pandas · Requests ·
          BeautifulSoup · ddgs (DuckDuckGo) · smtplib · Composio

  Lancement :  streamlit run app.py
====================================================================
"""

from __future__ import annotations

import inspect
import json
import os
import random
import re
import smtplib
import ssl
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

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
MODE_AI = "AI Agency (MaisonNova)"
MODES = [MODE_COPY, MODE_WEB, MODE_SEO, MODE_AI]

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
    MODE_AI: {
        "emoji": "🤖",
        "label": "🤖 AI Agency (MaisonNova)",
        "desc": "Cible les PME (3-20 employés) sans IA sur leur site — audit web automatique (chatbot/assistant/IA absents) et argumentaire « IA pour votre entreprise ».",
    },
}

GEMINI_MODELS = [
    "gemini-3.5-flash",   # DÉFAUT : répond actuellement (quota gratuit 3.6-flash souvent épuisé)
    "gemini-3.6-flash",   # dernier modèle stable (souvent quota 429 sur plan gratuit)
    "gemini-2.5-flash",   # toujours supporté (compromis coût/performance)
    "gemini-2.5-pro",
    # NB : gemini-2.0-flash retiré de la liste — modèle arrêté par Google (404 NOT_FOUND)
]

LEAD_COLS = ["name", "website", "email", "phone", "source", "flag", "segment", "snippet", "audit", "status",
             "linkedin", "employees", "ai_target", "ai_audit"]

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
    MODE_AI: [
        "PME {city} {country}",
        "entreprise de services {city} {country}",
        "société {city} {country}",
        "bureau {city} {country}",
        "agence {city} {country}",
        "startup {city} {country}",
        "commerçant {city} {country}",
        "hôtel {city} {country}",
        "clinique {city} {country}",
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
    MODE_AI: [
        {"label": "🏢 PME & services B2B", "queries": [
            "PME {city} {country}", "entreprise de services {city} {country}",
            "société de conseil {city} {country}", "bureau d'études {city} {country}",
        ]},
        {"label": "🏥 Santé & bien-être", "queries": [
            "clinique {city} {country}", "cabinet médical {city} {country}",
            "pharmacie {city} {country}", "cabinet dentaire {city} {country}",
        ]},
        {"label": "🏨 Hôtellerie & tourisme", "queries": [
            "hôtel {city} {country}", "agence de voyage {city} {country}",
            "auberge {city} {country}", "location de voitures {city} {country}",
        ]},
        {"label": "🛍️ Commerce & distribution", "queries": [
            "boutique {city} {country}", "magasin {city} {country}",
            "grossiste {city} {country}", "e-commerce {city} {country}",
        ]},
        {"label": "🏠 Immobilier & construction", "queries": [
            "agence immobilière {city} {country}", "promoteur immobilier {city} {country}",
            "entreprise de construction {city} {country}", "architecte {city} {country}",
        ]},
        {"label": "🎓 Éducation & formation", "queries": [
            "école {city} {country}", "centre de formation {city} {country}",
            "institut {city} {country}", "école de langues {city} {country}",
        ]},
        {"label": "🍽️ Restaurants & cafés", "queries": [
            "restaurant {city} {country}", "café {city} {country}", "traiteur {city} {country}",
        ]},
        {"label": "🔧 Artisans & industriels", "queries": [
            "atelier {city} {country}", "menuiserie {city} {country}",
            "garage {city} {country}", "imprimerie {city} {country}",
        ]},
        {"label": "🚚 Transport & logistique", "queries": [
            "transport {city} {country}", "logistique {city} {country}",
            "livraison {city} {country}", "taxi {city} {country}",
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
    MODE_AI: {
        "subject": "{LeadName} — Et si votre site accueillait vos clients 24h/24 ?",
        "body": (
            "Bonjour {LeadName},\n\n"
            "Nous avons analysé votre présence en ligne à {Location} et relevé une opportunité "
            "précise : votre site ne propose aujourd'hui aucun assistant IA ni chatbot. Or, la "
            "plupart des visiteurs qui posent une question après les heures d'ouverture ne "
            "reviennent jamais — c'est un chiffre d'affaires qui s'échappe chaque nuit.\n\n"
            "{Audit}\n\n"
            "Chez {AgencyName}, nous installons un assistant IA sur votre site : il répond aux "
            "clients instantanément (24h/24), qualifie leurs demandes et leur fixe rendez-vous — "
            "le tout en français, adapté à votre activité. Conçu pour les PME de 3 à 20 employés, "
            "sans équipe technique. Premier déploiement pilote offert, sans engagement.\n\n"
            "À très vite,\n{AgencyName}\n\n—\n{PaymentPlan}"
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
    MODE_AI: (
        "Bonjour {LeadName} 👋\nJe suis {AgencyName}. Nous avons scanné votre site à {Location} : "
        "aucun chatbot ni assistant IA n'y répond aux clients. Un assistant IA 24h/24 = des "
        "demandes qualifiées et des rendez-vous automatiques. Déploiement pilote offert pour "
        "les PME de 3 à 20 employés. On en parle ?"
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
    MODE_AI: {
        "subject": "{LeadName} — What if your website answered your customers 24/7?",
        "body": (
            "Hello {LeadName},\n\n"
            "We analyzed your online presence in {Location} and spotted a precise opportunity: "
            "your website currently offers no AI assistant or chatbot. Yet most visitors who ask "
            "a question after business hours never come back — that is revenue slipping away "
            "every night.\n\n"
            "{Audit}\n\n"
            "At {AgencyName}, we deploy an AI assistant on your website: it answers customers "
            "instantly (24/7), qualifies their requests and books appointments — in French, "
            "tailored to your business. Built for SMEs with 3 to 20 employees, no tech team "
            "required. First pilot deployment offered, no commitment.\n\n"
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
    MODE_AI: (
        "Hello {LeadName} 👋\nI'm from {AgencyName}. We scanned your website in {Location}: "
        "no chatbot or AI assistant answers your customers. A 24/7 AI assistant = qualified "
        "requests and automatic bookings. Free pilot deployment for SMEs with 3-20 employees. "
        "Shall we talk?"
    ),
}


# ------------------------------------------------------------------
#  v6 — Persistance locale · Géolocalisation francophone ·
#  Audit IA des sites · LinkedIn Sniper · Personnalisation IA par pays
# ------------------------------------------------------------------

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"

# Champs du dashboard sauvegardés instantanément dans settings.json.
# ⚠️ Stockés EN CLAIR sur la machine locale (comme demandé) — protégez ce
# fichier, ne le partagez pas et ne le committez jamais (cf. .gitignore).
SETTINGS_KEYS = ["agency", "gemini_key", "gmail_user", "gmail_pass", "my_wa",
                 "composio_key", "openai_key", "openai_model", "iban",
                 "africa_payment", "city", "country", "fr_country", "lang_en",
                 "ddg_region", "gmail_accounts", "warmup_enabled", "warmup_start",
                 "daily_limit"]

# --- Mots-clés IA détectés par l'Audit Web (module AI Agency) ---
AI_AUDIT_KEYWORDS = ["chatbot", "assistant", "ia", "ai", "intercom", "crisp"]
# Indices techniques plus fiables qu'un simple mot dans le texte visible.  Ces
# fournisseurs laissent normalement une signature dans le HTML même lorsque le
# widget n'est pas encore ouvert.
AI_VENDOR_PATTERNS = {
    "Intercom": r"intercom|widget\.intercom|intercomcdn",
    "Crisp": r"crisp\.chat|\$crisp|client\.crisp",
    "Tidio": r"tidio\.co|tidiochat",
    "HubSpot chat": r"hubspot.*chat|hs-scripts\.com.*conversations",
    "Drift": r"drift\.com|js\.driftt",
    "Zendesk": r"zendesk.*web_widget|static\.zdassets",
    "LiveChat": r"livechatinc\.com|__lc",
    "Botpress": r"botpress",
    "Tawk.to": r"tawk\.to|tawkto",
    "JivoChat": r"jivosite|jivochat",
    "ManyChat": r"manychat",
    "Chatwoot": r"chatwoot",
    "Tiledesk": r"tiledesk",
    "LiveAgent": r"liveagent|ladesk\.com",
    "Zopim": r"zopim",
    "Freshchat": r"freshchat|freshworks\.com/widgets",
    "Gorgias": r"gorgias\.chat",
    "Olark": r"olark",
    "Userlike": r"userlike",
    "HelpCrunch": r"helpcrunch",
    "Landbot": r"landbot",
    "ChatBot.com": r"chatbot\.com|chatbotcdn",
    "Acobot": r"acobot|acobot\.ai",
    "MobileMonkey": r"mobilemonkey",
    "Smooch": r"smooch|sunshineconversations",
}
# « IA » / « AI » sont des acronymes : correspondance EXACTE (majuscules) pour éviter
# les faux positifs du français (« j'ai », « plaine », …). Les autres mots-clés sont
# insensibles à la casse (chatbot, assistant, Intercom, Crisp…).
AI_ACRONYMS = ("ia", "ai")
AI_PATTERNS = {k: re.compile(re.escape(k), re.I) for k in AI_AUDIT_KEYWORDS
               if k not in AI_ACRONYMS}
AI_TARGET_YES = "🎯 Oui"

# --- Pays francophones (sélecteur v6) ---
_ACCENTS = str.maketrans(
    "àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ",
    "aaaeeeeiioouuucAAAEEEEIIOOUUUC")


def _norm_key(s) -> str:
    """Normalise une chaîne : minuscules, sans accents — pour comparer des pays/libellés."""
    return str(s or "").translate(_ACCENTS).strip().lower()


FRANCO_COUNTRIES = {
    "France": {"country": "France", "region": "fr-fr", "africa": False,
               "tone": "ton formel, sobre et professionnel — vouvoiement",
               "cities": ["Paris", "Lyon", "Marseille", "Bordeaux", "Lille",
                           "Toulouse", "Nantes", "Nice"]},
    "Belgique": {"country": "Belgique", "region": "fr-be", "africa": False,
                  "tone": "ton formel et courtois — vouvoiement",
                  "cities": ["Bruxelles", "Liège", "Namur", "Charleroi", "Gand", "Anvers"]},
    "Suisse": {"country": "Suisse", "region": "fr-ch", "africa": False,
                "tone": "ton formel et précis — vouvoiement",
                "cities": ["Genève", "Lausanne", "Fribourg", "Neuchâtel", "Sion", "Montreux"]},
    "Luxembourg": {"country": "Luxembourg", "region": "fr-fr", "africa": False,
                    "tone": "ton formel et professionnel — vouvoiement",
                    "cities": ["Luxembourg", "Esch-sur-Alzette", "Differdange", "Dudelange"]},
    "Canada (Québec)": {"country": "Québec", "region": "ca-fr", "africa": False,
                         "tone": "ton professionnel et direct, un peu plus chaleureux — vouvoiement",
                         "cities": ["Montréal", "Québec", "Laval", "Gatineau",
                                     "Sherbrooke", "Trois-Rivières"]},
    "Togo": {"country": "Togo", "region": "wt-wt", "africa": True,
              "tone": "ton chaleureux et convivial, mais professionnel — vouvoiement respectueux",
              "cities": ["Lomé", "Kara", "Sokodé", "Kpalimé", "Atakpamé"]},
    "Côte d'Ivoire": {"country": "Côte d'Ivoire", "region": "wt-wt", "africa": True,
                       "tone": "ton chaleureux et convivial, mais professionnel — vouvoiement respectueux",
                       "cities": ["Abidjan", "Bouaké", "Yamoussoukro", "San-Pédro", "Korhogo"]},
    "Sénégal": {"country": "Sénégal", "region": "wt-wt", "africa": True,
                 "tone": "ton chaleureux et respectueux, mais professionnel — vouvoiement",
                 "cities": ["Dakar", "Thiès", "Saint-Louis", "Touba", "Ziguinchor"]},
    "Bénin": {"country": "Bénin", "region": "wt-wt", "africa": True,
               "tone": "ton chaleureux et convivial, mais professionnel — vouvoiement respectueux",
               "cities": ["Cotonou", "Porto-Novo", "Parakou", "Abomey-Calavi", "Bohicon"]},
    "Maroc": {"country": "Maroc", "region": "wt-wt", "africa": True,
               "tone": "ton courtois et professionnel, légèrement chaleureux — vouvoiement",
               "cities": ["Casablanca", "Rabat", "Marrakech", "Fès", "Tanger", "Agadir"]},
}
FRANCO_LABELS = list(FRANCO_COUNTRIES) + ["✍️ Autre / libre"]
AFRICAN_COUNTRY_TERMS = {info["country"] for info in FRANCO_COUNTRIES.values()
                         if info["africa"]}
_AFRICAN_NORM = {_norm_key(c) for c in AFRICAN_COUNTRY_TERMS}

REGIONS = ["fr-fr", "fr-be", "fr-ch", "ca-fr", "en-gb", "de-de", "wt-wt", "us-en"]

# Réponses manuelles possibles (colonne « Réponse détectée » du Dashboard)
RESPONSE_OPTS = ["", "✅ Répondu", "📅 Rendez-vous", "❌ Pas intéressé", "📞 À rappeler"]

# --- Détection des numéros MOBILES par pays (liens wa.me) ---
MOBILE_PREFIXES = {
    "33": ("6", "7"),          # France
    "32": ("4",),              # Belgique
    "41": ("7",),              # Suisse
    "352": ("6",),             # Luxembourg
    "1": ("3", "4", "5", "6", "7", "8", "9"),  # Canada / Québec
    "228": ("9",),             # Togo (mobiles en 9x)
    "229": ("4", "6", "9"),   # Bénin
    "225": ("0", "5", "7", "8"),  # Côte d'Ivoire
    "221": ("7",),             # Sénégal
    "212": ("6", "7"),         # Maroc
}


def load_settings() -> dict:
    """Charge settings.json (persistance ZÉRO perte) — dict vide si absent/corrompu."""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _settings_snapshot() -> dict:
    """Instantané des champs à persister (None → ""). Les dates sont converties
    en ISO (JSON ne sait pas sérialiser un objet datetime.date)."""
    out = {}
    for k in SETTINGS_KEYS:
        v = st.session_state.get(k)
        if v is None:
            out[k] = ""
        elif isinstance(v, datetime):
            out[k] = v.date().isoformat()
        elif hasattr(v, "isoformat"):  # datetime.date (date_input)
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def persist_settings() -> None:
    """Sauvegarde instantanée : écrit settings.json dès qu'un champ change."""
    snap = _settings_snapshot()
    if snap == st.session_state.get("_settings_hash"):
        return  # rien n'a changé → aucune écriture disque
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        st.session_state["_settings_hash"] = snap
    except Exception:  # noqa: BLE001
        pass


def tone_for_country(country: str) -> str:
    """Ton IA cible selon le pays (formel en France, plus chaleureux au Togo…)."""
    c = _norm_key(country)
    for label, info in FRANCO_COUNTRIES.items():
        if c and (c == _norm_key(info["country"]) or c == _norm_key(label)
                  or _norm_key(label).startswith(c) or c.startswith(_norm_key(label))):
            return info["tone"]
    return "ton professionnel et courtois — vouvoiement"


def is_mobile_phone(phone) -> bool:
    """True si le numéro correspond à un indicatif MOBILE (France +33 6/7, Togo +228 9x,
    Sénégal +221 7x, Maroc +212 6/7, Québec +1, etc.) — sinon False (fixe/inconnu)."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return False
    for cc, prefixes in MOBILE_PREFIXES.items():
        if digits.startswith(cc):
            rest = digits[len(cc):]
            return bool(rest and rest[0] in prefixes)
    return False


# --- Audit IA des sites (module AI Agency — balayage HTML BeautifulSoup) ---

def analyze_ai_html(html: str) -> dict:
    """Analyse le HTML d'un site : absence des mots-clés IA (chatbot, assistant, IA, AI,
    Intercom, Crisp) + présence d'un <form> ou du mot « Contact » → Cible Prioritaire IA.
    Extrait aussi le titre, la meta description et le texte visible — utilisés ensuite
    par Gemini pour un audit argumenté sur le contenu RÉEL du site."""
    base = {"missing": [], "has_form": False, "has_contact": False, "target": False,
            "signals": [], "title": "", "meta": "", "text": "", "detail": ""}
    if not html:
        return {**base, "missing": list(AI_AUDIT_KEYWORDS),
                "detail": "Site inaccessible ou page vide."}
    if not _BS4_AVAILABLE:
        return {**base, "missing": list(AI_AUDIT_KEYWORDS),
                "detail": "BeautifulSoup absent — installez `beautifulsoup4`."}
    soup = BeautifulSoup(html, "html.parser")
    html_low = html.lower()
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:200]
    meta = ""
    mt = soup.find("meta", attrs={"name": "description"})
    if mt and mt.get("content"):
        meta = str(mt["content"]).strip()[:300]
    for t in soup(["script", "style"]):
        t.decompose()
    text_raw = soup.get_text(" ", strip=True) or ""
    text_low = text_raw.lower()
    missing = []
    for k in AI_AUDIT_KEYWORDS:
        if k in AI_ACRONYMS:
            # Acronyme : correspondance EXACTE « IA » / « AI » (pas « j'ai »)
            hit = bool(re.search(rf"\b{re.escape(k.upper())}\b", text_raw))
        else:
            hit = bool(AI_PATTERNS[k].search(text_low))
        if not hit:
            missing.append(k)
    has_form = bool(soup.find("form"))
    has_contact = bool(re.search(r"contact", text_low))
    signals = [label for label, pattern in AI_VENDOR_PATTERNS.items()
               if re.search(pattern, html_low, re.I)]
    # Le ciblage ne doit pas dépendre de l'absence d'UN SEUL mot-clé : c'était
    # la source principale de faux positifs. Un site est prioritaire seulement
    # s'il propose un moyen de contact et qu'aucun assistant/chat identifiable
    # (visible ou technique) n'est trouvé.
    has_ai = bool(signals) or not missing
    target = bool(not has_ai and (has_form or has_contact))
    parts = []
    if signals:
        parts.append("assistant/chat détecté : " + ", ".join(signals))
    elif has_ai:
        parts.append("indice IA/chatbot visible sur le site")
    else:
        parts.append("aucun assistant ou chatbot identifiable dans la page analysée")
    parts.append("formulaire de contact présent" if has_form else "pas de formulaire")
    parts.append("mot « Contact » présent" if has_contact else "mot « Contact » absent")
    detail = " — ".join(parts) + (" → 🎯 Cible Prioritaire IA." if target else "")
    text = re.sub(r"\s+", " ", text_raw).strip()[:600]
    return {"missing": missing, "has_form": has_form, "has_contact": has_contact,
            "signals": signals, "target": target, "detail": detail,
            "title": title, "meta": meta, "text": text}


def audit_ai_website(url: str) -> dict:
    """Vérifie le site (requests + BeautifulSoup) et applique les critères « Cible Prioritaire IA ».
    Retourne aussi titre / meta / texte visible pour alimenter l'audit Gemini."""
    base = {"missing": [], "has_form": False, "has_contact": False, "target": False,
            "signals": [], "title": "", "meta": "", "text": "", "detail": ""}
    if not url or not has_website(url):
        return {**base, "detail": "Pas de site web professionnel (annuaire / réseau social) — "
                                  "hors périmètre IA."}
    try:
        r = requests.get(normalize_url(url), timeout=12, headers={"User-Agent": UA},
                         allow_redirects=True)
        if r.status_code != 200:
            return {**base, "detail": f"Site inaccessible (HTTP {r.status_code})."}
        res = analyze_ai_html(r.text)
        # Rapport enrichi : titre + description + conclusion — utilisable tel quel
        # par Gemini comme « faille détectée » dans l'argumentaire de vente.
        parts = []
        if res.get("title"):
            parts.append(f"Titre : {res['title']}")
        parts.append(res.get("detail", ""))
        if res.get("meta"):
            parts.append(f"Description : {res['meta']}")
        res["detail"] = " — ".join(p for p in parts if p)
        return res
    except Exception as exc:  # noqa: BLE001
        return {**base, "detail": f"Erreur lors du scan de {str(url)[:60]} : {exc}"}


def audit_ai_batch(df: pd.DataFrame, progress_cb=None, max_workers: int = 8) -> pd.DataFrame:
    """Audit IA parallèle (ThreadPoolExecutor — l'UI reste fluide, RAM ~40 Mo/worker).
    Remplit les colonnes ai_target / ai_audit en conservant l'index d'origine."""
    df = df.copy()
    if df.empty:
        return df
    for col in ("ai_target", "ai_audit"):
        if col not in df.columns:
            df[col] = ""
    urls = [str(r.get("website", "") or "") for _, r in df.iterrows()]
    results: list[dict] = [None] * len(df)  # type: ignore[list-item]
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(audit_ai_website, u): i for i, u in enumerate(urls)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception:  # noqa: BLE001
                results[i] = {"missing": [], "has_form": False, "has_contact": False,
                              "signals": [], "target": False, "title": "", "meta": "",
                              "text": "", "detail": "Erreur de scan."}
            done += 1
            if progress_cb:
                progress_cb(done / len(df))
    for i, res in enumerate(results):
        df.loc[df.index[i], "ai_target"] = AI_TARGET_YES if res["target"] else ""
        df.loc[df.index[i], "ai_audit"] = res.get("detail", "")
    return df


# --- LinkedIn Sniper (Google Dorking via DuckDuckGo — gratuit) ---

def search_linkedin_profiles(niche: str, city: str, country: str, region: str = "wt-wt",
                             max_results: int = 10) -> list[dict]:
    """Profils de décideurs via site:linkedin.com/in/ + niche + ville.
    Retourne une liste de dicts {name, url, title}."""
    if not _DDGS_AVAILABLE:
        raise RuntimeError("Librairie de recherche absente — installez `ddgs` (pip install ddgs).")
    parts = [p for p in ("site:linkedin.com/in/", niche, city, country) if str(p).strip()]
    query = " ".join(parts)
    try:
        results = DDGS().text(query, region=region or "wt-wt", max_results=int(max_results))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Recherche LinkedIn impossible : {exc}") from exc
    rows: list[dict] = []
    seen: set[str] = set()
    for r in results or []:
        url = normalize_url(r.get("href") or "")
        if "linkedin.com/in/" not in url.lower():
            continue
        if url in seen:
            continue
        seen.add(url)
        title = re.sub(r"\s*[|•·–—-]\s*LinkedIn.*$", "", r.get("title") or "", flags=re.I)
        rows.append({"name": clean_name(title) or "Profil LinkedIn",
                     "url": url, "title": (r.get("title") or "")[:140]})
    return rows


# --- Personnalisation IA par pays (Gemini Flash — 100 % du message rédigé par l'IA) ---

def _parse_gen_email(raw: str) -> tuple[str, str]:
    """Extrait objet + corps d'une sortie « OBJET: … / CORPS: … » (repli robuste).
    Accepte les variantes markdown (**OBJET:**), « Sujet: » / « Subject: » et
    « Corps: » / « Body: » selon la langue du modèle."""
    raw = (raw or "").strip()
    # Découpe proprement les marqueurs markdown gras (**…) — les étoiles peuvent
    # apparaître AVANT OU APRÈS le deux-points : « **OBJET:** » comme « OBJET : ».
    _star = r"\*{0,2}\s*"
    _lab = _star + r"(?:OBJET|SUJET|SUBJECT|OBJECT)" + _star
    m_subj = re.search(_lab + r"[:：]" + _star + r"([^\n]+)", raw, re.I)
    _lab2 = _star + r"(?:CORPS|BODY|MESSAGE)" + _star
    m_body = re.search(_lab2 + r"[:：]" + _star + r"(.+)", raw, re.I | re.S)
    if m_subj and m_body:
        return m_subj.group(1).strip(), m_body.group(1).strip()
    if m_subj:
        return m_subj.group(1).strip(), raw
    if m_body:
        return raw[:80].strip(), m_body.group(1).strip()
    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) > 1:
        return lines[0][:120], "\n".join(lines[1:]).strip()
    return "", raw


def personalize_email(mode: str, agency: str, city: str, country: str, lang: str, lead,
                      audit: str = "", faille: str = "", api_key: str = "",
                      model: str = GEMINI_MODELS[0], temperature: float = 0.7) -> tuple[str, str]:
    """Gemini rédige 100 % de l'email (objet + corps) : niche, faille détectée, pays cible
    (formel en France, plus chaleureux au Togo…). Placeholders {…} conservés."""
    en = lang != "fr"
    tone = tone_for_country(country)
    lead_name = str(lead.get("name", "") or "…")
    snippet = str(lead.get("snippet", "") or "").strip()
    employees = str(lead.get("employees", "") or "").strip()
    site = str(lead.get("website", "") or "").strip()
    # Angle réel : audit IA du site (MODE_AI) ou contenu récupéré du site
    angle = faille or audit or "diagnostic standard du secteur"
    if snippet and len(snippet) > 30:
        angle += f" | Contenu réel du site : {snippet[:500]}"
    if employees:
        angle += f" | Effectif : {employees} employés"
    prompt = (
        "Tu es un copywriter senior B2B. Rédige UN email de prospection COMPLET — l'objet ET le "
        "corps — 100 % personnalisé pour ce prospect et adapté au pays cible.\n"
        f"· Service : {MODE_INFO[mode]['desc']}\n"
        f"· Prospect : « {lead_name} » ({city} {country})\n"
        f"· Site : {site or 'non communiqué'}\n"
        f"· Angle / constat réel : {angle}\n"
        f"· Ton cible ({country}) : {tone}.\n"
        f"· Langue : {'Anglais' if en else 'Français'}.\n"
        "Contraintes impératives :\n"
        "- N'invente AUCUN chiffre, prix, statistique ou témoignage précis ; appuie-toi "
        "sur le constat réel fourni (contenu du site, audit).\n"
        "- Email sobre, percutant, ~150-180 mots maximum, avec un CTA clair.\n"
        "- Utilise les placeholders {LeadName}, {Location}, {AgencyName}, {Audit} si besoin — "
        "ils seront remplacés automatiquement ; n'écris PAS le nom réel dans le corps.\n"
        "- Signe avec l'agence via le placeholder {AgencyName}.\n"
        "- Format STRICT, exactement :\n"
        "OBJET: <objet en une ligne>\n"
        "CORPS:\n<corps complet>\n"
    )
    raw = gemini_generate(api_key, model, prompt, temperature=temperature, max_tokens=900)
    subject, body = _parse_gen_email(raw)
    if not subject:
        subject = f"{lead_name} — {mode}"[:140]
    return subject, body


def personalize_wa(mode: str, agency: str, city: str, country: str, lang: str, lead,
                   faille: str = "", api_key: str = "",
                   model: str = GEMINI_MODELS[0], temperature: float = 0.7) -> str:
    """Gemini rédige le message WhatsApp (max ~250 caractères) adapté au pays et à la faille."""
    en = lang != "fr"
    tone = tone_for_country(country)
    lead_name = str(lead.get("name", "") or "…")
    snippet = str(lead.get("snippet", "") or "").strip()
    angle = faille or "diagnostic standard du secteur"
    if snippet and len(snippet) > 30:
        angle += f" | Contenu réel du site : {snippet[:300]}"
    prompt = (
        "Tu es un commercial senior expert en prospection WhatsApp. Rédige UN message WhatsApp "
        "de prospection B2B (max 250 caractères, pas d'émoticône excessive).\n"
        f"· Service : {MODE_INFO[mode]['desc']}\n"
        f"· Prospect : « {lead_name} » ({city} {country})\n"
        f"· Angle / constat réel : {angle}\n"
        f"· Ton cible ({country}) : {tone}.\n"
        f"· Langue : {'Anglais' if en else 'Français'}.\n"
        "· Utilise les placeholders {LeadName}, {Location}, {AgencyName} — remplacés "
        "automatiquement.\n"
        "· Termine par une question simple (CTA) ; n'invente AUCUN chiffre.\n"
    )
    raw = gemini_generate(api_key, model, prompt, temperature=temperature, max_tokens=400)
    return (raw or "").strip()


# --- Suivi des campagnes lancées (Dashboard « Campagnes en cours ») ---

def _campaign_append(channel: str, total: int) -> dict:
    """Ajoute une campagne lancée dans le registre de session (Dashboard)."""
    camps = st.session_state.setdefault("campaigns", [])
    rec = {
        "id": int(time.time() * 1000) % 10 ** 9,
        "nom": f"Campagne {len(camps) + 1} — {st.session_state.get('mode', '')}",
        "pays": st.session_state.get("country", "") or "—",
        "source": channel,
        "total": int(total),
        "envoyés": 0,
        "statut": "En cours",
        "début": datetime.now().strftime("%d/%m %H:%M"),
    }
    camps.append(rec)
    return rec


def _campaign_update(campaign_id: int, sent: int, statut: str) -> None:
    for rec in st.session_state.get("campaigns", []):
        if rec.get("id") == campaign_id:
            rec["envoyés"] = int(sent)
            rec["statut"] = statut
            return


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
    if mode == MODE_AI:
        return "⚠️ PME sans site (hors périmètre IA)" if is_directory else "Site détecté"
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
                  "🎯 Cible Prioritaire IA", "🏢 ICP 3-20 employés (IA)",
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
    if opt == "🎯 Cible Prioritaire IA":
        if "ai_target" not in df.columns:
            return pd.Series(False, index=df.index)
        return df["ai_target"].astype(str).str.contains("Oui")
    if opt == "🏢 ICP 3-20 employés (IA)":
        if "employees" not in df.columns:
            return pd.Series(False, index=df.index)

        def _icp(v) -> bool:
            m = re.search(r"\d+", str(v))
            return bool(m and 3 <= int(m.group()) <= 20)

        return df["employees"].map(_icp)
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


def fetch_snippet(url: str, max_chars: int = 1400) -> str:
    """Extrait le contenu RÉEL d'un site : titre + meta description + texte visible
    (les 2-3 premiers paragraphes). Alimente l'audit Gemini pour des argumentaires
    basés sur le site, pas sur un texte générique."""
    if not url or not _BS4_AVAILABLE:
        return ""
    try:
        r = requests.get(normalize_url(url), timeout=12, headers={"User-Agent": UA},
                         allow_redirects=True)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
        meta = soup.find("meta", attrs={"name": "description"})
        meta_txt = (str(meta["content"]).strip() if meta and meta.get("content") else "")
        # Paragraphes les plus informatifs (2-3 premiers avec un minimum de contenu)
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")
                 if len(p.get_text(" ", strip=True)) > 40]
        body = "\n".join(paras[:3])[:max_chars]
        parts = [p for p in (title, meta_txt, body) if p]
        if not parts:
            return ""
        # Déduplication simple (titre répété dans le corps…)
        joined = parts[0]
        for p in parts[1:]:
            if p[:60] not in joined:
                joined += "\n" + p
        return joined[:max_chars * 2]
    except Exception:
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
    want_phone = mode in (MODE_WEB, MODE_SEO, MODE_AI)
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
                "linkedin": "",
                "employees": "",
                "ai_target": "",
                "ai_audit": "",
            })
        if progress_cb:
            progress_cb((qi + 1) / len(queries))

    return pd.DataFrame(rows, columns=LEAD_COLS) if rows else empty_leads()


def parse_csv_leads(uploaded) -> pd.DataFrame:
    """Import CSV/XLSX robuste : encodage Excel Windows et séparateur auto."""
    raw = uploaded.getvalue() if hasattr(uploaded, "getvalue") else uploaded.read()
    if not raw:
        raise ValueError("Le fichier est vide.")
    filename = str(getattr(uploaded, "name", "")).lower()
    if filename.endswith((".xlsx", ".xls")):
        try:
            df = pd.read_excel(__import__("io").BytesIO(raw), dtype=str)
        except ImportError as exc:
            raise ValueError("Import Excel indisponible : installez openpyxl.") from exc
    else:
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
            try:
                # sep=None détecte automatiquement ; engine python gère ; et ,.
                df = pd.read_csv(__import__("io").BytesIO(raw), encoding=encoding,
                                 sep=None, engine="python", dtype=str)
                break
            except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                last_error = exc
        else:
            raise ValueError(f"CSV illisible : {last_error}")
    if df.empty:
        raise ValueError("Le fichier ne contient aucune ligne.")
    df = df.where(pd.notna(df), "")
    low = {c: str(c).strip().lower() for c in df.columns}

    # Bornes de mot : lettres accentuées incluses — « hotel » ne doit PAS matcher
    # « tel », « domain » ne doit PAS matcher « in », « job title » reste un repli.
    _WORD = "a-zà-öø-ÿ0-9"

    def pick(names: list[str]) -> str | None:
        # 1) nom de colonne EXACT (priorité absolue)
        for col in df.columns:
            if low[col] in names:
                return col
        # 2) mot entier dans le nom de colonne
        for col in df.columns:
            cname = low[col]
            if any(re.search(rf"(?<![{_WORD}]){re.escape(n)}(?![{_WORD}])", cname)
                   for n in names if len(n) >= 2):
                return col
        # 3) sous-chaîne — uniquement pour des libellés assez précis (>= 4 lettres)
        for col in df.columns:
            cname = low[col]
            if any(n in cname for n in names if len(n) >= 4):
                return col
        return None

    # Nom : on préfère nettement name/nom/entreprise/company — « title » (exports
    # Instant Data Scraper) n'est qu'un repli, jamais au détriment d'un « job title ».
    name_c = pick(["name", "nom", "business", "company", "entreprise", "société",
                   "raison sociale"]) or pick(["title", "titre"])
    first_c = pick(["first name", "prénom"])
    last_c = pick(["last name", "nom de famille"])
    merge_names = bool(first_c and last_c and first_c != last_c)
    if merge_names:
        name_c = None
    url_c = pick(["website", "url", "site", "link", "lien", "href", "web"])
    email_c = pick(["email", "mail", "courriel"])
    phone_c = pick(["phone", "tel", "whatsapp", "mobile", "téléphone"])
    emp_c = pick(["employees", "employee", "effectif", "taille", "employés", "personnel"])
    li_c = pick(["linkedin", "profil"])
    li_c = li_c if li_c and li_c != name_c else None

    name_c = name_c or df.columns[0]
    rows: list[dict] = []
    for _, row in df.iterrows():
        email = _norm(row[email_c]) if email_c else ""
        phone = _norm(row[phone_c]) if phone_c else ""
        website = normalize_url(_norm(row[url_c]) if url_c else "")
        if merge_names:
            name = f"{_norm(row[first_c])} {_norm(row[last_c])}".strip() or "Sans nom"
        else:
            name = _norm(row[name_c]) or "Sans nom"
        rows.append({
            "name": name,
            "website": website,
            "email": email,
            "phone": phone,
            "source": "CSV",
            "flag": "",
            "segment": classify_segment(website),
            "snippet": "",
            "audit": "",
            "status": "",
            "linkedin": normalize_url(_norm(row[li_c])) if li_c else "",
            "employees": _norm(row[emp_c]) if emp_c else "",
            "ai_target": "",
            "ai_audit": "",
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
    """Appel Gemini avec nouvelle tentative automatique sur 429 / 5xx ET bascule
    automatique sur un autre modèle si le modèle demandé est en quota (429) ou
    arrêté (404) — ex. quota quotidien gratuit de gemini-3.6-flash épuisé.

    Backoff exponentiel : ~5s, ~12s, ~27s avant de tenter le modèle suivant.
    Ordre de repli : GEMINI_MODELS (hors modèle demandé)."""
    fallback_models = [m for m in GEMINI_MODELS if m != model]
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
            if not _is_rate_limit(exc) and not _is_not_found(exc):
                raise
            if attempt >= max_retries:
                # Modèle indisponible (quota 429 persistant / 404) : bascule automatique
                # sur un autre modèle de la liste (ex. gemini-3.5-flash).
                for fb in fallback_models:
                    try:
                        if _GENAI_STATE == "new":
                            client = _genai.Client(api_key=api_key)
                            resp = client.models.generate_content(
                                model=fb,
                                contents=prompt,
                                config=_genai_types.GenerateContentConfig(
                                    temperature=temperature, max_output_tokens=max_tokens,
                                ),
                            )
                            text = (resp.text or "").strip()
                        elif _GENAI_STATE == "legacy":
                            _genai_legacy.configure(api_key=api_key)
                            text = _genai_legacy.GenerativeModel(fb).generate_content(prompt).text.strip()
                        else:
                            text = ""
                        if text:
                            try:
                                st.toast(f"🔄 Bascule automatique : génération via {fb} "
                                         f"({model} indisponible/quotas).", icon="🔄")
                            except Exception:  # noqa: BLE001
                                pass
                            return text
                    except Exception as fb_exc:  # noqa: BLE001
                        if _is_not_found(fb_exc) or _is_rate_limit(fb_exc):
                            continue  # ce modèle est aussi indisponible, on essaie le suivant
                        raise
                raise last_exc
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
                 segment: str = SEG_NO_SITE, lang: str = "fr", website: str = "",
                 faille: str = "") -> str:
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
        MODE_AI: L("installation d'un assistant IA (chatbot) sur le site du prospect — réponse "
                   "24h/24, qualification des demandes, prise de rendez-vous automatique",
                   "deploying an AI assistant (chatbot) on the prospect's website — 24/7 "
                   "answers, lead qualification, automatic booking"),
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

    faille_line = (
        L(f"· Faille détectée (scan IA du site) : {faille}.\n",
          f"· Detected weakness (AI website scan): {faille}.\n")
        if faille else ""
    )
    icp_line = (
        L("· ICP : PME de 3 à 20 employés (cible idéale).\n",
          "· ICP: SMEs with 3 to 20 employees (ideal target).\n")
        if mode == MODE_AI else ""
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
        f"{faille_line}{icp_line}"
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
        f"{faille_line}{icp_line}"
        f"Prospect: {angle}\n"
        f"Provided excerpt: « {snippet or 'none'} »\n"
        "Answer in English, premium tone.\n",
    )


# ------------------------------------------------------------------
#  Envoi d'emails : smtplib + Composio
# ------------------------------------------------------------------


def body_to_html(text: str, image_cids: list[str] | None = None,
                 cta: dict | None = None, video: str = "") -> str:
    """Convertit le corps (texte brut) en email HTML professionnel CLAIR.

    Thème clair (fond blanc, texte sombre) : lisible partout — Gmail affiche les
    fonds sombres sur fond blanc en forçant les couleurs, ce qui rend le texte
    illisible. Un email clair est aussi bien mieux noté par les filtres anti-spam
    (pas d'image de fond, ratio texte/image élevé, style « courriel pro »).
    Contenu enrichi optionnel : images (inline cid), bouton CTA doré, vidéo.
    """
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
                       'style="max-width:100%;height:auto;border-radius:8px;'
                       'margin:0 0 18px 0;display:block;"/>'),
            block)
        block = re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            lambda m: (f'<a href="{m.group(2)}" '
                       'style="color:#8a6d1f;text-decoration:underline;'
                       f'font-family:Helvetica,Arial,sans-serif;">{m.group(1)}</a>'),
            block)
        return block

    paras = []
    for block in re.split(r"\n\s*\n", text or ""):
        if block.strip():
            paras.append(
                f'<p style="margin:0 0 16px 0;line-height:1.7;color:#222222;">{_richify(block)}</p>')
    body = "\n".join(paras) or "<p></p>"

    rich: list[str] = []
    for cid in image_cids or []:
        rich.append(
            f'<img src="cid:{cid}" alt="" style="max-width:100%;height:auto;'
            'border-radius:8px;margin:0 0 18px 0;display:block;"/>')
    if cta and cta.get("url"):
        rich.append(
            f'<a href="{_html.escape(str(cta["url"]))}" style="display:inline-block;'
            'background:#c9a45c;color:#ffffff;text-decoration:none;padding:12px 26px;'
            'border-radius:6px;font-weight:700;font-family:Helvetica,Arial,sans-serif;'
            'margin:6px 0 20px 0;">'
            f'{_html.escape(str(cta.get("label") or "En savoir plus"))}</a>')
    if video and str(video).strip():
        rich.append(
            f'<a href="{_html.escape(str(video))}" style="display:inline-block;'
            'border:1px solid #c9a45c;color:#8a6d1f;text-decoration:none;'
            'padding:12px 26px;border-radius:6px;font-weight:700;'
            'font-family:Helvetica,Arial,sans-serif;margin:0 0 20px 0;">'
            '▶️ Regarder la vidéo</a>')
    rich_html = "\n".join(rich)

    return (
        "<div style=\"background:#f4f4f2;padding:32px 12px;font-family:Helvetica,Arial,sans-serif;\">"
        "<div style=\"max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e0e0dc;"
        "border-radius:10px;padding:36px;\">"
        "<div style=\"color:#8a6d1f;font-size:12px;letter-spacing:2px;text-transform:uppercase;"
        "margin-bottom:18px;border-bottom:1px solid #eaeae6;padding-bottom:14px;\">"
        "Scriba Omniscient · Prospection</div>"
        f"{rich_html}{body}"
        "<div style=\"margin-top:24px;padding-top:14px;border-top:1px solid #eaeae6;"
        "color:#888888;font-size:12px;font-family:Helvetica,Arial,sans-serif;\">"
        "Message professionnel envoyé dans le cadre d'une prospection B2B. Si vous n'êtes pas le "
        "bon interlocuteur, répondez « STOP » pour ne plus être recontacté.</div>"
        "</div></div>"
    )


def send_via_smtp(sender: str, password: str, to: str, subject: str, body: str,
                  html_body: str | None = None,
                  images: list[dict] | None = None,
                  sender_name: str = "") -> str:
    """Envoie un email Gmail via smtplib (ENVOI RÉEL — pas de simulation).

    `images` = liste de dicts {maintype, subtype, data} attachées en inline
    (cid: img_0, img_1, …).
    `sender_name` = nom d'affichage (ex. nom de l'agence) — Gmail l'affiche dans
    la boîte de réception, ce qui rassure le prospect et améliore le taux d'ouverture.

    Structure MIME : multipart/alternative -> [texte brut, multipart/related ->
    [HTML + images inline]].  (L'ancienne implémentation utilisait
    `add_related` APRÈS `add_alternative`, ce qui levait
    `ValueError: Cannot convert alternative to related` dès qu'une image était
    jointe — le mail n'était jamais envoyé.)

    Anti-spam : en-têtes propres (From avec nom d'affichage, Reply-To explicite,
    List-Unsubscribe déclaré) + texte brut + HTML clair. Gmail signe SPF/DKIM
    automatiquement pour les envois via smtp.gmail.com.
    """
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    display = (str(sender_name or "").strip() or sender)
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{display} <{sender}>"
    msg["To"] = to
    msg["Reply-To"] = sender
    msg["Subject"] = subject
    msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(body or "", "plain", "utf-8"))
    if images:
        # partie « related » : HTML + images inline (cid: img_0, img_1, …)
        related = MIMEMultipart("related")
        related.attach(MIMEText(html_body or body_to_html(body or ""), "html", "utf-8"))
        for i, img in enumerate(images):
            subtype = str(img.get("subtype") or "png").lower()
            part = MIMEImage(img["data"], _subtype=subtype)
            part.add_header("Content-ID", f"<img_{i}>")
            part.add_header("Content-Disposition", "inline", filename=f"img_{i}.{subtype}")
            related.attach(part)
        msg.attach(related)
    elif html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
        server.login(sender, password)
        server.send_message(msg)
    return "ok"


SMTP_HINT = ("💡 Identifiants Gmail refusés (535). Utilisez un MOT DE PASSE D'APPLICATION "
             "(jamais votre mot de passe normal) — https://myaccount.google.com/apppasswords. "
             "Vérifiez : validation en 2 étapes activée, code collé SANS espaces, bonne adresse. "
             "Alternative : canal « composio (Gmail OAuth) » dans l'onglet Outreach.")

# --- Multi-comptes Gmail : roulement automatique des expéditeurs + réchauffement ---

# Réchauffement progressif : limite quotidienne par semaine (10 -> 30 -> 60 -> 100 -> …)
WARMUP_SCHEDULE = [10, 30, 60, 100, 150, 200]


def parse_gmail_accounts() -> list[tuple[str, str]]:
    """Liste des comptes Gmail configurés : [ (email, motdepasse), … ]
    = compte principal (gmail_user/gmail_pass) + comptes additionnels
    (champ `gmail_accounts`, un « email:motdepasse » par ligne)."""
    accounts: list[tuple[str, str]] = []
    gu = _norm(st.session_state.get("gmail_user", ""))
    gp = st.session_state.get("gmail_pass", "") or ""
    if gu and gp:
        accounts.append((gu, gp))
    for line in str(st.session_state.get("gmail_accounts", "") or "").splitlines():
        line = line.strip()
        if ":" in line:
            email, pwd = line.split(":", 1)
            email, pwd = email.strip(), pwd.strip()
            if email and pwd and (email, pwd) not in accounts:
                accounts.append((email, pwd))
    return accounts


@st.cache_data(ttl=120, show_spinner=False)
def _accounts_status_cached(accounts_tuple: tuple) -> str:
    """Statut du nombre de comptes configurés (en cache 2 min)."""
    n = len(accounts_tuple)
    if n == 0:
        return "Aucun compte Gmail configuré."
    return f"{n} compte(s) Gmail prêt(s) — envois répartis automatiquement."


_DAILY_LOCK = threading.Lock()


def daily_send_limit() -> int:
    """Limite quotidienne : plan de réchauffement (progressif) ou limite fixe, 0 = illimité."""
    if not st.session_state.get("warmup_enabled"):
        try:
            return max(0, int(st.session_state.get("daily_limit", 0) or 0))
        except (TypeError, ValueError):
            return 0
    start = st.session_state.get("warmup_start", "") or ""
    d0 = None
    try:
        d0 = datetime.strptime(str(start), "%Y-%m-%d").date() if start else None
    except ValueError:
        d0 = None
    if not d0:
        return WARMUP_SCHEDULE[0]
    weeks = max(0, (datetime.now().date() - d0).days // 7)
    if weeks >= len(WARMUP_SCHEDULE):
        try:
            return max(0, int(st.session_state.get("daily_limit", 200) or 200))
        except (TypeError, ValueError):
            return 200
    return WARMUP_SCHEDULE[weeks]


def daily_sent_count() -> int:
    """Emails déjà envoyés aujourd'hui (compteur persistant de session)."""
    key = str(datetime.now().date())
    return int(st.session_state.get("_daily_sent", {}).get(key, 0))


def daily_remaining() -> int:
    """Emails restants autorisés aujourd'hui (999 999 si illimité)."""
    limit = daily_send_limit()
    if limit <= 0:
        return 999_999
    return max(0, limit - daily_sent_count())


def _account_send_fn(agency: str):
    """Ferme un expéditeur qui TOURNE sur tous les comptes Gmail configurés
    (round-robin) et comptabilise les envois dans le quota quotidien.
    Chaque email part de l'un des comptes — la réputation est répartie."""
    accounts = parse_gmail_accounts()
    if not accounts:
        raise RuntimeError("Aucun compte Gmail configuré (sidebar).")
    idx = [0]

    def send_fn(item):
        sender, password = accounts[idx[0] % len(accounts)]
        idx[0] += 1
        res = send_via_smtp(sender, password, item["email"], item["subject"],
                            item["body"], html_body=item.get("html"),
                            images=item.get("images"), sender_name=agency)
        with _DAILY_LOCK:
            _ds = st.session_state.setdefault("_daily_sent", {})
            key = str(datetime.now().date())
            _ds[key] = int(_ds.get(key, 0)) + 1
        return res

    return send_fn


def _outreach_queue_cap(queue: list) -> tuple[list, str]:
    """Réduit la file d'envoi au quota quotidien restant. Retourne (queue, message)."""
    remaining = daily_remaining()
    if remaining >= len(queue):
        return queue, ""
    note = (f"⚠️ Quota quotidien atteint ({daily_send_limit()} emails/jour) : seuls "
            f"les {remaining} premiers emails seront envoyés aujourd'hui. Relancez "
            "demain pour continuer (réchauffement progressif).")
    return queue[:remaining], note

# Mots déclencheurs de spam à éviter dans l'objet / le corps (FR + EN).
# Un email de prospection sobre et personnel passe mieux les filtres Gmail.
SPAM_TRIGGERS = [
    "gratuit", "free", "offre exceptionnelle", "offre limitée", "dernière chance",
    "urgent", "action urgente", "100%", "100 %", "gagné", "win", "$$$", "prix cassé",
    "promotion", "cliquez ici", "click here", "en ligne maintenant", "viagra",
    "cash", "money", "million", "gagner de l'argent", "make money", "deal incroyable",
    "sans risque", "risk free", "test gratuit", "essai gratuit", "répondez vite",
    "act now", "bonus", "réduction massive", "prix imbattable", "meilleure offre",
    "cliquez maintenant", "actuellement en promotion", "-%", "-%", "offre spéciale",
]


def spam_risk_warning(subject: str, body: str = "") -> list[str]:
    """Liste les mots déclencheurs de spam trouvés dans l'objet/corps (vide si propre)."""
    hay = f"{subject or ''} {body or ''}".lower()
    found = []
    for w in SPAM_TRIGGERS:
        if w.lower() in hay:
            found.append(w)
    return found


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


def payment_block(mode: str, iban: str, africa_payment: str, country: str = "") -> str:
    is_africa = bool(country) and _norm_key(country) in _AFRICAN_NORM
    if mode == MODE_COPY and not is_africa:
        if iban.strip():
            return (f"Paiement sécurisé par virement SEPA — IBAN (Grey.co) : {iban.strip()}. "
                    "Facture professionnelle fournie.")
        return ("Paiement sécurisé par virement SEPA via Grey.co (IBAN communiqué sur demande). "
                "Facture professionnelle fournie.")
    if is_africa or mode in (MODE_WEB, MODE_SEO):
        return (f"Paiement flexible en 2 tranches : {africa_payment.strip() or DEFAULT_AFRICA_PAYMENT}. "
                "Réduction si paiement comptant.")
    if iban.strip():
        return (f"Paiement sécurisé par virement SEPA — IBAN (Grey.co) : {iban.strip()}. "
                "Facture professionnelle fournie.")
    return ("Paiement sécurisé par virement SEPA via Grey.co (IBAN communiqué sur demande). "
            "Facture professionnelle fournie.")


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


def _normalize_leads_index() -> None:
    """Garantit un index UNIQUE (RangeIndex) sur `leads` / `leads_edit`.

    L'éditeur de données dynamique (num_rows="dynamic") peut produire des index
    dupliqués ou None quand des lignes sont ajoutées : deux leads partagent alors
    le même index, ce qui casse les clés de widgets basées sur l'index
    (ex. StreamlitDuplicateElementKey 'snippet_20' dans l'onglet Audit).
    La sélection ✓ est repositionnelle et préservée.
    """
    leads = st.session_state.get("leads")
    if leads is None or leads.empty:
        return
    if leads.index.is_unique and not any(v is None for v in leads.index):
        return  # déjà propre
    sel = None
    edit = st.session_state.get("leads_edit")
    if edit is not None and not edit.empty and SEL_COL in edit.columns \
            and len(edit) == len(leads):
        sel = edit[SEL_COL].fillna(False).astype(bool).tolist()
    st.session_state["leads"] = leads.reset_index(drop=True)
    new_edit = st.session_state["leads"].copy()
    new_edit[SEL_COL] = sel if sel is not None else False
    st.session_state["leads_edit"] = new_edit
    st.session_state["edit_version"] = -1  # force le data_editor à repartir des données
    st.session_state["leads_version"] = st.session_state.get("leads_version", 0) + 1


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
    st.session_state.setdefault("campaigns", [])
    st.session_state.setdefault("responses", {})
    st.session_state.setdefault("tracked_clicks", 0)
    st.session_state.setdefault("ln_niche", "")
    st.session_state.setdefault("ln_city", "")
    st.session_state.setdefault("lang_en", False)
    st.session_state.setdefault("africa_payment", DEFAULT_AFRICA_PAYMENT)

    # --- v6 : chargement automatique des champs depuis settings.json (ZÉRO perte) ---
    loaded = load_settings()
    for k, v in loaded.items():
        if v is None or k not in SETTINGS_KEYS:
            continue
        st.session_state.setdefault(k, v)
    # warmup_start est stocké en ISO (str) dans settings.json → reconverti en date
    _ws = st.session_state.get("warmup_start")
    if isinstance(_ws, str) and _ws:
        try:
            st.session_state["warmup_start"] = datetime.strptime(_ws, "%Y-%m-%d").date()
        except ValueError:
            st.session_state["warmup_start"] = datetime.now().date()
    if "_daily_sent" not in st.session_state:
        st.session_state["_daily_sent"] = {}
    if "fr_country" not in loaded:
        saved_country = _norm_key(loaded.get("country", ""))
        if saved_country:
            match = next((lab for lab, info in FRANCO_COUNTRIES.items()
                          if _norm_key(info["country"]) == saved_country), None)
            st.session_state.setdefault("fr_country", match or "✍️ Autre / libre")
        else:
            st.session_state.setdefault("fr_country", "France")
    st.session_state.setdefault("_fr_prev", st.session_state.get("fr_country"))

    # Réparation des données héritées d'une session plus ancienne : colonnes manquantes
    # (segment v1 → linkedin/employees/ai_target/ai_audit v6)
    for dfk in ("leads", "leads_edit"):
        df = st.session_state.get(dfk)
        if df is None:
            continue
        if "segment" not in df.columns:
            df["segment"] = df["website"].map(classify_segment).fillna(SEG_NO_SITE)
        for col in ("linkedin", "employees", "ai_target", "ai_audit"):
            if col not in df.columns:
                df[col] = ""


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
        logo_up = st.file_uploader("Logo (optionnel)", type=["png", "jpg", "jpeg", "webp"],
                                   key="logo_up", help="Enregistré en permanence (logo.png) et "
                                   "affiché dans la barre latérale.")
        if logo_up is not None:
            try:
                _logo_path = Path(__file__).resolve().parent / "logo.png"
                _data = logo_up.getvalue()
                if not _logo_path.exists() or _logo_path.read_bytes() != _data:
                    _logo_path.write_bytes(_data)
                    st.toast("Logo enregistré ✓", icon="🖼️")
            except Exception:  # noqa: BLE001
                pass
        if Path(__file__).resolve().parent.joinpath("logo.png").exists():
            st.image(str(Path(__file__).resolve().parent / "logo.png"), width=130)
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
            st.divider()
            st.caption("**🚀 Comptes Gmail supplémentaires (roulement)** — un « email:motdepasse "
                       "d'application » par ligne. Les envois sont répartis automatiquement "
                       "entre tous les comptes (réputation + volume multipliés).")
            st.text_area("Comptes additionnels (email:motdepasse par ligne)",
                         key="gmail_accounts", height=90,
                         placeholder="agence1@gmail.com:abcd efgh ijkl mnop\nagence2@gmail.com:wxyz …")
            _accs = parse_gmail_accounts()
            if _accs:
                st.success(_accounts_status_cached(tuple(_accs)))
            else:
                st.warning("Aucun compte Gmail configuré — les envois email sont désactivés.")
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
            st.selectbox("Modèle OpenAI", OPENAI_MODELS, key="openai_model")

        st.markdown("### 🎯 Mode")
        st.selectbox("Modèle d'affaires", MODES, key="mode",
                     format_func=lambda m: MODE_INFO[m]["label"])
        st.caption(MODE_INFO[st.session_state["mode"]]["desc"])

        st.markdown("### 🌐 Langue de génération")
        st.toggle(
            "FRANÇAIS / ENGLISH",
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
        st.selectbox("Pays (zone francophone)", FRANCO_LABELS, key="fr_country",
                     help="Sélectionnez un pays francophone : le pays, la région DuckDuckGo et le "
                          "ton des messages IA s'adaptent automatiquement. « ✍️ Autre / libre » "
                          "laisse le champ Pays totalement libre.")
        _frc = st.session_state.get("fr_country", "")
        if _frc and _frc != "✍️ Autre / libre":
            _finfo = FRANCO_COUNTRIES[_frc]
            if st.session_state.get("_fr_prev") != _frc:
                # Changement de pays : met à jour pays / ville suggérée / région DDG
                st.session_state["country"] = _finfo["country"]
                if not st.session_state.get("city"):
                    st.session_state["city"] = _finfo["cities"][0]
                st.session_state["ddg_region"] = _finfo["region"]
                st.session_state["_fr_prev"] = _frc
            st.caption("Villes suggérées : " + ", ".join(_finfo["cities"][:6]))
        else:
            st.session_state["_fr_prev"] = _frc or ""
        c1, c2 = st.columns(2)
        c1.text_input("Ville", key="city", placeholder="Lomé")
        c2.text_input("Pays", key="country", placeholder="Togo")

        st.markdown("### 💰 Paiement & confiance")
        st.text_input("IBAN (Grey.co) — emails EU", key="iban", placeholder="FR76 1234 …")
        st.text_area("Split T-Money / Flooz — clients Afrique",
                     key="africa_payment", height=70)

        st.markdown("### 🚦 Quota quotidien & réchauffement")
        st.caption("Protège votre réputation d'expéditeur : Gmail limite à ~500 emails/jour "
                   "par compte, et un volume soudain = spam. Le réchauffement augmente "
                   "progressivement la limite (10 → 30 → 60 → … → 200/jour).")
        cw1, cw2 = st.columns(2)
        cw1.toggle("Plan de réchauffement", key="warmup_enabled",
                   help="Active la montée en volume progressive (2-4 semaines conseillées).")
        cw2.number_input("Limite fixe / max (emails/jour)", 0, 5000, 200, key="daily_limit",
                         help="0 = illimité (déconseillé). Limite maximale après réchauffement.")
        st.date_input("Date de début du réchauffement", key="warmup_start",
                      value=datetime.now().date(),
                      help="Jour 1 du réchauffement — la limite monte chaque semaine.")
        _lim = daily_send_limit()
        _used = daily_sent_count()
        if _lim > 0:
            st.progress(min(1.0, _used / _lim if _lim else 0),
                        text=f"Aujourd'hui : {_used} / {_lim} emails envoyés")
        else:
            st.caption(f"Aujourd'hui : {_used} emails envoyés (illimité)")

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
        region = c1.selectbox("Région de recherche", REGIONS, key="ddg_region")
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

    with st.expander("📄 Importer des leads (CSV)", expanded=True):
        uploaded = st.file_uploader("Fichier CSV ou Excel", type=["csv", "txt", "xlsx", "xls"], key="csv_up",
                                    help="Exports Instant Data Scraper, Excel/Windows et CSV séparés par virgule, point-virgule ou tabulation.")
        if uploaded and st.button("📥 Importer le fichier", type="secondary"):
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

    with st.expander("🎯 LinkedIn Sniper — profils décideurs (Google Dorking)", expanded=False):
        st.caption("Recherche gratuite (DuckDuckGo) de profils de gérants / décideurs via "
                   "`site:linkedin.com/in/` + niche + ville. Les profils trouvés sont ajoutés "
                   "dans la colonne « LinkedIn » et en leads dédiées (source LinkedIn).")
        l1, l2, l3 = st.columns([2, 1, 1])
        niche = l1.text_input("Niche / fonction (ex : gérant, directeur commercial, fondateur)",
                              key="ln_niche", placeholder="gérant")
        ln_city = l2.text_input("Ville", key="ln_city", placeholder="Lomé")
        ln_max = l3.number_input("Profils max", 3, 30, 10, key="ln_max")
        if st.button("🎯 Lancer le LinkedIn Sniper", type="primary"):
            if not _DDGS_AVAILABLE:
                st.error("`ddgs` absent — `pip install ddgs` puis relancez l'app.")
            else:
                q_city = (ln_city or "").strip() or (st.session_state.get("city", "") or "").strip()
                with st.spinner("LinkedIn Sniper en action…"):
                    try:
                        profils = search_linkedin_profiles(
                            niche, q_city, st.session_state.get("country", ""),
                            st.session_state.get("ddg_region", "wt-wt"), int(ln_max))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Erreur LinkedIn Sniper : {exc}")
                        profils = []
                if not profils:
                    st.info("Aucun profil LinkedIn trouvé — élargissez la niche ou changez de "
                            "région de recherche.")
                else:
                    rows = []
                    for p in profils:
                        rows.append({"name": p["name"], "website": "", "email": "", "phone": "",
                                     "source": "LinkedIn", "flag": "Profil décideur",
                                     "segment": SEG_NO_SITE, "snippet": p.get("title", ""),
                                     "audit": "", "status": "", "linkedin": p["url"],
                                     "employees": "", "ai_target": "", "ai_audit": ""})
                    new_df = pd.DataFrame(rows, columns=LEAD_COLS)
                    existing = st.session_state["leads"]
                    # Associe les profils aux leads existantes par similarité de nom
                    for _, nr in new_df.iterrows():
                        nm = _norm_key(nr["name"])
                        if not nm:
                            continue
                        m = existing["name"].map(lambda x: nm == _norm_key(x) or nm in _norm_key(x))
                        if bool(m.any()) and "linkedin" in existing.columns:
                            existing.loc[m, "linkedin"] = nr["linkedin"]
                    st.session_state["leads"] = (pd.concat([existing, new_df], ignore_index=True)
                                                  if not existing.empty else new_df)
                    st.session_state["leads_version"] += 1
                    st.toast(f"{len(profils)} profil(s) LinkedIn ajouté(s) ✓", icon="🎯")

    with st.expander("🤖 Audit IA des sites — Cible Prioritaire IA (MaisonNova)", expanded=False):
        st.caption("Balayage HTML automatique (BeautifulSoup, parallélisé) : détecte l'absence "
                   "d'IA/chatbot (chatbot, assistant, IA, AI, Intercom, Crisp) et la présence "
                   "d'un formulaire ou du mot « Contact ». Les leads correspondantes sont "
                   "marquées « Cible Prioritaire IA » (colonne dédiée).")
        aa_scope = st.radio("Portée de l'audit",
                            ["Toutes les leads", "Leads avec site web",
                             "🎯 Sélection actuelle (✓ / filtre)"],
                            index=1, horizontal=True, key="ai_audit_scope")
        aa_workers = st.number_input("Parallélisme (workers)", 1, 16, 8, key="ai_audit_workers",
                                     help="Scans simultanés — ~40 Mo par worker, restez sous 8 Go.")
        if st.button("⚡ Lancer l'audit IA des sites", type="primary"):
            scope_df = st.session_state["leads"]
            if aa_scope == "Leads avec site web":
                scope_df = scope_df[scope_df["website"].map(has_website)]
            elif aa_scope == "🎯 Sélection actuelle (✓ / filtre)":
                scope_df, _ = _outreach_plan(scope_df)
            if scope_df.empty:
                st.warning("Aucune lead dans le périmètre choisi.")
            else:
                prog = st.progress(0.0, text="Scan HTML des sites…")
                try:
                    new_df = audit_ai_batch(scope_df,
                                            progress_cb=lambda p: prog.progress(
                                                p, text="Scan HTML des sites…"),
                                            max_workers=int(aa_workers))
                    for col in ("ai_target", "ai_audit"):
                        st.session_state["leads"].loc[new_df.index, col] = new_df[col]
                    n_target = int((new_df["ai_target"].astype(str).str.contains("Oui")).sum())
                    st.session_state["leads_version"] += 1
                    st.toast(f"{len(new_df)} site(s) scanné(s) — "
                             f"{n_target} cible(s) prioritaire(s) IA ✓", icon="⚡")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Erreur audit IA : {exc}")
                finally:
                    prog.empty()

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
            "linkedin": st.column_config.TextColumn("LinkedIn (décideur)", width="medium"),
            "employees": st.column_config.TextColumn("Employés", width="small"),
            "ai_target": st.column_config.TextColumn("Cible IA", width="small"),
            "ai_audit": st.column_config.TextColumn("Audit IA", width="medium"),
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
    # Index unique garanti : les lignes ajoutées dans l'éditeur dynamique peuvent
    # dupliquer l'index (ex. deux leads d'index 20) -> clés de widgets en collision.
    _normalize_leads_index()
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
    # permettre d'auditer des leads hors filtre. On DÉDUPLIQUE aussi : la sélection stockée
    # (audit_sel) peut contenir des doublons hérités d'un état précédent — sans cette étape,
    # deux widgets partagent la même clé (StreamlitDuplicateElementKey 'snippet_20').
    allowed = set(opts)
    selected = list(dict.fromkeys(i for i in selected if i in allowed))

    need_snippets = [i for i in selected
                     if mode in (MODE_COPY, MODE_AI)
                     or str(leads.loc[i].get("segment", "")) == SEG_BAD_SITE]
    # Clés uniques PAR POSITION : même si deux leads partageaient le même index
    # (données héritées), chaque widget a une clé distincte. La même map sert à la
    # boucle de génération (lecture de l'extrait saisi / récupéré).
    snippet_key: dict = {i: f"snippet_{_pos}_{i}" for _pos, i in enumerate(need_snippets)}
    # Extraits récupérés AUTOMATIQUEMENT (bouton « Générer » sans saisie manuelle).
    # Stockés HORS des clés de widgets : écrire dans st.session_state[_sk] après
    # l'instanciation du text_area lève StreamlitAPIException.
    auto_snippets: dict = st.session_state.setdefault("_auto_snippets", {})
    if need_snippets:
        st.markdown("#### Extraits de sites (Copywriting / IA / Segment B — critique IA)")
        for i in need_snippets:
            _sk = snippet_key[i]
            with st.expander(f"✂️ Extrait pour « {leads.loc[i, 'name']} »", expanded=False):
                col1, col2 = st.columns([3, 1])
                st.text_area(
                    "Texte / description du site", key=_sk, height=110,
                    placeholder="Collez un extrait (ou récupérez-le du site) : l'IA le critiquera "
                                "pour le Segment B, ou s'en inspirera en mode Copywriting.",
                )
                col2.button("🔎 Récupérer du site", key=f"fetch_{_sk}",
                            on_click=_fetch_snippet_cb, args=(i, _sk))
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
                if mode in (MODE_COPY, MODE_AI) or seg == SEG_BAD_SITE:
                    _sk = snippet_key.get(i)
                    snippet = (st.session_state.get(_sk, "") or "").strip() if _sk else ""
                    if not snippet and _sk:
                        snippet = (auto_snippets.get(_sk, "") or "").strip()
                    if not snippet and row.get("snippet"):
                        snippet = str(row["snippet"])
                    if not snippet and has_website(str(row.get("website", "") or "")):
                        # Contenu RÉEL du site récupéré automatiquement — l'audit
                        # Gemini travaille sur le site, pas sur un texte générique.
                        snippet = fetch_snippet(str(row["website"]))
                        if snippet and _sk:
                            auto_snippets[_sk] = snippet  # hors widget -> pas d'exception
                location = f"{st.session_state.get('city', '')} {st.session_state.get('country', '')}".strip()
                faille = str(row.get("ai_audit", "") or "") if mode == MODE_AI else ""
                prompt = audit_prompt(mode, str(row["name"]), location or "…", snippet,
                                      segment=seg, lang=st.session_state.get("lang", "fr"),
                                      website=str(row.get("website", "")), faille=faille)
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


def _gen_email_gemini_cb() -> None:
    """Gemini rédige 100 % de l'email (objet + corps) : ton du pays + faille détectée."""
    leads = st.session_state.get("leads")
    if leads is None or leads.empty:
        st.session_state["_out_error"] = "Importez d'abord des leads (onglet Discovery)."
        return
    api_key = st.session_state.get("gemini_key", "")
    if not api_key:
        st.session_state["_out_error"] = "Renseignez la clé Gemini dans la barre latérale."
        return
    target, _ = _outreach_plan(leads)
    row = target.iloc[0] if not target.empty else leads.iloc[0]
    mode = st.session_state["mode"]
    audit = st.session_state["audits"].get(lead_key(row), "")
    faille = str(row.get("ai_audit", "") or "") or audit or ""
    try:
        subj, body = personalize_email(
            mode, st.session_state.get("agency", ""), st.session_state.get("city", ""),
            st.session_state.get("country", ""), st.session_state.get("lang", "fr"), row,
            audit=audit, faille=faille, api_key=api_key,
            model=st.session_state.get("gemini_model") or GEMINI_MODELS[0])
        st.session_state["email_subject"] = subj
        st.session_state["email_body"] = body
        st.session_state["_out_toast"] = "Email généré par Gemini ✓ (ton adapté au pays)"
    except Exception as exc:  # noqa: BLE001
        st.session_state["_out_error"] = f"Échec génération : {exc}"


def _gen_wa_gemini_cb() -> None:
    """Gemini rédige le message WhatsApp : ton du pays + faille détectée."""
    leads = st.session_state.get("leads")
    if leads is None or leads.empty:
        st.session_state["_out_error"] = "Importez d'abord des leads (onglet Discovery)."
        return
    api_key = st.session_state.get("gemini_key", "")
    if not api_key:
        st.session_state["_out_error"] = "Renseignez la clé Gemini dans la barre latérale."
        return
    target, _ = _outreach_plan(leads)
    row = target.iloc[0] if not target.empty else leads.iloc[0]
    mode = st.session_state["mode"]
    audit = st.session_state["audits"].get(lead_key(row), "")
    faille = str(row.get("ai_audit", "") or "") or audit or ""
    try:
        st.session_state["wa_msg"] = personalize_wa(
            mode, st.session_state.get("agency", ""), st.session_state.get("city", ""),
            st.session_state.get("country", ""), st.session_state.get("lang", "fr"), row,
            faille=faille, api_key=api_key,
            model=st.session_state.get("gemini_model") or GEMINI_MODELS[0])
        st.session_state["_out_toast"] = "Message WhatsApp généré par Gemini ✓ (ton adapté au pays)"
    except Exception as exc:  # noqa: BLE001
        st.session_state["_out_error"] = f"Échec génération : {exc}"


def _gen_both_gemini_cb() -> None:
    """Gemini rédige l'email ET le message WhatsApp en un seul clic (templates complets)."""
    # L'email d'abord : ses placeholders servent de base au message WhatsApp
    _gen_email_gemini_cb()
    if st.session_state.get("_out_error"):
        return  # l'erreur de l'email est déjà signalée, on ne masque pas
    _gen_wa_gemini_cb()
    if not st.session_state.get("_out_error"):
        st.session_state["_out_toast"] = ("Email + WhatsApp générés par Gemini ✓ "
                                           "(ton adapté au pays, placeholders conservés)")


def _fetch_snippet_cb(i: int, widget_key: str = "") -> None:
    """Récupère le contenu réel du site dans l'extrait de la lead (clé de widget passée)."""
    site = st.session_state["leads"].loc[i, "website"]
    got = fetch_snippet(site)
    if got:
        st.session_state[widget_key or f"snippet_{i}"] = got
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
        _spam = spam_risk_warning(subject, body)
        if _spam:
            st.warning(f"⚠️ Mots à risque de spam détectés : **{', '.join(_spam)}**. "
                       "Remplacez-les pour éviter le dossier spam (ex. « gratuit », « offre "
                       "exceptionnelle », « urg », « 100% »). Un email sobre et personnalisé "
                       "passe mieux les filtres Gmail.")
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
        g1, g2 = st.columns([1, 1])
        g1.button("✨ Générer l'email avec Gemini (ton du pays + faille détectée)",
                  use_container_width=True, key="gen_email_btn",
                  on_click=_gen_email_gemini_cb,
                  disabled=not bool(st.session_state.get("gemini_key")),
                  help="L'IA (Gemini Flash) rédige 100 % de l'email — objet + corps — adapté au "
                       "pays cible (formel en France, plus chaleureux au Togo…) et au constat "
                       "réel du site (audit / contenu récupéré). Placeholders {…} conservés.")
        g2.button("🤖 Générer email + WhatsApp (un clic)",
                  use_container_width=True, key="gen_both_btn",
                  on_click=_gen_both_gemini_cb,
                  disabled=not bool(st.session_state.get("gemini_key")),
                  help="Gemini rédige en un seul clic le template d'email (objet + corps) ET le "
                       "message WhatsApp — 100 % personnalisés, placeholders {…} conservés.")
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
                                    st.session_state.get("africa_payment", ""),
                                    st.session_state.get("country", "")) if payment_on else ""
            loc = f"{st.session_state.get('city','')} {st.session_state.get('country','')}".strip()
            agency = st.session_state.get("agency", "")
            preview = fill_template(body, row, agency, loc, mode, audit, payment)
            preview_subject = fill_template(subject, row, agency, loc, mode)
            with st.expander("Aperçu (1ʳᵉ lead)", expanded=True):
                st.markdown(f"**Objet :** {preview_subject}")
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
            _spam_send = spam_risk_warning(subject, body)
            if _spam_send:
                st.warning(f"⚠️ {len(_spam_send)} mot(s) à risque de spam dans le template : "
                           f"**{', '.join(_spam_send)}**. Vous pouvez envoyer quand même, mais "
                           "le risque de finir en spam est élevé.")
            b1, b2 = st.columns(2)
            if b1.button("▶️ Lancer la campagne", type="primary", use_container_width=True,
                         disabled=running or not recipients):
                creds_ok = True
                if channel.startswith("composio"):
                    if not st.session_state.get("composio_key"):
                        st.error("Renseignez la clé Composio (sidebar) — puis connectez Gmail sur composio.dev.")
                        creds_ok = False
                elif not parse_gmail_accounts():
                    st.error("Renseignez au moins un compte Gmail (sidebar : adresse + mot de passe "
                             "d'application, ou comptes additionnels).")
                    creds_ok = False
                if creds_ok:
                    payment = payment_block(mode, st.session_state.get("iban", ""),
                                            st.session_state.get("africa_payment", ""),
                                            st.session_state.get("country", "")) if payment_on else ""
                    img_list = st.session_state.get("email_images_data") or []
                    cids = [f"img_{i}" for i in range(len(img_list))]
                    cta_url = (st.session_state.get("email_cta_url") or "").strip()
                    cta = ({"url": cta_url,
                            "label": (st.session_state.get("email_cta_label") or "").strip()
                                     or "En savoir plus"} if cta_url else None)
                    video_url = (st.session_state.get("email_video_url") or "").strip()
                    queue = []
                    loc = f"{st.session_state.get('city','')} {st.session_state.get('country','')}".strip()
                    agency = st.session_state.get("agency", "")
                    for i in recipients:
                        row = email_leads.loc[i]
                        audit = st.session_state["audits"].get(lead_key(row), "")
                        q = {
                            "name": str(row["name"]),
                            "email": str(row["email"]),
                            "subject": fill_template(subject, row, agency, loc, mode),
                            "body": fill_template(body, row, agency, loc, mode, audit, payment),
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
                            send_fn = _account_send_fn(agency)  # roulement multi-comptes
                        queue, quota_note = _outreach_queue_cap(queue)
                        if quota_note:
                            st.warning(quota_note)
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
                        state["campaign_id"] = _campaign_append("Email", len(queue))["id"]
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
                    _campaign_update(state.get("campaign_id"), state["pos"],
                                     "Interrompue" if state.get("stopped") else "Terminée")
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
        _spam_wa = spam_risk_warning("", st.session_state.get("wa_msg", ""))
        if _spam_wa:
            st.warning(f"⚠️ Mots à risque dans le message WhatsApp : **{', '.join(_spam_wa)}**.")
        c1, c2 = st.columns([1, 3])
        c1.button("🔄 Modèle par défaut", use_container_width=True, on_click=_reset_wa_msg)
        c2.button("✍️ Améliorer le message avec OpenAI", use_container_width=True,
                  disabled=not (bool(st.session_state.get("openai_key")) and _OPENAI_AVAILABLE),
                  on_click=_improve_wa_openai)
        c2.button("✨ Générer le message avec Gemini (ton du pays + faille)",
                  use_container_width=True, key="gen_wa_btn",
                  on_click=_gen_wa_gemini_cb,
                  disabled=not bool(st.session_state.get("gemini_key")),
                  help="Gemini rédige le message WhatsApp adapté au pays cible et à la faille "
                       "détectée — placeholders {…} conservés.")
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
                        elif not parse_gmail_accounts():
                            st.error("Renseignez au moins un compte Gmail (sidebar : adresse + mot "
                                     "de passe d'application, ou comptes additionnels) — ou "
                                     "choisissez le canal Composio.")
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
                                                 st.session_state.get("africa_payment", ""),
                                                 st.session_state.get("country", ""))
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
                                email_fn = _account_send_fn(agency)  # roulement multi-comptes
                            queue, quota_note = _outreach_queue_cap(queue)
                            if quota_note:
                                st.warning(quota_note)
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
                            state["campaign_id"] = _campaign_append(
                                "Hybride (WhatsApp + Email)", len(queue))["id"]
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
                        _campaign_update(hstate.get("campaign_id"), hstate["pos"],
                                         "Interrompue" if hstate.get("stopped") else "Terminée")
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
    country = st.session_state.get("country", "") or "—"
    responses = st.session_state.setdefault("responses", {})

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Leads", len(leads))
    c2.metric("Contactées", stats["contacted"])
    c3.metric("WhatsApp", stats["wa"])
    c4.metric("Emails", stats["mail"])
    c5.metric("Échecs", stats["fail"])
    succ = stats["mail"] + stats["wa"]
    c6.metric("Taux de succès",
              f"{100 * succ / (succ + stats['fail']):.0f} %" if (succ + stats["fail"]) else "—")

    answered = sum(1 for v in responses.values() if v and not str(v).startswith("❌"))
    clicks = int(st.session_state.get("tracked_clicks", 0) or 0)
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Taux de réponse",
              f"{100 * answered / stats['contacted']:.0f} %" if stats["contacted"] else "—")
    r2.metric("Taux de clic (liens trackés)",
              f"{100 * clicks / stats['mail']:.0f} %" if stats["mail"] else "—")
    r3.metric("Réponses positives", answered)
    r4.number_input("🖱️ Clics trackés (manuel)", 0, 100000, key="tracked_clicks")

    st.markdown("#### 🗂️ Campagnes en cours")
    st.caption("Reporting v6 — colonnes [Nom | Pays | Source | Statut Envoi | Réponse détectée]. "
               "Le statut de réponse est marqué MANUELLEMENT dans la colonne dédiée.")
    if leads.empty:
        st.info("Aucune lead — lancez une recherche dans l'onglet Discovery.")
    else:
        rows = []
        for _, r in leads.iterrows():
            rows.append({
                "Nom": str(r.get("name", "")),
                "Pays": country,
                "Source (Maps/LinkedIn…)": str(r.get("source", "") or "—"),
                "Statut Envoi": str(r.get("status", "") or "—"),
                "Réponse détectée (manuel)": responses.get(lead_key(r), ""),
            })
        camp_df = pd.DataFrame(rows)
        edited = st.data_editor(
            camp_df, key="resp_editor", hide_index=True, use_container_width=True, height=300,
            disabled=["Nom", "Pays", "Source (Maps/LinkedIn…)", "Statut Envoi"],
            column_config={
                "Réponse détectée (manuel)": st.column_config.SelectboxColumn(
                    "Réponse détectée (manuel)", options=RESPONSE_OPTS, width="medium"),
            },
        )
        for (_, lr), (_, er) in zip(leads.iterrows(), edited.iterrows()):
            k = lead_key(lr)
            v = er.get("Réponse détectée (manuel)", "")
            if v:
                responses[k] = v
            elif k in responses:
                responses.pop(k, None)

    st.markdown("#### 🚀 Campagnes lancées")
    camps = st.session_state.get("campaigns", [])
    if camps:
        st.dataframe(pd.DataFrame(camps), hide_index=True, use_container_width=True, height=180)
        st.caption("Les campagnes lancées depuis l'onglet Outreach apparaissent ici avec leur "
                   "progression et leur statut (En cours / Terminée / Interrompue).")
    else:
        st.caption("Aucune campagne lancée pour l'instant — lancez un envoi dans l'onglet Outreach.")

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
    _normalize_leads_index()

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
        f'<div class="brand-title">Prospector <small>V6</small></div>'
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

    # v6 : sauvegarde instantanée des champs modifiés (settings.json)
    persist_settings()

    st.markdown(
        '<div class="ftr">⛏️ SCRIBA OMNISCIENT PROSPECTOR · <b>v6</b> · '
        'settings.json · 10 pays francophones · LinkedIn Sniper · Audit IA sites · '
        'Dashboard campagnes · IA par pays</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
