"""Couche d'accès aux données SharePoint pour le reporting.

Réutilise les credentials du projet defraiement-functions voisin (le fichier
local.settings.json est lu depuis le dossier sibling pour éviter de dupliquer
les secrets).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import msal
import pandas as pd
import streamlit as st


# ──────────────────────────────────────────────────────────────────────
# 1. Credentials
# ──────────────────────────────────────────────────────────────────────

def _load_credentials() -> dict:
    """Charge les credentials Graph.

    Priorité :
    1. **Variables d'environnement** (Azure App Service, prod)
       — Les 3 GRAPH_* sont posées via App Service > Configuration.
    2. **`local.settings.json`** (dev local sur Mac Mini)
       — Fallback pour rester compatible avec le workflow existant.

    Cet ordre garantit qu'en prod on ne lit JAMAIS un fichier de secrets
    même s'il traînait dans le container par erreur.
    """
    import os
    # (1) Prod / Azure App Service — env vars
    env_id     = os.environ.get("GRAPH_CLIENT_ID", "").strip()
    env_secret = os.environ.get("GRAPH_CLIENT_SECRET", "").strip()
    env_tenant = os.environ.get("GRAPH_TENANT_ID", "").strip()
    if env_id and env_secret and env_tenant:
        creds = {
            "GRAPH_CLIENT_ID":     env_id,
            "GRAPH_CLIENT_SECRET": env_secret,
            "GRAPH_TENANT_ID":     env_tenant,
        }
        # Clés optionnelles (site RH pour la liste Membres, overrides…) —
        # sans elles, l'onglet Vérif planning ne peut pas charger les membres.
        for opt in ("SHAREPOINT_HR_SITE_ID", "SHAREPOINT_MEMBRES_LIST",
                    "SHAREPOINT_FINANCES_SITE_ID"):
            v = os.environ.get(opt, "").strip()
            if v:
                creds[opt] = v
        return creds

    # (2) Dev local — local.settings.json de defraiement-functions
    candidates = [
        Path(__file__).parent.parent / "defraiement-functions" / "local.settings.json",
        Path.home() / "Documents" / "defraiement-functions" / "local.settings.json",
        Path(__file__).parent / "local.settings.json",
    ]
    for c in candidates:
        if c.exists():
            return json.loads(c.read_text())["Values"]
    raise FileNotFoundError(
        "Credentials Graph introuvables :\n"
        "  - env vars GRAPH_CLIENT_ID/SECRET/TENANT_ID absentes\n"
        "  - local.settings.json non trouvé dans :\n    - "
        + "\n    - ".join(str(c) for c in candidates)
    )


_CREDS: dict = {}

def _get_creds() -> dict:
    global _CREDS
    if not _CREDS:
        _CREDS = _load_credentials()
    return _CREDS


# ──────────────────────────────────────────────────────────────────────
# 2. Token Graph
# ──────────────────────────────────────────────────────────────────────

@st.cache_resource
def _msal_app() -> msal.ConfidentialClientApplication:
    cfg = _get_creds()
    return msal.ConfidentialClientApplication(
        cfg["GRAPH_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{cfg['GRAPH_TENANT_ID']}",
        client_credential=cfg["GRAPH_CLIENT_SECRET"],
    )


def _get_token() -> str:
    tok = _msal_app().acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in tok:
        raise RuntimeError(f"Auth Graph échouée : {tok.get('error_description')}")
    return tok["access_token"]


# ──────────────────────────────────────────────────────────────────────
# 3. Lecture des listes SP
# ──────────────────────────────────────────────────────────────────────

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Statuts du workflow RACS (mis à jour #20 — juillet 2026) :
#   Soumise → ApprouveeChef → VerifieeAdmin → EncodeeBanque → SigneeVirement → Payee
#
# - "SigneeVirement" : virement signé par la Trésorière (l'argent va partir)
# - "Payee"          : paiement confirmé par extrait bancaire (état final)
#
# Pour le reporting "demandes payées", on inclut LES DEUX statuts :
#   - Les demandes récentes en Payee (workflow bouclé post-#20)
#   - Les demandes historiques en SigneeVirement (avant l'étape confirmer_paiement)
STATUTS_PAYE     = ("SigneeVirement", "Payee")
STATUTS_EN_COURS = ("Soumise", "ApprouveeChef", "VerifieeAdmin", "EncodeeBanque")
STATUTS_TOUS     = STATUTS_PAYE + STATUTS_EN_COURS

# Rétro-compat — pointe désormais sur le statut final "Payee"
STATUT_PAYE = "Payee"


def _fetch_list(site_id: str, list_name: str, select: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly",
    }
    url = (
        f"{GRAPH_BASE}/sites/{site_id}/lists/{list_name}/items"
        f"?$expand=fields($select={select})&$top=500"
    )
    items: list[dict] = []
    while url:
        r = httpx.get(url, headers=headers, timeout=60.0)
        r.raise_for_status()
        data = r.json()
        items.extend(data.get("value") or [])
        url = data.get("@odata.nextLink")
    return items


def _site_id_finances() -> str:
    cfg = _get_creds()
    if cfg.get("SHAREPOINT_FINANCES_SITE_ID"):
        return cfg["SHAREPOINT_FINANCES_SITE_ID"]
    headers = {"Authorization": f"Bearer {_get_token()}"}
    r = httpx.get(
        f"{GRAPH_BASE}/sites/acsrs1310.sharepoint.com:/sites/Finances",
        headers=headers, timeout=15.0,
    )
    r.raise_for_status()
    return r.json()["id"]


# ──────────────────────────────────────────────────────────────────────
# 4. Demandes payées
# ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Chargement des demandes…")
def load_demandes_all() -> pd.DataFrame:
    """Charge TOUTES les demandes (tous statuts hors refusées).

    Pour rester rapide et flexible, on lit tout une fois, puis le filtrage
    par statut + période est fait côté Streamlit (en mémoire pandas).

    Colonne `date_ref` = date_signature si la demande est Payée (a une signature),
    sinon date_soumission. C'est la date sur laquelle on filtre côté UI selon la
    granularité (mois / semaine / année / personnalisée).
    """
    site = _site_id_finances()
    select = (
        "Title,Numero_Ref,Typedefraiement,Statut,Date_Soumission,"
        "Montant_Total_Propose,Montant_Total_Final,Demandeur_Email,"
        "Demandeur_Nom,Demandeur_Prenom,Date_Signature"
    )
    raw = _fetch_list(site, "Demandes_Defraiement", select)

    rows = []
    for item in raw:
        f = item.get("fields") or {}
        statut = f.get("Statut") or ""
        # Garde les statuts utiles (workflow + payée). On exclut Refusee*
        # qui apparaîtrait comme bruit dans les stats financières.
        if statut not in STATUTS_TOUS:
            continue
        rows.append({
            "id":               int(item["id"]),
            "numero_ref":       f.get("Numero_Ref") or "",
            "type":             f.get("Typedefraiement") or "",
            "statut":           statut,
            "date_soumission":  f.get("Date_Soumission") or None,
            "date_signature":   f.get("Date_Signature") or None,
            "montant_total":    float(
                f.get("Montant_Total_Final") or f.get("Montant_Total_Propose") or 0
            ),
            "demandeur_email":  (f.get("Demandeur_Email") or "").strip().lower(),
            "demandeur_nom":    f.get("Demandeur_Nom") or "",
            "demandeur_prenom": f.get("Demandeur_Prenom") or "",
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # SharePoint renvoie les dates en ISO 8601 avec suffixe Z (UTC).
    # On force utc=True pour parser, puis tz_localize(None) pour avoir un
    # dtype datetime64[ns] tz-naive uniforme. Sans ça, le mix tz-aware + NaT
    # casse le fillna et plante les .dt plus loin.
    def _parse_dt(series):
        s = pd.to_datetime(series, errors="coerce", utc=True)
        # tz_localize(None) sur un Series déjà tz-aware enlève le tz.
        return s.dt.tz_localize(None) if hasattr(s, "dt") else s

    df["date_paiement"]    = _parse_dt(df["date_signature"])
    df["date_soumission"]  = _parse_dt(df["date_soumission"])
    df["demandeur_label"]  = (df["demandeur_prenom"] + " " + df["demandeur_nom"]).str.strip()

    # date_ref = paiement si dispo, sinon soumission.
    df["date_ref"] = df["date_paiement"].fillna(df["date_soumission"])

    df["year"]  = df["date_ref"].dt.year
    df["month"] = df["date_ref"].dt.to_period("M").astype(str)
    df["week"]  = df["date_ref"].dt.to_period("W").astype(str)
    return df


# Rétro-compat : alias qui filtre sur les payées uniquement.
def load_demandes_payees() -> pd.DataFrame:
    df = load_demandes_all()
    if df.empty:
        return df
    return df[df["statut"].isin(STATUTS_PAYE)].copy()


@st.cache_data(ttl=300, show_spinner="Chargement des lignes de défraiement…")
def load_lignes() -> pd.DataFrame:
    site = _site_id_finances()
    select = (
        "Title,ID_Demande,Type_Service,Periode,Qualification,"
        "Date_Prestation,Quantite,Montant_Propose,Details"
    )
    raw = _fetch_list(site, "Lignes_Defraiement", select)
    rows = []
    for item in raw:
        f = item.get("fields") or {}
        try:
            id_demande = int(f.get("ID_Demande") or 0)
        except (ValueError, TypeError):
            id_demande = 0
        rows.append({
            "id":             int(item["id"]),
            "id_demande":     id_demande,
            "type_service":   f.get("Type_Service") or "",
            "periode":        f.get("Periode") or "",
            "qualification":  f.get("Qualification") or "",
            "date_prestation": f.get("Date_Prestation") or None,
            "quantite":       int(f.get("Quantite") or 1),
            "montant":        float(f.get("Montant_Propose") or 0),
            "details":        f.get("Details") or "",
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date_prestation"] = pd.to_datetime(df["date_prestation"], errors="coerce")
    return df


def lignes_des_demandes(demandes_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Joint les lignes au DataFrame de demandes passé en paramètre.

    Si demandes_df est None, utilise load_demandes_payees() (rétro-compat).
    Si demandes_df est fourni, c'est lui qui détermine quelles demandes on
    inclut (filtré par statut+période côté Streamlit en amont).
    """
    if demandes_df is None:
        demandes_df = load_demandes_payees()
    lignes = load_lignes()
    if demandes_df.empty or lignes.empty:
        return pd.DataFrame()
    # NB : on renomme "id" côté demandes AVANT le merge. L'ancien code utilisait
    # suffixes=("", "_demande") → le "id" de droite devenait "id_demande", en
    # collision avec la colonne id_demande existante des lignes (interdit par
    # les pandas récents).
    dem = demandes_df[[
        "id", "date_ref", "date_paiement", "demandeur_label", "demandeur_email",
        "statut", "type",
    ]].rename(columns={"id": "demande_sp_id", "type": "type_demande"})
    df = lignes.merge(
        dem, left_on="id_demande", right_on="demande_sp_id", how="inner",
    ).drop(columns=["demande_sp_id"])
    # Sécurise le type datetime avant les opérations .dt
    df["date_ref"] = pd.to_datetime(df["date_ref"], errors="coerce")
    df["year"]  = df["date_ref"].dt.year
    df["month"] = df["date_ref"].dt.to_period("M").astype(str)
    df["week"]  = df["date_ref"].dt.to_period("W").astype(str)
    return df


# Rétro-compat
def lignes_des_demandes_payees() -> pd.DataFrame:
    return lignes_des_demandes(load_demandes_payees())


# ──────────────────────────────────────────────────────────────────────
# 4bis. Virements collectifs archivés (#32)
# ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Chargement des virements collectifs…")
def load_virements_collectifs() -> pd.DataFrame:
    """Fichiers Excel archivés dans la bibliothèque Virements_Collectifs (#32).

    Colonnes : fichier, url (webUrl SharePoint), genere_le, acteur,
    nb_demandes, montant_total, references (une réf par ligne).
    Retourne un DataFrame vide si la bibliothèque n'existe pas / est vide.
    """
    try:
        site = _site_id_finances()
        headers = {"Authorization": f"Bearer {_get_token()}"}
        url = (
            f"{GRAPH_BASE}/sites/{site}/lists/Virements_Collectifs/items"
            f"?$expand=fields,driveItem&$top=500"
        )
        items: list[dict] = []
        while url:
            r = httpx.get(url, headers=headers, timeout=30.0)
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("value") or [])
            url = data.get("@odata.nextLink")
    except Exception:
        return pd.DataFrame()

    rows = []
    for it in items:
        f = it.get("fields") or {}
        d = it.get("driveItem") or {}
        if not d.get("file"):
            continue  # ignore dossiers éventuels
        rows.append({
            "fichier":       d.get("name") or "",
            "url":           d.get("webUrl") or "",
            "genere_le":     f.get("Created"),
            "acteur":        f.get("Acteur") or "",
            "nb_demandes":   int(f.get("Nb_Demandes") or 0),
            "montant_total": float(f.get("Montant_Total") or 0),
            "references":    f.get("References_Incluses") or "",
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        g = pd.to_datetime(df["genere_le"], errors="coerce", utc=True)
        df["genere_le"] = g.dt.tz_localize(None)
        df = df.sort_values("genere_le", ascending=False).reset_index(drop=True)
    return df


# ──────────────────────────────────────────────────────────────────────
# 5. Membres + Vérification planning
# ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner="Chargement des membres…")
def load_membres_actifs() -> pd.DataFrame:
    """Liste des membres actifs depuis SP Membres (site RH).

    Retourne un DataFrame avec colonnes : email, nom, prenom, label.
    """
    cfg = _get_creds()
    site_id   = cfg.get("SHAREPOINT_HR_SITE_ID")
    list_name = cfg.get("SHAREPOINT_MEMBRES_LIST") or "Membres"
    if not site_id:
        return pd.DataFrame()
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly",
    }
    select = "field_2,field_3,field_4,field_9,EmailPro"
    url = (
        f"{GRAPH_BASE}/sites/{site_id}/lists/{list_name}/items"
        f"?$expand=fields($select={select})&$top=500"
    )
    items: list[dict] = []
    while url:
        r = httpx.get(url, headers=headers, timeout=30.0)
        r.raise_for_status()
        data = r.json()
        items.extend(data.get("value") or [])
        url = data.get("@odata.nextLink")

    rows = []
    for it in items:
        f = it.get("fields") or {}
        if f.get("field_2") is False:  # Actif=Non → skip
            continue
        nom    = (f.get("field_3") or "").strip()
        prenom = (f.get("field_4") or "").strip()
        if not nom and not prenom:
            continue
        email_pro = (f.get("EmailPro") or "").strip()
        email_perso = (f.get("field_9") or "").strip()
        email = email_pro or email_perso
        rows.append({
            "nom":    nom,
            "prenom": prenom,
            "email":  email,
            "label":  f"{prenom} {nom}".strip(),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["nom", "prenom"]).reset_index(drop=True)
    return df


def check_planning_for_member(nom: str, prenom: str, date_iso: str, periode: str) -> dict:
    """Wrapper de check_planning_presence (depuis le projet defraiement-functions).

    Importation dynamique pour ne pas créer de dépendance dure entre les 2 projets.
    Si l'import échoue (fichier introuvable, dépendance manquante…), retourne un
    statut d'erreur clair plutôt que de planter Streamlit.
    """
    import sys
    from pathlib import Path

    # Ajoute defraiement-functions/ au path pour pouvoir importer graph_client
    candidates = [
        Path(__file__).parent.parent / "defraiement-functions",
        Path.home() / "Documents" / "defraiement-functions",
    ]
    for c in candidates:
        if c.exists() and str(c) not in sys.path:
            sys.path.insert(0, str(c))

    try:
        from graph_client import check_planning_presence  # type: ignore
    except Exception as e:
        return {
            "status": "IMPORT_ERROR",
            "code": "",
            "label": f"Module graph_client introuvable : {e}",
        }

    try:
        return check_planning_presence(nom, prenom, date_iso, periode)
    except Exception as e:
        return {
            "status": "EXCEPTION",
            "code": "",
            "label": f"Erreur lors du check : {e}",
        }
