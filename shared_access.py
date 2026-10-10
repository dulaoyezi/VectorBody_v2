"""Shared testing login for the locally hosted VectorBody Web application.

The configured email is a WEBSITE LOGIN ID, not an SMTP account.
No mailbox password is used or transmitted. This is a shared test account,
not student-specific authentication or independent private report storage.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, RedirectResponse
from pydantic import BaseModel, Field

COOKIE_NAME = "vb_test_session"
SESSION_SECONDS = 12 * 60 * 60
FAIL_WINDOW_SECONDS = 15 * 60
MAX_FAILED_ATTEMPTS = 8


class LoginPayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def install_shared_access(app: FastAPI, data_dir: Path) -> None:
    """Attach login, QR login-link and API-wide authentication middleware."""
    email = os.getenv("VECTORBODY_TEST_EMAIL", "huanjiaceshi@163.com").strip().casefold()
    password = os.getenv("VECTORBODY_TEST_PASSWORD", "")
    if len(password) < 12:
        raise RuntimeError(
            "设置至少12位的 VECTORBODY_TEST_PASSWORD（VectorBody专用密码，不能是163邮箱密码）。"
        )
    # PBKDF2 avoids storing or logging the raw website password.
    salt = hashlib.sha256(("VectorBody shared login:" + email).encode("utf-8")).digest()
    password_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000)
    public_url = os.getenv("VECTORBODY_PUBLIC_URL", "").strip().rstrip("/")
    secure_cookie = _truthy(os.getenv(
        "VECTORBODY_COOKIE_SECURE", "true" if public_url else "false"
    ))
    if public_url and not secure_cookie:
        raise RuntimeError("公网 HTTPS 登录必须启用安全 Cookie；请删除 VECTORBODY_COOKIE_SECURE=false。")
    if public_url:
        parsed = urlsplit(public_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or len(public_url) > 1024
        ):
            raise RuntimeError("VECTORBODY_PUBLIC_URL 必须是独立的 HTTPS 网站根地址。")
    db_path = Path(data_dir) / "shared_access.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS sessions(
                token_hash TEXT PRIMARY KEY,
                expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS failed_logins(
                source TEXT PRIMARY KEY,
                window_started INTEGER NOT NULL,
                count INTEGER NOT NULL
            );"""
        )

    def authenticated(request: Request) -> bool:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return False
        with connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE token_hash=? AND expires>?",
                (_digest(token), int(time.time())),
            ).fetchone()
        return row is not None

    def source_key(request: Request) -> str:
        # Cloudflare supplies CF-Connecting-IP on requests traversing its tunnel.
        # Keep the application bound to loopback, so remote clients cannot
        # directly forge the header by bypassing the tunnel.
        address = request.headers.get("cf-connecting-ip") or (
            request.client.host if request.client else "unknown"
        )
        return _digest(address[:128])

    def login_attempt_allowed(source: str, now: int) -> bool:
        with connect() as conn:
            row = conn.execute(
                "SELECT window_started,count FROM failed_logins WHERE source=?", (source,)
            ).fetchone()
        if not row or now - row["window_started"] >= FAIL_WINDOW_SECONDS:
            return True
        return row["count"] < MAX_FAILED_ATTEMPTS

    def record_failure(source: str, now: int) -> None:
        with connect() as conn:
            row = conn.execute(
                "SELECT window_started,count FROM failed_logins WHERE source=?", (source,)
            ).fetchone()
            if not row or now - row["window_started"] >= FAIL_WINDOW_SECONDS:
                conn.execute(
                    "INSERT OR REPLACE INTO failed_logins VALUES(?,?,1)",
                    (source, now),
                )
            else:
                conn.execute(
                    "UPDATE failed_logins SET count=count+1 WHERE source=?",
                    (source,),
                )

    router = APIRouter(prefix="/api/auth", tags=["Account"])

    @router.get("/config")
    def auth_config():
        return {
            "email": email,
            "shared_account": True,
            "qr_enabled": bool(public_url),
            "public_url": public_url or None,
        }

    @router.get("/me")
    def me(request: Request):
        if not authenticated(request):
            raise HTTPException(status_code=401, detail="请先登录 VectorBody。")
        return {"email": email, "shared_account": True}

    @router.post("/login")
    def login(data: LoginPayload, request: Request):
        now = int(time.time())
        source = source_key(request)
        if not login_attempt_allowed(source, now):
            raise HTTPException(status_code=429, detail="登录尝试过多，请15分钟后再试。")
        supplied = hashlib.pbkdf2_hmac(
            "sha256", data.password.encode("utf-8"), salt, 180_000
        )
        good_password = hmac.compare_digest(supplied, password_digest)
        good_email = hmac.compare_digest(data.email.strip().casefold(), email)
        if not (good_email and good_password):
            record_failure(source, now)
            raise HTTPException(status_code=401, detail="测试邮箱或系统密码不正确。")
        token = secrets.token_urlsafe(32)
        with connect() as conn:
            conn.execute("DELETE FROM failed_logins WHERE source=?", (source,))
            conn.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            conn.execute(
                "INSERT INTO sessions VALUES(?,?)", (_digest(token), now + SESSION_SECONDS)
            )
        response = JSONResponse({"ok": True, "email": email})
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            path="/",
        )
        return response

    @router.post("/logout")
    def logout(request: Request):
        token = request.cookies.get(COOKIE_NAME)
        if token:
            with connect() as conn:
                conn.execute(
                    "DELETE FROM sessions WHERE token_hash=?", (_digest(token),)
                )
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @router.get("/qr")
    def public_qr():
        if not public_url:
            raise HTTPException(
                status_code=404,
                detail="请先设置 VECTORBODY_PUBLIC_URL 为公网 HTTPS 登录地址。",
            )
        import qrcode

        qr = qrcode.QRCode(box_size=7, border=3)
        qr.add_data(public_url + "/")
        qr.make(fit=True)
        img = qr.make_image(fill_color="#263b2d", back_color="white")
        data = io.BytesIO()
        img.save(data, format="PNG")
        return Response(
            content=data.getvalue(),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    app.include_router(router)

    @app.middleware("http")
    async def check_access(request: Request, call_next):
        path = request.url.path
        method = request.method
        # Reject cross-origin writes even if the user is already authenticated.
        if method not in {"GET", "HEAD", "OPTIONS"} and path.startswith("/api/"):
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "禁止跨站提交请求。"}, status_code=403)
            origin = request.headers.get("origin")
            if origin:
                origin_host = urlsplit(origin).netloc.casefold()
                request_host = (request.headers.get("host") or "").casefold()
                public_host = urlsplit(public_url).netloc.casefold() if public_url else ""
                if origin_host not in {request_host, public_host}:
                    return JSONResponse(
                        {"detail": "禁止跨站提交请求。"}, status_code=403
                    )

        is_public_api = path in {"/api/health"} or path.startswith("/api/auth/")
        # Visitors must pass the shared test login before seeing the evaluation UI.
        if path in {"/", "/web/index.html"} and not authenticated(request):
            return RedirectResponse(url="/login", status_code=303)
        if path.startswith("/api/") and not is_public_api and method != "OPTIONS":
            if not authenticated(request):
                return JSONResponse(
                    {"detail": "请先使用测试账号登录。"}, status_code=401
                )
            # Sharing the test account must not allow any visitor to remove
            # other visitors' assessment records by default.
            if method == "DELETE" and path.startswith("/api/reports/"):
                if not _truthy(os.getenv("VECTORBODY_SHARED_ALLOW_DELETE", "false")):
                    return JSONResponse(
                        {"detail": "统一测试账号不允许删除历史报告。"}, status_code=403
                    )

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path.startswith("/api/reports") or path.startswith("/api/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response
