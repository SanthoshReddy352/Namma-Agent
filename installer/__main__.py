"""`python -m installer` -> the modern React installer (pywebview window).

Use `--cli` for a no-GUI install (same flow, streamed to the terminal) on headless
boxes.
"""
import sys

if "--cli" in sys.argv:
    from installer import core
    dest = core.default_install_dir()
    core.bootstrap(dest, print)
    core.create_shortcuts(dest, print)
    print(f"\nInstalled to {dest}. Run the first-time setup:")
    print(f'  "{core.venv_python(dest)}" -m namma_agent --setup')
else:
    from installer.app import main
    main()
