# Open-Source Readiness Review

## Current Status

ATO Bot is **not ready for a public repository yet**, but the first cleanup tranche is complete. The application runs, migrations are current, 24 backend unit tests pass, the frontend builds, and the frontend dependency audit reports zero known vulnerabilities after upgrades.

## Completed in This Tranche

- Added Git, Docker, secret, runtime-data, and generated-output exclusions.
- Prevented backend `.env`, uploads, outputs, tests, and local collector data from entering production image contexts.
- Replaced `npm install` with deterministic `npm ci` in the frontend image.
- Forced CPU-only PyTorch in the backend image so document embeddings do not pull an unused CUDA runtime.
- Upgraded React Router and Vite to remove known frontend dependency vulnerabilities.
- Removed the obsolete dashboard as a product entry point.
- Made the incomplete cATO/integration slice experimental and disabled by default.
- Removed the personal LAN IP from the public Compose configuration and defaulted to localhost-only exposure.
- Added public README, security policy, contribution guidance, feature status, and CI configuration.

## P0 Before Public Release

1. **Select a license.** The repository cannot be called open source without a public license. Apache-2.0 is recommended for consideration because it includes an explicit patent grant; ownership and patent strategy must be reviewed before adding it.
2. **Move startup schema creation into Alembic.** `backend/app/main.py` currently contains 119 `CREATE`, `ALTER`, or index statements. Fresh installs work because application startup repairs the schema, but that is not a reviewable or reliable migration contract.
3. **Run a full secret and sensitive-data review on the exact Git staging set.** The current workspace contains live `.env` files, host-identifying collector payloads, generated reports, uploads, and local Docker image archives. They are now ignored, but the staged file list must be inspected before the first commit.
4. **Complete the backend dependency audit.** The hardened runtime blocked `pip-audit` temporary execution. CI now owns this check, but the first public commit must not proceed until it passes in a clean runner.
5. **Add end-to-end authorization and assessment tests.** One 24-test module is insufficient for a security product with 35 API modules and 26 frontend pages.

## P1 Before a Stable Release

- Add API integration tests for authentication, project isolation, assessment lifecycle, reviewer permissions, evidence eligibility, reports, and exports.
- Add browser tests for login, upload, ingestion, assessment navigation, review, remediation, and downloads.
- Replace broad unbounded Python dependency ranges with a reviewed lock or constraints process.
- Split the frontend bundle; the default bundle remains over 1 MB before lazy-route cleanup is fully applied.
- Add release versioning, changelog, container image provenance, SBOM generation, and signed release artifacts.
- Review bundled NIST/OSCAL data provenance and add a `NOTICE` file for third-party data and dependencies.

## Publication Gate

Before creating the GitHub repository:

1. Add the selected `LICENSE` and `NOTICE` files.
2. Initialize Git locally.
3. Run `git status --ignored` and inspect every staged file.
4. Run the CI workflow locally or in a private GitHub repository.
5. Confirm no real evidence, credentials, customer names, hostnames, internal IPs, generated reports, or patent work product are staged.
6. Tag the first release only after the migration and test P0 items are closed.
