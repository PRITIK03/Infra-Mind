# Contributing to InfraMind (AWS Instance Advisor)

Thank you for contributing! To maintain high engineering rigor, reproducibility, and reliability, we follow a strict branching and testing discipline.

---

## 1. Branching & PR Discipline

* **Primary Integration Branch:** `V2` (or `main` for release tags).
* **Feature Branches:** Create focused feature branches named by domain and intent:
  * `feat/<feature-name>` for new capabilities
  * `fix/<bug-name>` for bug fixes and patches
  * `test/<suite-name>` for test additions and fixtures
  * `docs/<topic>` for documentation improvements
* **Pull Request Workflow:**
  * Open all PRs against the `V2` base branch.
  * Direct pushes to `V2` or `main` are restricted.
  * PR descriptions should detail the problem solved, architectural trade-offs, and verification commands executed.

---

## 2. CI Quality Gates & Pre-Merge Checklist

All continuous integration checks must pass green before merging any pull request:

1. **Backend Test Suite (pytest):**
   ```bash
   cd aws-instance-advisor
   python -m pytest tests/ -v
   ```
   * All unit, regression, and scenario tests must pass (100% mocked, zero paid network calls).

2. **Frontend Test Suite (Vitest & Axe-Core):**
   ```bash
   cd aws-advisor-ui
   npm test
   ```
   * All component rendering and WCAG accessibility audits must pass.

3. **Frontend Linting & Type Checking:**
   ```bash
   cd aws-advisor-ui
   npm run lint
   ```

4. **Playwright E2E Smoke Suite:**
   ```bash
   cd aws-advisor-ui
   npx playwright test
   ```

---

## 3. Engineering & Architectural Standards

* **Deterministic Guarantees:** Do not delegate deterministic tasks (e.g. Terraform HCL synthesis, Well-Architected rules, pricing math, disagreement scoring) to non-deterministic LLM prompts. Use typed Python builder logic.
* **Fail-Fast Startup Config:** Any newly introduced required settings must be included in `validate_startup_config()` in `app.config`.
* **Graceful-Optional Integration Pattern:** External services (Redis, Sentry, search, MCP) must degrade gracefully to process-local defaults when unconfigured or unreachable.
* **Dependency Pinning:** Exact version constraints must be pinned in `requirements.txt` and locked in `package-lock.json`.
