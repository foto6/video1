# Creator R21 production publish execution

R21 preserves the R12 contracts `creator.publish_provider.v1`, `creator.publish_request.v1`, and `creator.publish_provider_receipt.v2`. It adds production transport implementations underneath the unchanged `prepare -> recover -> submit -> status` boundary.

No live post was made while implementing or testing R21.

## Credential boundary

Creator state stores only opaque `credentialRef` and `authorizationRef` values.

Production secret material is resolved at runtime. The built-in environment resolver maps an opaque credential reference to a hashed environment-variable name and keeps these values only in memory:

- access token;
- authorized subject/account ID;
- granted scopes;
- expiry;
- revoked/interactive-login state.

Access tokens, refresh tokens, passwords, cookies, authorization headers, or credential JSON are never written to the R12 ledger, R21 operation journal, receipts, readiness reports, or test logs.

If OAuth consent/login is missing, expired, revoked, or requires interactive login, the R12 operator state becomes `waiting_for_credentials` with the explicit reason. Creator does not automate CAPTCHA, 2FA, login pages, or credential entry.

## Durable side-effect safety

R21 adds `creator.publish_operation_journal.r21.v1`.

Before any provider mutation it writes a durable side-effect intent. Provider operation identity is persisted immediately after a successful acknowledgement. The existing R12 coordinator still performs authoritative recovery before submit.

If a mutation may have been accepted but no provider operation identity was acknowledged:

- recovery returns non-authoritative `unknown`;
- the R12 coordinator moves to `recoverable_unknown`;
- Creator does not blindly replay the mutation.

Known 429 responses use bounded Retry-After/exponential backoff. Read-only preflight/status requests may retry bounded 5xx/timeouts. Ambiguous failures on mutating calls are treated as unknown instead of being retried blindly.

## Instagram Reels

Implementation: direct Instagram/Meta content publishing API.

Production preflight verifies:

- exact OAuth subject/account binding;
- `instagram_business_content_publish` grant;
- exact Creator MP4, 9:16, 15-60 second binding;
- H.264/HEVC video, optional AAC audio;
- 23-60 FPS;
- width <= 1920;
- file <= 1 GB;
- `profile:<account-id>` destination binding;
- public HTTPS video URL;
- read-only account lookup.

Creator then creates the Reel media container, polls container processing, durably records a publish-commit intent, publishes the finished container exactly once, and records the returned media ID/permalink.

The Instagram Graph API version is configuration, not a permanent hard-coded best version.

Human/account setup that cannot be automated:

- eligible Instagram professional account;
- Meta/Instagram developer application and current content-publishing permission/access;
- OAuth/consent, including any login/2FA;
- externally reachable HTTPS media hosting;
- exact current Graph API version selection.

After that setup and while authorization remains valid, account preflight, container creation, processing checks, publish commit, receipt creation, and Growth handoff are automated.

Current reference:
https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api

## TikTok Direct Post

Implementation: official Content Posting API Direct Post using `PULL_FROM_URL`.

R21 intentionally uses the verified-domain pull path for production so the durable journal never needs to store TikTok one-time `upload_token` URLs.

Preflight verifies:

- `video.publish` scope and exact OAuth subject;
- latest creator info via `creator_info/query`;
- chosen `privacy:<level>` is currently allowed for that creator;
- Creator MP4/9:16/15-60 second profile;
- H.264/HEVC and 23-60 FPS;
- 360-4096 pixel dimensions;
- <= 4 GB;
- creator-specific maximum duration;
- caption <= 2200 UTF-16 units;
- configured HTTPS media URL.

Human/account setup that cannot be automated:

- TikTok developer application with Content Posting API;
- approval for `video.publish`;
- creator OAuth consent/login;
- required UX consent/privacy selection;
- verified media URL domain/prefix for `PULL_FROM_URL`;
- TikTok audit before unaudited-client visibility restrictions can be lifted.

After setup, creator-info preflight, Direct Post initialization, provider-side media pull, processing/moderation polling, receipt validation, and Growth handoff are automated.

References:
https://developers.tiktok.com/doc/content-posting-api-get-started/
https://developers.tiktok.com/doc/content-posting-api-reference-direct-post/
https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status/
https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide/

## YouTube Shorts

Implementation: YouTube Data API v3 `videos.insert` resumable upload.

Preflight verifies:

- `youtube.upload` OAuth scope;
- exact authorized channel ID via `channels.list?mine=true`;
- Creator MP4/9:16/15-60 second profile;
- supported H.264/HEVC baseline;
- <= 256 GB;
- explicit `privacy:public|private|unlisted` destination.

The resumable session is durably tracked as provider operation identity. OAuth headers/tokens are never persisted. After upload acknowledgement, Creator polls video processing and records the terminal video ID and canonical watch URL.

Human/account setup that cannot be automated:

- Google Cloud project with YouTube Data API;
- OAuth client and channel owner consent/login/2FA;
- `youtube.upload` authorization;
- API-project audit/verification when required for non-private publication.

Google documents that uploads from unverified API projects created after July 28, 2020 are restricted to private viewing until audit.

References:
https://developers.google.com/youtube/v3/docs/videos/insert
https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol

## Sandbox one-command publish

The installed command never performs a live network call:

```bash
creator-publish-sandbox \
  --media ./final.mp4 \
  --authorization ./release.authorization.v1.json \
  --platform tiktok \
  --account-id sandbox-account \
  --destination privacy:SELF_ONLY \
  --credential-ref vault-ref://sandbox/tiktok \
  --caption "Sandbox publish" \
  --cta "Learn more" \
  --out ./publish-sandbox
```

It runs the existing R12 request/prepare/recover/submit/status/receipt flow with a synthetic provider, then creates the existing Growth handoff. Outputs are:

- `publish-request.json`
- `publish-ledger.jsonl`
- `provider-receipt.json`
- `growth-handoff.json`
- `sandbox-report.json`

The report states `networkUsed=false`, `liveSideEffect=false`, and synthetic evidence is ineligible for live performance claims.

## CI fault evidence

CI uses only `FakeHttpTransport` and R12 synthetic providers. No external HTTP or paid call occurs.

Deterministic tests cover:

- Instagram, TikTok, and YouTube request/response mappings;
- lost acknowledgement after a mutation may have been accepted;
- processing timeout;
- 429 Retry-After/backoff;
- expired authorization;
- revoked credential reference;
- interactive authorization requirement;
- malformed receipt;
- restart between request/submit/processing/receipt phases;
- duplicate request;
- out-of-order status after terminal completion.

## Readiness boundary

R21 proves executable production code paths, not live account entitlement.

Each platform remains deployment-blocked until the operator completes its provider/account/API setup and validates that account in a separately authorized live preflight. No real post or account mutation is performed by this milestone.
