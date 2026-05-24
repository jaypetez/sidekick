# Contributing to Sidekick

Thanks for your interest in contributing! This document is the source of truth
for how work flows into `main` — branch protection, code review, and the
mechanics of getting a change merged.

If anything here is out of date or unclear, open an issue or a PR against this
file.

---

## Table of contents

- [Code of Conduct](#code-of-conduct)
- [Getting started](#getting-started)
- [Branching and commits](#branching-and-commits)
- [Making changes](#making-changes)
- [Submitting a pull request](#submitting-a-pull-request)
- [Code review and sign-off](#code-review-and-sign-off)
- [Branch protection rules](#branch-protection-rules)
- [Merge strategy](#merge-strategy)
- [Reporting bugs](#reporting-bugs)
- [Suggesting features](#suggesting-features)
- [Security issues](#security-issues)
- [Dependencies](#dependencies)
- [Releases](#releases)
- [Maintainers](#maintainers)

---

## Code of Conduct

Participation in this project is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to abide by
its terms.

## Getting started

1. Fork the repo and clone your fork.
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Run the test suite to confirm your environment works: `pytest -v`
4. Create a branch for your change: `git checkout -b your-feature`

## Branching and commits

- **Never push directly to `main`.** It is protected (see
  [Branch protection rules](#branch-protection-rules)). All changes land via
  pull request.
- **Branch from `main`.** Keep your branch up to date by rebasing on `main`
  rather than merging `main` into your branch — the repo requires linear
  history.
- **Branch naming.** Use short, descriptive, kebab-case names with an optional
  prefix:
  - `feat/short-description` — new functionality
  - `fix/short-description` — bug fixes
  - `docs/short-description` — documentation only
  - `chore/short-description` — tooling, deps, CI, refactors without behavior
    change
- **Commit messages.** Keep the subject line under ~72 characters, written in
  the imperative mood ("Add X", not "Added X" or "Adds X"). Explain the *why*
  in the body when the change is non-obvious.
- **One logical change per commit** where practical. Squash fixups before
  requesting review.

## Making changes

- **Keep PRs focused.** One logical change per PR is much easier to review
  than a sprawling refactor.
- **Add or update tests** when you change behavior. PRs that change behavior
  without test coverage will usually be asked to add some.
- **Run `pytest -v` locally** before pushing.
- **Match the existing code style.** Where unclear, prefer readability over
  cleverness.
- **Do not introduce new dependencies** without flagging them in the PR
  description. Dependency additions get extra scrutiny.

## Submitting a pull request

1. Push your branch to your fork (external contributors) or to `origin`
   (collaborators).
2. Open a PR against `main`.
3. Fill out the PR template — the "why" is more important than the "what".
4. Link any related issues with `Closes #123` or `Relates to #456`.
5. Mark the PR as a draft if it's not ready for review yet.
6. Resolve any merge conflicts by rebasing on `main`, not by merging `main`
   into your branch.
7. Be patient — this is a small project and reviews may take a few days.

## Code review and sign-off

This repo uses a **code owners** model. Every PR into `main` requires approval
from a code owner before it can be merged.

- **Code owners are defined in [`CODEOWNERS`](CODEOWNERS).**
- **At least one approving review from a code owner is required.** GitHub will
  automatically request a review from the appropriate owner based on the files
  you changed.
- **Stale reviews are dismissed automatically** when you push new commits, so
  re-request review after pushing fixes.
- **All review conversations must be resolved** before merge.
- **PR authors cannot approve their own PRs** — this is enforced by GitHub.
  Maintainers with admin access may bypass required reviews on their own PRs
  when no other code owner is available; this should be the exception, not the
  rule, and bypassed merges are logged in the repo's audit log.

If you are a code owner and you receive a review request:
- Aim for an initial response within ~3 business days.
- Be constructive. Reference [CONTRIBUTING.md](CONTRIBUTING.md) and the
  [Code of Conduct](CODE_OF_CONDUCT.md) when relevant.
- Approve, request changes, or comment — don't leave reviews open without a
  verdict.

## Branch protection rules

The `main` branch is protected with the following rules (configured via the
GitHub API). The intent is documented here so contributors know what to
expect; the live settings can be inspected at
`Settings → Branches → Branch protection rules` on GitHub.

| Rule                                       | Setting   |
| ------------------------------------------ | --------- |
| Require a pull request before merging      | **Yes**   |
| Required approving reviews                 | **1**     |
| Dismiss stale approvals on new commits     | **Yes**   |
| Require review from Code Owners            | **Yes**   |
| Require approval of the most recent push   | **Yes**   |
| Require conversation resolution before merge | **Yes** |
| Require linear history                     | **Yes**   |
| Allow force pushes                         | **No**    |
| Allow deletions                            | **No**    |
| Block creations                            | **No**    |
| Enforce on administrators                  | **No**    |

> **Why "Enforce on administrators: No"?** This project currently has a single
> maintainer. GitHub does not allow PR authors to approve their own PRs, so
> requiring code-owner approval with strict admin enforcement would deadlock
> solo maintenance. Admin bypass is reserved for solo merges; once additional
> code owners are added to [`CODEOWNERS`](CODEOWNERS), admin enforcement
> should be turned on (`enforce_admins: true`).

### Required status checks

Every PR must pass the following CI jobs before it can merge:

| Job name              | What it runs                                     |
| --------------------- | ------------------------------------------------ |
| `lint`                | `ruff check .` + `ruff format --check .`         |
| `typecheck`           | `mypy src/sidekick` (strict mode)                |
| `test (py3.11)`       | `pytest` with 80% coverage floor on Python 3.11  |
| `test (py3.12)`       | same, on Python 3.12                             |
| `dependency-review`   | GitHub's dependency-review-action (PRs only)     |

Apply these checks to branch protection via `gh api`:

```sh
gh api -X PATCH repos/jaypetez/sidekick/branches/main/protection/required_status_checks \
  -F strict=true \
  -F 'contexts[]=lint' \
  -F 'contexts[]=typecheck' \
  -F 'contexts[]=test (py3.11)' \
  -F 'contexts[]=test (py3.12)' \
  -F 'contexts[]=dependency-review'
```

## Local pre-commit setup

The repo ships a `.pre-commit-config.yaml` that mirrors the lint + format
checks CI runs, so contributors catch issues before pushing:

```sh
pip install -e ".[dev]"
pre-commit install
```

After that, `ruff check --fix` and `ruff format` run automatically on every
commit.

## Merge strategy

- **Squash and merge** is the default for feature branches. The squashed
  commit message should match the PR title and link to the PR (`(#123)`).
- **Rebase and merge** is acceptable when the branch's commit history is
  already clean and each commit stands on its own.
- **Merge commits are disabled** to preserve linear history on `main`.
- **Delete the branch after merge.** GitHub is configured to do this
  automatically.

## Reporting bugs

Use the [bug report issue template](ISSUE_TEMPLATE/bug_report.yml). Include:
- What you did
- What you expected
- What actually happened
- Your environment (OS, Python version, etc.)

## Suggesting features

Open an issue with the
[feature request template](ISSUE_TEMPLATE/feature_request.yml) **before**
writing code. Discussing the approach first saves wasted effort if the change
doesn't fit the project's direction.

## Security issues

**Do not open public issues for security vulnerabilities.** See
[SECURITY.md](SECURITY.md) for the private reporting process.

## Dependencies

- Dependency updates are managed automatically by
  [Dependabot](dependabot.yml). PRs from Dependabot still require code-owner
  review before merging.
- New direct dependencies require discussion in the PR description: what does
  it add, why is it preferred over what's already in the dependency tree, and
  what's the maintenance / security posture of the upstream?

## Releases

- Releases are cut from `main` by a maintainer.
- Tags follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.
- Release notes are generated from merged PRs since the previous tag.

## Maintainers

Current maintainers / code owners are listed in [`CODEOWNERS`](CODEOWNERS).

To be added as a maintainer:
1. Have several merged, high-quality PRs on the project.
2. Open an issue or reach out to an existing maintainer.
3. Maintainers are added by amending [`CODEOWNERS`](CODEOWNERS) and granting
   the appropriate GitHub collaborator role.
