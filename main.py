from kivy.app import App
from kivy.lang import Builder
from kivy.properties import (
    ListProperty, NumericProperty, BooleanProperty, ObjectProperty
)
    # ListProperty = λίστα που ενημερώνει UI όταν αλλάζει
    # NumericProperty = αριθμός που το Kivy το αναγνωρίζει σαν observable
    # BooleanProperty = True/False observable
    # ObjectProperty = generic object observable
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, Line
from kivy.uix.label import Label
from kivy.metrics import dp

from optimizer import optimize_cut_multi_start
from PIL import Image, ImageDraw, ImageFont
import os
import json
import traceback


def pastel_rgb(name: str):
    # σταθερό παστέλ χρώμα για κάθε όνομα κομματιού
    rnd = hash(name) & 0xFFFFFF
    r = (120 + (rnd & 0x3F)) / 255.0
    g = (120 + ((rnd >> 6) & 0x3F)) / 255.0
    b = (120 + ((rnd >> 12) & 0x3F)) / 255.0
    return r, g, b


class SheetView(Widget):
    # μία σχεδιαστική προβολή για ένα φύλλο μελαμίνης
    sheet_w = NumericProperty(0)   # πλάτος φύλλου σε mm
    sheet_h = NumericProperty(0)   # ύψος φύλλου σε mm
    pieces  = ListProperty([])     # [{name,x,y,w,h,...}, ...]
    grid_on = BooleanProperty(False)
    snap_mm = NumericProperty(10)

    _selected_index = NumericProperty(-1)
    _drag_offset = ObjectProperty((0.0, 0.0))
    _origin_px = ObjectProperty((0.0, 0.0))
    _scale = NumericProperty(1.0)

    def on_size(self, *args): self.redraw()
    def on_pos(self, *args): self.redraw()
    def on_pieces(self, *args): self.redraw()
    def on_sheet_w(self, *args): self.redraw()
    def on_sheet_h(self, *args): self.redraw()
    def on_grid_on(self, *args): self.redraw()

    def _layout_metrics(self):
        # υπολογίζει πώς θα χωρέσει το φύλλο μέσα στο widget
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
        # από οθόνη (pixel) σε mm φύλλου
        ox, oy = self._origin_px
        s = self._scale
        return (px - ox) / s, (py - oy) / s

    def _mm_to_px_rect(self, x, y, w, h):
        # από mm φύλλου σε pixel οθόνης
        ox, oy, s = self._origin_px[0], self._origin_px[1], self._scale
        return (ox + x*s, oy + y*s, w*s, h*s)

    @staticmethod
    def _overlap(a, b):
        # ελέγχει αν δυο ορθογώνια επικαλύπτονται
        ax2 = a["x"] + a["w"]; ay2 = a["y"] + a["h"]
        bx2 = b["x"] + b["w"]; by2 = b["y"] + b["h"]
        return not (ax2 <= b["x"] or bx2 <= a["x"] or ay2 <= b["y"] or by2 <= a["y"])

    def _is_valid(self, idx, new_x, new_y, new_w, new_h):
        # 1. να είναι μέσα στο φύλλο
        if new_x < 0 or new_y < 0:
            return False
        if new_x + new_w > self.sheet_w:
            return False
        if new_y + new_h > self.sheet_h:
            return False
        # 2. να μην πατάει πάνω σε άλλο κομμάτι
        test = {"x": new_x, "y": new_y, "w": new_w, "h": new_h}
        for j, other in enumerate(self.pieces):
            if j == idx:
                continue
            if self._overlap(test, other):
                return False
        return True

    def _snap_val(self, v):
        # σνάπ στο grid (π.χ. κάθε 10mm)
        step = max(1, int(self.snap_mm))
        return round(v / step) * step

    def redraw(self):
        # ξαναζωγράφισε το φύλλο
        if self.sheet_w <= 0 or self.sheet_h <= 0:
            return
        ox, oy, s = self._layout_metrics()
        self.canvas.clear()
        with self.canvas:
            # λευκό background φύλλου
            Color(1,1,1,1)
            Rectangle(pos=(ox,oy), size=(self.sheet_w*s, self.sheet_h*s))
            # περίγραμμα φύλλου
            Color(0,0,0,1)
            Line(rectangle=(ox,oy,self.sheet_w*s,self.sheet_h*s), width=1.4)

            # grid κάθε 100mm
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
                Line(
                    rectangle=(px,py,w,h),
                    width=2 if i == self._selected_index else 1
                )

    def on_touch_down(self, touch):
        # επίλεξε κομμάτι για drag αν πατάς πάνω του
        if not self.collide_point(*touch.pos):
            return False
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
        # drag κομματιού με έλεγχο ορίων / overlap
        if self._selected_index < 0:
            return False
        mx,my = self._px_to_mm(*touch.pos)
        p = self.pieces[self._selected_index]
        dx,dy = self._drag_offset

        cand_x = mx - dx
        cand_y = my - dy

        # clamp στα όρια του φύλλου
        cand_x = max(0, min(cand_x, self.sheet_w - p["w"]))
        cand_y = max(0, min(cand_y, self.sheet_h - p["h"]))

        # αν έχουμε grid_on -> snap
        if self.grid_on:
            cand_x = self._snap_val(cand_x)
            cand_y = self._snap_val(cand_y)
            cand_x = max(0, min(cand_x, self.sheet_w - p["w"]))
            cand_y = max(0, min(cand_y, self.sheet_h - p["h"]))

        if self._is_valid(self._selected_index, cand_x, cand_y, p["w"], p["h"]):
            # valid νέα θέση
            p["x"], p["y"] = cand_x, cand_y
            p["last_ok_x"], p["last_ok_y"] = cand_x, cand_y
        else:
            # κράτα την τελευταία καλή
            p["x"] = p.get("last_ok_x", p["x"])
            p["y"] = p.get("last_ok_y", p["y"])

        self.redraw()
        return True

    def on_touch_up(self, touch):
        return self._selected_index >= 0

    def rotate_selected(self, *args):
        # περιστροφή επιλεγμένου κομματιού 90°
        i = self._selected_index
        if i < 0:
            return
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

    def export_png(self, out_path):
        # κάνει render σε PNG για export/share/εκτύπωση
        W, H = self.sheet_w, self.sheet_h
        if W <= 0 or H <= 0:
            return
        target_w = 1500
        scale = target_w / float(W)
        target_h = int(H * scale)

        img = Image.new("RGB", (target_w+2, target_h+2), (255,255,255))
        d = ImageDraw.Draw(img)

        # περίγραμμα φύλλου
        d.rectangle([(1,1),(1+W*scale,1+H*scale)], outline=(0,0,0), width=4)

        # grid στο export
        if self.grid_on:
            spacing = 100
            gx = spacing
            while gx < W:
                d.line(
                    [(gx*scale+1,1),(gx*scale+1,H*scale+1)],
                    fill=(220,220,220),
                    width=1
                )
                gx += spacing
            gy = spacing
            while gy < H:
                d.line(
                    [(1,gy*scale+1),(W*scale+1,gy*scale+1)],
                    fill=(220,220,220),
                    width=1
                )
                gy += spacing

        # γραμματοσειρά
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()

        # κομμάτια
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

            d.rectangle([(x1,y1),(x2,y2)],
                        fill=col,
                        outline=(0,0,0),
                        width=2)

            label = f"{p['name']}\n{p['w']}x{p['h']}"
            cx = (x1+x2)/2
            cy = (y1+y2)/2
            for line in label.split("\n"):
                tw, th = d.textsize(line, font=font)
                d.text(
                    (cx - tw/2, cy - th/2),
                    line,
                    fill=(0,0,0),
                    font=font
                )
                cy += th


class SimplePanel(BoxLayout):
    """
    Panel για 1 φύλλο:
    - Header info (scrap, κάλυψη)
    - SheetView (drag, rotate, κλπ)
    """
    def __init__(self, index, sheet_w, sheet_h, placed_list, parent_app, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            padding=10,
            spacing=6,
            **kwargs
        )
        self.height = dp(380)
        self.index = index
        self.parent_app = parent_app

        # αν sheet_w/h είναι None, αυτό θα βοηθήσει το debug
        used = sum(p["w"]*p["h"] for p in placed_list) if placed_list else 0
        total = (sheet_w or 0) * (sheet_h or 0)
        util = (100.0*used/total) if total else 0.0
        scrap = total - used if total else 0

        header_text = (
            f"Φύλλο {index} | {sheet_w}x{sheet_h} | "
            f"Scrap {scrap} | Κάλυψη {util:.1f}%"
        )

        header_lbl = Label(
            text=header_text,
            size_hint_y=None,
            height=dp(24),
            font_size="14sp"
        )
        self.add_widget(header_lbl)

        # το σχέδιο / interaction
        self.view = SheetView(
            size_hint_y=None,
            height=dp(340),
            sheet_w=sheet_w if sheet_w else 0,
            sheet_h=sheet_h if sheet_h else 0,
            pieces=placed_list if placed_list else [],
            grid_on=False,
            snap_mm=10,
        )
        self.add_widget(self.view)

    def export_png(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"layout_sheet_{self.index}.png")
        self.view.export_png(path)
        return path


class CutApp(App):
    title = "Cut Optimizer (Mobile)"

    def build(self):
        root = Builder.load_file("cutapp.kv")
        if root is None:
            fb = BoxLayout()
            fb.add_widget(Label(text="KV load failed. Έλεγξε cutapp.kv"))
            self.root_widget = fb
        else:
            self.root_widget = root

        self.pieces = []   # [(w,h,q), ...]
        self._panels = []  # [SimplePanel,...]
        return self.root_widget

    def set_status(self, txt):
        # γράφει κάτω στο status label
        self.root_widget.ids.summary_label.text = txt

    def _append_log(self, longtext):
        # γράφουμε debug σε αρχείο για πιο μετά
        try:
            out_dir = self.user_data_dir
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "debug_log.txt")
            with open(path, "a", encoding="utf-8") as f:
                f.write(longtext + "\n\n")
        except:
            pass

    def report(self, stage, detail=""):
        # generic καταγραφή error
        self.set_status(f"ERR:{stage}")
        full = f"[{stage}] {detail}\nTRACE:\n{traceback.format_exc()}"
        self._append_log(full)
        return

    # ------- κομμάτια --------
    def add_piece(self, *args):
        ids = self.root_widget.ids
        try:
            w = int(ids.pw.text.strip())
            h = int(ids.ph.text.strip())
            q = int(ids.pq.text.strip())
            if w<=0 or h<=0 or q<=0:
                raise ValueError
        except Exception as e:
            return self.report("ADD_PIECE_PARSE", str(e))

        self.pieces.append((w,h,q))
        ids.piece_list.add_widget(
            Label(
                text=f"{w} x {h}  x{q}",
                size_hint_y=None,
                height=dp(22),
                font_size="14sp"
            )
        )

        ids.pw.text = ""
        ids.ph.text = ""
        ids.pq.text = "1"
        self.set_status("OK: added piece")

    def clear_pieces(self, *args):
        self.pieces = []
        self.root_widget.ids.piece_list.clear_widgets()
        self.set_status("Λίστα άδεια.")

    # ------- save / load job --------
    def _job_path(self):
        os.makedirs(self.user_data_dir, exist_ok=True)
        return os.path.join(self.user_data_dir, "job.json")

    def save_job(self, *args):
        ids = self.root_widget.ids
        job = {
            "sheet_w": ids.sheet_w.text.strip(),
            "sheet_h": ids.sheet_h.text.strip(),
            "kerf": ids.kerf.text.strip(),
            "attempts": ids.attempts.text.strip(),
            "rot_allowed": ids.rot_allowed.active,
            "strategy": ids.strategy.text.strip(),
            "pieces": self.pieces,
        }
        path = self._job_path()
        try:
            with open(path,"w",encoding="utf-8") as f:
                json.dump(job,f,ensure_ascii=False,indent=2)
        except Exception as e:
            return self.report("SAVE_JOB", str(e))
        self.set_status("Job saved")

    def load_job(self, *args):
        path = self._job_path()
        if not os.path.exists(path):
            self.set_status("Δεν υπάρχει αποθηκευμένη δουλειά.")
            return
        try:
            with open(path,"r",encoding="utf-8") as f:
                job = json.load(f)
        except Exception as e:
            return self.report("LOAD_JOB_PARSE", str(e))

        ids = self.root_widget.ids
        ids.sheet_w.text = str(job.get("sheet_w","2800"))
        ids.sheet_h.text = str(job.get("sheet_h","2070"))
        ids.kerf.text    = str(job.get("kerf","3"))
        ids.attempts.text = str(job.get("attempts","50"))
        ids.strategy.text = job.get("strategy","BSSF")
        ids.rot_allowed.active = bool(job.get("rot_allowed",True))

        self.pieces = job.get("pieces", [])
        plist = ids.piece_list
        plist.clear_widgets()
        for (w,h,q) in self.pieces:
            plist.add_widget(
                Label(
                    text=f"{w} x {h}  x{q}",
                    size_hint_y=None,
                    height=dp(22),
                    font_size="14sp"
                )
            )

        self.set_status("Job loaded")

    # ------- optimizer / δημιουργία φύλλων --------
    def run_optimizer(self, *args):
        # STAGE1: input parsing
        try:
            ids = self.root_widget.ids
            W = int(ids.sheet_w.text.strip())
            H = int(ids.sheet_h.text.strip())
            K = int(ids.kerf.text.strip())
            att = int(ids.attempts.text.strip())
            allow_rot = ids.rot_allowed.active
            strat = ids.strategy.text.strip()
        except Exception as e:
            return self.report("STAGE1_INPUT", str(e))

        if W<=0 or H<=0 or K<0 or att<=0:
            self.set_status("Δώσε σωστές θετικές τιμές.")
            return
        if not self.pieces:
            self.set_status("Δεν έχεις τεμάχια.")
            return

        # STAGE2: optimization (άλγο που γεμίζει τα φύλλα)
        try:
            sheets = optimize_cut_multi_start(
                W,H,K,
                self.pieces,
                strat,
                allow_rot,
                att
            )
        except Exception as e:
            return self.report("STAGE2_OPTIMIZER", str(e))

        if not sheets:
            self.set_status("Άδειο αποτέλεσμα (κανένα φύλλο).")
            return

        # STAGE3: καθάρισε το UI container
        try:
            cont = ids.sheets_container
            cont.clear_widgets()
            self._panels = []
        except Exception as e:
            return self.report("STAGE3_CONTAINER", str(e))

        total_used = 0
        total_area = 0
        panel_fail = False
        panel_fail_msg = ""

        # STAGE4: για κάθε φύλλο που έφτιαξε ο optimizer
        for idx, sh in enumerate(sheets, start=1):
            if sh is None:
                # δεν περιμένω να γίνει αλλά το κρατάμε
                self._append_log("[STAGE4_NULL] sheet is None at index " + str(idx))
                continue

            # 4A: metrics φύλλου
            try:
                used = sh.get_used_area()
                total = sh.sheet_w * sh.sheet_h
                total_used += used
                total_area += total
            except Exception as e:
                return self.report("STAGE4A_GETAREA", str(e))

            # 4B: μετέτρεψε τα PlacedPiece αντικείμενα σε dicts για το UI
            safe_placed_list = []
            try:
                for pp in sh.get_all_placed():
                    nm = getattr(pp.piece, "name", "?")
                    x  = getattr(pp, "x", 0)
                    y  = getattr(pp, "y", 0)
                    wv = pp.width()
                    hv = pp.height()
                    safe_placed_list.append({
                        "name": nm if nm is not None else "?",
                        "x": float(x),
                        "y": float(y),
                        "w": float(wv),
                        "h": float(hv),
                        "rot": bool(getattr(pp, "rotated", False)),
                        "last_ok_x": float(x),
                        "last_ok_y": float(y),
                    })
            except Exception as e:
                return self.report("STAGE4B_BUILD_LIST", str(e))

            # 4C: φτιάξε το panel για το φύλλο
            try:
                panel = SimplePanel(
                    idx,
                    getattr(sh, "sheet_w", None),
                    getattr(sh, "sheet_h", None),
                    safe_placed_list,
                    self
                )
            except Exception as e:
                # Αν αποτύχει εδώ, θέλω να ΔΩ το γιατί στην οθόνη
                panel_fail = True
                msg = (
                    f"SIMPLEPANEL {type(e).__name__}: {e} | "
                    f"sheet_w={getattr(sh,'sheet_w',None)} "
                    f"sheet_h={getattr(sh,'sheet_h',None)} "
                    f"pieces={len(safe_placed_list)}"
                )
                panel_fail_msg = msg
                self._append_log("[STAGE4C_SIMPLEPANEL_FAIL] " + msg)
                # δείξε σύντομο status για να μου το πεις
                self.set_status("ERR:"+msg[:70])
                continue

            # 4D: ακόμα κι αν δεν καταφέρει να το δείξει στο UI,
            #     τουλάχιστον κράτα το panel στη μνήμη για export_png
            self._panels.append(panel)

            # δοκίμασε να το βάλεις οπτικά στο container
            try:
                cont.add_widget(panel)
            except Exception as e:
                panel_fail = True
                msg = (
                    f"ADDWIDGET {type(e).__name__}: {e} | "
                    f"panel_index={idx}"
                )
                panel_fail_msg = msg
                self._append_log("[STAGE4D_ADDWIDGET_FAIL] " + msg)
                # δεν σταματάμε, προχωράμε στα επόμενα φύλλα

        # STAGE5: ενημέρωση status στο τέλος
        try:
            overall_util = (100.0*total_used/total_area) if total_area else 0.0

            # enable τα κουμπιά export/share τώρα που έχουμε panels (ή και όχι)
            ids.export_all_btn.disabled = False
            ids.share_all_btn.disabled = False

            if panel_fail and len(self._panels) == 0:
                # καθολικό fail, ούτε ένα panel usable
                self.set_status("ERR:"+panel_fail_msg[:70])
            else:
                # έχουμε τουλάχιστον ένα panel usable
                self.set_status(
                    f"OK ✔  Φύλλα: {len(self._panels)} | Κάλυψη {overall_util:.1f}%"
                )

        except Exception as e:
            return self.report("STAGE5_SUMMARY", str(e))

    # ------- export / share png --------
    def export_all_png(self, *args):
        if not self._panels:
            self.set_status("Δεν υπάρχουν φύλλα για export.")
            return
        out_dir = self.user_data_dir
        os.makedirs(out_dir, exist_ok=True)

        paths = []
        for panel in self._panels:
            path = panel.export_png(out_dir)
            paths.append(path)

        self._append_log("[EXPORT]\n" + "\n".join(paths))
        self.set_status("PNG saved")

    def share_all_png(self, *args):
        if not self._panels:
            self.set_status("Τίποτα για share.")
            return
        out_dir = self.user_data_dir
        os.makedirs(out_dir, exist_ok=True)

        paths = []
        for panel in self._panels:
            path = panel.export_png(out_dir)
            paths.append(path)

        self._append_log("[SHARE_FILES]\n" + "\n".join(paths))
        self.set_status("Ready to share")


if __name__ == "__main__":
    CutApp().run()
