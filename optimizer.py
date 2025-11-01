# optimizer.py
import random
from copy import deepcopy
from typing import List, Tuple, Optional


class Piece:
    def __init__(self, w: int, h: int, name: Optional[str] = None):
        self.w = w
        self.h = h
        self.name = name

    def __repr__(self):
        return f"{self.name or ''}({self.w}x{self.h})"


class PlacedPiece:
    def __init__(self, piece: Piece, x: int, y: int, rotated: bool):
        self.piece = piece
        self.x = x
        self.y = y
        self.rotated = rotated

    def width(self):
        return self.piece.h if self.rotated else self.piece.w

    def height(self):
        return self.piece.w if self.rotated else self.piece.h


class FreeRect:
    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = x
        self.y = y
        self.w = w
        self.h = h


class SheetLayout:
    def __init__(self, sheet_w: int, sheet_h: int, kerf: int = 0,
                 strategy: str = "BSSF", allow_rotation: bool = True):
        self.sheet_w = sheet_w
        self.sheet_h = sheet_h
        self.kerf = kerf
        self.strategy = strategy
        self.allow_rotation = allow_rotation

        self.placed: List[PlacedPiece] = []
        self.free_rects: List[FreeRect] = [FreeRect(0, 0, sheet_w, sheet_h)]

    def get_all_placed(self) -> List[PlacedPiece]:
        return list(self.placed)

    def get_used_area(self) -> int:
        return sum(p.width() * p.height() for p in self.placed)

    @staticmethod
    def _intersects(a: FreeRect, b: FreeRect) -> bool:
        return not (
            a.x + a.w <= b.x or
            b.x + b.w <= a.x or
            a.y + a.h <= b.y or
            b.y + b.h <= a.y
        )

    @staticmethod
    def _contains(a: FreeRect, b: FreeRect) -> bool:
        return (
            b.x >= a.x and
            b.y >= a.y and
            b.x + b.w <= a.x + a.w and
            b.y + b.h <= a.y + a.h
        )

    def try_place_piece(self, piece: Piece) -> bool:
        orientations = [False, True] if self.allow_rotation else [False]

        # 1) exact-fit pass
        exact_best = None
        for i, fr in enumerate(self.free_rects):
            for rot in orientations:
                pw = piece.h if rot else piece.w
                ph = piece.w if rot else piece.h
                if pw <= fr.w and ph <= fr.h:
                    if pw == fr.w or ph == fr.h:
                        cand = (fr.y, fr.x, i, rot, fr.x, fr.y, pw, ph)
                        if exact_best is None or cand < exact_best:
                            exact_best = cand
        if exact_best is not None:
            _, _, fr_i, rot, x, y, pw, ph = exact_best
            self._place_and_split(fr_i, piece, rot, x, y, pw, ph)
            return True

        # 2) scored pass
        def base_score(fr_w, fr_h, pw, ph):
            leftover_h = fr_h - ph
            leftover_w = fr_w - pw
            short_side = min(leftover_h, leftover_w)
            long_side  = max(leftover_h, leftover_w)
            area_left  = leftover_h * leftover_w
            st = self.strategy
            if st == "BSSF":
                return (short_side, area_left)
            elif st == "BAF":
                return (area_left, short_side)
            elif st == "BLSF":
                return (long_side, short_side)
            else:
                return (short_side, area_left)

        def strip_bias(fr: FreeRect, pw: int, ph: int) -> int:
            penalty = 10_000
            if fr.x == 0:
                penalty -= 200
            col_hits = [
                p for p in self.placed
                if p.x == fr.x and p.width() == pw and (p.y + p.height()) <= fr.y + 1
            ]
            if col_hits:
                penalty -= 5000
            penalty -= min(fr.y, 200)
            return penalty

        best = None
        for i, fr in enumerate(self.free_rects):
            for rot in orientations:
                pw = piece.h if rot else piece.w
                ph = piece.w if rot else piece.h
                if pw <= fr.w and ph <= fr.h:
                    primary = base_score(fr.w, fr.h, pw, ph)
                    sb = strip_bias(fr, pw, ph)
                    cand = (
                        primary[0], primary[1],
                        fr.y, fr.x,
                        sb,
                        i, rot, fr.x, fr.y, pw, ph
                    )
                    if best is None or cand < best:
                        best = cand

        if best is None:
            return False

        _, _, _, _, _, fr_i, rot, x, y, pw, ph = best
        self._place_and_split(fr_i, piece, rot, x, y, pw, ph)
        return True

    def _place_and_split(self, fr_i: int, piece: Piece, rotated: bool,
                         x: int, y: int, pw: int, ph: int):
        self.placed.append(PlacedPiece(piece, x, y, rotated))
        fr = self.free_rects.pop(fr_i)

        kx = self.kerf if (x + pw) < (fr.x + fr.w) else 0
        ky = self.kerf if (y + ph) < (fr.y + fr.h) else 0

        rx = x + pw + kx
        rw = (fr.x + fr.w) - rx
        if rw > 0:
            self.free_rects.append(FreeRect(rx, fr.y, rw, fr.h))

        by = y + ph + ky
        bh = (fr.y + fr.h) - by
        if bh > 0:
            self.free_rects.append(FreeRect(fr.x, by, fr.w, bh))

        self._prune_free_rects_with(FreeRect(x, y, pw, ph))
        self._merge_free_rects()

    def _prune_free_rects_with(self, used: FreeRect):
        out = []
        for fr in self.free_rects:
            if not self._intersects(fr, used):
                out.append(fr)
                continue

            if used.y > fr.y:
                out.append(FreeRect(fr.x, fr.y, fr.w, used.y - fr.y))

            if used.y + used.h < fr.y + fr.h:
                out.append(
                    FreeRect(fr.x, used.y + used.h, fr.w,
                             (fr.y + fr.h) - (used.y + used.h))
                )

            if used.x > fr.x:
                top = max(fr.y, used.y)
                bottom = min(fr.y + fr.h, used.y + used.h)
                out.append(FreeRect(fr.x, top, used.x - fr.x, bottom - top))

            if used.x + used.w < fr.x + fr.w:
                right_x = used.x + used.w
                top = max(fr.y, used.y)
                bottom = min(fr.y + fr.h, used.y + used.h)
                out.append(
                    FreeRect(right_x, top, (fr.x + fr.w) - right_x, bottom - top)
                )

        self.free_rects = [r for r in out if r.w > 0 and r.h > 0]

    def _merge_free_rects(self):
        cleaned = []
        for i, a in enumerate(self.free_rects):
            if any(i != j and self._contains(b, a) for j, b in enumerate(self.free_rects)):
                continue
            cleaned.append(a)
        self.free_rects = cleaned

        merged = True
        while merged:
            merged = False
            out = []
            used = [False] * len(self.free_rects)
            for i, a in enumerate(self.free_rects):
                if used[i]:
                    continue
                did = False
                for j in range(i + 1, len(self.free_rects)):
                    if used[j]:
                        continue
                    b = self.free_rects[j]
                    if a.y == b.y and a.h == b.h and (a.x + a.w == b.x or b.x + b.w == a.x):
                        out.append(FreeRect(min(a.x, b.x), a.y, a.w + b.w, a.h))
                        used[i] = used[j] = True
                        merged = True
                        did = True
                        break
                    if a.x == b.x and a.w == b.w and (a.y + a.h == b.y or b.y + b.h == a.y):
                        out.append(FreeRect(a.x, min(a.y, b.y), a.w, a.h + b.h))
                        used[i] = used[j] = True
                        merged = True
                        did = True
                        break
                if not did and not used[i]:
                    out.append(a)
                    used[i] = True
            self.free_rects = out


def _flatten_piece_list(piece_list: List[Tuple[int,int,int]]) -> List[Piece]:
    out: List[Piece] = []
    c = 1
    for (w, h, q) in piece_list:
        for _ in range(q):
            out.append(Piece(w, h, name=f"P{c}"))
            c += 1
    return out

def _pack_once(pieces: List[Piece], W:int, H:int, K:int,
               strat:str, rot:bool) -> List[SheetLayout]:
    sheets: List[SheetLayout] = []
    for p in pieces:
        placed = False
        for sh in sheets:
            if sh.try_place_piece(p):
                placed = True
                break
        if not placed:
            sh = SheetLayout(W, H, K, strat, rot)
            if not sh.try_place_piece(p):
                raise ValueError(f"Το κομμάτι {p} δεν χωράει στο φύλλο {W}x{H}!")
            sheets.append(sh)
    return sheets

def _score_sheets(sheets: List[SheetLayout]):
    n = len(sheets)
    scrap = sum(sh.sheet_w * sh.sheet_h - sh.get_used_area() for sh in sheets)
    return (n, scrap)

def _rebuild_sheet_from_placed(sh: SheetLayout):
    remain = [Piece(p.width(), p.height(), p.piece.name) for p in sh.placed]
    strat, rot = sh.strategy, sh.allow_rotation
    sh.free_rects = [FreeRect(0, 0, sh.sheet_w, sh.sheet_h)]
    sh.placed = []
    for rp in sorted(remain, key=lambda x: x.w * x.h, reverse=True):
        sh.try_place_piece(rp)
    sh.strategy, sh.allow_rotation = strat, rot

def _global_compactor(sheets: List[SheetLayout], strat: str, rot: bool):
    improved = True
    while improved:
        improved = False
        best_score = _score_sheets(sheets)
        for si in range(len(sheets) - 1, 0, -1):
            donor = sheets[si]
            parts = sorted(donor.get_all_placed(), key=lambda p: p.width() * p.height())
            for part in parts:
                candidate_piece = Piece(part.width(), part.height(), part.piece.name)
                moved = False
                for rcv in sheets[:si]:
                    old_s, old_r = rcv.strategy, rcv.allow_rotation
                    rcv.strategy, rcv.allow_rotation = strat, rot
                    if rcv.try_place_piece(candidate_piece):
                        moved = True
                    rcv.strategy, rcv.allow_rotation = old_s, old_r
                    if moved:
                        break
                if moved:
                    donor.placed.remove(part)
                    if donor.placed:
                        _rebuild_sheet_from_placed(donor)
                    else:
                        sheets.pop(si)
                    new_score = _score_sheets(sheets)
                    if new_score < best_score:
                        best_score = new_score
                        improved = True
                    break
            if improved:
                break

def _global_refine_heavy(sheets: List[SheetLayout], strat: str, rot: bool,
                         W: int, H: int, K: int, rounds: int = 3):
    def sheet_waste(sh: SheetLayout):
        total = sh.sheet_w * sh.sheet_h
        return total - sh.get_used_area()

    for _ in range(rounds):
        if len(sheets) <= 1:
            break
        order = list(range(len(sheets)))
        order.sort(key=lambda idx: sheet_waste(sheets[idx]), reverse=True)
        changed = False
        for victim_idx in order[:2]:
            if victim_idx >= len(sheets):
                continue
            victim = sheets[victim_idx]
            victim_pieces = [Piece(p.width(), p.height(), p.piece.name) for p in victim.get_all_placed()]
            others = []
            for j, sh in enumerate(sheets):
                if j == victim_idx:
                    continue
                clone = SheetLayout(W, H, K, strat, rot)
                for pp in sorted(sh.get_all_placed(), key=lambda q: q.width()*q.height(), reverse=True):
                    clone.try_place_piece(Piece(pp.width(), pp.height(), pp.piece.name))
                others.append(clone)
            pool = []
            for sh2 in others:
                for pp in sh2.get_all_placed():
                    pool.append(Piece(pp.width(), pp.height(), pp.piece.name))
            pool.extend(victim_pieces)
            pool.sort(key=lambda p: p.w*p.h, reverse=True)
            i = 0
            while i < len(pool):
                j = i+1
                area0 = pool[i].w * pool[i].h
                while j < len(pool) and abs(pool[j].w*pool[j].h - area0) <= max(1, area0//50):
                    j += 1
                chunk = pool[i:j]
                random.shuffle(chunk)
                pool[i:j] = chunk
                i = j
            new_sheets: List[SheetLayout] = []
            fail = False
            for p in pool:
                done = False
                for sh2 in new_sheets:
                    if sh2.try_place_piece(p):
                        done = True
                        break
                if not done:
                    shn = SheetLayout(W, H, K, strat, rot)
                    if not shn.try_place_piece(p):
                        fail = True
                        break
                    new_sheets.append(shn)
            if fail:
                continue
            old_score = _score_sheets(sheets)
            new_score = _score_sheets(new_sheets)
            if new_score < old_score:
                sheets[:] = new_sheets
                changed = True
                break
        if not changed:
            break


def optimize_cut_multi_start(W:int, H:int, K:int,
                             piece_list: List[Tuple[int,int,int]],
                             strategy: str, allow_rotation: bool,
                             attempts: int = 50) -> List[SheetLayout]:
    base = _flatten_piece_list(piece_list)
    best_sheets = None
    best_score = None
    for _ in range(attempts):
        pieces = deepcopy(base)
        pieces.sort(key=lambda p: p.w*p.h, reverse=True)
        i = 0
        while i < len(pieces):
            j = i+1
            area0 = pieces[i].w * pieces[i].h
            while j < len(pieces) and abs(pieces[j].w*pieces[j].h - area0) <= max(1, area0//50):
                j += 1
            chunk = pieces[i:j]
            random.shuffle(chunk)
            pieces[i:j] = chunk
            i = j
        sheets = _pack_once(pieces, W, H, K, strategy, allow_rotation)
        _global_compactor(sheets, strategy, allow_rotation)
        _global_refine_heavy(sheets, strategy, allow_rotation, W, H, K, rounds=3)
        sc = _score_sheets(sheets)
        if best_score is None or sc < best_score:
            best_score = sc
            best_sheets = deepcopy(sheets)
    return best_sheets or []
