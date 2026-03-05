"""dmgbuild settings for Scouting Stats.

Used by `dmgbuild` to create a styled DMG with a background image,
icon positioning, and an Applications shortcut.

Environment variables (set by the Makefile):
    APP_PATH        Path to the built .app bundle
    DMG_BACKGROUND  Path to the background image (retina @2x PNG)
"""

import os

app_path = os.environ["APP_PATH"]
background = os.environ["DMG_BACKGROUND"]
retina_background = os.environ.get("DMG_BACKGROUND_RETINA", background)

# Volume name shown in Finder title bar
volume_name = "Scouting Stats"

# DMG format: UDBZ = bzip2 compressed (smaller than UDZO)
format = "UDBZ"

# Window size must match the background image (logical points, not pixels)
window_rect = ((200, 120), (660, 400))

# Icon view settings
icon_size = 120
text_size = 14

# Background image (1x for standard, 2x for retina)
background = background
retina_background = retina_background

# Contents: app on the left, Applications alias on the right
files = [app_path]
symlinks = {"Applications": "/Applications"}

icon_locations = {
    "Scouting Stats.app": (170, 175),
    "Applications": (490, 175),
}

# Hide file extensions in the DMG window
hide_extensions = ["Scouting Stats.app"]
