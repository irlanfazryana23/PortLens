# Releasing PortLens

Releases are built and published by GitHub Actions when a tag such as `v1.0.0` is pushed. The workflow is `.github/workflows/release.yml`.

## One-time setup: first push

1. On GitHub, create an **empty** repository named `PortLens` (no README, license or .gitignore).
2. From the project folder:

   ```powershell
   git remote add origin https://github.com/irlanfazryana23/PortLens.git
   git push -u origin main
   ```

3. Open the **Actions** tab and confirm the **CI** workflow passes on `main`.
4. Optional but recommended, under **Settings > Branches**, protect `main` and require the CI checks.

If the release workflow later fails with a permissions error, open **Settings > Actions > General > Workflow permissions** and choose **Read and write permissions**.

## Publish a release

1. Update **both** of these for the new version:
   - `VERSION` (for example `1.1.0`).
   - `CHANGELOG.md`: add a `## [1.1.0] - YYYY-MM-DD` section above the previous one. Its text becomes the release notes.
2. Run the checks locally:

   ```powershell
   python -m pytest
   powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
   ```

   The tests also fail if `VERSION` and the top changelog entry disagree.
3. Commit and push to `main`, then wait for CI to pass:

   ```powershell
   git add VERSION CHANGELOG.md
   git commit -m "Release 1.1.0"
   git push
   ```

4. Tag the commit and push the tag:

   ```powershell
   git tag v1.1.0
   git push origin v1.1.0
   ```

5. Open the **Actions** tab and watch **Release**. When it finishes, the **Releases** page has a new release with:
   - `PortLens-1.1.0-portable.zip`
   - `PortLens-1.1.0.exe`
   - `SHA256SUMS.txt`

The workflow stops with a clear message if the tag does not match `VERSION`, if a test fails, or if the package check fails. Nothing is published in those cases.

### Creating the release in the GitHub web page instead

If you create the release yourself on the Releases page (with the tag `v1.1.0` pointing at the right commit), the tag push still starts the workflow. It then attaches the files to your release instead of creating a new one, and your release notes are kept.

## First release checklist (1.0.0)

- [ ] `VERSION` is `1.0.0` and `CHANGELOG.md` has a `## [1.0.0]` section.
- [ ] CI is green on `main`.
- [ ] `git tag v1.0.0` and `git push origin v1.0.0`.
- [ ] Download the ZIP from the release, check it against `SHA256SUMS.txt`, and start the EXE on a clean Windows machine.

## Notes

- The EXE is **not code-signed**, so Windows SmartScreen may warn users. The release notes say so. Signing needs a certificate; never commit certificates or keys (the ignore rules exclude common key files).
- Only `VERSION` sets the version. The build derives the EXE name, the Windows file properties and the ZIP name from it.
- To fix a bad release, delete the release and the tag on GitHub, fix the problem, and tag again. Prefer publishing a new patch version once people have downloaded the files.
- Update `assets/mark.png`, then run `python scripts/make_icons.py` to regenerate the icon and logo.
