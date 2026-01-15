# CodeClone GitHub Action

Runs CodeClone to detect architectural code duplication in Python projects.

## Usage

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v1
  with:
    path: .
    fail-on-new: true