# ⛏️ Scriba Omniscient Prospector v6

Tableau de bord Streamlit de prospection automatisée pour **4 modèles d'affaires** depuis une seule interface :

| Mode | Cible | Paiement | Canal |
|---|---|---|---|
| 🖋️ **European Copywriting Sniper** | Agences immobilières (EU) | Virement SEPA — **IBAN Grey.co** | Email (FR/EN/DE) |
| 🌍 **Local Web-Design Hunter** | PME sans site web (local / Afrique) | Split **10k/40k T-Money ou Flooz** | Email + WhatsApp |
| 📍 **Local SEO Visibility** | Fiches Google Maps faibles | Split **10k/40k T-Money ou Flooz** | Email + WhatsApp |
| 🤖 **AI Agency (MaisonNova)** | PME **3-20 employés** sans IA sur leur site | SEPA (EU) / split local (Afrique) | Email + WhatsApp |

**Stack** : Streamlit · Google GenAI (Gemini) · Pandas · Requests · BeautifulSoup · `ddgs` (DuckDuckGo) · smtplib · Composio (optionnel).

## 🆕 Nouveautés v6

1. **Persistance ZÉRO perte** — `settings.json` sauvegarde automatiquement (à chaque modification) la clé Gemini, l'email expéditeur, le mot de passe d'application, le nom de l'agence, le pays, etc. — et recharge tout au démarrage. Le **logo** est enregistré en `logo.png`. ⚠️ Fichier local en clair : ne le committez jamais (gitignoré).
2. **Découverte géo-localisée francophone** — sélecteur de pays [France, Belgique, Suisse, Luxembourg, Canada (Québec), Togo, Côte d'Ivoire, Sénégal, Bénin, Maroc] : le pays, la région DuckDuckGo, les villes suggérées et le ton des messages IA s'adaptent automatiquement.
3. **LinkedIn Sniper** — profils de décideurs via Google Dorking (`site:linkedin.com/in/` + niche + ville), colonne dédiée « LinkedIn » dans le dashboard.
4. **Audit IA des sites (module AI Agency)** — scan HTML parallèle (BeautifulSoup, 8 workers) : absence de `chatbot` / `assistant` / `IA` / `AI` / `Intercom` / `Crisp` + présence d'un `<form>` ou du mot « Contact » → lead marquée **🎯 Cible Prioritaire IA**. Filtres dédiés + colonnes `ai_target` / `ai_audit`.
5. **Dashboard de campagnes** — tableau [Nom | Pays | Source | Statut Envoi | Réponse détectée (manuel)] + campagnes lancées suivies en direct, **taux de réponse** et **taux de clic** (liens trackés).
6. **Personnalisation IA par pays** — Gemini rédige 100 % de l'email / du message WhatsApp selon la niche, la faille détectée et le pays cible (ton formel en France, plus chaleureux au Togo…).
7. **📬 Envoi Masse (Excel → Gmail)** — importez un fichier Excel avec des adresses email, rédigez un seul message, et l'outil envoie l'email à chaque adresse une par une. Les erreurs sont ignorées, le quota Gmail (500/24h) est respecté avec arrêt automatique, et un rapport détaillé (✅ envoyés / ❌ échoués / ⏳ restants) est affiché à la fin.

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

> 💾 **Persistance automatique** : dès que vous modifiez un champ (agence, clés, pays, email…), il est écrit instantanément dans `settings.json` et rechargé au prochain démarrage — **zéro perte de données**, même après fermeture.

1. **Identité** — nom de l'agence, **logo** (optionnel, enregistré en `logo.png`), **clé API Gemini** ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
2. **Gmail (smtplib)** — adresse + **mot de passe d'application** ([myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)). ⚠️ La validation en 2 étapes doit être activée.
3. **Composio (optionnel)** — clé API [composio.dev](https://composio.dev) pour envoyer via Gmail OAuth. Connectez le toolkit `gmail` avec `user_id = scriba-prospector-local`, puis choisissez « composio (Gmail OAuth) » dans l'onglet Outreach.
4. **Mode** — choisissez l'un des 3 modèles d'affaires.
5. **Localisation** — sélecteur **pays francophone** (10 pays) + ville : la région DuckDuckGo et le ton IA suivent le pays choisi.
6. **Paiement & confiance** — votre **IBAN Grey.co** (injecté dans les emails EU) et le texte du **split T-Money / Flooz** (injecté pour les clients africains). Le pays cible ajuste automatiquement le bloc de paiement (Afrique → split local, EU → SEPA).
7. **Langue de génération** — le toggle **FRANÇAIS / ENGLISH** bascule instantanément la langue des audits IA, des emails et des messages WhatsApp (modèles par défaut ; vos messages personnalisés sont préservés).

## 4. Utilisation

### 🧭 Onglet 1 — Lead Discovery & Scraper
- **Recherche DuckDuckGo** : requêtes adaptées au mode + localisation (région réglable). Aucun coût, aucune clé.
- **🎯 LinkedIn Sniper** : Google Dorking (`site:linkedin.com/in/`) pour trouver les profils des gérants/décideurs par niche + ville — ajoutés dans la colonne « LinkedIn » et en leads dédiées.
- **🤖 Audit IA des sites** (module AI Agency) : scan HTML parallèle (workers réglables) → marquage **Cible Prioritaire IA** (filtres dédiés : « 🎯 Cible Prioritaire IA », « 🏢 ICP 3-20 employés »).
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

### 📬 Onglet 3b — Envoi Masse (Excel → Gmail)
- **Upload Excel/CSV** : importez un fichier contenant des adresses email — détection automatique de la colonne email + colonne nom optionnelle.
- **Message unique** : rédigez un seul objet + corps ; placeholder `{Name}` pour personnaliser par destinataire.
- **Envoi séquentiel** : emails envoyés un par un via Gmail (smtplib), avec délai humain anti-spam (réglable 5–300 s).
- **Quota Gmail** : compteur intégré — **500 emails / 24h par compte Gmail** — arrêt automatique quand la limite est atteinte.
- **Multi-comptes** : envois répartis entre tous les comptes Gmail configurés (round-robin) + réchauffement progressif.
- **Erreurs ignorées** : chaque échec (adresse invalide, refus SMTP…) est journalisé et l'envoi continue au suivant.
- **Rapport final** : ✅ envoyés, ❌ échoués, 📊 total traité, ⏳ restants + détail de chaque échec.

### 🚀 Onglet 3 — Smart Outreach
- **✨ Génération IA par pays (Gemini Flash)** : un clic rédige 100 % de l'email (objet + corps) ou du message WhatsApp — adapté à la niche, à la faille détectée et au pays cible (formel en France, plus chaleureux au Togo…), placeholders `{…}` conservés.
- **Email** : éditeur de template avec placeholders `{AgencyName} {LeadName} {LeadWebsite} {LeadEmail} {Location} {Mode} {Audit} {PaymentPlan}` + insertion rapide par menu déroulant.
  - `{Audit}` = audit IA de la lead ; `{PaymentPlan}` = bloc paiement automatique (IBAN Grey.co pour l'EU, split T-Money/Flooz pour l'Afrique).
  - **Template libre** : écrivez l'objet et le corps avec les accolades `{…}` — remplacées automatiquement par les infos du client à l'envoi ; **toute colonne de la lead fonctionne** (ex. `{Phone}`, `{Segment}`, `{City}`, `{Country}`), insensible à la casse ; placeholder inconnu laissé tel quel, champ vide → « … ».
  - **Contenu enrichi** : 🖼️ upload d'images (jointes en inline `cid`, affichées dans Gmail), 🔗 bouton CTA doré, 🎬 lien vidéo — injectés dans l'email HTML (canal smtplib) ; + liens markdown `[texte](url)` et images `![légende](url)` directement dans le corps.
  - **Anti-spam** : envoi séquentiel avec délai aléatoire **60–120 s** (réglable), bouton **⏹️ Stop** réactif, journal en direct, mode test 2–6 s.
- **WhatsApp** : génération de lien `wa.me` avec message persuasif pré-rempli (site + WhatsApp pour la diaspora, QR code + avis pour le SEO).

### 📊 Onglet 4 — Dashboard de campagne (v6)
- **Campagnes en cours** : tableau [Nom | Pays | Source (Maps/LinkedIn) | Statut Envoi | **Réponse détectée (manuel)**] — colonne dédiée pour marquer les réponses.
- **Campagnes lancées** : suivi en direct des envois (En cours / Terminée / Interrompue).
- **Statistiques** : Total contactés, **Taux de réponse**, **Taux de clic** (saisie manuelle des clics trackés), Taux de succès, répartition par segment, historique en direct.

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
