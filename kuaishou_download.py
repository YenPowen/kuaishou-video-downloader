#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快手视频批量下载工具
功能：粘贴一批快手短链接，自动解析视频地址并下载到指定文件夹。
"""

import os
import sys


# --------------------------------------------------------------------------
# 隐藏 CMD 控制台窗口
# --------------------------------------------------------------------------
def _hide_console() -> None:
    """双击 .py 运行时 Windows 会附带一个黑色控制台窗口。
    这里在程序启动的第一时间把它隐藏掉，只保留 tkinter 界面。
    若用 pythonw.exe 运行（本来就没有控制台），本函数什么都不做。
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
    except Exception:
        pass


# 必须放在下面几个重量级导入之前，否则控制台会先闪一下再消失
_hide_console()


def _fatal(message: str) -> None:
    """控制台已隐藏，致命错误改用弹窗提示，免得用户看不到报错。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "启动失败", 0x10)
    except Exception:
        sys.stderr.write(message + "\n")
    sys.exit(1)


from pathlib import Path
from datetime import datetime
import json
import re
import shutil
import threading
import queue
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


# --------------------------------------------------------------------------
# 下载核心
# --------------------------------------------------------------------------
UA_M = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")
HEADERS = {"User-Agent": UA_M, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}

# 分享页地址，一个失败换下一个
BASES = [
    "https://m.kuaishou.com/fw/photo/%s",
    "https://v.m.chenzhongtech.com/fw/photo/%s?fid=0&cc=share_copylink&followRefer=151",
]

DEFAULT_DIR = Path.home() / "Downloads" / "快手视频"

# 窗口图标（内嵌 PNG，避免依赖外部文件）
ICON_PNG_B64 = (
    "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"
)

# 支持三种链接：www.kuaishou.com/short-video/xxx、www.gifshow.com/fw/photo/xxx、纯 ID
ID_RE = re.compile(r"(?:short-video|/photo)/([A-Za-z0-9_-]{6,})")
BARE_RE = re.compile(r"^[A-Za-z0-9_-]{10,16}$")


def parse_input(text: str):
    """把用户粘贴的文本拆成条目列表：("id", 短链ID) 或 ("share", v.kuaishou.com 短链)"""
    items, seen = [], set()
    for line in text.splitlines():
        line = line.strip().strip('"\'，,。；;')
        if not line or line.startswith("#"):
            continue
        m = ID_RE.search(line)
        if m:
            pid = m.group(1)
            if pid not in seen:
                seen.add(pid)
                items.append(("id", pid))
            continue
        if "v.kuaishou.com" in line:
            key = line
            if key not in seen:
                seen.add(key)
                items.append(("share", line))
            continue
        if BARE_RE.match(line):
            if line not in seen:
                seen.add(line)
                items.append(("id", line))
    return items


def resolve_share_link(url: str, timeout: int = 20) -> str:
    """把 v.kuaishou.com 短链解析成 short-video 的 ID"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        final = r.geturl()
    m = ID_RE.search(final)
    if m:
        return m.group(1)
    raise RuntimeError("短链未解析出视频 ID")


def fetch_page(pid: str, stop_event=None) -> str:
    """抓取分享页 HTML，返回页面源码"""
    last = None
    for base in BASES:
        url = base % pid
        for attempt in range(2):
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("已停止")
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=25) as r:
                    body = r.read().decode("utf-8", "replace")
                if len(body) > 5000:
                    return body
                last = "返回页面内容过短"
            except Exception as e:
                last = str(e)
            threading.Event().wait(1.2 * (attempt + 1))
    raise RuntimeError(last or "抓取失败")


def parse_page(body: str) -> dict:
    """从页面里抠出 mp4 地址 / 封面 / 作者"""
    info = {}
    m = re.search(r'"mainMvUrls":\[\{"cdn":"[^"]*","url":"([^"]+)"', body)
    if m:
        info["video"] = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
    for key, field in (("userName", "author"), ("caption", "caption"), ("photoId", "photo_id")):
        m = re.search(r'"%s":"((?:[^"\\]|\\.)*)"' % key, body)
        if m:
            raw = m.group(1)
            try:
                info[field] = json.loads('"%s"' % raw)
            except Exception:
                info[field] = raw
    return info


def sanitize(name: str, maxlen: int = 40) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:maxlen].strip().strip(".")


def download_file(url: str, dest: Path, stop_event=None, timeout: int = 90) -> int:
    """流式下载到 .part，成功后再改名，避免留下半截文件"""
    tmp = str(dest) + ".part"
    req = urllib.request.Request(url, headers=dict(HEADERS, **{"Referer": "https://m.kuaishou.com/"}))
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        while True:
            if stop_event is not None and stop_event.is_set():
                f.close()
                os.remove(tmp)
                raise RuntimeError("已停止")
            chunk = r.read(1024 * 512)
            if not chunk:
                break
            f.write(chunk)
    size = os.path.getsize(tmp)
    if size < 10000:
        os.remove(tmp)
        raise RuntimeError("文件过小（%d 字节）" % size)
    if dest.exists():
        dest.unlink()
    os.rename(tmp, dest)
    return size


def download_one(idx: int, kind: str, value: str, out_dir: Path, stop_event) -> dict:
    """下载单条，返回结果字典（不抛异常）"""
    rec = {"idx": idx, "id": value, "status": "fail", "size": 0, "file": "", "error": ""}
    try:
        pid = value if kind == "id" else resolve_share_link(value)
        rec["id"] = pid
        body = fetch_page(pid, stop_event)
        info = parse_page(body)
        if not info.get("video"):
            raise RuntimeError("页面无视频数据（可能已删除 / 私密）")

        name = "%03d_%s" % (idx, pid)
        dest = out_dir / (name + ".mp4")
        if dest.exists() and dest.stat().st_size > 10000:
            rec.update(status="skip", file=dest.name, size=dest.stat().st_size)
            return rec

        size = download_file(info["video"], dest, stop_event)
        rec.update(status="ok", file=dest.name, size=size,
                   author=info.get("author", ""), caption=info.get("caption", ""))
    except Exception as e:
        rec["error"] = str(e)[:160]
    return rec


def write_manifest(recs, out_dir: Path) -> Path:
    """把本次结果写成清单文件"""
    ok = [r for r in recs if r["status"] in ("ok", "skip")]
    fail = [r for r in recs if r["status"] == "fail"]
    total = sum(r["size"] for r in ok)
    lines = [
        "快手视频下载清单",
        "生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "目标文件夹：%s" % out_dir,
        "总数：%d    成功：%d    失败：%d    合计：%.2f GB"
        % (len(recs), len(ok), len(fail), total / 1073741824),
        "",
        "序号\t短链ID\t文件名\t大小(MB)\t状态",
    ]
    for r in recs:
        st = {"ok": "OK", "skip": "已存在", "fail": "失败"}.get(r["status"], r["status"])
        lines.append("%03d\t%s\t%s\t%.1f\t%s"
                     % (r["idx"], r["id"], r["file"] or "-", r["size"] / 1048576.0, st))
    if fail:
        lines.append("")
        lines.append("未能获取视频地址的链接：")
        for r in fail:
            lines.append("  %03d  %s  %s" % (r["idx"], r["id"], r["error"]))
    p = out_dir / ("下载清单_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    p.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
    return p


# --------------------------------------------------------------------------
# 界面
# --------------------------------------------------------------------------
class KuaishouApp:
    def __init__(self, root):
        self.root = root
        self.root.title("快手视频批量下载工具")
        self.root.minsize(800, 700)

        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.running = False

        main = tk.Frame(root, padx=20, pady=16)
        main.pack(fill="both", expand=True)

        tk.Label(main, text="快手视频批量下载", font=("微软雅黑", 18, "bold")).pack(pady=(0, 4))
        tk.Label(main, text="把视频链接粘贴到下面，每行一条（也支持只填短链 ID，或 v.kuaishou.com 分享链接）",
                 fg="#666").pack(pady=(0, 8))

        # ---- 链接输入 ----
        input_frame = tk.Frame(main)
        input_frame.pack(fill="both", expand=False)
        tk.Label(input_frame, text="视频链接：", anchor="w").pack(fill="x")

        box = tk.Frame(input_frame)
        box.pack(fill="both", expand=True)
        self.text = tk.Text(box, height=7, wrap="none", font=("Consolas", 9))
        self.text.pack(side="left", fill="both", expand=True)
        ysb = tk.Scrollbar(box, command=self.text.yview)
        ysb.pack(side="right", fill="y")
        self.text.config(yscrollcommand=ysb.set)

        # ---- 输出目录 ----
        dir_frame = tk.Frame(main)
        dir_frame.pack(fill="x", pady=(10, 0))
        tk.Label(dir_frame, text="保存到：", anchor="w").pack(side="left")
        self.dir_var = tk.StringVar(value=str(DEFAULT_DIR))
        tk.Entry(dir_frame, textvariable=self.dir_var).pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(dir_frame, text="浏览", command=self.choose_dir, width=8).pack(side="left")

        # ---- 选项行 ----
        opt_frame = tk.Frame(main)
        opt_frame.pack(fill="x", pady=(8, 0))
        tk.Label(opt_frame, text="同时下载：").pack(side="left")
        self.workers_var = tk.IntVar(value=4)
        ttk.Spinbox(opt_frame, from_=1, to=8, width=4, textvariable=self.workers_var).pack(side="left", padx=(0, 16))
        tk.Label(opt_frame, text="已存在同名文件时自动跳过", fg="#888").pack(side="left")

        # ---- 按钮行 ----
        btn_frame = tk.Frame(main)
        btn_frame.pack(fill="x", pady=10)
        self.btn_start = tk.Button(btn_frame, text="开始下载", command=self.start, bg="#27ae60", fg="white",
                                   font=("微软雅黑", 11, "bold"), width=14)
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = tk.Button(btn_frame, text="停止", command=self.stop, bg="#c0392b", fg="white",
                                  state="disabled", font=("微软雅黑", 11, "bold"), width=8)
        self.btn_stop.pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="清空列表", command=self.clear, bg="#e67e22", fg="white",
                  font=("微软雅黑", 11, "bold"), width=10).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="打开文件夹", command=self.open_dir, bg="#3498db", fg="white",
                  font=("微软雅黑", 11, "bold"), width=11).pack(side="left")

        # ---- 进度 ----
        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(main, variable=self.progress_var, maximum=100).pack(fill="x", pady=(4, 4))
        self.status_label = tk.Label(main, text="就绪", anchor="w", fg="#555")
        self.status_label.pack(fill="x")

        # ---- 日志 ----
        tk.Label(main, text="下载记录：", anchor="w").pack(fill="x", pady=(10, 2))
        log_frame = tk.Frame(main)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Listbox(log_frame, height=12, font=("Consolas", 9), activestyle="none")
        self.log.pack(side="left", fill="both", expand=True)
        log_sb = tk.Scrollbar(log_frame, command=self.log.yview)
        log_sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=log_sb.set)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # -------- 强制刷新布局，然后自动调整窗口大小并居中 --------
        self.root.update_idletasks()
        w = max(self.root.winfo_width(), 800)
        h = max(self.root.winfo_height(), 700)
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

        self.root.after(100, self.poll_queue)

    # ---------------- 界面动作 ----------------
    def choose_dir(self):
        d = filedialog.askdirectory(title="选择保存文件夹")
        if d:
            self.dir_var.set(d)

    def open_dir(self):
        d = Path(self.dir_var.get())
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    def clear(self):
        if self.running:
            messagebox.showwarning("提示", "正在下载，请先停止")
            return
        self.text.delete("1.0", tk.END)
        self.log.delete(0, tk.END)
        self.progress_var.set(0)
        self.status_label.config(text="就绪")

    def add_log(self, text, color="#333"):
        self.log.insert(tk.END, text)
        idx = self.log.size() - 1
        self.log.itemconfig(idx, foreground=color)
        self.log.see(idx)

    # ---------------- 下载流程 ----------------
    def start(self):
        if self.running:
            return
        items = parse_input(self.text.get("1.0", tk.END))
        if not items:
            messagebox.showwarning("提示", "请先粘贴至少一条视频链接")
            return

        out_dir = Path(self.dir_var.get().strip() or str(DEFAULT_DIR))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", "无法创建输出文件夹：\n%s" % e)
            return

        self.running = True
        self.stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress_var.set(0)
        self.log.delete(0, tk.END)
        self.status_label.config(text="共识别到 %d 条链接，开始下载..." % len(items))

        workers = max(1, min(8, int(self.workers_var.get() or 4)))
        threading.Thread(target=self._worker, args=(items, out_dir, workers), daemon=True).start()

    def stop(self):
        if self.running:
            self.stop_event.set()
            self.status_label.config(text="正在停止，等待当前文件结束...")
            self.btn_stop.config(state="disabled")

    def _worker(self, items, out_dir, workers):
        total = len(items)
        recs = []
        done = 0
        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {}
                for i, (kind, value) in enumerate(items, 1):
                    futures[ex.submit(download_one, i, kind, value, out_dir, self.stop_event)] = i
                for fut in as_completed(futures):
                    rec = fut.result()
                    recs.append(rec)
                    done += 1
                    self.queue.put(("result", rec, done, total))
                    if self.stop_event.is_set() and done >= total:
                        break
        except Exception as e:
            self.queue.put(("error", str(e)))

        recs.sort(key=lambda r: r["idx"])
        manifest = None
        try:
            manifest = write_manifest(recs, out_dir)
        except Exception:
            pass
        self.queue.put(("done", recs, manifest, self.stop_event.is_set()))

    def poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "result":
                    _, rec, done, total = msg
                    if rec["status"] == "ok":
                        txt = "[%03d/%03d] ✓ %6.1fMB  %s" % (rec["idx"], total, rec["size"] / 1048576.0, rec["file"])
                        self.add_log(txt, "#1e8449")
                    elif rec["status"] == "skip":
                        self.add_log("[%03d/%03d] - 已存在  %s" % (rec["idx"], total, rec["file"]), "#7f8c8d")
                    else:
                        self.add_log("[%03d/%03d] ✗ 失败  %s  %s" % (rec["idx"], total, rec["id"], rec["error"]), "#c0392b")
                    self.progress_var.set(done * 100.0 / total)
                    self.status_label.config(text="处理中 %d/%d" % (done, total))
                elif kind == "error":
                    self.add_log("错误：%s" % msg[1], "#c0392b")
                elif kind == "done":
                    _, recs, manifest, stopped = msg
                    self.on_finished(recs, manifest, stopped)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def on_finished(self, recs, manifest, stopped):
        self.running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

        ok = [r for r in recs if r["status"] == "ok"]
        skip = [r for r in recs if r["status"] == "skip"]
        fail = [r for r in recs if r["status"] == "fail"]
        size = sum(r["size"] for r in recs)

        self.progress_var.set(100 if not stopped else self.progress_var.get())
        self.status_label.config(
            text="%s  成功 %d / 跳过 %d / 失败 %d，合计 %.2f GB"
                 % ("已停止" if stopped else "下载完成", len(ok), len(skip), len(fail), size / 1073741824))

        msg = "成功：%d\n已存在跳过：%d\n失败：%d\n合计：%.2f GB" % (len(ok), len(skip), len(fail), size / 1073741824)
        if manifest:
            msg += "\n\n清单文件：\n%s" % manifest.name
        if fail:
            msg += "\n\n失败的链接可以在清单文件里查看。"
        messagebox.showinfo("完成" if not stopped else "已停止", msg)

    def on_close(self):
        if self.running:
            if not messagebox.askyesno("确认", "正在下载，确定要退出吗？"):
                return
            self.stop_event.set()
        self.root.destroy()


if __name__ == "__main__":
    # -------- 添加 Windows DPI 感知，解决高缩放比下界面显示问题 --------
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    try:
        root.iconphoto(True, tk.PhotoImage(data=ICON_PNG_B64))
    except Exception:
        pass
    app = KuaishouApp(root)
    root.mainloop()
