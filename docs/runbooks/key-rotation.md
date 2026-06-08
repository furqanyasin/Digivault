# Runbook — Vault Key Rotation

Rotating the credential-vault Fernet key with **zero downtime**, using `MultiFernet`.

## Concepts

- `VAULT_ENCRYPTION_KEYS` — comma-separated, **ordered** list of Fernet keys.
  - The **first** key encrypts all new data.
  - **All** keys are tried when decrypting, so old ciphertext keeps working.
- `VAULT_ENCRYPTION_KEY` — legacy single key, only used when `VAULT_ENCRYPTION_KEYS` is empty.

## When to rotate

- Scheduled rotation (e.g. quarterly).
- Suspected key compromise (rotate immediately, then audit `CredentialAccessLog`).
- Personnel change with key access.

## Procedure

### 1. Generate a new key
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Prepend it as the new primary
Set the env var on **all** backend + Celery worker hosts. New key first, current key second:
```
VAULT_ENCRYPTION_KEYS=<NEW_KEY>,<CURRENT_KEY>
```
> If you were using the legacy `VAULT_ENCRYPTION_KEY`, move its value into `VAULT_ENCRYPTION_KEYS` as the second entry.

### 3. Deploy / restart
Restart the API and Celery workers so every process loads both keys. At this point:
- New writes are encrypted under `<NEW_KEY>`.
- Existing data still decrypts under `<CURRENT_KEY>`.
- **The system is fully functional with the old key not yet removed.**

### 4. Re-encrypt existing blobs
```bash
python manage.py rotate_vault_keys --dry-run   # preview count
python manage.py rotate_vault_keys             # perform rotation
```
Idempotent and resumable — safe to re-run if interrupted.

### 5. Retire the old key
Once `rotate_vault_keys` completes, drop the old key:
```
VAULT_ENCRYPTION_KEYS=<NEW_KEY>
```
Deploy / restart again. Verify a credential reveal works in the app.

## Verification
- `python manage.py rotate_vault_keys --dry-run` reports 0 pending after step 4? (it always re-rotates, so instead) confirm a reveal endpoint returns the correct plaintext after step 5.
- Spot-check several credentials across teams via the reveal API.

## Rollback
- Before step 5 (old key still present): set `VAULT_ENCRYPTION_KEYS` back to `<CURRENT_KEY>` and restart. No data loss — old key never left the list.
- After step 5: if reveals fail, re-add the old key (`<NEW_KEY>,<OLD_KEY>`) and restart while you investigate. **Never** discard the old key until reveals are verified.

## Key escrow
Store every retired key in your secrets manager until you are certain no ciphertext encrypted under it remains anywhere (including DB backups). A restored backup predating rotation will need its era's key to decrypt.
