"""PyInstaller entry point for the bundled sync binary.

This file is compiled by PyInstaller into a self-contained executable
(native-app/python-bin/sync or sync.exe) that ships inside the Electron app.

End-users never interact with this directly — it is spawned by main.js.

To rebuild after modifying the Python source:
  macOS/Linux:  bash build-scripts/build-python-mac.sh
  Windows:      build-scripts\\build-python-win.bat
"""

import sys
import os

# When PyInstaller bundles the app, sys._MEIPASS points to the temp directory
# where the bundled files are extracted at runtime. Add it to sys.path so that
# scouting_db (and its dependencies) can be imported.
if getattr(sys, "frozen", False):
    bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    sys.path.insert(0, bundle_dir)

from scouting_db.native_sync import main  # noqa: E402 — must come after path fix

if __name__ == "__main__":
    main()
