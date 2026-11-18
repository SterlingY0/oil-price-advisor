# -*- coding: utf-8 -*-
"""在 github.com 的 git 端口不通时，改用 REST API 把本地文件提交到仓库。

用法： python tools/publish_api.py <TOKEN> [--pages]

做的事：
  1) 读取本地文件 → 建 blob → 建 tree → 建 commit → 更新 refs/heads/main
  2) --pages 时尝试开启 GitHub Pages（main / root）并轮询构建
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
API = "https://api.github.com"
FILES = ["index.html", ".nojekyll", "README.md"]
MSG = "油价参谋：国内油价与加油建议（单文件静态站）"
TOKEN = ""


def api(method, path, body=None):
    headers = {
        "User-Agent": "oil-price-advisor-publish",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer " + TOKEN,
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(4):
        req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
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
            print("  [net] %s %s 重试 %d/4: %s" % (method, path, attempt + 1, e))
            time.sleep(3 + attempt * 3)
    raise SystemExit("[FAIL] 网络错误: %s" % last)


def main():
    global TOKEN
    args = sys.argv[1:]
    want_pages = "--pages" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    TOKEN = args[0].strip()

    st, me = api("GET", "/user")
    if st != 200:
        print("[FAIL] token 无效 %s: %s" % (st, str(me)[:200]))
        return 1
    print("[ok] token:", me.get("login"))

    st, repo = api("GET", "/repos/%s/%s" % (OWNER, REPO))
    if st != 200:
        print("[FAIL] 仓库不可访问 %s: %s" % (st, str(repo)[:200]))
        return 1
    print("[ok] 仓库: %s private=%s default_branch=%s size=%s"
          % (repo["full_name"], repo["private"], repo.get("default_branch"), repo.get("size")))

    pre = "/repos/%s/%s" % (OWNER, REPO)

    # 已有 main 的话拿它的 tree 作 base（保留历史），否则全新 tree
    parent = None
    st, ref = api("GET", "/repos/%s/%s/git/ref/heads/main" % (OWNER, REPO))
    if st == 200:
        parent = ref["object"]["sha"]
        print("[ok] 已有 main:", parent[:7])
    elif st not in (404, 409):
        print("[warn] 取 ref 失败 %s: %s" % (st, str(ref)[:150]))

    tree = []
    for name in FILES:
        full = os.path.join(ROOT, name)
        raw = open(full, "rb").read() if os.path.exists(full) else b""
        st, blob = api("POST", pre + "/git/blobs", {
            "content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
        if st not in (200, 201):
            print("[FAIL] blob %s 失败 %s: %s" % (name, st, str(blob)[:200]))
            return 1
        tree.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print("  blob %-14s %6d bytes  %s" % (name, len(raw), blob["sha"][:7]))

    body = {"tree": tree}
    if parent:
        st, base_tree = api("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, parent))
        if st == 200:
            body["base_tree"] = base_tree["tree"]["sha"]
    st, newtree = api("POST", pre + "/git/trees", body)
    if st not in (200, 201):
        print("[FAIL] tree 失败 %s: %s" % (st, str(newtree)[:200]))
        return 1
    print("[ok] tree:", newtree["sha"][:7])

    cbody = {"message": MSG, "tree": newtree["sha"]}
    if parent:
        cbody["parents"] = [parent]
    st, commit = api("POST", pre + "/git/commits", cbody)
    if st not in (200, 201):
        print("[FAIL] commit 失败 %s: %s" % (st, str(commit)[:300]))
        return 1
    print("[ok] commit:", commit["sha"][:7])

    if parent:
        st, out = api("PATCH", "/repos/%s/%s/git/refs/heads/main" % (OWNER, REPO),
                      {"sha": commit["sha"], "force": True})
        ok = st in (200, 201)
    else:
        st, out = api("POST", "/repos/%s/%s/git/refs" % (OWNER, REPO),
                      {"ref": "refs/heads/main", "sha": commit["sha"]})
        ok = st in (200, 201)
    if not ok:
        print("[FAIL] 更新 ref 失败 %s: %s" % (st, str(out)[:300]))
        return 1
    print("[ok] main 指向", commit["sha"][:7])

    if not want_pages:
        return 0

    src = {"source": {"branch": "main", "path": "/"}}
    st, out = api("POST", "/repos/%s/%s/pages" % (OWNER, REPO), src)
    if st == 201:
        print("[ok] Pages 已开启")
    elif st in (409, 422):
        st2, out2 = api("PUT", "/repos/%s/%s/pages" % (OWNER, REPO), src)
        if st2 in (200, 204):
            print("[ok] Pages 已更新")
        else:
            print("[FAIL] Pages 更新失败 %s: %s" % (st2, str(out2)[:300]))
            return 1
    else:
        print("[FAIL] Pages 开启失败 %s: %s" % (st, str(out)[:300]))
        return 1

    for _ in range(40):
        st, b = api("GET", "/repos/%s/%s/pages/builds/latest" % (OWNER, REPO))
        if st != 200:
            print("[warn] builds 查询失败 %s: %s" % (st, str(b)[:150]))
            break
        state = b.get("status")
        print("  build:", state, (b.get("error") or {}).get("message", ""))
        if state == "built":
            break
        if state == "errored":
            return 1
        time.sleep(10)

    st, pages = api("GET", "/repos/%s/%s/pages" % (OWNER, REPO))
    print("[done] 站点地址:", pages.get("html_url"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
