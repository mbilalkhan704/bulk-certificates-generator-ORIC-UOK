"""
Certificate Bulk Generator
===========================
A standalone desktop app (similar to Canva's "Bulk Create") that:
  1. Loads a CSV file and lets you pick which column holds the name.
  2. Loads a certificate template image (any size, tuned for ~2000x1414).
  3. Lets you drag-position the name directly on a live preview, or type
     exact pixel coordinates.
  4. Lets you pick a font from a bundled "fonts" folder (Great Vibes by
     default) or load any other .ttf/.otf file on the fly.
  5. Generates one file per CSV row (PDF, PNG, or JPG - your choice) with
     the name burned in, saved into a "certificates" subfolder of the
     chosen output directory, named after the person (e.g. "Muhammad
     bilal khan" -> "Muhammad_Bilal_Khan").

Run directly with:  python certificate_generator.py
See README.md in this folder for how to bundle it into a single .exe.
"""

import os
import sys
import csv
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from PIL import Image, ImageDraw, ImageFont, ImageTk


# ---------------------------------------------------------------------------
# Helpers for locating bundled resources (works both when run as a plain
# .py script AND when frozen into a onefile PyInstaller .exe).
# ---------------------------------------------------------------------------
def resource_path(relative_path: str) -> str:
    """Return an absolute path to a resource, whether running from source
    or from inside a PyInstaller onefile bundle."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


FONTS_DIR = resource_path("fonts")
MAX_PREVIEW_W = 860
MAX_PREVIEW_H = 610
SAMPLE_TEXT_FALLBACK = "Sample Name"
FONT_EXTS = (".ttf", ".otf")


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name or "unnamed"


def name_to_filename(raw_name: str) -> str:
    """Turn a raw CSV name into a filename stem: each word capitalized,
    words joined with underscores. e.g. 'bilal' -> 'Bilal',
    'Muhammad bilal khan' -> 'Muhammad_Bilal_Khan'."""
    cleaned = sanitize_filename(raw_name)
    words = cleaned.split(" ")
    words = [w.capitalize() for w in words if w]
    return "_".join(words) or "Unnamed"


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class CertificateApp(tk.Tk):
    LOAD_FONT_SENTINEL = "➕ Load font file (.ttf/.otf)..."

    def __init__(self):
        super().__init__()
        self.title("Certificate Bulk Generator")
        self.geometry("1320x760")
        self.minsize(1150, 660)

        # ---- state -----------------------------------------------------
        self.csv_path = None
        self.csv_headers = []
        self.csv_rows = []

        self.cert_image = None          # full-resolution PIL.Image (RGBA)
        self.preview_base = None        # scaled-down PIL.Image for canvas
        self.preview_scale = 1.0
        self.tk_preview_img = None      # keep a reference (avoid GC)

        self.available_fonts = {}       # display name -> filepath

        self.name_col = tk.StringVar()
        self.pos_x = tk.IntVar(value=1000)
        self.pos_y = tk.IntVar(value=700)
        self.font_size = tk.IntVar(value=90)
        self.font_color = "#1a1a1a"
        self.align_var = tk.StringVar(value="center")
        self.font_choice = tk.StringVar()
        self.output_dir = None
        self.output_format = tk.StringVar(value="PDF")

        self._dragging = False

        self._ensure_fonts_dir()
        self._scan_fonts()
        self._build_ui()
        self._refresh_font_dropdown()

    # ------------------------------------------------------------------
    # Font discovery
    # ------------------------------------------------------------------
    def _ensure_fonts_dir(self):
        try:
            os.makedirs(FONTS_DIR, exist_ok=True)
        except Exception:
            pass

    def _scan_fonts(self):
        self.available_fonts.clear()
        if os.path.isdir(FONTS_DIR):
            for fname in sorted(os.listdir(FONTS_DIR)):
                if fname.lower().endswith(FONT_EXTS):
                    display = os.path.splitext(fname)[0]
                    self.available_fonts[display] = os.path.join(FONTS_DIR, fname)

    def _default_font_name(self):
        for name in self.available_fonts:
            if "greatvibes" in name.lower().replace(" ", "").replace("-", ""):
                return name
        return next(iter(self.available_fonts), None)

    def _refresh_font_dropdown(self):
        names = list(self.available_fonts.keys())
        values = names + [self.LOAD_FONT_SENTINEL]
        self.font_combo["values"] = values
        default = self._default_font_name()
        if default and not self.font_choice.get():
            self.font_choice.set(default)
        elif not names:
            self.font_choice.set("")
            messagebox.showwarning(
                "No fonts found",
                "No .ttf/.otf files were found in the 'fonts' folder next to "
                "this program.\n\nPut GreatVibes-Regular.ttf (and any other "
                "fonts you want available by default) into that folder, "
                "then restart the app. You can also use 'Load font file...' "
                "for a one-off font.",
            )

    def _on_font_selected(self, _event=None):
        if self.font_choice.get() == self.LOAD_FONT_SENTINEL:
            path = filedialog.askopenfilename(
                title="Choose a font file",
                filetypes=[("Font files", "*.ttf *.otf")],
            )
            if not path:
                # revert to previous / default selection
                self.font_choice.set(self._default_font_name() or "")
                return
            display = os.path.splitext(os.path.basename(path))[0]
            self.available_fonts[display] = path
            self._refresh_font_dropdown()
            self.font_choice.set(display)
        self._redraw_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        left = ttk.Frame(root, width=380)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        right = ttk.Frame(root)
        right.pack(side="left", fill="both", expand=True)

        # ---- 1. CSV -----------------------------------------------------
        box = self._section(left, "1. CSV data")
        ttk.Button(box, text="Upload CSV...", command=self._upload_csv).pack(fill="x")
        self.csv_label = ttk.Label(box, text="No file selected", foreground="#666")
        self.csv_label.pack(fill="x", pady=(4, 8))

        ttk.Label(box, text="Column to use as the name:").pack(anchor="w")
        self.name_combo = ttk.Combobox(box, textvariable=self.name_col, state="readonly")
        self.name_combo.pack(fill="x", pady=(2, 0))
        self.name_combo.bind("<<ComboboxSelected>>", lambda e: self._redraw_preview())

        # ---- 2. Certificate image ---------------------------------------
        box = self._section(left, "2. Certificate template")
        ttk.Button(box, text="Upload certificate image...", command=self._upload_image).pack(fill="x")
        self.img_label = ttk.Label(box, text="No image selected", foreground="#666")
        self.img_label.pack(fill="x", pady=(4, 0))

        # ---- 3. Position -------------------------------------------------
        box = self._section(left, "3. Name position (pixels, on the original image)")
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="X:").pack(side="left")
        x_spin = ttk.Spinbox(row, from_=0, to=20000, textvariable=self.pos_x, width=8,
                              command=self._redraw_preview)
        x_spin.pack(side="left", padx=(4, 14))
        ttk.Label(row, text="Y:").pack(side="left")
        y_spin = ttk.Spinbox(row, from_=0, to=20000, textvariable=self.pos_y, width=8,
                              command=self._redraw_preview)
        y_spin.pack(side="left", padx=(4, 0))
        for w in (x_spin, y_spin):
            w.bind("<KeyRelease>", lambda e: self._redraw_preview())
        ttk.Label(box, text="Tip: click and drag directly on the preview →",
                  foreground="#666").pack(anchor="w", pady=(4, 0))

        # ---- 4. Font -------------------------------------------------
        box = self._section(left, "4. Font & style")
        ttk.Label(box, text="Font:").pack(anchor="w")
        self.font_combo = ttk.Combobox(box, textvariable=self.font_choice, state="readonly")
        self.font_combo.pack(fill="x", pady=(2, 8))
        self.font_combo.bind("<<ComboboxSelected>>", self._on_font_selected)

        row = ttk.Frame(box)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Size:").pack(side="left")
        size_spin = ttk.Spinbox(row, from_=6, to=1000, textvariable=self.font_size, width=6,
                                 command=self._redraw_preview)
        size_spin.pack(side="left", padx=(4, 14))
        size_spin.bind("<KeyRelease>", lambda e: self._redraw_preview())

        ttk.Label(row, text="Color:").pack(side="left")
        self.color_swatch = tk.Label(row, text="  ", bg=self.font_color, relief="sunken", width=3)
        self.color_swatch.pack(side="left", padx=(4, 4))
        ttk.Button(row, text="Choose...", command=self._choose_color).pack(side="left")

        row2 = ttk.Frame(box)
        row2.pack(fill="x")
        ttk.Label(row2, text="Alignment:").pack(side="left")
        for val, label in (("left", "Left"), ("center", "Center"), ("right", "Right")):
            ttk.Radiobutton(row2, text=label, value=val, variable=self.align_var,
                             command=self._redraw_preview).pack(side="left", padx=4)

        # ---- 5. Output -------------------------------------------------
        box = self._section(left, "5. Output & generate")
        ttk.Button(box, text="Choose output folder...", command=self._choose_output_dir).pack(fill="x")
        self.out_label = ttk.Label(box, text="No output folder selected", foreground="#666")
        self.out_label.pack(fill="x", pady=(2, 0))
        ttk.Label(box, text="A 'certificates' subfolder will be created there.",
                  foreground="#666").pack(anchor="w", pady=(0, 8))

        ttk.Label(box, text='Each file is named after the row\'s name, e.g. '
                             '"Muhammad bilal khan" → "Muhammad_Bilal_Khan".',
                  foreground="#666", wraplength=340, justify="left").pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Save as:").pack(side="left")
        ttk.Combobox(row, textvariable=self.output_format, state="readonly", width=8,
                     values=["PDF", "PNG", "JPG"]).pack(side="left", padx=4)

        self.generate_btn = ttk.Button(box, text="Generate all certificates",
                                        command=self._start_generation)
        self.generate_btn.pack(fill="x", pady=(10, 6))
        self.progress = ttk.Progressbar(box, mode="determinate")
        self.progress.pack(fill="x")
        self.status_label = ttk.Label(box, text="", foreground="#666")
        self.status_label.pack(fill="x", pady=(4, 0))

        # ---- Preview canvas ----------------------------------------------
        ttk.Label(right, text="Live preview (click & drag to position the name)",
                  font=("", 10, "bold")).pack(anchor="w")
        self.canvas = tk.Canvas(right, bg="#dedede", highlightthickness=1,
                                 highlightbackground="#aaaaaa")
        self.canvas.pack(fill="both", expand=True, pady=(6, 0))
        self.canvas.bind("<Button-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)

    def _section(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill="x", pady=(0, 10))
        return frame

    # ------------------------------------------------------------------
    # CSV handling
    # ------------------------------------------------------------------
    def _upload_csv(self):
        path = filedialog.askopenfilename(title="Choose a CSV file",
                                           filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                rows = list(reader)
        except Exception as exc:
            messagebox.showerror("Could not read CSV", str(exc))
            return
        if not headers or not rows:
            messagebox.showerror("Empty CSV", "That file has no columns or no data rows.")
            return

        self.csv_path = path
        self.csv_headers = headers
        self.csv_rows = rows
        self.csv_label.config(text=f"{os.path.basename(path)}  ({len(rows)} rows)")
        self.name_combo["values"] = headers

        guess = next((h for h in headers if h.strip().lower() == "name"), headers[0])
        self.name_col.set(guess)
        self._redraw_preview()

    # ------------------------------------------------------------------
    # Image handling
    # ------------------------------------------------------------------
    def _upload_image(self):
        path = filedialog.askopenfilename(
            title="Choose a certificate image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.webp")],
        )
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Could not open image", str(exc))
            return

        self.cert_image = img
        w, h = img.size
        note = ""
        expected_ratio = 2000 / 1414
        ratio = w / h if h else 0
        if abs(ratio - expected_ratio) > 0.08:
            note = "  (unusual proportions for a certificate - double check it)"
        self.img_label.config(text=f"{os.path.basename(path)}  {w}x{h}px{note}")

        # build the scaled-down preview base image
        scale = min(MAX_PREVIEW_W / w, MAX_PREVIEW_H / h, 1.0)
        self.preview_scale = scale
        preview_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        self.preview_base = img.resize(preview_size, Image.LANCZOS)
        self.canvas.config(width=preview_size[0], height=preview_size[1])

        # default position: roughly centered
        self.pos_x.set(int(w * 0.5))
        self.pos_y.set(int(h * 0.5))
        self._redraw_preview()

    # ------------------------------------------------------------------
    # Color / output dir
    # ------------------------------------------------------------------
    def _choose_color(self):
        rgb, hexcode = colorchooser.askcolor(color=self.font_color, title="Choose text color")
        if hexcode:
            self.font_color = hexcode
            self.color_swatch.config(bg=hexcode)
            self._redraw_preview()

    def _choose_output_dir(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output_dir = path
            self.out_label.config(text=path)

    # ------------------------------------------------------------------
    # Preview drawing / dragging
    # ------------------------------------------------------------------
    def _get_sample_text(self):
        col = self.name_col.get()
        if self.csv_rows and col in self.csv_headers:
            val = self.csv_rows[0].get(col, "")
            if val:
                return val
        return SAMPLE_TEXT_FALLBACK

    def _get_selected_font_path(self):
        return self.available_fonts.get(self.font_choice.get())

    def _load_font(self, size):
        path = self._get_selected_font_path()
        if path:
            try:
                return ImageFont.truetype(path, max(1, size))
            except Exception:
                pass
        return ImageFont.load_default()

    def _draw_aligned_text(self, draw, text, font, x, y, color, align):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if align == "center":
            draw_x = x - w / 2 - bbox[0]
        elif align == "right":
            draw_x = x - w - bbox[0]
        else:
            draw_x = x - bbox[0]
        draw_y = y - h / 2 - bbox[1]
        draw.text((draw_x, draw_y), text, font=font, fill=color)

    def _redraw_preview(self):
        if self.preview_base is None:
            return
        img = self.preview_base.copy()
        draw = ImageDraw.Draw(img)

        scaled_size = max(1, round(self.font_size.get() * self.preview_scale))
        font = self._load_font(scaled_size)
        text = self._get_sample_text()

        px = self.pos_x.get() * self.preview_scale
        py = self.pos_y.get() * self.preview_scale

        try:
            self._draw_aligned_text(draw, text, font, px, py, self.font_color, self.align_var.get())
        except Exception:
            pass

        # crosshair marker showing the anchor point
        draw.line([(px - 8, py), (px + 8, py)], fill="red", width=1)
        draw.line([(px, py - 8), (px, py + 8)], fill="red", width=1)

        self.tk_preview_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_preview_img)

    def _canvas_to_image_coords(self, cx, cy):
        if self.preview_scale <= 0:
            return 0, 0
        x = int(round(cx / self.preview_scale))
        y = int(round(cy / self.preview_scale))
        if self.cert_image:
            w, h = self.cert_image.size
            x = max(0, min(w, x))
            y = max(0, min(h, y))
        return x, y

    def _on_canvas_press(self, event):
        if self.preview_base is None:
            return
        self._dragging = True
        x, y = self._canvas_to_image_coords(event.x, event.y)
        self.pos_x.set(x)
        self.pos_y.set(y)
        self._redraw_preview()

    def _on_canvas_drag(self, event):
        if not self._dragging or self.preview_base is None:
            return
        x, y = self._canvas_to_image_coords(event.x, event.y)
        self.pos_x.set(x)
        self.pos_y.set(y)
        self._redraw_preview()

    # ------------------------------------------------------------------
    # Bulk generation
    # ------------------------------------------------------------------
    def _start_generation(self):
        if not self.csv_rows:
            messagebox.showerror("Missing CSV", "Please upload a CSV file first.")
            return
        if self.cert_image is None:
            messagebox.showerror("Missing image", "Please upload a certificate image first.")
            return
        if not self.name_col.get():
            messagebox.showerror("Missing column", "Please select the name column.")
            return
        if not self.output_dir:
            messagebox.showerror("Missing output folder", "Please choose an output folder.")
            return
        if not self._get_selected_font_path():
            messagebox.showerror("Missing font", "Please select a valid font.")
            return

        self.generate_btn.config(state="disabled")
        self.progress.config(maximum=len(self.csv_rows), value=0)
        self.status_label.config(text="Generating...")

        thread = threading.Thread(target=self._generate_worker, daemon=True)
        thread.start()

    def _generate_worker(self):
        col = self.name_col.get()
        font_path = self._get_selected_font_path()
        font = ImageFont.truetype(font_path, self.font_size.get())
        fmt = self.output_format.get()
        ext = {"PDF": ".pdf", "PNG": ".png", "JPG": ".jpg"}[fmt]

        dest_dir = os.path.join(self.output_dir, "certificates")
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception as exc:
            self.after(0, lambda: self._generation_failed(str(exc)))
            return

        done, skipped = 0, []
        used_names = {}

        for i, row in enumerate(self.csv_rows, start=1):
            raw_name = (row.get(col) or "").strip()
            if not raw_name:
                skipped.append(f"row {i} (empty name)")
                self._report_progress(i)
                continue

            out_img = self.cert_image.copy()
            draw = ImageDraw.Draw(out_img)
            self._draw_aligned_text(draw, raw_name, font, self.pos_x.get(),
                                     self.pos_y.get(), self.font_color, self.align_var.get())

            base = name_to_filename(raw_name)
            count = used_names.get(base, 0)
            used_names[base] = count + 1
            filename = base if count == 0 else f"{base}_{count}"
            out_path = os.path.join(dest_dir, filename + ext)

            try:
                if fmt == "PDF":
                    out_img.convert("RGB").save(out_path, "PDF", resolution=300.0)
                elif fmt == "JPG":
                    out_img.convert("RGB").save(out_path, "JPEG", quality=95)
                else:
                    out_img.save(out_path, "PNG")
                done += 1
            except Exception as exc:
                skipped.append(f"row {i} ({exc})")

            self._report_progress(i)

        self.after(0, lambda: self._generation_done(done, skipped, dest_dir))

    def _generation_failed(self, message):
        self.generate_btn.config(state="normal")
        self.status_label.config(text="Failed.")
        messagebox.showerror("Could not create output folder", message)

    def _report_progress(self, i):
        self.after(0, lambda: self.progress.config(value=i))

    def _generation_done(self, done, skipped, dest_dir):
        self.generate_btn.config(state="normal")
        self.status_label.config(text=f"Done: {done} generated, {len(skipped)} skipped.")
        msg = f"Generated {done} certificate(s) ({self.output_format.get()}) to:\n{dest_dir}"
        if skipped:
            preview = "\n".join(skipped[:10])
            more = "" if len(skipped) <= 10 else f"\n...and {len(skipped) - 10} more"
            msg += f"\n\nSkipped {len(skipped)}:\n{preview}{more}"
        messagebox.showinfo("Generation complete", msg)


if __name__ == "__main__":
    app = CertificateApp()
    app.mainloop()
    