# Certificate Bulk Generator

A standalone desktop app that works like Canva's "Bulk Create": upload a CSV,
pick the name column, upload a certificate template, drag the name into
place, pick a font, and generate one image per row.

## 1. Set up

```
pip install -r requirements.txt
```

`tkinter` is not in requirements.txt because it ships with standard Python
installers on Windows and macOS. On some Linux distros you may need to
install it separately, e.g. `sudo apt install python3-tk`.

## 2. Add your fonts

Create a `fonts` folder right next to `certificate_generator.py` (the app
will also auto-create an empty one on first run) and drop `.ttf`/`.otf`
files into it. Put your Great Vibes file in there, e.g.:

```
fonts/
  GreatVibes-Regular.ttf
```

Any font you place in that folder shows up automatically in the app's font
dropdown, with Great Vibes selected by default (the app matches on the name
"great vibes" case-insensitively). Add as many other fonts as you like -
they all get bundled into the exe later with no internet download required
at runtime. Users can also click "Load font file..." in the dropdown at
runtime to use a one-off font that isn't in that folder.

## 3. Run it and test

```
python certificate_generator.py
```

Try uploading a sample CSV, a certificate image, dragging the name around,
and generating a batch, before you bundle anything.

## 4. Bundle into a single .exe

```
pip install pyinstaller

# Windows (note the semicolon):
pyinstaller --onefile --windowed --name CertificateGenerator --add-data "fonts;fonts" certificate_generator.py

# macOS / Linux (note the colon):
pyinstaller --onefile --windowed --name CertificateGenerator --add-data "fonts:fonts" certificate_generator.py
```

- `--onefile` produces a single executable.
- `--windowed` stops a console window from popping up alongside the GUI.
- `--add-data "fonts;fonts"` bundles your fonts folder inside the exe so it
  never needs to be downloaded or shipped separately - the app's
  `resource_path()` helper finds it correctly whether it's running from
  source or from inside the bundle.
- Add `--icon=youricon.ico` if you want a custom taskbar icon.

The finished executable will be in `dist/CertificateGenerator.exe`. It is
fully self-contained - the person running it doesn't need Python, Pillow, or
the fonts installed on their machine.

## Notes on how positioning works

- X/Y are pixel coordinates on the *original, full-resolution* certificate
  image, not the shrunk-down preview. The app converts between the two
  automatically, so a position you set by dragging on the preview lines up
  exactly with the final output.
- The app was built assuming certificates around 2000x1414px (a common
  export size), but it works with any image size - it just warns you if the
  proportions look unusual.
- Vertical placement is always centered on the Y value you set; horizontal
  alignment (left/center/right) is controlled by the alignment radio
  buttons, which is the standard way name-plate certificates are laid out.

## Output files

Certificates are saved into a `certificates` subfolder created inside
whatever output directory you choose - e.g. if you pick `C:\Output`, files
land in `C:\Output\certificates\`. Use the "Save as" dropdown to choose
PDF, PNG, or JPG.

Each filename is built from the row's name: every word is capitalized and
words are joined with underscores. For example:

- `bilal` → `Bilal.pdf` (or `.png` / `.jpg`, depending on your choice)
- `Muhammad bilal khan` → `Muhammad_Bilal_Khan.pdf`

If two rows produce the same filename, later ones get `_1`, `_2`, etc.
appended so nothing gets overwritten.