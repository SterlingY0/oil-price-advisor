# -*- coding: utf-8 -*-
"""把 D:\\oil-price-advisor 推送到 GitHub 并开启 Pages。

用法（在本文件所在目录执行）：
    python tools/publish.py <TOKEN> [--make-public]

TOKEN 需要细粒度 PAT，权限：
    Contents: Read and write     # 推送
    Pages: Read and write        # 开启 Pages
    Administration: Read and write  # 仅在加 --make-public 把私有库转为公开时需要

私有仓库 + 免费账号不支持 Pages：这种组合下必须加 --make-public，或改用别的托管。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER = "SterlingY0"
REPO = "oil-price-advisor"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
TOKEN = ""
UA = {"User-Agent": "oil-price-advisor-publish", "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"}


def api(method, path, body=None):
    headers = dict(UA)
    headers["Authorization"] = "Bearer " + TOKEN
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw}


def main():
    global TOKEN
    args = [a for a in sys.argv[1:]]
    make_public = "--make-public" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    TOKEN = args[0].strip()

    status, me = api("GET", "/user")
    if status != 200:
        print("[FAIL] token 无效 (%s): %s" % (status, str(me)[:200]))
        return 1
    plan = (me.get("plan") or {}).get("name", "?")
    print("[ok] token 属于 %s，plan=%s" % (me.get("login"), plan))

    status, repo = api("GET", "/repos/%s/%s" % (OWNER, REPO))
    print("[ok] 仓库可访问: %s (private=%s, default_branch=%s)"
          % (repo.get("full_name"), repo.get("private"), repo.get("default_branch")))

    if repo.get("private") and plan == "free" and not make_public:
        print("[stop] 私有仓库 + 免费账号无法开 Pages。确认转公开后加 --make-public 重跑。")
        return 3
    if repo.get("private") and make_public:
        status, out = api("PATCH", "/repos/%s/%s" % (OWNER, REPO), {"private": False})
        if status != 200:
            print("[FAIL] 转公开失败 (%s): %s" % (status, str(out)[:300]))
            return 1
        print("[ok] 仓库已转为公开")

    url = "https://%s:%s@github.com/%s/%s.git" % (OWNER, TOKEN, OWNER, REPO)
    push = subprocess.run(["git", "-c", "credential.helper=", "push", url, "main:main"],
                          cwd=ROOT, capture_output=True, text=True)
    print((push.stderr or push.stdout).strip()[-500:])
    if push.returncode != 0:
        print("[FAIL] 推送失败")
        return 1
    print("[ok] 已推送 main")

    src = {"source": {"branch": "main", "path": "/"}}
    status, out = api("POST", "/repos/%s/%s/pages" % (OWNER, REPO), src)
    if status == 201:
        print("[ok] Pages 已开启")
    elif status in (409, 422):
        status2, out2 = api("PUT", "/repos/%s/%s/pages" % (OWNER, REPO), src)
        if status2 in (200, 204):
            print("[ok] Pages 已更新为 main / root")
        else:
            print("[FAIL] 开启 Pages 失败 (%s): %s" % (status2, str(out2)[:300]))
            return 1
    else:
        print("[FAIL] 开启 Pages 失败 (%s): %s" % (status, str(out)[:300]))
        return 1

    for i in range(40):
        status, b = api("GET", "/repos/%s/%s/pages/builds/latest" % (OWNER, REPO))
        st = b.get("status") if isinstance(b, dict) else None
        print("  build:", st, b.get("error", {}).get("message", "") if isinstance(b, dict) else "")
        if st == "built":
            break
        if st == "errored":
            print("[FAIL] Pages 构建报错:", str(b)[:300])
            return 1
        time.sleep(10)

    status, pages = api("GET", "/repos/%s/%s/pages" % (OWNER, REPO))
    print("[done] 站点地址:", pages.get("html_url"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
