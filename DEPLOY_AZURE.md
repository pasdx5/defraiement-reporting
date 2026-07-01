# Déploiement Azure App Service

Ce document décrit comment déployer le reporting Streamlit sur Azure pour
rendre l'outil accessible à toute l'équipe OA (Daniel & co) au lieu de
tourner uniquement en local sur le Mac Mini de JP.

## Architecture cible

```
User (Daniel, OA members)
   │
   ▼
reporting.acsrs.be   ─── CNAME ───▶  app-defraiement-reporting.azurewebsites.net
   │                                       │
   │  Azure AD Easy Auth (tenant ACSRS)     │
   ▼                                       ▼
Login MS @acsrs.be                    Streamlit (app.py)
                                           │
                                           ▼
                                       Graph API
                                           │
                                           ▼
                                      SharePoint lists
                                      (Demandes_Defraiement, etc.)
```

## Credentials

En prod, les 3 env vars ci-dessous sont posées dans **App Service > Configuration**
(pas de `local.settings.json` en prod). `data.py` a un fallback qui lit le fichier
local en dev.

- `GRAPH_CLIENT_ID`
- `GRAPH_CLIENT_SECRET` (⚠️ à stocker en Key Vault → référencer avec `@Microsoft.KeyVault(...)`)
- `GRAPH_TENANT_ID`

Ce sont les MÊMES credentials que la Function App `fn-defraiement-auth-acsrs`.
La app registration a déjà les permissions `Sites.ReadWrite.All` avec admin consent.

## Créer les ressources Azure

```bash
RG=rg-defraiment
LOC=westeurope
PLAN=asp-defraiement-reporting
APP=app-defraiement-reporting

# Nouveau plan Linux (nécessaire : la Function App est sur un plan Windows)
az appservice plan create -n $PLAN -g $RG --sku B1 --is-linux --location $LOC

# Web App Python 3.11
az webapp create -g $RG --plan $PLAN --name $APP --runtime "PYTHON:3.11"

# Startup Streamlit
az webapp config set -g $RG --name $APP --startup-file \
  "python -m streamlit run app.py --server.port=8000 --server.address=0.0.0.0 --server.enableCORS=false --server.enableXsrfProtection=false"

# Env vars Graph (idem que la Function App)
az webapp config appsettings set -g $RG --name $APP --settings \
  GRAPH_CLIENT_ID="XXX" \
  GRAPH_CLIENT_SECRET="XXX" \
  GRAPH_TENANT_ID="XXX" \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  WEBSITES_PORT=8000
```

## Auth Easy Auth (Azure AD)

1. Créer une **App Registration** dans le tenant ACSRS (portal.azure.com) :
   - Nom : `defraiement-reporting-auth`
   - Redirect URI : `https://app-defraiement-reporting.azurewebsites.net/.auth/login/aad/callback`
   - (plus tard : `https://reporting.acsrs.be/.auth/login/aad/callback`)

2. Activer Easy Auth sur la Web App :

```bash
az webapp auth update -g $RG -n $APP \
  --enabled true \
  --action LoginWithAzureActiveDirectory \
  --aad-tenant-id "$TENANT_ID_ACSRS" \
  --aad-client-id "$APP_REG_CLIENT_ID"
```

3. Whitelist les users autorisés dans l'App Registration :
   - Enterprise Applications > defraiement-reporting-auth > Users and groups
   - Ajouter : JP, Daniel, membres OA
   - Property "User assignment required" → Yes

## Custom domain reporting.acsrs.be

1. Chez le registrar : ajouter CNAME `reporting` → `app-defraiement-reporting.azurewebsites.net`
2. Ajouter le hostname dans App Service :

```bash
az webapp config hostname add -g $RG --webapp-name $APP --hostname reporting.acsrs.be
```

3. Certificat Azure managed (gratuit) :

```bash
az webapp config ssl create -g $RG --name $APP --hostname reporting.acsrs.be
az webapp config ssl bind -g $RG --name $APP --hostname reporting.acsrs.be \
  --certificate-thumbprint "<thumbprint retourné par create>" \
  --ssl-type SNI
```

## Deploy le code

Option A — Zip deploy manuel (première fois / dépannage) :

```bash
cd ~/Documents/defraiement-reporting
zip -r deploy.zip . -x "*.venv/*" "*__pycache__/*" "*.git/*" "*.DS_Store"
az webapp deploy -g $RG -n $APP --src-path deploy.zip --type zip
```

Option B — GitHub Actions (recommandé pour prod) : voir `.github/workflows/deploy.yml`
(à créer sur base du template `azure-static-web-apps` de app-defraiement).

## Debug

- Logs live : `az webapp log tail -g $RG -n $APP`
- SSH dans le container : `az webapp ssh -g $RG -n $APP`
- Restart : `az webapp restart -g $RG -n $APP`

## Budget

- App Service Plan B1 Linux = ~13€/mois (24/7)
- Facturable sur les crédits Azure Nonprofit si activés → 0€ out-of-pocket
