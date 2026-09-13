# Sales Xray standalone companion release

This source-owned companion serves the standalone frontend. It shares the AC
identity and conversation API through the existing edge. It does not add an image
to the four-image core release manifest or replace a learner/admin/coach frontend.
Deploy staging first, validate it, then promote the same verified image to production.

| Environment | Exact public host                        | Edge alias                          |
| ----------- | ---------------------------------------- | ----------------------------------- |
| Staging     | `salesxray-staging.authorityclosers.com` | `ac-staging-sales-xray-web:3016`    |
| Production  | `salesxray.authorityclosers.com`         | `ac-production-sales-xray-web:3016` |

## Identity and routing

The core API receives the source profile's exact `AC_SALES_XRAY_APP_URL`. Password
login uses the existing same-origin AC endpoint and host-only session cookie.
Existing-account Google sign-in uses a signed `sales_xray` authentication surface;
registration and linking through that surface are rejected. Register these exact
callbacks on the current approved Google web client before Google browser testing:

- `https://salesxray-staging.authorityclosers.com/v1/auth/google/callback`
- `https://salesxray.authorityclosers.com/v1/auth/google/callback`

The app fetches `/v1/me/workspaces` and requires explicit selection when the session
has no selected tenant, including a sole available workspace. Selection uses the
canonical `/v1/context` endpoint and does not infer membership or grant access.
The learner app supplies registration/recovery; no second identity store is added.

Source-owned core Caddy routes send `/v1` and `/v1/*` on each exact host to its AC
API. Other paths go to its companion edge alias. The hold routes include the same
hosts. The apex is unchanged. Existing Cloudflare tunnel ingress may add the two
exact hosts pointing to the verified local edge only after access/routing proof.
The source does not create DNS or mutate the tunnel.

## Build and verify

Dispatch `.github/workflows/sales-xray-web-image.yml` with the reviewed exact
40-character source SHA after CI passes. The workflow builds Linux amd64, checks
the baked release marker and actual `/health`, then saves and reloads the image.
It uploads four files, under the shared packaging mutex and 450 MB artifact pool
ceiling, with one-day retention. No registry push or VPS image build is needed.

Download the matching successful run's artifact into an absolute, operator-owned,
immutable directory. Keep the metadata SHA256 from that reviewed CI artifact as
the separate provenance anchor. Do not trust a hash supplied by an unrelated
download, source `web-image.env` as shell code, or let other processes mutate the
directory while verification and loading run.

```sh
python3 infra/sales-xray-web/verify-artifact.py \
  --artifact-dir "$ARTIFACT_DIR" \
  --source-sha40 "$REVIEWED_SOURCE_SHA" \
  --metadata-sha256 "$REVIEWED_METADATA_SHA256"
docker load --input "$ARTIFACT_DIR/web-image.tar.gz"
```

The verifier binds source, metadata, archive checksum, OCI manifest and image
configuration. Its output contains only `verified_source`, `runtime_ref`,
`config_id` and `archive_sha`. Record these with the successful CI run ID.

After loading, inspect the exact immutable image reference. Some Docker stores
resolve the OCI transport manifest directly; classic Docker resolves the bound
image configuration ID instead. Either choice must resolve to the verifier's
exact `config_id`. Record the selected reference and inspected ID; fail if they
differ. Never use a mutable tag or invent a registry digest. Inspect/run the
selected immutable reference with networking disabled to prove the baked
`/app/.ac-release-id` equals the reviewed source before activation.

Generate a separate one-line operator env file containing only
`AC_WEB_IMAGE=<verified immutable runtime reference>` from the verified result.
The downloaded `web-image.env` remains an evidence file, not executable input.

```sh
docker compose --env-file infra/sales-xray-web/environments/staging.env \
  --env-file "$VERIFIED_RUNTIME_ENV" \
  -f infra/sales-xray-web/compose.yaml up -d --wait --wait-timeout 90
```

Use the production source profile only after staging passes. The container has
no published host port, API/provider/DB credentials or data mounts. It runs as
UID/GID 1000 with a read-only filesystem, no capabilities, no privilege escalation,
32 MiB scratch, 384 MiB RAM, 0.5 CPU and 128 PIDs. Its sole network is `ac_edge`.
The core release owner must use the source-owned edge lifecycle to activate the
matching routes/API settings; running this compose alone does not publish a host.

## Acceptance and rollback

For each environment save the source/image IDs and test receipts for:

1. Exact-host `/health` returns the baked release SHA, correct service and HTTP 200.
2. Anonymous app and login render; private history/report APIs return 401.
3. Real password and Google existing-account browser sign-in use a host-only cookie.
4. Workspace selection lists current memberships; selecting another tenant fails.
5. Upload, job progress, report, source-linked transcript/replay and deletion work
   under the separately enabled hosted service. Prove expired/revoked access fails.
6. Logout removes private access; no browser request goes to a provider or localhost.
7. Observe container health/resource limits and core app parity during canary.

Enabling the frontend host does not grant recording/provider approval, minute
entitlements or activate analysis. Those stay in the current canonical hosted
service configuration. Do not replay an expired private-call approval. Provider
acceptance uses a currently authorized exact recording and a reserved quote.

Keep the previous verified companion artifact/runtime env and core rollback
release. If canary fails, apply the source-owned hold route first, restore the
previous companion reference and core release through the release controller, then
verify health/auth again before reopening. On first launch, rollback is the hold
route plus stopping this companion project; it does not alter the apex or another
app. Record the actual rollback exercise and resulting release IDs.
