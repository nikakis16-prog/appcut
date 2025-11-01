# main.py
from kivy.app import App
from kivy.lang import Builder
from kivy.properties import (
    ListProperty, NumericProperty, BooleanProperty, ObjectProperty
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, Line
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.textinput import TextInput
from kivy.metrics import dp

from optimizer import optimize_cut_multi_start
from PIL import Image, ImageDraw, ImageFont
import os
import json


# --------- Utility ---------
def pastel_rgb(name: str):
    rnd = hash(name) & 0xFFFFFF
    r = (120 + (rnd & 0x3F)) / 255.0
    g = (120 + ((rnd >> 6) & 0x3F)) / 255.0
    b = (120 + ((rnd >> 12) & 0x3F)) / 255.0
    return r, g, b


# --------- Interactive Sheet View ---------
class SheetView(Widget):
    sheet_w = NumericProperty(0)     # mm
    sheet_h = NumericProperty(0)     # mm
    pieces  = ListProperty([])       # list of dict {name,x,y,w,h,rot,last_ok_x,last_ok_y}
    grid_on = BooleanProperty(False)
    snap_mm = NumericProperty(10)

    _selected_index = NumericProperty(-1)
    _drag_offset = ObjectProperty((0.0, 0.0))  # (dx,dy) σε mm
    _origin_px = ObjectProperty((0.0, 0.0))    # (ox,oy) σε px
    _scale = NumericProperty(1.0)

    def on_size(self, *args): self.redraw()
    def on_pos(self, *args): self.redraw()
    def on_pieces(self, *args): self.redraw()
    def on_sheet_w(self, *args): self.redraw()
    def on_sheet_h(self, *args): self.redraw()
    def on_grid_on(self, *args): self.redraw()

    # ----- γεωμετρία προβολής -----
    def _layout_metrics(self):
        margin = dp(8)
        avail_w = max(1, self.width - 2*margin)
        avail_h = max(1, self.height - 2*margin)
        sx = avail_w / float(self.sheet_w or 1)
        sy = avail_h / float(self.sheet_h or 1)
        scale = min(sx, sy)
        ox = self.x + margin
        oy = self.y + margin
        self._origin_px = (ox, oy)
        self._scale = scale
        return ox, oy, scale

    def _px_to_mm(self, px, py):
        ox, oy = self._origin_px
        s = self._scale
        return (px - ox) / s, (py - oy) / s

    def _mm_to_px_rect(self, x, y, w, h):
        ox, oy, s = self._origin_px[0], self._origin_px[1], self._scale
        return (ox + x*s, oy + y*s, w*s, h*s)

    # ----- έλεγχοι εγκυρότητας -----
    @staticmethod
    def _overlap(a, b):
        ax2 = a["x"] + a["w"]; ay2 = a["y"] + a["h"]
        bx2 = b["x"] + b["w"]; by2 = b["y"] + b["h"]
        return not (ax2 <= b["x"] or bx2 <= a["x"] or ay2 <= b["y"] or by2 <= a["y"])

    def _is_valid(self, idx, new_x, new_y, new_w, new_h):
        if new_x < 0 or new_y < 0: return False
        if new_x + new_w > self.sheet_w: return False
        if new_y + new_h > self.sheet_h: return False
        test = {"x": new_x, "y": new_y, "w": new_w, "h": new_h}
        for j, other in enumerate(self.pieces):
            if j == idx: continue
            if self._overlap(test, other):
                return False
        return True

    def _snap_val(self, v):
        step = max(1, int(self.snap_mm))
        return round(v / step) * step

    # ----- σχεδίαση -----
    def redraw(self):
        if self.sheet_w <= 0 or self.sheet_h <= 0:
            return
        ox, oy, s = self._layout_metrics()
        self.canvas.clear()
        with self.canvas:
            # φύλλο
            Color(1,1,1,1)
            Rectangle(pos=(ox,oy), size=(self.sheet_w*s, self.sheet_h*s))
            Color(0,0,0,1)
            Line(rectangle=(ox,oy,self.sheet_w*s,self.sheet_h*s), width=1.4)

            # grid
            if self.grid_on:
                Color(0.8,0.8,0.8,1)
                spacing = 100
                gx = spacing
                while gx < self.sheet_w:
                    Rectangle(pos=(ox + gx*s, oy), size=(1, self.sheet_h*s))
                    gx += spacing
                gy = spacing
                while gy < self.sheet_h:
                    Rectangle(pos=(ox, oy + gy*s), size=(self.sheet_w*s, 1))
                    gy += spacing

            # κομμάτια
            for i, p in enumerate(self.pieces):
                r,g,b = pastel_rgb(p["name"])
                Color(r,g,b,1)
                px,py,w,h = self._mm_to_px_rect(p["x"], p["y"], p["w"], p["h"])
                Rectangle(pos=(px,py), size=(w,h))
                Color(0,0,0,1)
                Line(rectangle=(px,py,w,h), width=2 if i == self._selected_index else 1)

    # ----- χειρισμός αφής -----
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos): return False
        mx,my = self._px_to_mm(*touch.pos)
        hit = -1
        for i in range(len(self.pieces)-1, -1, -1):
            p = self.pieces[i]
            if p["x"] <= mx <= p["x"]+p["w"] and p["y"] <= my <= p["y"]+p["h"]:
                hit = i
                break
        if hit >= 0:
            self._selected_index = hit
            dx = mx - self.pieces[hit]["x"]
            dy = my - self.pieces[hit]["y"]
            self._drag_offset = (dx, dy)
            self.redraw()
            return True
        return False

    def on_touch_move(self, touch):
        if self._selected_index < 0: return False
        mx,my = self._px_to_mm(*touch.pos)
        p = self.pieces[self._selected_index]
        dx,dy = self._drag_offset
        cand_x = mx - dx
        cand_y = my - dy

        # clamp
        cand_x = max(0, min(cand_x, self.sheet_w - p["w"]))
        cand_y = max(0, min(cand_y, self.sheet_h - p["h"]))

        # snap αν το grid είναι ON
        if self.grid_on:
            cand_x = self._snap_val(cand_x)
            cand_y = self._snap_val(cand_y)
            cand_x = max(0, min(cand_x, self.sheet_w - p["w"]))
            cand_y = max(0, min(cand_y, self.sheet_h - p["h"]))

        if self._is_valid(self._selected_index, cand_x, cand_y, p["w"], p["h"]):
            p["x"], p["y"] = cand_x, cand_y
            p["last_ok_x"], p["last_ok_y"] = cand_x, cand_y
        else:
            p["x"], p["y"] = p.get("last_ok_x", p["x"]), p.get("last_ok_y", p["y"])

        self.redraw()
        return True

    def on_touch_up(self, touch):
        return self._selected_index >= 0

    # ----- κουμπί περιστροφής -----
    def rotate_selected(self):
        i = self._selected_index
        if i < 0: return
        p = self.pieces[i]
        new_w, new_h = p["h"], p["w"]
        nx = min(p["x"], self.sheet_w - new_w)
        ny = min(p["y"], self.sheet_h - new_h)

        if self._is_valid(i, nx, ny, new_w, new_h):
            p["w"], p["h"] = new_w, new_h
            p["x"], p["y"] = nx, ny
            p["rot"] = not p["rot"]
            p["last_ok_x"], p["last_ok_y"] = nx, ny
            self.redraw()

    # ----- export PNG αυτού του φύλλου -----
    def export_png(self, out_path):
        W, H = self.sheet_w, self.sheet_h
        target_w = 1500
        scale = target_w / float(W)
        target_h = int(H * scale)

        img = Image.new("RGB", (target_w+2, target_h+2), (255,255,255))
        d = ImageDraw.Draw(img)

        d.rectangle([(1,1),(1+W*scale,1+H*scale)], outline=(0,0,0), width=4)

        if self.grid_on:
            spacing = 100
            gx = spacing
            while gx < W:
                d.line([(gx*scale+1,1),(gx*scale+1,H*scale+1)], fill=(220,220,220), width=1)
                gx += spacing
            gy = spacing
            while gy < H:
                d.line([(1,gy*scale+1),(W*scale+1,gy*scale+1)], fill=(220,220,220), width=1)
                gy += spacing

        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()

        for p in self.pieces:
            x1 = p["x"]*scale + 1
            y1 = p["y"]*scale + 1
            x2 = (p["x"]+p["w"])*scale + 1
            y2 = (p["y"]+p["h"])*scale + 1
            rnd = hash(p["name"]) & 0xFFFFFF
            col = (
                120 + (rnd & 0x3F),
                120 + ((rnd>>6) & 0x3F),
                120 + ((rnd>>12)&0x3F)
            )
            d.rectangle([(x1,y1),(x2,y2)], fill=col, outline=(0,0,0), width=2)
            label = f"{p['name']}\n{p['w']}x{p['h']}"
            cx = (x1+x2)/2; cy = (y1+y2)/2
            for line in label.split("\n"):
                tw, th = d.textsize(line, font=font)
                d.text((cx - tw/2, cy - th/2), line, fill=(0,0,0), font=font)
                cy += th


# --------- Ένα panel ανά φύλλο ---------
class SheetPanel(BoxLayout):
    """
    - Header με στατιστικά
    - Toolbar (Grid toggle / Snap / Rotate / Export / Share)
    - SheetView (interactive)
    """
    def __init__(self, index, sheet_w, sheet_h, placed_list, parent_app, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, padding=10, spacing=6, **kwargs)
        self.height = dp(400)
        self.index = index
        self.parent_app = parent_app

        used = sum(p["w"]*p["h"] for p in placed_list)
        total = sheet_w * sheet_h
        util = (100.0*used/total) if total else 0.0
        scrap = total - used

        self.header = Label(
            text=f"Φύλλο {index} | {sheet_w}x{sheet_h} | Scrap: {scrap} | Κάλυψη {util:.1f}%",
            size_hint_y=None, height=dp(22), font_size="14sp"
        )
        self.add_widget(self.header)

        # toolbar row
        toolbar = BoxLayout(size_hint_y=None, height=dp(36), spacing=6)

        self.grid_btn = ToggleButton(text="Grid OFF", state="normal", size_hint_x=None, width=dp(80))
        self.grid_btn.bind(on_release=self._toggle_grid)
        toolbar.add_widget(self.grid_btn)

        toolbar.add_widget(Label(text="Snap(mm):", size_hint_x=None, width=dp(70)))
        self.snap_input = TextInput(text="10", multiline=False, size_hint_x=None, width=dp(60))
        toolbar.add_widget(self.snap_input)

        rot_btn = Button(text="Rotate sel", size_hint_x=None, width=dp(90))
        rot_btn.bind(on_release=lambda *_: self.view.rotate_selected())
        toolbar.add_widget(rot_btn)

        export_btn = Button(text="💾 PNG", size_hint_x=None, width=dp(70))
        export_btn.bind(on_release=self._export_this)
        toolbar.add_widget(export_btn)

        share_btn = Button(text="📤 Path", size_hint_x=None, width=dp(70))
        share_btn.bind(on_release=self._share_this)
        toolbar.add_widget(share_btn)

        self.add_widget(toolbar)

        # interactive view
        self.view = SheetView(
            size_hint_y=None, height=dp(320),
            sheet_w=sheet_w, sheet_h=sheet_h,
            pieces=placed_list, grid_on=False, snap_mm=10
        )
        self.add_widget(self.view)

    def _toggle_grid(self, *_):
        on = (self.grid_btn.state == "down")
        self.grid_btn.text = "Grid ON" if on else "Grid OFF"
        try:
            self.view.snap_mm = max(1, int(self.snap_input.text.strip()))
        except:
            self.view.snap_mm = 10
            self.snap_input.text = "10"
        self.view.grid_on = on
        self.view.redraw()

    def _export_this(self, *_):
        out_dir = self.parent_app.user_data_dir
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"layout_sheet_{self.index}.png")
        self.view.export_png(path)
        self.parent_app.set_status(f"Saved: {path}")

    def _share_this(self, *_):
        # Για τώρα: ίδιο με export αλλά απλά δείχνουμε path καθαρά για copy/share
        out_dir = self.parent_app.user_data_dir
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"layout_sheet_{self.index}.png")
        self.view.export_png(path)
        self.parent_app.set_status(f"Share this file: {path}")


# --------- APP ---------
class CutApp(App):
    title = "Cut Optimizer (Mobile)"

    def build(self):
        self.root_widget = Builder.load_file("cutapp.kv")
        self.pieces = []   # [(w,h,qty), ...]
        self._panels = []
        return self.root_widget

    def set_status(self, txt):
        self.root_widget.ids.summary_label.text = txt

    # ------- κομμάτια -------
    def add_piece(self):
        ids = self.root_widget.ids
        try:
            w = int(ids.pw.text.strip())
            h = int(ids.ph.text.strip())
            q = int(ids.pq.text.strip())
            if w<=0 or h<=0 or q<=0: raise ValueError
        except:
            self.set_status("Λάθος τεμάχιο (θετικοί ακέραιοι).")
            return
        self.pieces.append((w,h,q))
        ids.piece_list.add_widget(
            Label(
                text=f"{w} x {h}  x{q}",
                size_hint_y=None, height=dp(22), font_size="14sp"
            )
        )
        ids.pw.text = ""
        ids.ph.text = ""
        ids.pq.text = "1"

    def clear_pieces(self):
        self.pieces = []
        plist = self.root_widget.ids.piece_list
        plist.clear_widgets()
        self.set_status("Λίστα άδεια.")

    # ------- save/load job -------
    def _job_path(self):
        os.makedirs(self.user_data_dir, exist_ok=True)
        return os.path.join(self.user_data_dir, "job.json")

    def save_job(self):
        ids = self.root_widget.ids
        job = {
            "sheet_w": ids.sheet_w.text.strip(),
            "sheet_h": ids.sheet_h.text.strip(),
            "kerf": ids.kerf.text.strip(),
            "attempts": ids.attempts.text.strip(),
            "rot_allowed": ids.rot_allowed.active,
            "strategy": ids.strategy.text.strip(),
            "pieces": self.pieces,  # [(w,h,q),...]
        }
        path = self._job_path()
        with open(path,"w",encoding="utf-8") as f:
            json.dump(job,f,ensure_ascii=False,indent=2)
        self.set_status(f"Job saved: {path}")

    def load_job(self):
        path = self._job_path()
        if not os.path.exists(path):
            self.set_status("Δεν υπάρχει αποθηκευμένη δουλειά.")
            return
        try:
            with open(path,"r",encoding="utf-8") as f:
                job = json.load(f)
        except Exception as e:
            self.set_status(f"Σφάλμα load: {e}")
            return

        ids = self.root_widget.ids
        ids.sheet_w.text = str(job.get("sheet_w","2800"))
        ids.sheet_h.text = str(job.get("sheet_h","2070"))
        ids.kerf.text    = str(job.get("kerf","3"))
        ids.attempts.text = str(job.get("attempts","50"))
        ids.strategy.text = job.get("strategy","BSSF")
        ids.rot_allowed.active = bool(job.get("rot_allowed",True))

        # rebuild piece list in UI
        self.pieces = job.get("pieces", [])
        plist = ids.piece_list
        plist.clear_widgets()
        for (w,h,q) in self.pieces:
            plist.add_widget(
                Label(
                    text=f"{w} x {h}  x{q}",
                    size_hint_y=None, height=dp(22), font_size="14sp"
                )
            )

        self.set_status("Job loaded.")

    # ------- optimizer -------
    def run_optimizer(self):
        ids = self.root_widget.ids
        try:
            W = int(ids.sheet_w.text.strip())
            H = int(ids.sheet_h.text.strip())
            K = int(ids.kerf.text.strip())
            att = int(ids.attempts.text.strip())
        except:
            self.set_status("Λάθος διαστάσεις φύλλου/kerf/attempts.")
            return

        allow_rot = ids.rot_allowed.active
        strat = ids.strategy.text.strip()

        if W<=0 or H<=0 or K<0 or att<=0:
            self.set_status("Δώσε σωστές θετικές τιμές.")
            return
        if not self.pieces:
            self.set_status("Δεν έχεις τεμάχια.")
            return

        try:
            sheets = optimize_cut_multi_start(W,H,K,self.pieces,strat,allow_rot,att)
        except Exception as e:
            self.set_status(f"Σφάλμα: {e}")
            return

        # καθάρισε παλιά panels
        cont = ids.sheets_container
        cont.clear_widgets()
        self._panels = []

        total_used = 0
        total_area = 0

        for idx, sh in enumerate(sheets, start=1):
            used = sh.get_used_area()
            total = sh.sheet_w * sh.sheet_h
            total_used += used
            total_area += total

            placed_list = []
            for p in sh.get_all_placed():
                placed_list.append({
                    "name": p.piece.name,
                    "x": p.x, "y": p.y,
                    "w": p.width(), "h": p.height(),
                    "rot": p.rotated,
                    "last_ok_x": p.x, "last_ok_y": p.y
                })

            panel = SheetPanel(idx, sh.sheet_w, sh.sheet_h, placed_list, self)
            cont.add_widget(panel)
            self._panels.append(panel)

        overall_util = (100.0*total_used/total_area) if total_area else 0.0
        ids.export_all_btn.disabled = False
        ids.share_all_btn.disabled = False
        self.set_status(f"Φύλλα: {len(self._panels)} | Συνολική κάλυψη {overall_util:.1f}%")

    # ------- Export / Share όλων -------
    def export_all_png(self):
        if not self._panels:
            self.set_status("Δεν υπάρχουν φύλλα για export.")
            return
        out_dir = self.user_data_dir
        os.makedirs(out_dir, exist_ok=True)
        for panel in self._panels:
            path = os.path.join(out_dir, f"layout_sheet_{panel.index}.png")
            panel.view.export_png(path)
        self.set_status(f"PNG saved in: {out_dir}")

    def share_all_png(self):
        # Στην παρούσα έκδοση "share" = γράφω PNG και σου δίνω path
        # (για πραγματικό Android share intent θέλουμε pyjnius & extra perms)
        if not self._panels:
            self.set_status("Τίποτα για share.")
            return
        out_dir = self.user_data_dir
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for panel in self._panels:
            path = os.path.join(out_dir, f"layout_sheet_{panel.index}.png")
            panel.view.export_png(path)
            paths.append(path)
        # δείξε ένα από τα paths (αν τα ανοίξεις με file manager τα στέλνεις WhatsApp / Viber)
        self.set_status("Έτοιμα για share:\n" + "\n".join(paths[-2:]))

if __name__ == "__main__":
    CutApp().run()
