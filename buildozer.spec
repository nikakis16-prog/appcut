[app]
title = Cut Optimizer
package.name = cutoptimizer
package.domain = org.cutshop
source.dir = .
source.include_exts = py,kv
version = 0.1
# προαιρετικό icon: icon.filename = icons/app_icon.png

requirements = python3,kivy==2.3.0,pillow==10.4.0
orientation = portrait
fullscreen = 0
log_level = 2

# Αν θες μόνο 64-bit ARM (πιο γρήγορο build)
android.archs = arm64-v8a
# Ελάχιστη/στόχος API (μπορείς να τα αυξήσεις αν χρειαστεί)
android.minapi = 24
android.api = 33
# Αποδοχή αδειών του Android SDK
android.accept_sdk_license = True

# Αν θέλεις ελληνικό όνομα πακέτου στο τηλέφωνο:
# presplash.filename = %(source.dir)s/presplash.png

# --- Μην αλλάξεις κάτι από κάτω χωρίς λόγο ---
[buildozer]
warn_on_root = 0
