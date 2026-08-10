# ⛏️ Scriba Omniscient Prospector v1.0

Tableau de bord Streamlit de prospection automatisée pour **3 modèles d'affaires** depuis une seule interface :

| Mode | Cible | Paiement | Canal |
|---|---|---|---|
| 🖋️ **European Copywriting Sniper** | Agences immobilières (EU) | Virement SEPA — **IBAN Grey.co** | Email (FR/EN/DE) |
| 🌍 **Local Web-Design Hunter** | PME sans site web (local / Afrique) | Split **10k/40k T-Money ou Flooz** | Email + WhatsApp |
| 📍 **Local SEO Visibility** | Fiches Google Maps faibles | Split **10k/40k T-Money ou Flooz** | Email + WhatsApp |

**Stack** : Streamlit · Google GenAI (Gemini) · Pandas · Requests · BeautifulSoup · `ddgs` (DuckDuckGo) · smtplib · Composio (optionnel).

---

## 1. Installation

```bash
pip install streamlit pandas requests beautifulsoup4 ddgs google-genai composio
```

(ou `pip install -r requirements.txt`)

## 2. Lancement

```bash
streamlit run app.py
```

L'app s'ouvre sur `http://localhost:8501`.

> **8 Go de RAM** : aucune librairie lourde (pas de Selenium / navigateur headless). Seuls `requests` et BeautifulSoup font le travail réseau.

## 3. Configuration (barre latérale)

1. **Identité** — nom de l'agence, **clé API Gemini** ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
2. **Gmail (smtplib)** — adresse + **mot de passe d'application** ([myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)). ⚠️ La validation en 2 étapes doit être activée.
3. **Composio (optionnel)** — clé API [composio.dev](https://composio.dev) pour envoyer via Gmail OAuth. Connectez le toolkit `gmail` avec `user_id = scriba-prospector-local`, puis choisissez « composio (Gmail OAuth) » dans l'onglet Outreach.
4. **Mode** — choisissez l'un des 3 modèles d'affaires.
5. **Localisation** — ville + pays.
6. **Paiement & confiance** — votre **IBAN Grey.co** (injecté dans les emails EU) et le texte du **split T-Money / Flooz** (injecté pour les clients africains).
7. **Langue de génération** — le toggle **FRANÇAIS / ENGLISH** bascule instantanément la langue des audits IA, des emails et des messages WhatsApp (modèles par défaut ; vos messages personnalisés sont préservés).

## 4. Utilisation

### 🧭 Onglet 1 — Lead Discovery & Scraper
- **Recherche DuckDuckGo** : requêtes adaptées au mode + localisation (région réglable). Aucun coût, aucune clé.
- **Import CSV** : compatible avec les exports **Instant Data Scraper** (détection automatique des colonnes name/website/email/phone).
- Table éditable (ajout manuel de numéros WhatsApp, suppression, export CSV), avec boutons **☑️ Tout sélectionner / ⬜ Tout désélectionner** (sélection totale en un clic) et compteur des leads cochées.
- **Le filtre actif OU la sélection (✓) pilotent l'onglet Outreach** : si un filtre est actif dans Discovery (ex. « ⚠️ Sans site web »), **seuls ces leads sont contactés** — la sélection ✓ n'est prise en compte que lorsqu'aucun filtre n'est actif (compteur « 🎯 Destinataires » affiché en tête d'onglet).

### 🧠 Onglet 2 — AI Audit Engine
- **Le filtre actif de Discovery s'applique aussi à l'Audit** : si vous filtrez les leads (ex. « ⚠️ Sans site web »), seules ces leads apparaissent dans la sélection « Leads à auditer ».
- Sélection des leads, puis génération par **Gemini** (`gemini-3.6-flash` par défaut) :
  - *Copywriting* : réécriture d'un extrait de description en style **« Luxe »** (accroche + corps sensoriel + CTA) — extrait collable ou **récupéré automatiquement du site** de l'agence.
  - *Web Design* : **3 arguments** sur les pertes liées à l'absence de site, focus **confiance diaspora**.
  - *SEO* : script de vente **QR code + avis 5 étoiles → chiffre d'affaires**.
- Audits stockés, éditables, exportables en Markdown.

### 🚀 Onglet 3 — Smart Outreach
- **Email** : éditeur de template avec placeholders `{AgencyName} {LeadName} {LeadWebsite} {LeadEmail} {Location} {Mode} {Audit} {PaymentPlan}` + insertion rapide par menu déroulant.
  - `{Audit}` = audit IA de la lead ; `{PaymentPlan}` = bloc paiement automatique (IBAN Grey.co pour l'EU, split T-Money/Flooz pour l'Afrique).
  - **Template libre** : écrivez l'objet et le corps avec les accolades `{…}` — remplacées automatiquement par les infos du client à l'envoi ; **toute colonne de la lead fonctionne** (ex. `{Phone}`, `{Segment}`, `{City}`, `{Country}`), insensible à la casse ; placeholder inconnu laissé tel quel, champ vide → « … ».
  - **Contenu enrichi** : 🖼️ upload d'images (jointes en inline `cid`, affichées dans Gmail), 🔗 bouton CTA doré, 🎬 lien vidéo — injectés dans l'email HTML (canal smtplib) ; + liens markdown `[texte](url)` et images `![légende](url)` directement dans le corps.
  - **Anti-spam** : envoi séquentiel avec délai aléatoire **60–120 s** (réglable), bouton **⏹️ Stop** réactif, journal en direct, mode test 2–6 s.
- **WhatsApp** : génération de lien `wa.me` avec message persuasif pré-rempli (site + WhatsApp pour la diaspora, QR code + avis pour le SEO).

## 5. Éthique & conformité

La prospection froide est encadrée (RGPD / loi Informatique et Libertés). Respectez les délais, proposez une désinscription, et ne sollicitez que des professionnels dans le cadre de leur activité. Les coordonnées issues de DuckDuckGo sont publiques, mais leur usage commercial doit rester proportionné et loyal.

## 6. Déploiement (Streamlit Community Cloud)

L'application est conçue pour **Streamlit Community Cloud** — la plateforme gratuite et officielle de Streamlit, connectée à GitHub :

1. **Poussez le code sur GitHub** (dépôt public recommandé pour le plan gratuit).
2. Rendez-vous sur [share.streamlit.io](https://share.streamlit.io) et connectez-vous avec votre compte GitHub.
3. Cliquez sur **Create app** → sélectionnez le dépôt → `app.py` comme fichier principal.
4. **Deploy !** L'app est en ligne sur `https://<nom>.streamlit.app`.

Chaque `git push` sur `main` redéploie automatiquement l'application.

> ⚠️ **Pourquoi pas Vercel ?** Vercel héberge des fonctions serverless *sans état* et sans WebSockets persistants, alors que Streamlit a besoin d'un processus Python continu (session state, endpoint `_stcore/stream`). Une app Streamlit ne peut pas y fonctionner correctement. Streamlit Community Cloud est l'hébergeur officiel, gratuit et sans configuration.

## 7. Dépannage

| Problème | Solution |
|---|---|
| `ddgs` rate-limité / erreur réseau | Relancez, baissez « résultats par requête », changez de région |
| Envoi Gmail refusé (535) | Utilisez le bouton **🔌 Tester la connexion Gmail** (sidebar) pour valider les identifiants : il faut un **mot de passe d'application**, pas le mot de passe normal (2 étapes activée, code sans espaces). Alternative : canal **composio (Gmail OAuth)** |
| `ModuleNotFoundError` | `pip install <module>` et relancez `streamlit run app.py` |
| Modèle Gemini introuvable (404) | L'app **bascule automatiquement** sur un autre modèle de la liste ; si tout échoue, vérifiez la clé (sidebar) et la liste des modèles (onglet Audit, rechargée toutes les 5 min) |
| Plusieurs instances / port occupé | `streamlit run app.py --server.port 8502` |
