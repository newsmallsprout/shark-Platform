import os
import urllib.request

VENDOR_DIR = os.path.join("static", "vendor")

ASSETS = [
    ("https://unpkg.com/vue@3/dist/vue.global.prod.js", os.path.join(VENDOR_DIR, "vue.global.prod.js")),
    ("https://unpkg.com/element-plus/dist/index.css", os.path.join(VENDOR_DIR, "element-plus", "index.css")),
    ("https://unpkg.com/element-plus/dist/index.full.min.js", os.path.join(VENDOR_DIR, "element-plus", "index.full.min.js")),
    ("https://unpkg.com/@element-plus/icons-vue/dist/index.iife.min.js", os.path.join(VENDOR_DIR, "icons", "index.iife.min.js")),
]

def ensure_vendor_assets():
    os.makedirs(VENDOR_DIR, exist_ok=True)
    for _, dst in ASSETS:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    for url, dst in ASSETS:
        try:
            if not os.path.exists(dst) or os.path.getsize(dst) == 0:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read()
                with open(dst, "wb") as f:
                    f.write(data)
        except Exception:
            pass
