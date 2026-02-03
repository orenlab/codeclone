# Security Policy

## Supported Versions

CodeClone is a static analysis tool and does not execute analyzed code at runtime.
Nevertheless, security and robustness are treated as first‑class concerns.

The following versions currently receive security updates:

| Version | Supported |
|---------|-----------|
| 1.2.x   | Yes       |
| 1.1.x   | No        |
| 1.0.x   | No        |

---

## Security Considerations

CodeClone operates purely on static input and follows a conservative execution model:

- Parses Python source code using the standard `ast` module
- Does **not** execute analyzed code
- Performs analysis in-process with explicit resource limits
- Generates static HTML reports without external dependencies

Potential risk areas include:

- malformed or adversarial source files
- extremely large inputs leading to resource exhaustion
- HTML report generation and embedding

These areas are explicitly tested and hardened, but are still the primary focus of
ongoing security review.

---

## Reporting a Vulnerability

If you believe you have discovered a security vulnerability, **do not open a public issue**.

Please report it privately via email:

**Email:** `pytelemonbot@mail.ru`  
**Subject:** `Security issue in CodeClone`

When reporting a vulnerability, please include:

- the affected CodeClone version
- a clear description of the issue
- minimal steps to reproduce
- an assessment of potential impact, if known

You will receive an acknowledgment within **72 hours**.

---

## What Is Not Considered a Security Issue

The following issues are **not** considered security vulnerabilities:

- false positives or false negatives in clone detection
- performance limitations on very large codebases
- UI or HTML layout issues
- missing CFG edge cases or semantic limitations

Such issues should be reported through the regular issue tracker as bugs or feature
requests.

---

## Disclosure Policy

- Confirmed vulnerabilities will be addressed promptly
- A patched release will be published as soon as feasible
- Credit will be given to the reporter unless anonymity is requested

---

Thank you for helping keep CodeClone secure, reliable, and trustworthy.
