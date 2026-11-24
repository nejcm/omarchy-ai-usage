# Agent Instructions

## Release

When asked to bump, release, or "commit and push" a version:

1. Bump `version` in `manifest.json` (semver: `fix` → patch, `feat` → minor).
2. Commit the work as Conventional Commits, then a separate `chore: release vX.Y.Z` commit containing only the manifest bump.
3. Push `main` to `origin`.
4. Update the marketplace verification issue to the new release commit:
   - Find the open `[Verify]: AI usage — newer upstream commit` issue in `omacom/omarchy-plugin-marketplace`
     (`gh search issues --author nejcm --repo omacom/omarchy-plugin-marketplace --state open`).
   - Replace the SHA under `### Target commit` in its body with the full SHA of the release commit
     (`gh issue edit <n> -R omacom/omarchy-plugin-marketplace --body-file <file>`); keep the rest of the body unchanged.
   - If no open verify issue exists, ask before opening a new one.
