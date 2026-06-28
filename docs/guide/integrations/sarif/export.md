# SARIF export

Contract: [SARIF projection](../../../book/integrations/sarif.md).

## Purpose

Explain how CodeClone projects canonical findings into SARIF and what IDEs or
code-scanning tools can rely on.

SARIF is a deterministic projection layer. The canonical source of truth
remains the report document.

## What SARIF is good for here

SARIF is useful as:

- an IDE-facing findings stream
- a code-scanning upload format
- another deterministic machine-readable projection over canonical report data

It is not the source of truth for:

- report integrity digest
- gating semantics
- baseline compatibility

## See also

- [05. Report](../../../book/05-report.md)
- [06. HTML Render](../../../book/06-html-render.md)
- [Examples / Sample Report](../../../examples/report.md)
