# Security Policy

## Reporting a Vulnerability

Do not disclose suspected vulnerabilities in a public issue. Use GitHub private vulnerability reporting after it is enabled for the repository. Until a private reporting channel is configured, keep the repository private and contact the maintainer directly.

Include the affected version or commit, reproduction steps, impact, and any suggested mitigation. Do not include real assessment evidence, credentials, tokens, personal data, or customer system details.

## Supported Versions

Before the first tagged release, only the current default branch is supported. A version-support table will be added when releases begin.

## Deployment Expectations

- Replace every example secret before startup.
- Keep the default localhost-only port bindings unless remote access is deliberately secured.
- Terminate TLS at a trusted reverse proxy for non-local deployments.
- Restrict uploaded evidence and generated reports as sensitive security data.
- Use a dedicated database, Redis instance, and model-provider account for production.
- Review AI-generated findings and artifacts before operational use.

