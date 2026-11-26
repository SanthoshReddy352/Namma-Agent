# Releasing Namma Agent — versions, tags & releases (beginner guide)

New to releases and tags? This walks through the whole thing from zero. By the end
you'll publish a version that installed Desktop Apps can **auto-detect and update
to**.

---

## The three concepts (in plain words)

1. **Version number** — a label like `2.3.0` that says "this is newer than 2.2.0".
   Namma Agent keeps it in **one file**: [`namma_agent/version.py`](../namma_agent/version.py).
   Format is **semantic versioning** `MAJOR.MINOR.PATCH`:
   - **PATCH** (`2.2.0 → 2.2.1`): bug fixes only.
   - **MINOR** (`2.2.0 → 2.3.0`): new features, nothing breaks.
   - **MAJOR** (`2.x → 3.0.0`): big/breaking changes.

2. **Git tag** — a permanent bookmark on one commit, named after the version, e.g.
   `v2.3.0`. Branches move as you commit; a tag stays pinned to that exact commit
   forever. (Convention: tag names start with `v`.)

3. **GitHub Release** — a tag **plus** a title, release notes, and downloadable
   files (the installers). This is the page users land on, and the thing the
   in-app updater reads.

**How they connect:** the app calls GitHub's API for the *latest release/tag* of
`SanthoshReddy352/Namma-Agent`, compares it to the `version.py` it's running, and shows the
**Update available** banner when the published one is higher. So: **bump
`version.py` → tag → publish a release**, and every installed app sees it.

---

## One-time setup (optional but recommended)

Install the GitHub CLI so you can release from the terminal:
- Windows: `winget install GitHub.cli`  ·  macOS: `brew install gh`  ·  Linux: see https://cli.github.com
- Then once: `gh auth login`

You can do everything from the GitHub website instead — both paths are shown below.

---

## Release, step by step

Say you're going from `2.2.0` to `2.3.0`.

### 1. Bump the version
Edit [`namma_agent/version.py`](../namma_agent/version.py):
```python
__version__ = "2.3.0"
```

### 2. Write the changelog
Add a section at the top of [`CHANGELOG.md`](../CHANGELOG.md) describing what changed
(this becomes your release notes).

### 3. Build the web UI
So the release ships it prebuilt (users without Node can run immediately):
```bash
cd namma_agent/webui && npm install && npm run build && cd ../..
```

### 4. Commit
```bash
git add -A
git commit -m "Release v2.3.0"
git push
```

### 5. Create the tag and push it
```bash
git tag -a v2.3.0 -m "Namma Agent v2.3.0"
git push --tags
```
- `-a` makes an **annotated** tag (carries a message/date — preferred for releases).
- `git push --tags` uploads the tag to GitHub (a plain `git push` does **not**).

### 6. Build the installers & publish — automatic (recommended)

**You don't need Windows + macOS + Linux machines.** Pushing the tag in step 5
triggers [`.github/workflows/release.yml`](../.github/workflows/release.yml), which
on GitHub's **free** runners:

1. builds the branded installer on **each** OS — `NammaAgentInstaller-2.3.0.exe`,
   `NammaAgent-2.3.0.dmg`, `NammaAgentInstaller-2.3.0-x86_64.AppImage`, plus a
   ready-to-run source zip,
2. builds the **Windows desktop app** installer (job `desktop`):
   `NammaAgentSetup-2.3.0.exe`, its `.blockmap`, and **`latest.yml`**. Its version
   comes from `namma_agent/version.py`.
3. **creates the GitHub Release** for the tag and attaches all of them, with
   auto-generated notes.

> **Desktop app auto-update depends on this release.** Installed desktop apps read
> `latest.yml` from the repository's **latest published release** and offer the update
> when its version is higher than theirs. So:
> - bump `version.py` for every release, since the same version is never offered again;
> - publish the release: drafts and pre-releases are ignored;
> - keep all three desktop files attached. The `.blockmap` makes later downloads
>   smaller, and `latest.yml` is what the app looks for.

So after `git push --tags`: open the repo's **Actions** tab, watch the *Release*
run finish (~10–15 min), then check **Releases** — everything is there. That's it.

> Want to test the build without releasing? Actions tab → *Release* → **Run
> workflow** (manual run): it builds and uploads the installers as downloadable
> **artifacts** instead of publishing a Release.

### 7. Build/publish manually (only if you prefer, or CI is unavailable)
On each OS you *do* have (a `.exe` needs Windows, a `.dmg` macOS, an `.AppImage`
Linux — see [installers/native/README.md](../installers/native/README.md)):
```bash
pip install pyinstaller
python installers/native/build.py        # outputs to installers/native/dist/
```
Then publish with the GitHub CLI (or drag the files into a new Release on the website):
```bash
gh release create v2.3.0 installers/native/dist/* --title "Namma Agent v2.3.0" --generate-notes
```

### 8. Verify
Open an already-installed app (one still on the old version). Within a few seconds
the **Update available** banner should appear → **Update now** pulls, reinstalls,
and relaunches.

For the **desktop app**, the banner's **Update now** (or Settings → About) downloads
`NammaAgentSetup-<new>.exe` with a progress bar, closes the app, runs the installer
with its progress window showing (no questions) and reopens it on the new version. The tray's **Check for updates…** asks on demand. To rehearse this
without publishing, see *Developing the desktop app* in the README (a local feed via
`NAMMA_DESKTOP_UPDATE_URL`).

Manual desktop build (Windows), if CI is unavailable:
```bash
cd desktop && npm ci && npm run dist     # → desktop/out/NammaAgentSetup-<ver>.exe, .blockmap, latest.yml
gh release upload v2.3.0 desktop/out/NammaAgentSetup-*.exe desktop/out/NammaAgentSetup-*.exe.blockmap desktop/out/latest.yml
```

---

## Fixing mistakes

- **Tagged the wrong commit / wrong number:**
  ```bash
  git tag -d v2.3.0                 # delete locally
  git push --delete origin v2.3.0  # delete on GitHub
  ```
  then re-tag correctly. (If a Release used it, delete the Release on GitHub first.)
- **Forgot a file in the Release:** edit the Release on GitHub and upload more assets,
  or `gh release upload v2.3.0 <file>`.
- **Bad notes:** edit the Release on GitHub any time — it doesn't change the code.

---

## Checklist

- [ ] `namma_agent/version.py` bumped
- [ ] `CHANGELOG.md` updated
- [ ] Web UI built (`npm run build`)
- [ ] Committed + pushed
- [ ] Annotated tag created + `git push --tags`
- [ ] Installers built per OS (optional) + source zip
- [ ] GitHub Release published for the tag, with assets attached
- [ ] Update banner verified on an old install

---

## Notes

- Until the **first** tag/release exists, the in-app check just reports "no update" —
  that's expected, not an error.
- The version comparison is lenient: `v2.3.0`, `2.3`, and `2.3.0` all match.
- Releasing is **publishing to the public** — anyone can download what you attach.
  Never attach `.env`, your `.venv`, or `data/*.db` (they may contain secrets or
  personal data). The build scripts already exclude these.
