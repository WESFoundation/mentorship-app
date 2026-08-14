# Environment Setup Guide

## Overview
All Google credentials (OAuth and Service Account) are now loaded from the `.env` file instead of hardcoded or from JSON files.

## Files Modified

### 1. `app.py`
- ✅ Added `from dotenv import load_dotenv` import
- ✅ Added `load_dotenv()` to load environment variables at startup
- ✅ Added `GOOGLE_CREDENTIALS` configuration section to read from `.env`
- ✅ Created `create_oauth_flow()` helper function to build OAuth flow from `.env` variables
- ✅ Updated OAuth Flow initialization to use `Flow.from_client_config()` instead of `Flow.from_client_secrets_file()`
- ✅ Updated `get_calendar_service()` to use `.env` credentials instead of `service_account.json`

### 2. `.env` (Created)
Contains all Google credentials:
- OAuth 2.0 Client ID and Secret
- Project ID and redirect URIs
- Service Account credentials (private key, email, certificate URLs)

### 3. `.env.example` (Created)
Template file showing all required environment variables. Use this as reference to set up `.env`.

### 4. `.gitignore` (Already Protected)
- `.env` file is already in `.gitignore` - credentials will NOT be committed to Git
- `service_account.json` and `client_secret.json` are also protected

## Setup Instructions

### Step 1: Copy `.env.example` to `.env`
```bash
cp .env.example .env
```

### Step 2: Fill in Your Google Credentials
Open `.env` and update all `your_*` placeholders with actual values from:
- **OAuth Credentials**: Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID
- **Service Account**: Google Cloud Console → APIs & Services → Credentials → Service Account

### Step 3: Verify `.env` is Loaded
The app will automatically load `.env` on startup. To verify:
```bash
python app.py
```

If credentials are missing, you'll see error messages like:
```
❌ GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET not set in .env file
❌ Missing required service account credentials in .env file
```

## Key Changes

### OAuth Flow Creation
**Before:**
```python
flow = Flow.from_client_secrets_file("client_secret.json", scopes=scopes)
```

**After:**
```python
flow = create_oauth_flow(scopes=scopes)
```

The new `create_oauth_flow()` function builds the client config from `.env` variables dynamically.

### Service Account Credentials
**Before:**
```python
creds = service_account.Credentials.from_service_account_file("service_account.json")
```

**After:**
```python
creds = service_account.Credentials.from_service_account_info(service_account_info)
```

Credentials are now constructed from `.env` variables, eliminating the need for JSON files.

## Security Notes

✅ **Credentials are NOT committed to Git** (protected by `.gitignore`)
✅ **Only `.env.example` is in the repo** (safe template)
✅ **Each developer has their own `.env` file** (local only)
✅ **Production credentials come from environment variables** (set on server/deployment platform)

## Environment Variables Used

```
# OAuth 2.0 Credentials
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_PROJECT_ID
GOOGLE_AUTH_URI
GOOGLE_TOKEN_URI
GOOGLE_REDIRECT_URI
GOOGLE_PRODUCTION_REDIRECT_URI

# Service Account Credentials
GOOGLE_PRIVATE_KEY_ID
GOOGLE_PRIVATE_KEY
GOOGLE_CLIENT_EMAIL
GOOGLE_AUTH_PROVIDER_CERT_URL
GOOGLE_CLIENT_CERT_URL

# Flask
SECRET_KEY
FLASK_ENV
```

## Troubleshooting

### Error: "GOOGLE_CLIENT_ID not set in .env"
**Solution:** Make sure `.env` file exists in project root and has the correct values.

### Error: "Missing required service account credentials"
**Solution:** Verify all `GOOGLE_*` variables for service account are filled in `.env`.

### Error: "invalid_client"
**Solution:** Double-check `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are correct and match your OAuth credentials.

### Private key format errors
**Solution:** Ensure `GOOGLE_PRIVATE_KEY` includes the `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----` markers exactly as shown in `.env.example`.

