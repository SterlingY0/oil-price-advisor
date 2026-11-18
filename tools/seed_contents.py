# -*- coding: utf-8 -*-
"""空仓库引导：用 Contents API 逐个文件提交（empty repo 无法用 git/blobs）。

用法： python tools/seed_contents.py <TOKEN>
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

OWNER = "SterlingY0"
REPO = "oil-price-advisor"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["index.html", ".nojekyll", "README.md"]
TOKEN = ""


def api(method, path, body=None):
    headers = {"User-Agent": "oil-price-advisor-publish", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "Authorization": "Bearer " + TOKEN}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(5):
        req = urllib.request.Request("https://api.github.com" + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw}
        except (urllib.error.URLError, OSError) as e:
            last = e
            print("  [net] %s %s 重试 %d/5: %s" % (method, path, attempt + 1, e))
            time.sleep(3 + attempt * 4)
    raise SystemExit("[FAIL] 网络错误: %s" % last)


def main():
    global TOKEN
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    TOKEN = sys.argv[1].strip()
    pre = "/repos/%s/%s" % (OWNER, REPO)

    for name in FILES:
        full = os.path.join(ROOT, name)
        raw = open(full, "rb").read() if os.path.exists(full) else b""
        body = {"message": "添加 " + name, "content": base64.b64encode(raw).decode("ascii"), "branch": "main"}
        st, cur = api("GET", pre + "/contents/" + name + "?ref=main")
        if st == 200:
            body["sha"] = cur["sha"]
            st, out = api("PUT", pre + "/contents/" + name, body)
            action = "更新"
        else:
            st, out = api("PUT", pre + "/contents/" + name, body)
            action = "新建"
        if st not in (200, 201):
            print("[FAIL] %s %s 失败 %s: %s" % (action, name, st, str(out)[:250]))
            return 1
        print("[ok] %s %s  %d bytes  commit=%s" % (action, name, len(raw), out["commit"]["sha"][:7]))

    st, repo = api("GET", pre)
    print("[ok] 仓库 size=%s default_branch=%s" % (repo.get("size"), repo.get("default_branch")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
