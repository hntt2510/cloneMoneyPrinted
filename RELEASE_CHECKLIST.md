# Release Checklist

## Pre-Release Gates
- [ ] All milestone tests pass (G01–G12)
- [ ] Full suite: 0 failures
- [ ] Runtime smoke: PASS
- [ ] main == origin/main
- [ ] Clean worktree
- [ ] Security audit: no secrets in logs/manifests
- [ ] Deterministic E2E fixture passes twice consecutively
- [ ] Release docs match actual CLI behavior
- [ ] No generated junk committed

## Release Steps
1. Run `.venv\Scripts\python.exe -m unittest discover -s test` — must be 0 failures
2. Run `.venv\Scripts\python.exe -m compileall app test` — must be clean
3. Run `uv lock --check` — must be clean
4. Run `npm --prefix remotion run typecheck` — must be clean
5. Run golden E2E fixture twice consecutively (`.venv\Scripts\python.exe -m unittest test.services.test_golden_e2e`)
6. Tag: `git tag -a v1.0.0 -m "Release v1.0.0: full autonomous video pipeline"`
7. Push tag: `git push origin v1.0.0`
