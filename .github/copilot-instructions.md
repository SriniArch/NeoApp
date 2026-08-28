# Copilot Instructions

## Repository

NeoApp2 is a Python trading application with:
- Tkinter desktop UI
- FastAPI web API
- Background worker
- Neo broker API
- File-based state
- Trading/risk/indicator engines

## Architecture Reference

For architecture, business logic, module relationships,
and important implementation details, consult:

docs/PROJECT_LOGIC.md

Use the document as a navigation guide, not as the source of truth.
The actual source code is authoritative.

## Context Rules

For a small change:
1. Start with the current file/symbol.
2. Inspect direct dependencies.
3. Do not scan the entire repository.

For cross-module changes:
1. Consult Logic/PROJECT_LOGIC.md.
2. Identify the relevant modules.
3. Inspect only those modules.

Only perform repository-wide searches when the problem
requires cross-cutting analysis.

## Modification Rules

- Keep changes minimal.
- Don't modify unrelated files.
- Follow existing architecture and patterns.
- Don't introduce new frameworks without asking.
- Verify changes against the actual source code.
