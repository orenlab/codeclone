# Security Policy

## Supported Versions

CodeClone is a static analysis tool and does not process untrusted input at runtime in production systems.

That said, we take security seriously.

| Version | Supported |
|---------|-----------|
| 1.1.x   | ✅ Yes     |
| 1.0.x   | ❌ No      |

---

## 🛡️ Security Considerations

CodeClone:

- Parses Python source code using `ast`
- Does **not** execute analyzed code
- Generates static HTML reports

Potential risk areas include:

- malformed source files
- extremely large inputs (resource exhaustion)
- HTML report generation

---

## 🚨 Reporting a Vulnerability

If you believe you have found a security vulnerability, **do not open a public issue**.

Instead, please report it privately:

📧 **Email:** `pytelemonbot@mail.ru`  
Subject: `Security issue in CodeClone`

Please include:

- CodeClone version
- Description of the issue
- Steps to reproduce
- Potential impact

You will receive an acknowledgment within **72 hours**.

---

## 🧪 What Is NOT Considered a Security Issue

The following are **not** security vulnerabilities:

- False positives or negatives in clone detection
- Performance issues on very large codebases
- UI / HTML layout problems
- Missing CFG edge cases (tracked as feature issues)

---

## 🕒 Disclosure Policy

- Valid vulnerabilities will be fixed promptly
- A patched release will be published
- Credit will be given unless anonymity is requested

---

Thank you for helping keep CodeClone safe and reliable.