#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快手视频批量下载 - 命令行版

用法示例：
    python kuaishou_download_cli.py -f ids.txt -o ./downloads
    python kuaishou_download_cli.py https://www.kuaishou.com/short-video/3xnpwak69gk2p9c
    python kuaishou_download_cli.py -f urls.txt -j 6 --manifest
"""

import argparse
import json
import os
import re
import shutil
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}

BASES = [
    "https://m.kuaishou.com/fw/photo/%s",
    "https://v.m.chenzhongtech.com/fw/photo/%s?fid=0&cc=share_copylink&followRefer=151",
]

# 支持：kuaishou.com/short-video/xxx、gifshow.com/fw/photo/xxx、纯 ID
ID_RE = re.compile(r"(?:short-video|/photo)/([A-Za-z0-9_-]{6,})")
BARE_RE = re.compile(r"^[A-Za-z0-9_-]{10,16}$")


def parse_targets(lines):
    """从文本行里解析出视频 ID（支持完整链接 / 纯 ID）"""
    items, seen = [], set()
    for line in lines:
        line = line.strip().strip('"\'，,')
        if not line:
            continue
        m = ID_RE.search(line)
        pid = m.group(1) if m else (line if BARE_RE.match(line) else None)
        if pid and pid not in seen:
            seen.add(pid)
            items.append(pid)
    return items


def fetch_page(pid, stop_event=None):
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


def parse_page(body):
    info = {}
    m = re.search(r'"mainMvUrls":\[\{"cdn":"[^"]*","url":"([^"]+)"', body)
    if m:
        info["video"] = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
    for key, field in (("userName", "author"), ("caption", "caption")):
        m = re.search(r'"%s":"((?:[^"\\]|\\.)*)"' % key, body)
        if m:
            try:
                info[field] = json.loads('"%s"' % m.group(1))
            except Exception:
                info[field] = m.group(1)
    return info


def sanitize(name, maxlen=40):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name)
    return re.sub(r"\s+", " ", name).strip().strip(".")[:maxlen].strip(".")


def download_file(url, dest, stop_event=None):
    tmp = str(dest) + ".part"
    req = urllib.request.Request(url, headers=dict(HEADERS, **{"Referer": "https://m.kuaishou.com/"}))
    with urllib.request.urlopen(req, timeout=90) as r, open(tmp, "wb") as f:
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


def download_one(idx, pid, out_dir, stop_event):
    rec = {"idx": idx, "id": pid, "status": "fail", "size": 0, "file": "", "error": ""}
    try:
        body = fetch_page(pid, stop_event)
        info = parse_page(body)
        if not info.get("video"):
            raise RuntimeError("页面无视频数据（可能已删除 / 私密）")

        dest = out_dir / ("%03d_%s.mp4" % (idx, pid))
        if dest.exists() and dest.stat().st_size > 10000:
            rec.update(status="skip", file=dest.name, size=dest.stat().st_size)
            return rec

        rec.update(status="ok", file=dest.name,
                   size=download_file(info["video"], dest, stop_event))
        rec["author"] = info.get("author", "")
    except Exception as e:
        rec["error"] = str(e)[:160]
    return rec


def write_manifest(recs, out_dir):
    ok = [r for r in recs if r["status"] in ("ok", "skip")]
    fail = [r for r in recs if r["status"] == "fail"]
    total = sum(r["size"] for r in ok)
    lines = [
        "快手视频下载清单",
        "生成时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    p = out_dir / ("下载清单_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    p.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
    return p


def main():
    ap = argparse.ArgumentParser(description="快手视频批量下载")
    ap.add_argument("urls", nargs="*", help="视频链接或短链 ID，可多个")
    ap.add_argument("-f", "--file", help="从文本文件读取链接（每行一条）")
    ap.add_argument("-o", "--out", default="downloads", help="保存目录，默认 ./downloads")
    ap.add_argument("-j", "--jobs", type=int, default=4, help="并发数，默认 4")
    args = ap.parse_args()

    lines = list(args.urls)
    if args.file:
        lines += Path(args.file).read_text(encoding="utf-8").splitlines()
    if not lines:
        ap.error("请提供链接，或用 -f 指定链接文件")
    if sys.stdin and not sys.stdin.isatty():
        lines += sys.stdin.read().splitlines()

    ids = parse_targets(lines)
    if not ids:
        ap.error("没有解析到有效的视频链接")

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    print("共 %d 条链接 → %s（并发 %d）" % (len(ids), out_dir, args.jobs))

    stop_event = threading.Event()
    recs = []
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futures = [ex.submit(download_one, i, pid, out_dir, stop_event)
                       for i, pid in enumerate(ids, 1)]
            for done, fut in enumerate(as_completed(futures), 1):
                rec = fut.result()
                recs.append(rec)
                if rec["status"] == "ok":
                    print("[%d/%d] ok  %6.1fMB  %s" % (rec["idx"], len(ids), rec["size"] / 1048576.0, rec["file"]))
                elif rec["status"] == "skip":
                    print("[%d/%d] skip %s" % (rec["idx"], len(ids), rec["file"]))
                else:
                    print("[%d/%d] FAIL %s  %s" % (rec["idx"], len(ids), rec["id"], rec["error"]))
    except KeyboardInterrupt:
        stop_event.set()
        print("\n已中断")

    recs.sort(key=lambda r: r["idx"])
    manifest = write_manifest(recs, out_dir) if recs else None
    ok = sum(1 for r in recs if r["status"] in ("ok", "skip"))
    print("完成：成功 %d / 失败 %d%s" % (ok, len(recs) - ok,
          ("，清单 " + manifest.name) if manifest else ""))


if __name__ == "__main__":
    main()
