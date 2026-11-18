<!--
PR title: Conventional Commits, e.g. `fix(web): reject empty chat messages`.
Squash-merge uses it as the commit subject on main. See CONTRIBUTING.md.
-->

## Summary

<!-- What does this PR change, and why? Focus on the "why" — the diff already shows the "what". -->

## Related issues

<!-- e.g. Closes #123, Relates to #456 -->

## Testing

<!-- How did you verify this works? -->
- [ ] Added or updated tests
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `mypy src/sidekick` passes
- [ ] `pytest` passes (80% coverage floor)

## Checklist

- [ ] I have read [CONTRIBUTING.md](CONTRIBUTING.md)
- [ ] My changes are focused on a single logical change
- [ ] I have not introduced new dependencies without discussion
- [ ] New env vars are catalogued in `src/sidekick/config_catalog.py` (and `.env.example` if operators set them)
- [ ] Docs updated if behavior or setup changed (README, `CLAUDE.md`, `docs/`)
