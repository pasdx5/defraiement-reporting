# État du projet défraiement — 2 juillet 2026 (après-midi)

## 🎯 Quick brief pour nouvelle session Claude

**Colle ce bloc au début d'une nouvelle conversation avec Claude pour le remettre dans le bain :**

> Contexte : je suis JP (jp.coel@acsrs.be), président ACSRS/RACS. Je maintiens **RACS Défraiement**, une app Belge de gestion des remboursements pour volontaires ambulanciers. Stack : React+TS+Tailwind (Static Web App) + Python Azure Functions + SharePoint Online (via Graph API). Auth CIAM `racsrs.ciamlogin.com` + fédération avec tenant `acsrs.be`. 3 repos locaux :
> - `~/Documents/app-defraiement` (frontend)
> - `~/Documents/defraiement-functions` (backend Python)
> - `~/Documents/defraiement-reporting` (Streamlit reporting)
>
> Contraintes strictes :
> - L'app est en production, 200+ users. Ne pas planter.
> - `local.settings.json` contient des secrets → **jamais commiter**.
> - `func azure functionapp publish` **toujours** avec `--build remote`, jamais `--no-build`.
> - Workflow : staging d'abord (`fn-defraiement-staging-acsrs` + branche `staging`), validation, puis prod (`fn-defraiement-auth-acsrs` + `main`).
>
> Pour l'état complet du projet et le backlog, lis `~/Documents/defraiement-reporting/STATUS.md`. Pour le code, les 3 repos ci-dessus.

---


## ✅ Ce qui est en place et fonctionnel

### Reporting v0.2 déployé sur Azure — 6/7
Nouveautés livrées : onglet **🏦 Virements** (registre des virements collectifs archivés #32, avec références par fichier), **filtre par type** sur l'onglet Par membre, granularité **"Toutes"**, **drill-down** historique par bénévole (cocher la case en début de ligne), fix du merge lignes (onglet Par type), et `SHAREPOINT_HR_SITE_ID`/`SHAREPOINT_MEMBRES_LIST` posés en app settings Azure → la liste des membres se charge dans Vérif planning (le bouton de vérification lui-même reste #39).
Notes déploiement : `WEBSITES_CONTAINER_START_TIME_LIMIT=600` posé (le cold start B1 dépassait les 230s par défaut → Application Error). En cas de 502/504 Kudu au deploy : `az webapp stop` → deploy → `az webapp start`.

### Reporting Streamlit hébergé Azure — #22 ✓ complet
Le reporting **tourne 24/7 sur Azure**, complètement indépendant du Mac Mini de JP.

- **URL live** : https://app-defraiement-reporting.azurewebsites.net
- **Users autorisés** (auth Azure AD requise) :
  - Jean-Philippe Coël (jp.coel@acsrs.be)
  - Daniel Gossey (d.gossey@acsrs.be)
  - Fabienne Felix (f.felix@acsrs.be)
  - Stéphane Tries (s.tries@acsrs.be)
- **Coût Azure** : ~13€/mois (App Service Plan B1 Linux)

### Nouveaux tarifs Nuit — #26 ✓ complet en prod

Depuis le 1er juillet 2026 :
- **Journée AMU/ATNUP** : 80€ (inchangé)
- **Nuit semaine** (Lu→Je soir) : **120€**
- **Nuit weekend** (Ve/Sa/Di soir, weekday ∈ {4,5,6}) : **150€**

État prod à jour :
- ✅ 8 tarifs Tarifs_Defraiement mis à jour (wildcards clôturés, 6 nouveaux tarifs actifs dès 30/6/26 UTC = 1/7/26 Bxl)
- ✅ Backend `fn-defraiement-auth-acsrs` déployé avec la détection weekday (commit `c82b3a4`)
- ✅ Code pushé sur GitHub `pasdx5/defraiement-functions` main
- ✅ **Validation empirique faite par JP vendredi 3/7 matin** : prestation Nuit WE testée → 150€ correctement appliqué. Tous les AMU qui encodent une prestation Nuit WE à partir de ce weekend seront à 150€. #26 clos.

### Refresh Finances_Staging depuis Finances — #27 ✓ complet
Staging remis à niveau au 2/7 : 85 demandes, 112 lignes, 323 historiques copiés de prod → travail sur données concrètes possible.

**Note** : après ce refresh, les tarifs #26 en staging ont été écrasés (miroir prod). Si besoin de retester #26 en staging, relancer `tarifs_wildcard_cleanup.py` + `tarifs_nuit_we_juillet2026.py` en staging.

### Domain hint acsrs.be sur re-auth — #14 ✓ complet en prod (2/7 après-midi)

`src/api.ts` — Quand `acquireTokenSilent` échoue (refresh token expiré), on détecte si l'account précédent était `@acsrs.be` (via username ou claim `hd`) et on rappelle `loginRedirect` avec `extraQueryParameters: { domain_hint: "acsrs.be" }` + `loginHint: acc.username`. Effet : le user acsrs.be qui revient après 90j est redirigé directement vers M365 acsrs.be au lieu de la page CIAM générique.

**Limitation** : ne s'applique QUE au re-auth après token expiré, PAS au premier login (cache vidé). Pour ça, voir #31.

### Archivage Excel virement collectif — #32 ✓ complet en prod (avant 2/7)

**Origine** : Daniel avait exporté un fichier Excel de virement collectif qui a été perdu — impossible ensuite de retracer les demandes incluses, le montant, l'acteur, la date exacte.

**Fix** : bibliothèque SharePoint `Virements_Collectifs` sur site Finances qui archive **AVANT** le renvoi du fichier au navigateur. Métadonnées automatiques : `Acteur`, `Nb_Demandes`, `Montant_Total`, `References_Incluses`. Invariant : "tout fichier bancaire en circulation existe dans l'archive". Si l'archivage échoue → l'export échoue → la transition batch (demandes → EncodeeBanque) n'a pas lieu.

Code : `graph_client.archiver_excel_virement()` (lignes 3309-3354), appelé depuis `/api/export-virement`. Setup : `scripts/setup_virements_collectifs.py`. Refresh staging inclut aussi la copie des fichiers.

### Historique Validation avec nom du demandeur — #30 ✓ complet en prod (2/7 après-midi)

`graph_client.get_historique_decisionnaire()` — Enrichit chaque entrée d'historique avec `demandeur_nom` et `demandeur_prenom` via fetch direct `/items/{id}` sur Demandes_Defraiement. **Parallélisé** avec `ThreadPoolExecutor` (10 workers) → ~500ms max pour 50 items.

**Bug résolu au passage** : la tentative initiale utilisait un batch `$filter=fields/id eq X or …` mais ce filtre échoue silencieusement côté Graph (l'ID interne d'un item SP n'est pas exposé dans `fields/id`, c'est un champ top-level). Le fetch direct via `/items/{id}` est le pattern robuste utilisé partout ailleurs dans le module.

Rendu frontend : `Validation.tsx` ligne 862-867, affiche `D-XXXX · Prénom Nom` dans l'historique.

## 🏗️ Architecture reporting

```
User (Daniel, Fabienne, Stéphane, JP)
    │
    ▼  https://app-defraiement-reporting.azurewebsites.net
    │
    ▼  Easy Auth (Azure AD tenant acsrs.be)
    │     ├─ Login avec compte @acsrs.be
    │     ├─ Assignment required = Yes
    │     └─ App Registration : defraiement-reporting-auth
    │
    ▼  Streamlit app (Python 3.11 sur App Service Linux)
    │     ├─ Managed Identity → Key Vault kv-defraiement
    │     ├─ Secrets : GRAPH_CLIENT_SECRET, MICROSOFT_PROVIDER_AUTHENTICATION_SECRET
    │     └─ Cache réponses 5 min (Streamlit @st.cache_resource)
    │
    ▼  Graph API
    │
    ▼  SharePoint Finances
          ├─ Demandes_Defraiement (filtrées Payee + SigneeVirement)
          └─ Lignes_Defraiement
```

## 📋 Ressources Azure

| Ressource | Nom | Type |
|-----------|-----|------|
| App Service Plan | asp-defraiement-reporting | Linux B1 |
| Web App | app-defraiement-reporting | Python 3.11 |
| App Registration | defraiement-reporting-auth | Single-tenant acsrs |
| Managed Identity | (system-assigned) | RBAC Key Vault Secrets User |
| Key Vault secret | auth-client-secret | Easy Auth |
| Function App PROD | fn-defraiement-auth-acsrs | Python |
| Function App STAGING | fn-defraiement-staging-acsrs | Python |
| SP site PROD | Finances | Prod des demandes |
| SP site STAGING | Finances_Staging | Copie de prod (rafraîchie 2/7) |

Tout dans `rg-defraiment` / subscription `Abonnement Azure 1` (ID: 383a8a5b-646f-4e1f-ad5e-a646afcafc97).

## 🔄 Redéployer le reporting

Depuis le Mac Mini :
```bash
cd ~/Documents/defraiement-reporting
git add . && git commit -m "..." && git push origin main
rm -f deploy.zip
zip -r deploy.zip . -x "*.venv/*" "*__pycache__/*" "*.git/*" "*.DS_Store" "*.pyc" "*local.settings.json*" "deploy.zip"
az webapp deploy --resource-group rg-defraiment --name app-defraiement-reporting --src-path deploy.zip --type zip
```
~2-3 min pour un redéploiement.

## 🔒 Ajouter/retirer un user autorisé

Portail Azure → **Entra ID** → **Enterprise Applications** → `defraiement-reporting-auth` → **Utilisateurs et groupes**. Effet immédiat.

## 🔄 Rafraîchir staging depuis prod

```bash
cd ~/Documents/defraiement-functions
.venv/bin/python scripts/refresh_staging_from_prod.py --dry-run    # preview
.venv/bin/python scripts/refresh_staging_from_prod.py              # live
```
~4-5 min. Wipe staging + copie complète (référence + 85 demandes + lignes + historique).

---

## 🧪 Environnement STAGING

### C'est quoi et pour quoi ?

Un miroir complet de prod pour tester des changements **sans risquer de casser l'app live** que les 200+ membres RACS utilisent. Tout changement backend (code Python) ou data (tarifs, cours, params) passe par staging d'abord.

### URLs

- **Frontend staging** : https://calm-moss-0166db803-staging.westeurope.7.azurestaticapps.net
  Preview environment de l'Azure Static Web App `swa-defraiement`, alimenté par la branche Git `staging` du repo `pasdx5/app-defraiement`.
- **Backend staging** : `https://fn-defraiement-staging-acsrs.azurewebsites.net/api`
  Function App Python dédiée qui lit de Finances_Staging SP.
- **SP staging** : https://acsrs1310.sharepoint.com/sites/Finances_Staging
  Site SharePoint avec les 7 mêmes listes que prod, remplies avec les données prod (rafraîchies au 2/7/26).

### Comment le backend staging pointe vers le SP staging

C'est via un env var override configuré sur la FA staging :

```
SHAREPOINT_SITE_FINANCES = Finances_Staging
```

Le code `graph_client._site_id("Finances")` vérifie l'env var `SHAREPOINT_SITE_FINANCES` et route automatiquement vers `Finances_Staging` si présent. Sur prod FA, cette variable n'existe pas → route vers `Finances`.

**Conséquence importante** : le code source est **identique** entre prod et staging. Le routage se fait uniquement via env vars Azure. Zéro branche de code à maintenir.

### Workflow staging → prod

```
1. Modifier le code local (graph_client.py, function_app.py, etc.)
2. Deploy backend staging :
     func azure functionapp publish fn-defraiement-staging-acsrs --python --build remote
3. Push branche staging :
     git push origin staging
     → GitHub Actions déploie le frontend staging (~2-3 min)
4. Tester sur les URLs staging
5. Une fois validé, promotion :
     git checkout main && git merge staging --no-ff -m "..." && git push origin main
     func azure functionapp publish fn-defraiement-auth-acsrs --python --build remote
```

### Comment tester une modif tarif (comme #26)

Les scripts SP ont un flag `--prod` pour cibler prod. **Sans flag = staging par défaut.**

```bash
# Staging (défaut) — safe
.venv/bin/python scripts/tarifs_nuit_we_juillet2026.py

# PROD (attention !) — demande confirmation "yes"
.venv/bin/python scripts/tarifs_nuit_we_juillet2026.py --prod
```

### Ressources Azure liées à staging

| Ressource | Nom |
|-----------|-----|
| Function App | fn-defraiement-staging-acsrs |
| Storage account | stdefraiementstg |
| Application Insights | ai-defraiement-staging |
| Static Web App preview env | swa-defraiement (branche staging) |
| SP site | Finances_Staging |

Toutes dans `rg-defraiment`. La FA staging tourne sur le même App Service Plan Consumption que prod (pas de coût dédié).

### Limitations connues

- **Pas d'auth différente** entre prod et staging côté frontend — même tenant CIAM `racsrs`, mêmes users. Les membres n'ont juste pas connaissance de l'URL staging.
- **Photos justificatifs** dans `Pièces jointes` NON copiées lors du refresh (seulement métadonnées SP). Impact réel : les liens vers les fichiers PJ des demandes staging cassent.
- **Numéros de référence** identiques à prod après refresh (D-YYYYMMDD-XXXXXX). Si tu crées une nouvelle demande sur staging après refresh, elle aura un numéro basé sur la date actuelle → pas de conflit.

### Quand rafraîchir staging

- **Quotidien** : pas nécessaire, staging peut vivre sa vie
- **Avant une grosse modif structurelle** : oui, pour partir d'un état connu
- **Après une modif prod (data)** qui doit être miroir : oui
- **Pour rejouer un scénario terrain** vu par un membre : oui, pour reproduire l'état exact

Coût : 4-5 min à chaque refresh.

---

## 📌 Tâches restantes

### Sécu / polish reporting (à faire quand tu peux)

**#24 — Custom domain `reporting.acsrs.be`** (priorité basse)
1. CNAME `reporting` → `app-defraiement-reporting.azurewebsites.net`
2. `az webapp config hostname add` + `az webapp config ssl create` + `bind`
3. Ajouter `https://reporting.acsrs.be/.auth/login/aad/callback` dans App Reg → Authentication → Redirect URIs

**#25 — Rotation client secret `easy-auth-webapp`** (sécu, faire avant fin de mois)
1. Portail → App Reg → Certificats & secrets → 🗑️ sur `easy-auth-webapp`
2. Nouveau secret 24 mois, copier la Valeur immédiatement
3. `az keyvault secret set --vault-name kv-defraiement --name auth-client-secret --value "NOUVELLE"`

**#23 — Azure Nonprofit Grant pour RACS ASBL** (bonus)
https://nonprofit.microsoft.com/en-us/getting-started — ~$3500/an de crédits Azure = coûts App Service couverts.

### App défraiement (main product)

**#1 — Filtres dans la vue Validation** (encombrement 50+ demandes)
**#2 — Warning "personne sous contrat"** (défraiement non autorisé)
**#3 — Warning RCY différencié** (volontaire vs contrat)
**#5 — Digest hebdomadaire Trésorière** (vendredi 6h) — remplace le digest quotidien
**#12 — Documenter workflow Git staging → prod**
**#13 — Skip page pédagogique** utilisateurs récurrents
**#15 — Réimplémenter vérification planning depuis dashboard**
**#31 — Refonte flow login** (skip CIAM pour @acsrs.be + supprimer "Stay signed in") — ticket documenté avec plan technique complet, à attaquer plus tard. Cf. section "Note technique #31" en fin de doc.
**#32 — Archivage des fichiers Virement collectif** ✅ COMPLET EN PROD 3/7 — bibliothèque `Virements_Collectifs` créée sur Finances + Finances_Staging, backend déployé partout (`main` = `f5d7f64`). Chaque export dépose l'Excel dans la bibliothèque (bloquant : archive échouée = export annulé) avec Acteur, Nb_Demandes, Montant_Total, References_Incluses. Parti en prod dans le même train : nouveau format d'export (Communication = référence brute, plus de colonne Référence) + colonne Encodé ☐/☑ pour le pointage manuel avant CODA. Embryon de la notion de lot (#36).
**#33 — Retry 429 dans `_graph_get/_graph_post/_graph_patch`** — respecter `Retry-After`. Sans ça, tout bulk de ~20 demandes risque l'échec partiel (cause racine de l'incident 2/7).
**#34 — Modal de confirmation avant bulk "Encoder"** — récap N demandes + total € + avertissement "génère le fichier bancaire et transmet à la signature". À discuter : séparation des rôles (Daniel vérifie, JP/trésorier encode) plutôt qu'un simple modal.
**#35 — Vue Trésorier en sous-onglets** — "À signer" (actionnable) / "En préparation" (lecture seule, sans checkbox). Corrige la confusion 34 affichées / 24 cochables.
**#36 — Notion de lot de virement** (réflexion, pas décidé) — entité Lot, signature et confirmation par lot, garantit l'invariant fichier bancaire ↔ statuts. Migration naturelle depuis #32.
**#40 — Sémantique "signature" honnête** — renommer l'étape Trésorier "Signer" en "Confirmer signature banque" : l'acteur réel (JP) constate la signature faite en banque par la Présidente, historique du type "jp.coel a constaté la signature (signataire banque : Présidente)". Supprime le besoin de retoucher Historique_Statuts à la main (pratique actuelle : remplacement manuel de l'email — incomplet d'ailleurs, le champ acteur sur Demandes_Defraiement garde le vrai). À coupler avec #17/Phase 4 (autorisation par rôle depuis le JWT).
**#41 — Notifications de statut aux bénévoles** — mail automatique au demandeur aux jalons clés : approuvée, refusée (avec motif), payée. Infra Power Automate déjà en place (digest #65). Désamorce les "c'est payé quand ?" avec 50 inscrits.
**#42 — Rapprochement bancaire CODA** — importer les extraits CODA et rapprocher communication ↔ Numero_Ref pour passer automatiquement les demandes en Payee avec la date réelle d'exécution. Supprime la confirmation manuelle de fin de mois et alimente #40. La colonne "Encodé" de l'export (pointage manuel) est l'intérim.
**#43 — Reporting : délais de traitement** — depuis Historique_Statuts : temps moyen par étape (soumission→approbation→vérification→encodage→signature→paiement), tendance dans le temps. Indicateur de santé du processus.
**#44 — Reporting : contrôle de cohérence virements ↔ statuts** — panneau comparant les références des fichiers archivés (Virements_Collectifs #32) aux statuts réels des demandes : détecte immédiatement un lot partiel (incident Daniel 2/7) ou une demande payée hors fichier. Extension de l'onglet 🏦 Virements.
**#45 — Reporting : vue budget annuel** — total défrayé vs enveloppe ASBL, projection fin d'année sur la tendance. Pour le CA. Rejoint #38 (volumétrie).
**#46 — UX mobile de la soumission** — vérifier/adapter le rendu téléphone du formulaire de demande (encodage en fin de garde).
**#39 — Vérif planning fonctionnelle sur Azure** — l'onglet Vérif planning du reporting importe `graph_client` depuis le dossier local `defraiement-functions` (Mac mini uniquement) → IMPORT_ERROR sur Azure. Fix : appeler l'endpoint API du backend prod (auth via `ADMIN_PLANNING_KEY` déjà présent dans les settings) au lieu de l'import local. Pré-requis fait le 3/7 : `SHAREPOINT_HR_SITE_ID` passé en app setting Azure pour charger la liste des membres (commit `78cfbc7`).
**#38 — Analyse volumétrie données** (~mi-juillet 2026, quinzaine après le 3/7) — analyser les fichiers/listes de données (Demandes, Lignes, Historique_Statuts, Virements_Collectifs...) pour extrapoler la croissance en records par mois puis par an, et décider du traitement de l'historique + stratégie d'archivage éventuelle.
**#37 — 401 "Token expiré" en cours de session** (vu par JP 3/7 en signant 14 demandes) — `api.ts` utilise l'idToken comme Bearer, mais `acquireTokenSilent` le sert depuis le cache en jugeant la fraîcheur sur l'access token → idToken expiré envoyé sans erreur après ~1h de session. Fix : dans `apiFetch`, sur 401 → retry une fois avec `acquireTokenSilent({ forceRefresh: true })`, sinon `loginRedirect` (conserver le domain_hint #14). Impact : aucune transition perdue (le backend rejette la requête entière avant traitement), juste une UX cassée.

## 📝 Note incident virement collectif 2-3/7

**Ce qui s'est passé** : Daniel a sélectionné les 21 demandes "À encoder" et déclenché le bulk Encoder (fichier `Virement-collectif-20260702-1203.xlsx`, 1 760 €). L'Excel a été généré, mais la transition batch `VerifieeAdmin → EncodeeBanque` n'a réussi que pour 3 demandes (148, 149, 151) — les 18 suivantes ont échoué, très probablement throttling Graph (pas de retry 429, cf. #33). Résultat : fichier bancaire de 21 lignes vs 3 demandes "À signer", puis mélange avec 10 nouvelles demandes approuvées ensuite (28 "À encoder").

**Correction** : JP a ré-encodé manuellement les 18 demandes concernées (liste = fichier de Daniel moins 148/149/151). L'Excel de 18 lignes regénéré au passage NE DOIT PAS être importé en banque — le fichier original de Daniel (21 lignes) reste la seule référence bancaire.

**Leçons** → tickets #32 à #36. Invariant à garantir : ce qui est "À signer" chez le trésorier = exactement le contenu d'un fichier bancaire existant et archivé.

**Changement connexe (en staging, pas encore en prod)** : format de l'export modifié — colonne Référence supprimée, Communication = référence brute (`D-XXXXXXXX-XXXXXX` sans préfixe "Defraiement"). Commit `b7a1265` branche `staging` de defraiement-functions. Reste : push (credentials locaux), deploy staging, test, merge main + prod.

## 📞 En cas de bug user

**"J'ai un 401 sur le reporting"** :
1. Vérifier qu'il est bien dans Enterprise Applications > defraiement-reporting-auth > Utilisateurs et groupes
2. Vérifier qu'il utilise son compte `@acsrs.be`
3. Tester en navigation privée (cookies MS parfois cassés)

**"Le reporting montre pas les bonnes données"** :
1. Cliquer 🔄 Rafraîchir les données dans la sidebar
2. Si persistant : `az webapp restart -g rg-defraiment -n app-defraiement-reporting`

**"Un membre a un tarif incorrect en Nuit WE"** (à vérifier vendredi 3/7 pour la 1ère fois) :
- Vérifier la date de prestation (weekday ∈ {4=Ven, 5=Sam, 6=Dim} → doit être 150€)
- Vérifier que le tarif Nuit_WE existe encore en prod (id=25 AMU + id=27 ATNUP)
- Vérifier que le backend prod a bien le code Nuit_WE (`az webapp log deployment list -g rg-defraiment -n fn-defraiement-auth-acsrs`)

---

---

## 📝 Note technique #31 — Refonte flow login (pour reprise ultérieure)

### Constat en test
Login cold start (cache MSAL vidé + pas de cookie SSO M365) impose **6 écrans** à un compte @acsrs.be :
1. Landing RACS (choix de compte)
2. Écran jaune "Attention" (instructions CIAM)
3. Page CIAM `racsrs.ciamlogin.com` (form vide + bouton rond en bas)
4. Microsoft login (email + password)
5. Face/PIN/security key (MFA)
6. Stay signed in? Yes/No

### Écrans éliminables
- **2 et 3** : le détour CIAM n'a pas d'utilité fonctionnelle pour un compte pro. Court-circuit possible en pointant directement vers `login.microsoftonline.com/acsrs.be`.
- **6** : désactivable via Entra Admin → Company Branding → "Show option to remain signed in" = No.

### Écrans NON éliminables (Microsoft impose)
- 4 (password) : première fois obligatoire
- 5 (MFA) : politique Conditional Access du tenant acsrs.be

### Plan technique
**Backend (`auth.py`)** — accepter 2 issuers selon claim `tid` du JWT :
- CIAM : `https://02a3f9fb-047c-4d18-b1ca-5064f6437837.ciamlogin.com/.../v2.0`
- acsrs.be : `https://sts.windows.net/2387572f-6647-4543-911e-dcbaf7fc0a07/`
- 2 JWKS clients, sélection selon `tid`

**Frontend** :
- Bouton "J'ai un compte @acsrs.be" → `loginRedirect({ authority: "https://login.microsoftonline.com/acsrs.be", ... })` (skip CIAM totalement)
- Supprimer l'écran d'instructions jaune (plus nécessaire)
- authConfig : garder CIAM comme authority par défaut pour comptes perso

**Config Entra** :
- Company Branding tenant acsrs.be : désactiver "Show option to remain signed in"
- Vérifier que l'app defraiement (clientId `c8eccbdf-...`) est accessible depuis les 2 tenants (multi-tenant ou double registration)

### Edge case documenté
Erreur AADSTS90072 vue en test : `j.coel@acsrs.be` identifié comme identity provider `live.com` (Microsoft consumer) ne peut pas accéder au tenant acsrs. Cause : l'user avait un ancien MSA (Microsoft Account personnel) sur cette adresse. Skip CIAM devrait éviter cette confusion en allant directement vers le tenant acsrs.be.

### Risque et estimation
Touche `auth.py` qui protège toutes les routes API → à faire en staging strict + tests exhaustifs avant merge prod. ~1-2h code + 30-60min tests. Gain : 6 → 3 écrans en cold start pour comptes @acsrs.be.

---

*Dernière mise à jour : 2 juillet 2026 après-midi (post-livraison #14 et #30 en prod)*
