# Runbook — Routing public traffic to the ingest worker pool

`api-ingest` is the same Django app as `api`, in its own container on
`127.0.0.1:8001`. It exists so that client-site traffic and the dashboard stop
sharing one set of uvicorn workers:

- **Before:** the snippet (`/api/s.js`) and every ingest endpoint shared the
  api's 4 workers with the dashboard. A traffic spike on one client site, at six
  or more posts per pageview, slowed every Stacks Monitor page for the whole team.
- **After:** public traffic goes to `api-ingest` (2 workers,
  `UVICORN_INGEST_WORKERS`). The dashboard keeps the api's 4 to itself.

`./deploy.sh` starts `api-ingest` and checks it answers on `:8001`, but it gets
**no traffic until the CloudPanel vhost routes to it**. That edit is made in the
CloudPanel UI, not in this repo. Until then nothing changes.

## Routing it (once)

CloudPanel → Sites → `stacksmonitor.com` → **Vhost**.

1. Confirm `api-ingest` is up first. A route to a stopped container answers 502
   to every client site:

   ```bash
   curl -sf http://127.0.0.1:8001/api/ready/ && echo OK
   ```

2. The vhost already has a `location /api/ingest/` block pointing at `:8000`.
   **Change its `proxy_pass` to `:8001`.** Don't add a second block with the
   same path, which nginx rejects. This one block covers `/api/ingest/`,
   `/api/ingest/heatmap/`, `/api/ingest/form-errors/`, `/api/ingest/js-errors/`
   and `/api/ingest/form-submission/`.

3. Add these blocks next to it, above the general `/api` block. Prefix matching
   picks the longest match, so they win over `/api/`:

   ```nginx
   location = /api/s.js {
       proxy_pass http://127.0.0.1:8001;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }

   # WordPress Connect snippet: PHP errors and the activity log.
   location /api/php-errors/ {
       proxy_pass http://127.0.0.1:8001;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }

   location /api/wp-activity/ {
       proxy_pass http://127.0.0.1:8001;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

   If the existing `/api/ingest/` block lacks the `X-Real-IP` /
   `X-Forwarded-For` lines, add them while you are there. The ingest throttles
   and the domain-binding logs read the client address from them.

4. **Save.** CloudPanel tests the config and reloads nginx.

## Verify

```bash
# The snippet still serves, now from api-ingest:
curl -s https://stacksmonitor.com/api/s.js | grep -c snippet_version     # 1

# Ingest requests are reaching api-ingest (open a client site in a browser first):
docker compose -f docker-compose.production.cloudpanel.yml logs --since 2m api-ingest | grep -c "POST /api/ingest/"
```

Then load the dashboard while a client site is busy. It should be as fast as
when the sites are quiet.

## Rollback

Point the blocks from step 2 and 3 back at `:8000` and save. The api still
serves every path, so nothing else needs to change.
