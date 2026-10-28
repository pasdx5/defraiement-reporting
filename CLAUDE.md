# CLAUDE.md — defraiement-reporting (reporting RACS Défraiement)

Tableau de bord **Streamlit** pour l'administration et la trésorerie :
statistiques sur les défraiements (payés / en cours), par période, par membre,
par type, virements collectifs, vérification planning, exports Excel/CSV.

- **Prod** : https://app-defraiement-reporting.azurewebsites.net
  (Azure AD Easy Auth, accès limité à quelques personnes).
- Langue de l'UI, des commits et de la doc : **français**.

## Écosystème (3 dépôts)

| Dépôt | Rôle |
|---|---|
| `pasdx5/app-defraiements` | Frontend React des bénévoles / valideurs |
| `pasdx5/defraiement-functions` | Backend Python (Azure Functions) |
| `pasdx5/defraiement-reporting` (ici) | Reporting — lit SharePoint **directement** via Graph (lecture seule), sans passer par l'API |

`STATUS.md` (ici) est le document d'état global **de tout le projet** :
ressources Azure, staging, backlog. À lire pour le contexte, en gardant à
l'esprit qu'il peut être en retard sur le code.

## Fichiers

- `app.py` — toute l'UI : barre latérale (filtre statut, granularité
  Mois/Semaine/Année/Toutes/Période personnalisée), puis onglets
  Vue d'ensemble · Par membre · Par type · Virements · Vérif planning · Exports.
- `data.py` — accès Graph (MSAL + httpx), chargement et normalisation des
  listes SharePoint en DataFrames pandas (cache Streamlit).
- `.streamlit/config.toml` — thème.

## Logique de filtrage (à respecter)

- `STATUTS_PAYE = (SigneeVirement, Payee)`, `STATUTS_EN_COURS` = le reste du
  workflow ; `Refusee` exclu.
- `date_ref` = date de paiement si disponible, sinon date de soumission. Le
  filtre période est `d_start <= date_ref < d_end + 1 jour`.
- `demandes` = filtré statut + période ; `demandes_all_raw` = tout, sans
  filtre. Dans « Par membre », le détail d'un bénévole suit les filtres
  (statut, période, type) ; l'historique complet (replié) les ignore.
- Ne pas appeler `st.stop()` dans un onglet : cela coupe le rendu des
  onglets suivants.

## Lancer en local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Credentials : variables `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` /
`GRAPH_TENANT_ID` (prod), sinon `local.settings.json` du dépôt voisin
`defraiement-functions`. **Jamais de secret dans ce dépôt.**

## Tester sans SharePoint

`streamlit.testing.v1.AppTest` sur `app.py`, en remplaçant
`data.load_demandes_all`, `data.load_virements_collectifs` et
`data.load_membres_actifs` par des DataFrames fictifs (colonnes : `id`,
`numero_ref`, `type`, `statut`, `date_soumission`, `date_paiement`,
`date_ref`, `montant_total`, `demandeur_email`, `demandeur_label`, …).
Au minimum avant push : `python -m py_compile app.py data.py`.

## Déploiement

- **Automatique** : chaque push sur `main` déclenche
  `.github/workflows/deploy.yml` → App Service `app-defraiement-reporting`
  (secret GitHub `AZURE_WEBAPP_PUBLISH_PROFILE`). ~8 min (build Oryx côté
  Azure). Relance manuelle possible depuis l'onglet Actions.
- Pas de staging pour le reporting : travailler sur une branche, ouvrir une
  PR, fusionner dans `main` une fois validé.
- Détails Azure (Easy Auth, domaine, dépannage, zip deploy manuel) :
  `DEPLOY_AZURE.md`. En cas de 502/504 au déploiement :
  `az webapp stop` → déployer → `az webapp start`.
