# Minimal integration boundary

This directory contains a standalone model prototype. Application and bridge changes are outside its publication scope.

## Existing code ownership

AcquisitionStudio remains the operational controller. Source upload, consent, owner checks, approval, retries, reconciliation and protected mutations stay there. The call-entry resolver and ReportExplorer's five section values are retained. All section transitions use native history REPLACE; background observations never create history entries. No router or state-machine migration is needed.

A pure `deriveWorkspaceView` consumes already validated controller data. The same production-target WorkspaceView, ProcessingExperience, report sections and persistent audio dock render it. The default view port is the pass-through in `src/view-port.ts`. A development-only alias may select the review adapter; neither a URL nor NEXT_PUBLIC flag enables it in a production build.

## Trusted collector

The existing live development bridge remains the sole fixed-upstream HTTP path: browser-facing 3016, inner Next 3116. The review process uses its launch-selected `analysis_read_only` policy. Operational mutations are denied before upstream dispatch; ordinary explicit login/logout/workspace selection remain permitted. No review control may weaken this policy. The small policy function here is only a fictional-test model, not a replacement route allowlist.

An opt-in collector observes the exact responses already delivered to the real controller. It records minimal status/transcript/report bytes with method, selected path and receive time. It never replaces public `/v1` responses or issues provider runs. Capture ordinals are allocated before asynchronous work; gaps are allowed and earlier completions cannot take over newer observations. There is one call per scope. The source set is not claimed atomic simply because responses were received nearby in time.

The application parser wrapper implements `Parse`. It invokes the real source/recording-bound parsers and returns the actual projected state, validated artifact bindings, permitted source-point IDs and a serializable display-data projection. It excludes functions, File objects, React nodes, cookies, challenge values and operational capabilities. The fictional test parser is not valid for this task. Each read revalidates rather than trusts a formerly rendered React object.

The bridge implements `Authorize` using current owner/session/tenant/resource reads. Grant scope and binding must equal the captured resource, and each captured transcript/report must remain individually authorized and match the grant fingerprint. Where a historical revision cannot be retrieved safely, access fails closed. A replay is not cache authority. State/permission checks, actual response provenance and CSRF remain server-side trust boundaries, not client-supplied flags.

## Display selection, controls and HMR

The separate same-origin `/__review/` control page is served by local tooling, not by production Next routes. It may select live data, an actual observed frame, or a UI-only presentation variation. It never overlays product pixels or changes X-Frame-Options DENY. Public product URLs select only call/section; local fragments select opaque frame references. The route's call UUID must equal the store scope before selection. Endpoint/session checks are required even when the frame ID is unguessable.

The controller owns one per-canvas review adapter, not a global app store. Its `render(liveModel)` chooses a display model; it never invokes setProgress/setResult or restores old approval. A held frame's mode and capture time must remain explicit in control chrome and page title. Real session/transport health is separate from the captured warning appearance. Unavailable selection remains visibly unavailable rather than silently returning to Live.

For HMR, keep the frame store in the local bridge process and only a validated descriptor in local control memory. After a component remount, the adapter calls `select(descriptor)` and obtains fresh authorization before rendering. CSS edits use the existing product source. Existing-call/report entry is not replayed as a synthetic operational journey. Returning Live discards the display selection; explicit forget/reset purges review history, pending selectors and leases. Logout/tenant change purges scope. Ordinary cosmetic view changes must not call store.reset.

ProcessingStatusCopy/ProcessingExperience can expose a narrow observational-age/health render input. Production supplies the current foreground timer. Observed mode supplies captured values. Presentation can vary that input with a visible label. It cannot change stage, report, language, authorization deadline, real Date or provider clocks. Rendering after a lease expiry must actively mask the private subtree: schedule an actual-time re-render at the lease boundary, subscribe to revoke/scope notifications, and stop media. Core read-time guards alone are not that integration proof.

## Required tests before installation

1. Existing report deep links remain neutral until authority, then go directly to the validated report. Optional entry failure cannot hide an otherwise authorized report. No automatic quote/reprocess occurs on restore.
2. Section REPLACE, Back/reload, stable mounted panels and one audio dock pass in the actual app. Long Hindi/Marathi content remains readable without fabricated translations.
3. Core capture/admission uses actual parser wrappers and trusted bridge response bytes. HMR reentry, revocation, tenant change and retention masking pass in the real browser; model tests do not substitute.
4. The bridge denies protected mutations with zero upstream fetch. Capture and control RPC have exact Host/Origin, CSRF, selected-call and resource checks. No remote URL, JS evaluation, generic fetch fallback, HAR or credential recording exists.
5. Production/static builds contain no local adapter, catalogue, controller or retrieval routes in module graphs/traced assets. A review-enabled build fails. The inner Next process has empty upstream rewrites even under controlled .env canary variants; only the fixed bridge owns VPS egress. The tested dev guard function alone is insufficient.
6. Six actual full-page sizes (320,375,390,768,1024,1440) and relevant internal-scroll/modal views are inspected; routine regression uses 390/1440 plus narrow text reflow. Pixel diffs complement focus, accessibility, lineage, write-denial and interaction assertions.

Node Playwright 1.58.2 from the host repository is the browser dependency. There is no Python substitution or installation step in this prototype.

## Release and data boundaries

Capture remains opt-in, bounded and in memory; an idle expiry sweep is required. Real call content and screenshots stay local. Public exports contain only generic architecture, sanitized source and fictional tests. No operational receipts, body hashes tied to customers, private notes or credentials belong in public Git history. Baseline acceptance binds source/build and permitted response lineage privately; source/content changes invalidate that acceptance.

The first installed milestone is one real authorized call, same product components, hold/reopen an actual observation, safe presentation interaction and explicit unavailable history. If authorization or build exclusion cannot be proved, retain read-only live inspection and disable historical selection. No merge, deployment, permission changes or provider spending follows from a passing prototype test.
