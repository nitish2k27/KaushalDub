"""File storage with the same interface for Supabase Storage (production) and a local folder (dev/tests).
Buckets: raw-videos, outputs, keyframes (all private; the browser only ever gets signed URLs)."""
import hashlib
import hmac
import mimetypes
import os
import shutil
import time
from urllib.parse import quote

import httpx

from .config import get_settings

BUCKETS = ["raw-videos", "outputs", "keyframes"]


class LocalStorage:
    def __init__(self, root, secret, public_base):
        self.root, self.secret, self.public_base = root, (secret or "local-dev").encode(), public_base.rstrip("/")
        for b in BUCKETS:
            os.makedirs(os.path.join(root, b), exist_ok=True)

    def _p(self, bucket, path):
        full = os.path.abspath(os.path.join(self.root, bucket, path))
        if not full.startswith(os.path.abspath(os.path.join(self.root, bucket))):
            raise ValueError("bad path")
        return full

    def put_file(self, bucket, path, local, content_type=None):
        dst = self._p(bucket, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(local, dst)
        return path

    def put_bytes(self, bucket, path, data, content_type=None):
        dst = self._p(bucket, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        return path

    def download(self, bucket, path, local):
        os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
        shutil.copyfile(self._p(bucket, path), local)
        return local

    def exists(self, bucket, path):
        return os.path.exists(self._p(bucket, path))

    def delete(self, bucket, path):
        if self.exists(bucket, path):
            os.remove(self._p(bucket, path))

    def sign(self, bucket, path, exp):
        return hmac.new(self.secret, f"{bucket}/{path}:{exp}".encode(), hashlib.sha256).hexdigest()

    def signed_url(self, bucket, path, expires=3600):
        exp = int(time.time()) + expires
        return f"{self.public_base}/files/{bucket}/{quote(path)}?exp={exp}&sig={self.sign(bucket, path, exp)}"

    def verify(self, bucket, path, exp, sig):
        return int(exp) >= time.time() and hmac.compare_digest(self.sign(bucket, path, int(exp)), sig)

    def local_path(self, bucket, path):
        return self._p(bucket, path)


class SupabaseStorage:
    def __init__(self, url, service_key):
        self.url = url.rstrip("/")
        from .db import service_headers
        self.h = service_headers(service_key)
        self.http = httpx.Client(timeout=300)

    def _obj(self, bucket, path):
        return f"{self.url}/storage/v1/object/{bucket}/{quote(path)}"

    def put_bytes(self, bucket, path, data, content_type=None):
        ct = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        r = self.http.post(self._obj(bucket, path), content=data,
                           headers={**self.h, "Content-Type": ct, "x-upsert": "true"})
        if r.status_code >= 400:
            raise RuntimeError(f"storage upload {r.status_code}: {r.text[:200]}")
        return path

    def put_file(self, bucket, path, local, content_type=None):
        with open(local, "rb") as f:
            return self.put_bytes(bucket, path, f.read(), content_type)

    def download(self, bucket, path, local):
        os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
        with self.http.stream("GET", self._obj(bucket, path), headers=self.h) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"storage download {r.status_code} for {bucket}/{path}")
            with open(local, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return local

    def exists(self, bucket, path):
        r = self.http.head(self._obj(bucket, path), headers=self.h)
        return r.status_code == 200

    def delete(self, bucket, path):
        self.http.request("DELETE", f"{self.url}/storage/v1/object/{bucket}", headers=self.h, json={"prefixes": [path]})

    def signed_url(self, bucket, path, expires=3600):
        r = self.http.post(f"{self.url}/storage/v1/object/sign/{bucket}/{quote(path)}", headers=self.h,
                           json={"expiresIn": expires})
        if r.status_code >= 400:
            return None
        return self.url + "/storage/v1" + r.json()["signedURL"]


_storage = None


def get_storage():
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = (SupabaseStorage(s.supabase_url, s.supabase_service_key) if s.use_supabase
                    else LocalStorage(os.path.join(s.data_dir, "files"), s.file_url_secret, s.public_api_url))
    return _storage


def set_storage(st):
    global _storage
    _storage = st
