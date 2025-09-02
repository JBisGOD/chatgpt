#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
초경량 DXF → SHP (항적라인 경량화·도곽 Clip) 툴
- UI: Tkinter (내장) / 탭 2개(보조 탭은 안내만)
- 의존성: ezdxf, pyshp(shapefile), (선택) 없음  ※ pyclipper 없이 축소 구현
- 좌표계: EPSG:32652 고정 (WKT .prj 저장)
- 인코딩: CP949 고정 (.cpg 작성)

기능 흐름
1) DXF 선택(여러 개)
2) 저장 폴더 선택
3) 도곽 DXF 선택(여러 개)  → 닫힌 LWPOLYLINE/POLYLINE의 경계 사각형(bbox)로 clip
4) 속성값 입력  → YEAR, PRO_TYPE, PRO_NAME, SITE, COMPANY, SUV_TYPE, VESSEL
   - SUV_DATE는 각 피처의 Layer명 앞 8자를 자동 추출
5) 실행

주의
- 도곽은 닫힌 폴리라인(대개 직사각형 도엽)을 권장합니다. 닫힌 도형이 없으면 각 도곽 DXF의 전체 bbox로 clip합니다.
- 라인 clip은 Cohen–Sutherland 알고리즘(축 정렬 사각형 기준)을 사용합니다.
- 더 가볍게 하기 위해 geopandas/shapely/fiona/pyproj 등 대형 바이너리는 전부 제거했습니다.

빌드 팁(권장)
    pip install ezdxf pyshp
    pyinstaller dxf_to_shp_ultralight.py --onefile --noconsole --strip
"""

import os
import re
import sys
import math
from typing import List, Tuple, Dict

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import ezdxf
import shapefile  # pyshp

# ==============================
# 상수
# ==============================
PRJ_WKT_EPSG_32652 = (
    'PROJCS["WGS 84 / UTM zone 52N",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",129],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["Easting",EAST],AXIS["Northing",NORTH],AUTHORITY["EPSG","32652"]]'
)

FIELDS = [
    ("YEAR", 4), ("PRO_TYPE", 20), ("PRO_NAME", 50), ("SITE", 20),
    ("COMPANY", 20), ("SUV_TYPE", 10), ("SUV_DATE", 8), ("VESSEL", 20)
]

# ==============================
# 기하 유틸 (경량)
# ==============================

def dp_simplify(points: List[Tuple[float, float]], epsilon: float) -> List[Tuple[float, float]]:
    """Douglas–Peucker (재귀/스택 혼합 경량 구현)."""
    if len(points) <= 2:
        return points[:]

    def _perp_dist(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(x - x1, y - y1)
        t = ((x - x1) * dx + (y - y1) * dy) / float(dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        projx, projy = x1 + t * dx, y1 + t * dy
        return math.hypot(x - projx, y - projy)

    stack = [(0, len(points) - 1)]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True

    while stack:
        s, e = stack.pop()
        a, b = points[s], points[e]
        idx, dmax = -1, 0.0
        for i in range(s + 1, e):
            d = _perp_dist(points[i], a, b)
            if d > dmax:
                idx, dmax = i, d
        if dmax > epsilon:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))

    return [pt for i, pt in enumerate(points) if keep[i]]


# Cohen–Sutherland region codes
INSIDE, LEFT, RIGHT, BOTTOM, TOP = 0, 1, 2, 4, 8

def _cs_code(x: float, y: float, rect) -> int:
    xmin, ymin, xmax, ymax = rect
    code = INSIDE
    if x < xmin: code |= LEFT
    elif x > xmax: code |= RIGHT
    if y < ymin: code |= BOTTOM
    elif y > ymax: code |= TOP
    return code


def clip_segment_rect(p1, p2, rect):
    """Cohen–Sutherland로 선분 vs 축사각형 clip. 결과가 없으면 None, 있으면 (x1,y1,x2,y2)."""
    x1, y1 = p1; x2, y2 = p2
    xmin, ymin, xmax, ymax = rect
    c1, c2 = _cs_code(x1, y1, rect), _cs_code(x2, y2, rect)

    while True:
        if not (c1 | c2):  # 완전 내부
            return (x1, y1, x2, y2)
        if c1 & c2:        # 완전 외부
            return None
        # 하나는 밖
        out = c1 or c2
        if out & TOP:
            x = x1 + (x2 - x1) * (ymax - y1) / (y2 - y1 + 1e-12)
            y = ymax
        elif out & BOTTOM:
            x = x1 + (x2 - x1) * (ymin - y1) / (y2 - y1 + 1e-12)
            y = ymin
        elif out & RIGHT:
            y = y1 + (y2 - y1) * (xmax - x1) / (x2 - x1 + 1e-12)
            x = xmax
        else:  # LEFT
            y = y1 + (y2 - y1) * (xmin - x1) / (x2 - x1 + 1e-12)
            x = xmin

        if out == c1:
            x1, y1 = x, y
            c1 = _cs_code(x1, y1, rect)
        else:
            x2, y2 = x, y
            c2 = _cs_code(x2, y2, rect)


def clip_polyline_by_rect(points: List[Tuple[float, float]], rect) -> List[List[Tuple[float, float]]]:
    """폴리라인을 축사각형으로 clip한 다중 파트 반환."""
    if len(points) < 2:
        return []
    parts = []
    cur = []
    for i in range(len(points) - 1):
        seg = clip_segment_rect(points[i], points[i + 1], rect)
        if seg is None:
            if cur:
                parts.append(cur)
                cur = []
            continue
        x1, y1, x2, y2 = seg
        p1, p2 = (x1, y1), (x2, y2)
        if not cur:
            cur.append(p1)
        else:
            # 연결 끊기 방지
            if (abs(cur[-1][0] - p1[0]) > 1e-9) or (abs(cur[-1][1] - p1[1]) > 1e-9):
                parts.append(cur)
                cur = [p1]
        cur.append(p2)
    if cur:
        parts.append(cur)
    # 길이가 2 미만인 파트 제거
    parts = [p for p in parts if len(p) >= 2]
    return parts


# ==============================
# DXF I/O (경량)
# ==============================

def read_dxf_lines(dxf_path: str) -> List[Dict]:
    """DXF에서 LINE / (L)POLYLINE을 추출하여 [{'points':[(x,y),...],'layer':str}, ...] 반환."""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    out = []
    for e in msp:
        t = e.dxftype()
        try:
            if t == "LINE":
                p1 = (float(e.dxf.start.x), float(e.dxf.start.y))
                p2 = (float(e.dxf.end.x), float(e.dxf.end.y))
                out.append({"points": [p1, p2], "layer": str(e.dxf.layer)})
            elif t == "LWPOLYLINE":
                pts = []
                for p in e.get_points():  # (x, y, [s_w, e_w, bulge, ...])
                    pts.append((float(p[0]), float(p[1])))
                if len(pts) >= 2:
                    out.append({"points": pts, "layer": str(e.dxf.layer)})
            elif t == "POLYLINE":
                pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in e.vertices()]
                if len(pts) >= 2:
                    out.append({"points": pts, "layer": str(e.dxf.layer)})
        except Exception:
            continue
    return out


def read_frame_rects(dxf_path: str) -> List[Tuple[float, float, float, float]]:
    """도곽 DXF에서 닫힌 폴리라인 → bbox 리스트 반환. 없으면 전체 bbox 1개."""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    rects = []
    xs, ys = [], []

    def bbox(pts):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    for e in msp:
        t = e.dxftype()
        try:
            if t == "LWPOLYLINE" and getattr(e, "closed", False):
                pts = [(float(p[0]), float(p[1])) for p in e.get_points()]
                if len(pts) >= 3:
                    rects.append(bbox(pts))
            elif t == "POLYLINE" and getattr(e, "is_closed", False):
                pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in e.vertices()]
                if len(pts) >= 3:
                    rects.append(bbox(pts))
            # 전체 bbox 추적
            if t in ("LINE", "LWPOLYLINE", "POLYLINE"):
                if t == "LINE":
                    xs.extend([float(e.dxf.start.x), float(e.dxf.end.x)])
                    ys.extend([float(e.dxf.start.y), float(e.dxf.end.y)])
                elif t == "LWPOLYLINE":
                    for p in e.get_points():
                        xs.append(float(p[0])); ys.append(float(p[1]))
                elif t == "POLYLINE":
                    for v in e.vertices():
                        xs.append(float(v.dxf.location.x)); ys.append(float(v.dxf.location.y))
        except Exception:
            continue

    if not rects and xs and ys:
        rects = [(min(xs), min(ys), max(xs), max(ys))]
    return rects


# ==============================
# SHP Writer (pyshp)
# ==============================

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _truncate(s: str, n: int) -> str:
    s = s if s is not None else ""
    if len(s) <= n:
        return s
    return s[:n]


def write_shp_lines(path_without_ext: str, features: List[Dict], attrs: Dict[str, str]):
    """
    features: [{"points":[(x,y),...], "layer": str}, ...]
    attrs: YEAR, PRO_TYPE, PRO_NAME, SITE, COMPANY, SUV_TYPE, VESSEL (SUV_DATE는 layer[:8])
    """
    base = os.path.splitext(path_without_ext)[0]
    w = shapefile.Writer(base, shapeType=shapefile.POLYLINE, encoding='cp949')
    w.autoBalance = 1

    # 필드 정의 (C = character)
    for name, ln in FIELDS:
        w.field(name, "C", ln)

    for f in features:
        pts = f["points"]
        if len(pts) < 2:
            continue
        layer = f.get("layer", "")
        suv_date = _truncate(str(layer)[:8], 8)
        rec = [
            _truncate(attrs.get("YEAR", ""), 4),
            _truncate(attrs.get("PRO_TYPE", ""), 20),
            _truncate(attrs.get("PRO_NAME", ""), 50),
            _truncate(attrs.get("SITE", ""), 20),
            _truncate(attrs.get("COMPANY", ""), 20),
            _truncate(attrs.get("SUV_TYPE", ""), 10),
            suv_date,
            _truncate(attrs.get("VESSEL", ""), 20),
        ]
        w.line([pts])
        w.record(*rec)

    w.close()

    # .prj (EPSG:32652)
    with open(base + ".prj", "w", encoding="utf-8") as f:
        f.write(PRJ_WKT_EPSG_32652)
    # .cpg
    with open(base + ".cpg", "w", encoding="utf-8") as f:
        f.write("CP949")


# ==============================
# Tkinter UI
# ==============================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("선영종합엔지니어링-기술연구소")
        self.geometry("980x580")

        self.dxf_files: List[str] = []
        self.frame_files: List[str] = []
        self.output_dir: str = ""
        self.attrs: Dict[str, str] = {}

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)

        self.tab_main = ttk.Frame(nb)
        nb.add(self.tab_main, text="항적라인 경량화 및 분할")
        self.tab_other = ttk.Frame(nb)
        nb.add(self.tab_other, text="DWG/DXF → SHP 변환 (준비중)")

        self._build_main_tab()
        ttk.Label(self.tab_other, text="이 탭은 준비 중입니다.", anchor="center").pack(expand=True)

    def _build_main_tab(self):
        left = ttk.Frame(self.tab_main)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)

        # 1. DXF 선택
        g1 = ttk.LabelFrame(left, text="1. DXF 선택")
        g1.pack(fill=tk.X, pady=5)
        self.lst_dxf = tk.Listbox(g1, height=6)
        self.lst_dxf.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(g1, text="DXF 파일 선택…", command=self.pick_dxf).pack(padx=6, pady=4)

        # 2. 저장 폴더 선택
        g2 = ttk.LabelFrame(left, text="2. 저장 폴더 선택")
        g2.pack(fill=tk.X, pady=5)
        self.lbl_out = ttk.Label(g2, text="저장 경로가 선택되지 않았습니다.")
        self.lbl_out.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(g2, text="폴더 선택…", command=self.pick_out).pack(padx=6, pady=4)

        # 3. 도곽 DXF 선택
        g3 = ttk.LabelFrame(left, text="3. 도곽 DXF 선택")
        g3.pack(fill=tk.X, pady=5)
        self.lst_frame = tk.Listbox(g3, height=6)
        self.lst_frame.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(g3, text="도곽 DXF 선택…", command=self.pick_frame).pack(padx=6, pady=4)

        # 4. 속성값 입력
        g4 = ttk.LabelFrame(left, text="4. 속성값 입력")
        g4.pack(fill=tk.X, pady=5)
        self.lbl_attr = ttk.Label(g4, text="미입력")
        self.lbl_attr.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(g4, text="속성값 입력 창 열기…", command=self.edit_attrs).pack(padx=6, pady=4)

        ttk.Button(left, text="실행", command=self.run).pack(fill=tk.X, pady=12)

        # 진행 표시
        right = ttk.Frame(self.tab_main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        ttk.Label(right, text="진행 로그").pack(anchor="w")
        self.txt_log = tk.Text(right, height=28)
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        self.pbar = ttk.Progressbar(right, mode='determinate', maximum=100)
        self.pbar.pack(fill=tk.X, pady=6)

    # --------------------
    # UI 핸들러
    # --------------------
    def pick_dxf(self):
        files = filedialog.askopenfilenames(title="DXF 파일들을 선택하세요", filetypes=[("DXF", "*.dxf"), ("All", "*.*")])
        if files:
            self.dxf_files = list(files)
            self.lst_dxf.delete(0, tk.END)
            for f in self.dxf_files:
                self.lst_dxf.insert(tk.END, f)

    def pick_out(self):
        d = filedialog.askdirectory(title="결과 파일들을 저장할 폴더를 선택하세요")
        if d:
            self.output_dir = d
            self.lbl_out.config(text=d)

    def pick_frame(self):
        files = filedialog.askopenfilenames(title="도곽 DXF 선택(여러 개 가능)", filetypes=[("DXF", "*.dxf"), ("All", "*.*")])
        if files:
            self.frame_files = list(files)
            self.lst_frame.delete(0, tk.END)
            for f in self.frame_files:
                self.lst_frame.insert(tk.END, f)

    def edit_attrs(self):
        dlg = AttrDialog(self)
        self.wait_window(dlg)
        if dlg.values:
            self.attrs = dlg.values
            self.lbl_attr.config(text="입력 완료")
        else:
            self.lbl_attr.config(text="미입력")

    def log(self, msg: str):
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.update_idletasks()

    # --------------------
    # 실행 로직
    # --------------------
    def run(self):
        if not self.dxf_files:
            messagebox.showwarning("경고", "DXF 파일을 선택하십시오.")
            return
        if not self.output_dir:
            messagebox.showwarning("경고", "저장 폴더를 선택하십시오.")
            return
        if not self.frame_files:
            messagebox.showwarning("경고", "도곽 DXF를 선택하십시오.")
            return
        if not self.attrs:
            messagebox.showwarning("경고", "속성값을 먼저 입력하십시오.")
            return

        self.pbar['value'] = 0
        total = len(self.dxf_files)

        for i, dxf_path in enumerate(self.dxf_files, start=1):
            file_name = os.path.splitext(os.path.basename(dxf_path))[0]
            self.log(f"[1/3] 읽기: {file_name}")
            try:
                feats = read_dxf_lines(dxf_path)
            except Exception as e:
                messagebox.showerror("에러", "DXF 읽기 실패\n{}\n{}".format(dxf_path, e))
                continue

            # 01.원본 저장
            out1 = os.path.join(self.output_dir, file_name, "01.원본")
            _ensure_dir(out1)
            shp1 = os.path.join(out1, f"{file_name}.shp")
            write_shp_lines(shp1, feats, self.attrs)

            # 02.경량화 (1m)
            self.log("[2/3] 단순화(1m)")
            feats_s = []
            for f in feats:
                simp = dp_simplify(f["points"], 1.0)
                if len(simp) >= 2:
                    feats_s.append({"points": simp, "layer": f.get("layer", "")})
            out2 = os.path.join(self.output_dir, file_name, "02.경량화")
            _ensure_dir(out2)
            shp2 = os.path.join(out2, f"{file_name}_1m.shp")
            write_shp_lines(shp2, feats_s, self.attrs)

            # 03.도엽별 (축사각형 Clip)
            self.log("[3/3] 도곽 Clip")
            out3 = os.path.join(self.output_dir, file_name, "03.도엽별")
            _ensure_dir(out3)
            for frame_path in self.frame_files:
                frame_name = re.sub(r'^[A-Za-z]+_', '', os.path.splitext(os.path.basename(frame_path))[0])
                rects = read_frame_rects(frame_path)
                if not rects:
                    self.log(f"  - 도곽 인식 실패: {frame_name} (전체 bbox 없음)")
                    continue
                # 모든 rect에 대해 clip 결과 누적
                clipped_feats = []
                for rect in rects:
                    for f in feats_s:
                        parts = clip_polyline_by_rect(f["points"], rect)
                        for p in parts:
                            clipped_feats.append({"points": p, "layer": f.get("layer", "")})
                if not clipped_feats:
                    self.log(f"  - Clip 결과 없음: {frame_name}")
                    continue
                shp3 = os.path.join(out3, f"{frame_name}_TLN.shp")
                write_shp_lines(shp3, clipped_feats, self.attrs)
                self.log(f"  - 저장: {os.path.basename(shp3)} ({len(clipped_feats)}개 피처)")

            self.pbar['value'] = int(i / max(1, total) * 100)
            self.update_idletasks()

        messagebox.showinfo("완료", "모든 작업이 완료되었습니다!")


# -----------------------------
# 속성 입력 Dialog
# -----------------------------
class AttrDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("속성값 입력")
        self.resizable(False, False)
        self.values = None

        defaults = {
            "YEAR": "",
            "PRO_TYPE": "",
            "PRO_NAME": "",
            "SITE": "",
            "COMPANY": "",
            "SUV_TYPE": "",
            "VESSEL": "",
        }

        self.entries: Dict[str, tk.Entry] = {}

        frm = ttk.Frame(self)
        frm.pack(padx=12, pady=10)

        def add_row(r, name, label, limit):
            ttk.Label(frm, text=f"{label} ({limit}자 이내)").grid(row=r, column=0, sticky="w", pady=3)
            e = ttk.Entry(frm, width=38)
            e.insert(0, defaults.get(name, ""))
            e.grid(row=r, column=1, sticky="we", padx=6, pady=3)
            self.entries[name] = e

        rows = [
            ("YEAR", "수행년도", 4),
            ("PRO_TYPE", "사업 유형", 20),
            ("PRO_NAME", "사업명", 50),
            ("SITE", "측량구역", 20),
            ("COMPANY", "측량 수행사", 20),
            ("SUV_TYPE", "측량 유형", 10),
            ("VESSEL", "측량 선박", 20),
        ]
        for i,(n, lbl, lim) in enumerate(rows):
            add_row(i, n, lbl, lim)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=12, pady=(0,10))
        ttk.Button(btns, text="확인", command=self.on_ok).pack(side=tk.LEFT)
        ttk.Button(btns, text="취소", command=self.destroy).pack(side=tk.LEFT, padx=6)

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def on_ok(self):
        vals = {n: self.entries[n].get() for n in self.entries}
        # 길이 제한 컷팅
        lens = {"YEAR":4, "PRO_TYPE":20, "PRO_NAME":50, "SITE":20, "COMPANY":20, "SUV_TYPE":10, "VESSEL":20}
        for k in list(vals.keys()):
            lim = lens.get(k, 255)
            if len(vals[k]) > lim:
                vals[k] = vals[k][:lim]
        self.values = vals
        self.destroy()


# ==============================
# main
# ==============================
if __name__ == '__main__':
    app = App()
    app.mainloop()
