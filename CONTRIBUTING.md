# Contributing to PortLens

Thanks for helping. Keep changes small and focused, and explain the printer problem a change solves.

## Set up

Requires Windows and Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python portlens.py          # run the app from source
python -m pytest            # run the tests
```

## Tests

- Logic that does not need a window belongs in `view_logic.py`, `settings_store.py` or `print_page.py`, with a test in `tests/`.
- UI tests in `tests/test_gui_smoke.py` drive the real window with fake scan results. They do not need a printer.
- The test page can be checked without paper: `print_page.render_preview(...)` draws it to an image. Look at the result when you change the layout.
- Tests never touch your real settings. They point `APPDATA` at a temporary folder.
- Printing to a real printer, network printers and other Windows versions cannot be covered by automated tests. If you tested on real hardware, say which printer and connection in your pull request.

## Code style

- Match the surrounding code. The project uses the standard library, Tkinter/ttk, `pywin32` and Pillow. Please do not add new runtime dependencies without discussing it in an issue first.
- Keep the scanning code (`collect_all_printer_data` and friends) separate from the window code.
- User-facing text is plain, short English.
- Status must never depend on color alone. Always include text.

## Behavior to preserve

- Scanning is read-only. Actions that change something (set default printer, print a test page) happen only when the user asks, and the test page asks for confirmation first.
- Virtual printers (PDF, XPS, OneNote and so on) never receive a test page.
- The selection and scroll position survive a refresh.
- Nothing is sent over the internet.

## Pull requests

1. Fork and create a branch from `main`.
2. Make your change and run `python -m pytest`.
3. Add a line under an `Unreleased` heading in `CHANGELOG.md` if the change is visible to users.
4. Open a pull request and fill in the template. Use fake or anonymized printer names in screenshots.

CI runs the tests on Python 3.10 and 3.13 and builds the package on every pull request.

## Reporting bugs

Use the bug report template. Remove private printer names, IP addresses and computer names from anything you share. For security problems, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Releases

Maintainers publish releases by following [docs/RELEASING.md](docs/RELEASING.md). Release files are built by GitHub Actions and are never committed to the repository.

By contributing, you agree that your contribution is licensed under the project's [MIT license](LICENSE).
