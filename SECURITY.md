# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected security vulnerability.
Use GitHub's private vulnerability reporting form:
https://github.com/misaka310/video-highlights-site/security/advisories/new

Include the affected file or endpoint, reproduction steps, impact, and any safe
mitigation you have identified.

Please do not include credentials, private keys, personal data, or live system
paths in a report. Redact those values and describe the shape of the data
instead.

## Scope and response

This repository publishes a static video-highlights site. Reports involving
the generated public data, third-party platform availability, or a deployment
provider should explain how they create a security impact in this repository.
We will acknowledge actionable reports and coordinate a fix or disclosure
timeline with the reporter.

We target an initial acknowledgement within 7 days. For a confirmed,
repository-controlled vulnerability, we target a remediation or documented
mitigation within 60 days, with faster handling for actively exploited or
high-impact issues. Coordinated public disclosure should wait until a fix or
mitigation is available unless an earlier disclosure timeline is required to
protect users.

## Secret handling

Runtime credentials, SSH keys, machine-specific paths, private IP addresses,
and deployment secrets must remain outside the repository. Use local
environment variables or the deployment provider's secret store. Public
documentation must use placeholders and sanitized examples.

<!-- managed-by: repo-launch-doctor-security-baseline-v1 -->

## Reporting a vulnerability

Please do **not** publish suspected vulnerabilities in a public issue. Report them privately through GitHub's security-advisory flow for this repository:

https://github.com/misaka310/video-highlights-site/security/advisories/new

Include the affected version or commit, reproduction steps, impact, and any suggested mitigation. Reports that include a minimal proof of concept are especially useful.

## Response timeline

- Initial acknowledgement target: within 7 days.
- Triage and severity assessment target: within 14 days.
- Fix timing depends on impact and complexity; critical issues are prioritized before routine feature work.
- Coordinated public disclosure should wait until a fix or mitigation is available whenever practical.

## Supported versions

The current default branch and the latest published release, when releases exist, receive security fixes. Older snapshots may not receive backports.
