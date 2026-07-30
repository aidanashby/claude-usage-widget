"""Build a distributable Windows zip. Run: python build.py

Produces dist/ClaudeUsageWidget-v<version>-win64.zip and a .sha256 beside it.
Used by CI and reproducible locally.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "ClaudeUsageWidget"
DIST = os.path.join(HERE, "dist")
BUILD = os.path.join(HERE, "build")


def version():
    source = open(os.path.join(HERE, "widget.pyw"), encoding="utf-8").read()
    return re.search(r'__version__ = "([^"]+)"', source).group(1)


def run(*command):
    print("$", " ".join(command))
    subprocess.run(command, check=True, cwd=HERE)


def main():
    tag = "v" + version()
    for folder in (DIST, BUILD):
        shutil.rmtree(folder, ignore_errors=True)

    icon = os.path.join(HERE, "icon.ico")
    run(sys.executable, "widget.pyw", "--write-icon", icon)

    # PyInstaller won't take a .pyw entry point, so give it a .py copy. The
    # copy is what gets frozen; widget.pyw stays the single source of truth.
    entry = os.path.join(HERE, "_entry.py")
    shutil.copyfile(os.path.join(HERE, "widget.pyw"), entry)
    try:
        run(
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--windowed",          # no console window
            "--onedir",            # not onefile: starts faster, fewer AV false positives
            "--name", NAME,
            "--icon", icon,
            entry,
        )
    finally:
        os.remove(entry)

    app = os.path.join(DIST, NAME)
    if not os.path.isdir(app):
        raise SystemExit("PyInstaller produced no %s folder" % NAME)
    shutil.copyfile(os.path.join(HERE, "README.md"), os.path.join(app, "README.md"))
    shutil.copyfile(os.path.join(HERE, "LICENSE"), os.path.join(app, "LICENSE"))

    archive = os.path.join(DIST, "%s-%s-win64.zip" % (NAME, tag))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(app):
            for filename in files:
                full = os.path.join(root, filename)
                z.write(full, os.path.relpath(full, DIST))

    digest = hashlib.sha256(open(archive, "rb").read()).hexdigest()
    with open(archive + ".sha256", "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (digest, os.path.basename(archive)))

    print("\nbuilt %s" % os.path.basename(archive))
    print("sha256 %s" % digest)
    print("size   %.1f MB" % (os.path.getsize(archive) / 1e6))


if __name__ == "__main__":
    main()
