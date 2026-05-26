# Prebid bundle catalog

This directory contains pre-built Prebid.js bundles. Each bundle includes a specific set of bid adapters plus the consent modules required for that combination.

A publisher's `<script>` tag points at one of these via `data-prebid-url`. The tag's `data-bidders` JSON must only reference bidders whose adapter is present in the chosen bundle — Prebid silently drops unknown bidders at registration.

## Catalog

| File | Bidders included | Use when |
| --- | --- | --- |
| `prebid.js` | `limelightDigital` | Default / single-bidder Limelight |

Add a row here whenever a new bundle ships.

## Building a new bundle

The build is just Prebid.js's official `gulp build` command — no custom tooling. Three options ranked by effort:

### Option A — Local build (right for one-off / first bundle in a combination)

```bash
# One-time setup
git clone --depth 1 https://github.com/prebid/Prebid.js.git ~/prebid-source
cd ~/prebid-source
git checkout v11.11.0     # pin to a known-good Prebid version
npm ci                    # ~2 min, one-time

# Build a bundle with the modules you need
npx gulp build --modules=limelightDigitalBidAdapter,appnexusBidAdapter,consentManagementTcf,consentManagementUsp

# Copy into this repo
cp build/dist/prebid.js  /path/to/bidding-player/prebid/prebid-limelight-appnexus.js
```

Always include the consent modules a publisher will need (`consentManagementTcf`, `consentManagementUsp`, optionally `consentManagementGpp`). Skipping them breaks the engine's consent default.

### Option B — CI workflow (right for repeat / cross-team)

The repo ships a `workflow_dispatch` workflow at `.github/workflows/build-prebid-bundle.yml`. Trigger it from the GitHub Actions UI:

1. Repo → **Actions** tab → **"Build Prebid bundle"** in the left sidebar
2. Click **"Run workflow"** (top right)
3. Fill in:
   - **modules**: comma-separated module list, e.g. `limelightDigitalBidAdapter,appnexusBidAdapter,magniteBidAdapter,consentManagementTcf,consentManagementUsp`
   - **bundle_name**: filename without `.js`, e.g. `prebid-limelight-appnexus-magnite`
   - **prebid_version**: tag from [github.com/prebid/Prebid.js/tags](https://github.com/prebid/Prebid.js/tags), e.g. `v11.11.0`
4. Wait ~3 minutes. The workflow commits the bundle to `prebid/<bundle_name>.js` on `main` and pushes.

### Option C — Prebid.org download tool (UI builder)

[docs.prebid.org/download.html](https://docs.prebid.org/download.html) — Prebid's official self-serve build UI. Pick modules, click download. Drop the resulting file into this directory and commit. Useful when you're not sure of the exact module names.

## Updating bundles (new Prebid release)

Prebid ships a release roughly every two weeks. To pull a new Prebid version through every bundle in the catalog:

1. Bump the `--prebid_version` input to the new tag (e.g. `v11.12.0`)
2. Run the CI workflow once per bundle, passing the *same* `modules` list each time and the *same* `bundle_name` (the workflow overwrites)
3. Bump the project `VERSION` file and tag `vX.Y.Z` to lock the new bytes in jsDelivr

Existing publisher tags pinned to an older `@vX.Y.Z` keep serving the older Prebid until they regenerate their tag — that's the whole point of jsDelivr immutability.

## Finding adapter module names

Every Prebid bidder ships as `modules/<bidderName>BidAdapter.js`. The module name is **bidderName + `BidAdapter`** (camelCase):

- `limelightDigital` → `limelightDigitalBidAdapter`
- `appnexus` → `appnexusBidAdapter`
- `magnite` → `magniteBidAdapter`
- `pubmatic` → `pubmaticBidAdapter`
- `openx` → `openxBidAdapter`
- `rubicon` → `rubiconBidAdapter`

Full list: [github.com/prebid/Prebid.js/tree/master/modules](https://github.com/prebid/Prebid.js/tree/master/modules) — every file ending in `BidAdapter.js` is a usable adapter.

## Naming convention

Bundle files should be named `prebid-<bidder1>-<bidder2>-…<bidderN>.js`, alphabetical by bidder. Examples:

- `prebid-limelight.js` — single
- `prebid-limelight-appnexus.js` — two
- `prebid-limelight-appnexus-magnite.js` — three
- `prebid-multi-major.js` — five+ (avoid 7-word filenames)

The legacy `prebid.js` is kept as an alias for `prebid-limelight.js` for v1 backwards compatibility. Don't repurpose that name.

## What's in every bundle

The CI workflow includes these consent modules in every build by default, since the engine's `consentManagement` config relies on them:

- `consentManagementTcf` (GDPR)
- `consentManagementUsp` (CCPA)
- `consentManagementGpp` (US state privacy — left inactive by engine default, but the module must be in the bundle in case a publisher opts in)
- `tcfControl` (the enforcer module)

You don't need to list these in the `modules` input — the workflow always appends them.
