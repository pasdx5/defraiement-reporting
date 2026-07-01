"""RACS Défraiement — Reporting administratif.

Lance avec :
    .venv/bin/streamlit run app.py

Ouvre automatiquement http://localhost:8501

Filtre par défaut : statut "Payées" = SigneeVirement + Payee (2 statuts finaux).
Granularité temporelle : semaine / mois / année civile.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from data import (
    load_demandes_all,
    lignes_des_demandes,
    load_membres_actifs,
    check_planning_for_member,
    STATUTS_PAYE,
    STATUTS_EN_COURS,
    STATUTS_TOUS,
)


# ══════════════════════════════════════════════════════════════════════
# Config page
# ══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="RACS Défraiement — Reporting",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; }
    [data-testid="stMetricValue"] { font-size: 2rem; }
    h1 { font-family: Georgia, serif; color: #111827; }
    h1 span.accent { color: #dc2626; }
    </style>
""", unsafe_allow_html=True)

st.markdown(
    "<h1>📊 RACS <span class='accent'>Défraiement</span> — Reporting</h1>",
    unsafe_allow_html=True,
)
# Caption mis à jour dynamiquement plus bas en fonction du filtre statut
caption_placeholder = st.empty()


# ══════════════════════════════════════════════════════════════════════
# Sidebar — filtres globaux
# ══════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.header("🔍 Filtres")

    # ── Sélecteur de statut (#A) ────────────────────────────────────────
    # Permet de voir au-delà des seules demandes payées pendant le pilote
    # (où aucune signature de virement n'a encore été apposée).
    statut_choice = st.selectbox(
        "Statut des demandes",
        options=[
            "💰 Payées uniquement",
            "⏳ En cours (pas encore payées)",
            "📦 Toutes (payées + en cours)",
        ],
        index=0,
        help=(
            "Payées = virement signé par la Trésorière OU paiement confirmé "
            "par extrait bancaire (statuts SigneeVirement + Payee). "
            "En cours = toute demande encore dans le workflow. "
            "Toutes = la somme des deux."
        ),
    )

    # Mapping vers les statuts SP correspondants
    if statut_choice.startswith("💰"):
        statuts_actifs = STATUTS_PAYE
        statut_label   = "payées"
        date_label     = "date de paiement"
    elif statut_choice.startswith("⏳"):
        statuts_actifs = STATUTS_EN_COURS
        statut_label   = "en cours dans le workflow"
        date_label     = "date de soumission"
    else:
        statuts_actifs = STATUTS_TOUS
        statut_label   = "tous statuts confondus"
        date_label     = "date de paiement (ou soumission si pas encore payée)"

    st.divider()

    granularite = st.radio(
        "Granularité temporelle",
        options=["Mois", "Semaine", "Année", "Période personnalisée"],
        index=0,
    )

    today = date.today()

    if granularite == "Semaine":
        annee = st.selectbox("Année", list(range(today.year, today.year - 5, -1)), index=0)
        weeks = list(range(1, 53 + 1))
        wk = st.selectbox("Semaine ISO", weeks, index=today.isocalendar().week - 1)
        d_start = datetime.strptime(f"{annee}-W{wk:02d}-1", "%G-W%V-%u").date()
        d_end   = d_start + timedelta(days=6)
    elif granularite == "Mois":
        annee = st.selectbox("Année", list(range(today.year, today.year - 5, -1)), index=0)
        mois  = st.selectbox(
            "Mois",
            options=list(range(1, 13)),
            format_func=lambda m: ["Janvier","Février","Mars","Avril","Mai","Juin",
                                   "Juillet","Août","Septembre","Octobre","Novembre","Décembre"][m-1],
            index=today.month - 1,
        )
        d_start = date(annee, mois, 1)
        if mois == 12:
            d_end = date(annee, 12, 31)
        else:
            d_end = date(annee, mois + 1, 1) - timedelta(days=1)
    elif granularite == "Année":
        annee = st.selectbox("Année", list(range(today.year, today.year - 5, -1)), index=0)
        d_start = date(annee, 1, 1)
        d_end   = date(annee, 12, 31)
    else:
        d_start = st.date_input("Du", value=date(today.year, 1, 1))
        d_end   = st.date_input("Au", value=today)

    st.divider()
    st.markdown(f"**📅 Période sélectionnée :**\n\n{d_start.strftime('%d %b %Y')} → {d_end.strftime('%d %b %Y')}")
    st.divider()

    if st.button("🔄 Rafraîchir les données", width="stretch"):
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════
# Chargement + filtrage
# ══════════════════════════════════════════════════════════════════════

demandes_all_raw = load_demandes_all()

# Mise à jour de la caption sous le titre selon le choix de statut
caption_placeholder.caption(
    f"Statistiques sur les demandes **{statut_label}**. Filtre temporel sur la {date_label}."
)

if demandes_all_raw.empty:
    st.info("Aucune demande dans la base pour le moment.")
    st.stop()

# Filtre par statut
demandes_all = demandes_all_raw[demandes_all_raw["statut"].isin(statuts_actifs)].copy()

if demandes_all.empty:
    st.warning(f"Aucune demande {statut_label} dans la base pour le moment.")
    st.stop()

# Filtre période sur date_ref (paiement si dispo, sinon soumission)
mask = (
    (demandes_all["date_ref"] >= pd.Timestamp(d_start)) &
    (demandes_all["date_ref"] <= pd.Timestamp(d_end) + pd.Timedelta(days=1))
)
demandes = demandes_all.loc[mask].copy()

if demandes.empty:
    st.warning(f"Aucune demande {statut_label} sur la période {d_start} → {d_end}.")
    st.stop()


# ══════════════════════════════════════════════════════════════════════
# Onglets
# ══════════════════════════════════════════════════════════════════════

tab_overview, tab_membre, tab_type, tab_planning, tab_exports = st.tabs([
    "📈 Vue d'ensemble",
    "👥 Par membre",
    "🚑 Par type",
    "🗓️ Vérif planning",
    "📥 Exports",
])


# ──────────────────────────────────────────────────────────────────────
# Vue d'ensemble
# ──────────────────────────────────────────────────────────────────────

with tab_overview:
    st.subheader("Vue d'ensemble")

    total_eur     = demandes["montant_total"].sum()
    nb_demandes   = len(demandes)
    nb_benevoles  = demandes["demandeur_email"].nunique()
    moyenne       = total_eur / nb_demandes if nb_demandes else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Total versé",       f"{total_eur:,.2f} €".replace(",", " "))
    c2.metric("📋 Nb demandes",       f"{nb_demandes}")
    c3.metric("👥 Bénévoles uniques", f"{nb_benevoles}")
    c4.metric("📊 Montant moyen",     f"{moyenne:,.2f} €".replace(",", " "))

    st.divider()

    st.markdown("### Évolution mensuelle (12 derniers mois)")
    today_dt  = pd.Timestamp(date.today())
    start_12m = today_dt - pd.DateOffset(months=12)
    last_12m  = demandes_all[demandes_all["date_ref"] >= start_12m]
    if not last_12m.empty:
        evo = last_12m.groupby("month").agg(
            montant=("montant_total", "sum"),
            nb=("id", "count"),
        ).reset_index().sort_values("month")
        fig = px.bar(evo, x="month", y="montant",
                     labels={"month": "Mois", "montant": "Total payé (€)"},
                     color_discrete_sequence=["#dc2626"])
        fig.update_layout(showlegend=False, height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Pas de données sur les 12 derniers mois.")

    st.markdown("### Répartition par type *(sur la période sélectionnée)*")
    rep = demandes.groupby("type").agg(
        montant=("montant_total", "sum"),
        nb=("id", "count"),
    ).reset_index()
    if not rep.empty:
        c1, c2 = st.columns([2, 3])
        with c1:
            fig = px.pie(rep, names="type", values="montant", hole=0.4,
                         color_discrete_sequence=px.colors.sequential.Reds_r)
            fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, width="stretch")
        with c2:
            rep_display = rep.rename(columns={
                "type": "Type", "montant": "Total (€)", "nb": "Nb demandes",
            })
            st.dataframe(rep_display, hide_index=True, width="stretch")


# ──────────────────────────────────────────────────────────────────────
# Par membre
# ──────────────────────────────────────────────────────────────────────

with tab_membre:
    st.subheader("Statistiques par membre")

    par_membre = demandes.groupby(["demandeur_email", "demandeur_label"]).agg(
        total=("montant_total", "sum"),
        nb=("id", "count"),
    ).reset_index().sort_values("total", ascending=False)

    par_membre = par_membre.rename(columns={
        "demandeur_label": "Bénévole",
        "demandeur_email": "Email",
        "total":           "Total reçu (€)",
        "nb":              "Nb demandes",
    })

    c1, c2, c3 = st.columns(3)
    c1.metric("Bénévoles payés", len(par_membre))
    c2.metric("Top bénéficiaire",
              f"{par_membre.iloc[0]['Total reçu (€)']:.0f} €" if len(par_membre) else "—")
    c3.metric("Moyenne par bénévole",
              f"{par_membre['Total reçu (€)'].mean():,.0f} €".replace(",", " ") if len(par_membre) else "—")

    st.markdown("### Top 10 des bénévoles défrayés sur la période")
    top10 = par_membre.head(10).iloc[::-1]
    if not top10.empty:
        fig = px.bar(top10, x="Total reçu (€)", y="Bénévole", orientation="h",
                     color_discrete_sequence=["#dc2626"])
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
        st.plotly_chart(fig, width="stretch")

    st.markdown("### Détail complet")
    search = st.text_input("🔍 Rechercher un bénévole ou un email", "")
    df_show = par_membre.copy()
    if search:
        m = df_show["Bénévole"].str.contains(search, case=False, na=False) | \
            df_show["Email"].str.contains(search, case=False, na=False)
        df_show = df_show[m]
    st.dataframe(df_show, hide_index=True, width="stretch",
                 column_config={
                     "Total reçu (€)": st.column_config.NumberColumn(format="%.2f €"),
                 })


# ──────────────────────────────────────────────────────────────────────
# Par type
# ──────────────────────────────────────────────────────────────────────

with tab_type:
    st.subheader("Statistiques par type de prestation")

    par_type = demandes.groupby("type").agg(
        total=("montant_total", "sum"),
        nb=("id", "count"),
        nb_benevoles=("demandeur_email", "nunique"),
    ).reset_index().sort_values("total", ascending=False)
    par_type = par_type.rename(columns={
        "type":         "Type",
        "total":        "Total (€)",
        "nb":           "Nb demandes",
        "nb_benevoles": "Nb bénévoles uniques",
    })

    st.dataframe(par_type, hide_index=True, width="stretch",
                 column_config={
                     "Total (€)": st.column_config.NumberColumn(format="%.2f €"),
                 })

    st.markdown("### Détail par service (AMU / ATNUP / Cours / Préventif…)")
    try:
        # On ne passe QUE les demandes filtrées (statut + période) → les lignes
        # héritent automatiquement du même filtre.
        lignes = lignes_des_demandes(demandes_all)
    except Exception as e:
        st.warning(f"Lignes indisponibles : {e}")
        lignes = pd.DataFrame()

    if not lignes.empty:
        mask_l = (
            (lignes["date_ref"] >= pd.Timestamp(d_start)) &
            (lignes["date_ref"] <= pd.Timestamp(d_end) + pd.Timedelta(days=1))
        )
        lignes_period = lignes.loc[mask_l]
        if not lignes_period.empty:
            par_service = lignes_period.groupby(["type_service", "periode"]).agg(
                total=("montant", "sum"),
                nb=("id", "count"),
            ).reset_index().rename(columns={
                "type_service": "Service",
                "periode":      "Période (J/N)",
                "total":        "Total (€)",
                "nb":           "Nb lignes",
            }).sort_values(["Service", "Période (J/N)"])
            st.dataframe(par_service, hide_index=True, width="stretch",
                         column_config={
                             "Total (€)": st.column_config.NumberColumn(format="%.2f €"),
                         })
        else:
            st.info("Pas de lignes sur la période.")


# ──────────────────────────────────────────────────────────────────────
# Vérif planning
# ──────────────────────────────────────────────────────────────────────

with tab_planning:
    st.subheader("Vérification de présence dans le planning trimestriel")
    st.caption(
        "Sélectionne un membre + une date + une période → vérifie sa présence "
        "dans le planning Excel (GestionPlannings/2026.xlsm)."
    )

    membres_df = load_membres_actifs()
    if membres_df.empty:
        st.warning("Impossible de charger la liste des membres actifs depuis SP.")
    else:
        col_a, col_b, col_c = st.columns([3, 2, 2])

        with col_a:
            # Selectbox avec recherche intégrée (Streamlit la fournit nativement)
            options = membres_df["label"].tolist()
            choix = st.selectbox(
                "👤 Membre",
                options=[""] + options,
                index=0,
                help="Tape les premières lettres du nom ou prénom pour filtrer.",
            )

        with col_b:
            date_check = st.date_input(
                "📅 Date",
                value=date.today(),
                help="Date de la prestation à vérifier.",
            )

        with col_c:
            periode_check = st.radio(
                "🌓 Période",
                options=["journee", "nuit"],
                format_func=lambda x: "☀️ Journée" if x == "journee" else "🌙 Nuit",
                horizontal=True,
            )

        if choix:
            membre = membres_df[membres_df["label"] == choix].iloc[0]
            nom = membre["nom"]
            prenom = membre["prenom"]

            if st.button("🔍 Vérifier le planning", type="primary", width="stretch"):
                with st.spinner(f"Vérification dans le planning pour {prenom} {nom}…"):
                    result = check_planning_for_member(
                        nom=nom,
                        prenom=prenom,
                        date_iso=date_check.isoformat(),
                        periode=periode_check,
                    )

                status = result.get("status", "INCONNU")
                code = result.get("code", "")
                label = result.get("label", "")
                periode_lbl = "Journée" if periode_check == "journee" else "Nuit"

                st.markdown("---")
                st.markdown(f"### Résultat pour **{prenom} {nom}** — {date_check.strftime('%d %b %Y')} ({periode_lbl})")

                if status == "OK":
                    st.success(
                        f"✅ **{prenom} {nom}** est bien planifié(e) le **{date_check.strftime('%d %b %Y')}** en **{periode_lbl}**.\n\n"
                        f"Code Excel : `{code}` — {label}"
                    )
                elif status == "NON_PLANIFIE":
                    st.warning(
                        f"⚠️ **{prenom} {nom}** N'EST PAS planifié(e) le **{date_check.strftime('%d %b %Y')}** en **{periode_lbl}**.\n\n"
                        f"Code Excel : `{code or '(vide)'}` — {label}"
                    )
                elif status == "MAUVAISE_PERIODE":
                    st.warning(
                        f"⚠️ **{prenom} {nom}** est planifié(e) ce jour-là **mais à l'autre période**.\n\n"
                        f"Code Excel : `{code}` — {label}"
                    )
                elif status == "MEMBRE_INTROUVABLE":
                    st.error(
                        f"❓ **{prenom} {nom}** n'est pas trouvé dans le planning trimestriel.\n\n"
                        f"Vérifie l'orthographe ou ce membre n'a peut-être pas de poste régulier."
                    )
                elif status == "EXCEL_INDISPONIBLE":
                    st.error(
                        f"❌ Impossible de lire le fichier Excel du planning.\n\n"
                        f"Vérifie que le fichier `2026.xlsm` est accessible sur GestionPlannings."
                    )
                elif status == "IMPORT_ERROR":
                    st.error(
                        f"❌ Module backend introuvable : {label}\n\n"
                        f"Le projet `defraiement-functions` doit être dans `~/Documents/` à côté de `defraiement-reporting`."
                    )
                else:
                    st.error(f"❌ Statut inconnu : `{status}` — {label}")

        st.markdown("---")
        st.markdown("### 📅 Accès direct au planning")
        st.markdown(
            "[Ouvrir le fichier planning Excel sur SharePoint](https://acsrs1310.sharepoint.com/sites/GestionPlannings/Shared%20Documents/Forms/AllItems.aspx)"
        )


# ──────────────────────────────────────────────────────────────────────
# Exports
# ──────────────────────────────────────────────────────────────────────

with tab_exports:
    st.subheader("Exports")
    st.markdown("Génère un fichier Excel avec plusieurs feuilles pour archive ou rapport.")

    def to_excel_bytes() -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            par_type_export = demandes.groupby("type").agg(
                Total_EUR=("montant_total", "sum"),
                Nb_Demandes=("id", "count"),
                Nb_Benevoles=("demandeur_email", "nunique"),
            ).reset_index().rename(columns={"type": "Type"})
            par_type_export.to_excel(writer, sheet_name="Par type", index=False)

            par_membre_export = demandes.groupby(["demandeur_label", "demandeur_email"]).agg(
                Total_EUR=("montant_total", "sum"),
                Nb_Demandes=("id", "count"),
            ).reset_index().rename(columns={
                "demandeur_label": "Bénévole",
                "demandeur_email": "Email",
            }).sort_values("Total_EUR", ascending=False)
            par_membre_export.to_excel(writer, sheet_name="Par membre", index=False)

            brut = demandes[[
                "numero_ref","type","statut",
                "date_soumission","date_paiement","montant_total",
                "demandeur_prenom","demandeur_nom","demandeur_email",
            ]].copy()
            brut.columns = ["N° Réf", "Type", "Statut",
                            "Date soumission", "Date paiement", "Montant (€)",
                            "Prénom", "Nom", "Email"]
            brut.sort_values(["Date soumission"]).to_excel(
                writer, sheet_name="Demandes brutes", index=False
            )
        buf.seek(0)
        return buf.getvalue()

    excel_bytes = to_excel_bytes()
    fname = f"reporting_RACS_defraiement_{d_start}_{d_end}.xlsx"

    st.download_button(
        label="📥 Télécharger l'export Excel",
        data=excel_bytes,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )

    st.divider()
    st.markdown("### Export CSV brut")
    csv_bytes = demandes.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Télécharger CSV brut",
        data=csv_bytes,
        file_name=f"demandes_brutes_{d_start}_{d_end}.csv",
        mime="text/csv",
        width="stretch",
    )


st.markdown(
    "<hr style='margin-top:3rem; opacity:0.3'>"
    "<p style='text-align:center; color:#9ca3af; font-size:0.8rem'>"
    "RACS Défraiement — Reporting · v0.1 · "
    "<a href='https://defraiement.acsrs.be' style='color:#dc2626'>defraiement.acsrs.be</a>"
    "</p>",
    unsafe_allow_html=True,
)
