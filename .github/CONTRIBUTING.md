# Contributing to Sidekick

Thanks for your interest in contributing! This document covers how to get set up and what we expect from contributions.

## Getting started

1. Fork the repo and clone your fork.
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Run the test suite to confirm your environment works: `pytest -v`
4. Create a branch for your change: `git checkout -b your-feature`

## Making changes

- Keep PRs focused. One logical change per PR is much easier to review than a sprawling refactor.
- Add or update tests when you change behavior.
- Run `pytest -v` locally before pushing.
- Match the existing code style. Where unclear, prefer readability over cleverness.

## Submitting a pull request

1. Push your branch and open a PR against `main`.
2. Fill out the PR template — the "why" is more important than the "what".
3. Link any related issues with `Closes #123`.
4. Be patient — this is a side project and reviews may take a few days.

## Reporting bugs

Use the bug report issue template. Include:
- What you did
- What you expected
- What actually happened
- Your environment (OS, Python version, etc.)

## Suggesting features

Open an issue with the feature request template before writing code. Discussing the approach first saves wasted effort if the change doesn't fit the project's direction.

## Security issues

Do **not** open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) for the private reporting process.

## Code of Conduct

Participation in this project is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
