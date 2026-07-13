# Deploy the ATS to Azure App Service (container) for UAT

The app is containerised so the Microsoft ODBC driver (needed for Azure SQL) is
baked in. Azure builds the image for you — **you do not need Docker installed**.

The web app connects to the **same `hr_recruitment` Azure SQL database**, so all
your existing candidates and the `admin` login are already there.

Names used below (change if you like): resource group `HRMS`, registry `hratsacr`,
web app `hr-ats` → URL `https://hr-ats.azurewebsites.net`.

---

## 0. One-time prep

- Use the **Azure Cloud Shell** (portal → the `>_` icon, choose **Bash**) so no
  local install is needed. `az` is already logged in there.
- Upload the project into Cloud Shell, or (simpler) run the build from your PC
  after installing the Azure CLI: https://aka.ms/installazurecli then `az login`.

Generate a production secret key (run locally, keep it safe — don't commit it):
```
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 1. Create a container registry and build the image
From the project folder (the one with the `Dockerfile`):
```bash
az group create -n HRMS -l centralindia          # (skip if HRMS already exists)
az acr create -n hratsacr -g HRMS --sku Basic --admin-enabled true
az acr build -r hratsacr -t ats:latest .          # Azure builds the image from your code
```

## 2. Create the App Service plan + web app (Linux container)
```bash
az appservice plan create -n hr-ats-plan -g HRMS --is-linux --sku B1
az webapp create -g HRMS -p hr-ats-plan -n hr-ats \
  --deployment-container-image-name hratsacr.azurecr.io/ats:latest
```
(`B1` ≈ the cheapest tier that runs containers; you can **Stop** the web app when
UAT isn't in use to avoid charges.)

Point the web app at the registry (admin creds):
```bash
az webapp config container set -g HRMS -n hr-ats \
  --container-image-name hratsacr.azurecr.io/ats:latest \
  --container-registry-url https://hratsacr.azurecr.io
```

## 3. Configure environment variables (App Settings)
```bash
az webapp config appsettings set -g HRMS -n hr-ats --settings \
  WEBSITES_PORT=8000 \
  DB_ENGINE=azure \
  DB_NAME=hr_recruitment \
  DB_HOST=<your-sql-server>.database.windows.net \
  DB_PORT=1433 \
  DB_USER='<your DB user>' \
  DB_PASSWORD='<your DB password>' \
  DJANGO_DEBUG=False \
  DJANGO_SECRET_KEY='<paste the generated secret key>' \
  DJANGO_ALLOWED_HOSTS='<your-app>.azurewebsites.net' \
  DJANGO_CSRF_TRUSTED_ORIGINS='https://<your-app>.azurewebsites.net' \
  MEDIA_ROOT=/home/media

# (use the real values from your local .env — never commit them)
```

## 4. Let the web app reach Azure SQL
Azure Portal → SQL server `hr-turnb-sql01` → **Networking** →
**"Allow Azure services and resources to access this server" = Yes** → Save.
(App Service outbound IPs are dynamic, so this is the simplest option.)

## 5. Restart and browse
```bash
az webapp restart -g HRMS -n hr-ats
```
Open **https://hr-ats.azurewebsites.net** → the landing page (Candidate / HR / Admin).
Log in as HR with `admin` / your password. First load may take ~1 min (container
cold start + serverless DB waking).

## 6. Ship updates later
Rebuild and restart whenever you change the code:
```bash
az acr build -r hratsacr -t ats:latest .
az webapp restart -g HRMS -n hr-ats
```

---

## Notes for UAT

- **Same database as local.** Local `start_server.bat` and the Azure web app both
  point at `hr_recruitment`. For an isolated UAT dataset, create a copy of the DB
  and point the web app's `DB_NAME`/host at the copy.
- **Share the URL** `https://hr-ats.azurewebsites.net` with UAT users on your
  network/org — no VPN needed, it's public but login-protected.
- **Diagnostics:** Portal → the web app → **Log stream** shows container logs;
  **SSH** (under Development Tools) opens a shell inside the container.
- **Secret key / password** live only in App Settings, never in git.
- **HTTPS** is automatic on `*.azurewebsites.net`.
