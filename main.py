from kivy.app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.metrics import dp
import os, json, traceback

from optimizer import optimize_cut_multi_start


class CutApp(App):
    title = "Cut Optimizer (Mobile Debug)"

    def build(self):
        root = Builder.load_file("cutapp.kv")
        if root is None:
            fb = BoxLayout()
            fb.add_widget(Label(text="KV load failed"))
            self.root_widget = fb
        else:
            self.root_widget = root
        self.pieces = []
        self._panels = []
        return self.root_widget

    def set_status(self, txt):
        self.root_widget.ids.summary_label.text = txt[:200]

    def set_debug(self, txt):
        self.root_widget.ids.debug_label.text = txt

    def _append_log(self, txt):
        try:
            path = os.path.join(self.user_data_dir, "debug_log.txt")
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(txt + "\n\n")
        except:
            pass

    def report(self, stage, detail=""):
        short = f"ERR:{stage}"
        self.set_status(short)
        full = f"[{stage}] {detail}\nTRACE:\n{traceback.format_exc()}"
        self.set_debug(full)
        self._append_log(full)
        return

    def add_piece(self, *a):
        ids = self.root_widget.ids
        try:
            w = int(ids.pw.text)
            h = int(ids.ph.text)
            q = int(ids.pq.text)
            if w <= 0 or h <= 0 or q <= 0:
                raise ValueError
        except Exception as e:
            return self.report("ADD_PIECE", str(e))
        self.pieces.append((w, h, q))
        ids.piece_list.add_widget(Label(text=f"{w}x{h}x{q}", size_hint_y=None, height=dp(22)))
        ids.pw.text = ids.ph.text = ""
        ids.pq.text = "1"
        self.set_status("Προστέθηκε τεμάχιο")

    def clear_pieces(self, *a):
        self.pieces = []
        self.root_widget.ids.piece_list.clear_widgets()
        self.set_status("Λίστα άδεια.")

    def _job_path(self):
        os.makedirs(self.user_data_dir, exist_ok=True)
        return os.path.join(self.user_data_dir, "job.json")

    def save_job(self, *a):
        ids = self.root_widget.ids
        job = {
            "sheet_w": ids.sheet_w.text,
            "sheet_h": ids.sheet_h.text,
            "kerf": ids.kerf.text,
            "attempts": ids.attempts.text,
            "rot_allowed": ids.rot_allowed.active,
            "strategy": ids.strategy.text,
            "pieces": self.pieces,
        }
        try:
            with open(self._job_path(), "w", encoding="utf-8") as f:
                json.dump(job, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return self.report("SAVE_JOB", str(e))
        self.set_status("Αποθηκεύτηκε")

    def load_job(self, *a):
        try:
            with open(self._job_path(), "r", encoding="utf-8") as f:
                job = json.load(f)
        except Exception as e:
            return self.report("LOAD_JOB", str(e))
        ids = self.root_widget.ids
        ids.sheet_w.text = str(job.get("sheet_w", "2800"))
        ids.sheet_h.text = str(job.get("sheet_h", "2070"))
        ids.kerf.text = str(job.get("kerf", "3"))
        ids.attempts.text = str(job.get("attempts", "10"))
        ids.strategy.text = job.get("strategy", "BSSF")
        ids.rot_allowed.active = job.get("rot_allowed", True)
        self.pieces = job.get("pieces", [])
        plist = ids.piece_list
        plist.clear_widgets()
        for (w, h, q) in self.pieces:
            plist.add_widget(Label(text=f"{w}x{h}x{q}", size_hint_y=None, height=dp(22)))
        self.set_status("Φορτώθηκε")

    def run_optimizer(self, *a):
        ids = self.root_widget.ids
        try:
            W = int(ids.sheet_w.text)
            H = int(ids.sheet_h.text)
            K = int(ids.kerf.text)
            att = int(ids.attempts.text)
            strat = ids.strategy.text
            rot = ids.rot_allowed.active
        except Exception as e:
            return self.report("STAGE1_INPUT", str(e))
        if not self.pieces:
            self.set_status("Δεν έχεις τεμάχια.")
            return

        try:
            sheets = optimize_cut_multi_start(W, H, K, self.pieces, strat, rot, att)
        except Exception as e:
            return self.report("STAGE2_OPT", str(e))

        if not sheets:
            self.set_status("Άδειο αποτέλεσμα.")
            return

        cont = ids.sheets_container
        cont.clear_widgets()
        self._panels = []

        total_used = 0
        total_area = 0
        panel_fail = False

        for idx, sh in enumerate(sheets, 1):
            try:
                used = sh.get_used_area()
                total = sh.sheet_w * sh.sheet_h
                total_used += used
                total_area += total
                placed = []
                for pp in sh.get_all_placed():
                    placed.append({
                        "name": getattr(pp.piece, "name", "?"),
                        "x": pp.x,
                        "y": pp.y,
                        "w": pp.width(),
                        "h": pp.height(),
                    })
            except Exception as e:
                return self.report("STAGE3_BUILD", str(e))

            try:
                # απλό test αντί για SimplePanel
                self.set_debug(
                    f"sheet {idx}\n"
                    f"sheet_w={sh.sheet_w}\n"
                    f"sheet_h={sh.sheet_h}\n"
                    f"pieces={len(placed)}\n"
                )
            except Exception as e:
                panel_fail = True
                self.set_debug(f"SIMPLEPANEL FAIL: {type(e).__name__} {e}")
                self._append_log(traceback.format_exc())

        overall = (100 * total_used / total_area) if total_area else 0
        if panel_fail:
            self.set_status("ERR:SIMPLEPANEL")
        else:
            self.set_status(f"OK ✔ Φύλλα:{len(sheets)} | Κάλυψη {overall:.1f}%")

    def export_all_png(self, *a):
        self.set_status("Dummy export για debug")

    def share_all_png(self, *a):
        self.set_status("Dummy share για debug")


if __name__ == "__main__":
    CutApp().run()
