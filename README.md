# RACS Défraiement — Reporting administratif

Petite app **Streamlit** locale qui interroge les listes SharePoint
`Demandes_Defraiement` et `Lignes_Defraiement` pour produire des stats
financières sur les défraiements payés.

## Installation initiale (une seule fois)

```bash
cd ~/Documents/defraiement-reporting
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## Lancement

```bash
cd ~/Documents/defraiement-reporting
.venv/bin/streamlit run app.py
```

Streamlit ouvre `http://localhost:8501` dans ton navigateur.
Arrêt : `Ctrl+C` dans le terminal.

## Credentials

L'app réutilise `local.settings.json` du projet `defraiement-functions`
voisin — pas besoin de copier les secrets.

Chemins testés :
1. `~/Documents/defraiement-functions/local.settings.json`
2. `~/Documents/defraiement-reporting/local.settings.json` (fallback)

## Fonctionnalités v0.1

- Filtre sur statut **Payée** (Signée Virement) uniquement
- 4 granularités : Semaine ISO, Mois, Année civile, Période personnalisée
- 4 onglets :
  - **Vue d'ensemble** : KPIs + évolution 12 mois + camembert par type
  - **Par membre** : Top 10 + tableau triable + recherche
  - **Par type** : par type de demande + détail par service
  - **Exports** : Excel multi-feuilles + CSV brut

Cache 5 minutes côté Streamlit. Bouton 🔄 pour forcer un refresh.

## Stack

Python 3.10+ · Streamlit · Pandas · Plotly · MSAL + httpx · openpyxl
