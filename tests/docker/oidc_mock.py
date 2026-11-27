"""Nhà cung cấp OpenID Connect giả cho test SSO (0.23): discovery, JWKS, authorize (tự đăng nhập người dùng chọn sẵn),
token (kiểm tra client secret Basic / post, PKCE S256, redirect_uri), userinfo. Ký id_token RS256 hoặc ES256 thật (thư
viện cryptography, chỉ dùng trong test). Chế độ lỗi qua /admin: sai aud, hết hạn, sai nonce, sai chữ ký, alg none, ...

Chạy: python oidc_mock.py <cổng> [cert key]   — điều khiển: POST /admin {"user": {...}, "alg": "RS256", "fault": ""}
"""
import base64, hashlib, json, secrets, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
TLS = sys.argv[2:4] if len(sys.argv) > 3 else None  # certfile keyfile -> HTTPS (id_token ES256 chỉ được nhận qua HTTPS)
ISS = f"{'https' if TLS else 'http'}://127.0.0.1:{PORT}"
CLIENT_ID, CLIENT_SECRET = "appmanager", "s3cret-value"
RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_KEY = ec.generate_private_key(ec.SECP256R1())
STATE = {"user": {"sub": "u-1", "preferred_username": "alice", "email": "alice@example.com", "groups": ["amp-admins"]},
         "alg": "RS256", "fault": "", "auth_method": "basic", "codes": {}, "token_calls": 0, "last_token_form": {}}
LOCK = threading.Lock()


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def int_b64(n: int) -> str:
    return b64u(n.to_bytes((n.bit_length() + 7) // 8, "big"))


def jwks():
    pub = RSA_KEY.public_key().public_numbers()
    other = RSA_OTHER.public_key().public_numbers()
    e = EC_KEY.public_key().public_numbers()
    return {"keys": [
        {"kty": "RSA", "kid": "other", "use": "sig", "alg": "RS256", "n": int_b64(other.n), "e": int_b64(other.e)},
        {"kty": "RSA", "kid": "rsa1", "use": "sig", "alg": "RS256", "n": int_b64(pub.n), "e": int_b64(pub.e)},
        {"kty": "EC", "kid": "ec1", "crv": "P-256", "x": b64u(e.x.to_bytes(32, "big")), "y": b64u(e.y.to_bytes(32, "big"))},
    ]}


def sign(claims: dict, alg: str, fault: str) -> str:
    header = {"alg": "none" if fault == "alg_none" else alg, "typ": "JWT", "kid": "ec1" if alg == "ES256" else "rsa1"}
    signing = f"{b64u(json.dumps(header).encode())}.{b64u(json.dumps(claims).encode())}"
    if fault == "alg_none":
        return signing + "."
    if alg == "ES256":
        r, s = decode_dss_signature(EC_KEY.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        h = {"RS256": hashes.SHA256(), "RS384": hashes.SHA384(), "RS512": hashes.SHA512()}[alg]
        key = RSA_OTHER if fault == "bad_sig" else RSA_KEY
        sig = key.sign(signing.encode(), padding.PKCS1v15(), h)
        if fault == "bad_sig":
            header["kid"] = "rsa1"  # ký bằng khoá khác nhưng nhận là rsa1
    return f"{signing}.{b64u(sig)}"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/.well-known/openid-configuration":
            iss = ISS + ("/wrong" if STATE["fault"] == "issuer_mismatch" else "")
            return self._json(200, {"issuer": iss, "authorization_endpoint": ISS + "/authorize", "token_endpoint": ISS + "/token",
                                    "userinfo_endpoint": ISS + "/userinfo", "jwks_uri": ISS + "/jwks",
                                    "id_token_signing_alg_values_supported": ["RS256", "ES256"],
                                    "code_challenge_methods_supported": ["S256"],
                                    "token_endpoint_auth_methods_supported": ["client_secret_post"] if STATE["auth_method"] == "post" else ["client_secret_basic"]})
        if u.path == "/jwks":
            return self._json(200, jwks())
        if u.path == "/authorize":
            if q.get("client_id") != CLIENT_ID or q.get("response_type") != "code" or q.get("code_challenge_method") != "S256":
                return self._json(400, {"error": "invalid_request"})
            if STATE["fault"] == "deny":
                loc = q["redirect_uri"] + "?" + urlencode({"error": "access_denied", "error_description": "User cancelled", "state": q.get("state", "")})
            else:
                code = secrets.token_urlsafe(16)
                with LOCK:
                    STATE["codes"][code] = {"redirect_uri": q["redirect_uri"], "nonce": q.get("nonce", ""), "challenge": q["code_challenge"],
                                            "user": dict(STATE["user"]), "scope": q.get("scope", "")}
                st = "tampered" if STATE["fault"] == "bad_state" else q.get("state", "")
                loc = q["redirect_uri"] + "?" + urlencode({"code": code, "state": st})
            self.send_response(302); self.send_header("Location", loc); self.end_headers(); return
        if u.path == "/userinfo":
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer at-"):
                return self._json(401, {"error": "invalid_token"})
            user = dict(STATE.get("last_user") or STATE["user"])
            if STATE["fault"] == "userinfo_other_sub":
                user["sub"] = "someone-else"; user["groups"] = ["amp-admins"]
            return self._json(200, user)
        self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode()
        if u.path == "/admin":
            data = json.loads(raw or "{}")
            with LOCK:
                for k in ("user", "alg", "fault", "auth_method"):
                    if k in data:
                        STATE[k] = data[k]
                if data.get("reset_counters"):
                    STATE["token_calls"] = 0
            return self._json(200, {"ok": True, "token_calls": STATE["token_calls"], "last_token_form": STATE["last_token_form"]})
        if u.path == "/token":
            form = {k: v[0] for k, v in parse_qs(raw).items()}
            STATE["token_calls"] += 1
            STATE["last_token_form"] = {k: ("***" if k == "client_secret" else v) for k, v in form.items()}
            cid, csec = form.get("client_id"), form.get("client_secret")
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                cid, csec = base64.b64decode(auth[6:]).decode().split(":", 1)
            if STATE["auth_method"] == "basic" and not auth.startswith("Basic "):
                return self._json(401, {"error": "invalid_client", "error_description": "Basic auth required"})
            if cid != CLIENT_ID or csec != CLIENT_SECRET:
                return self._json(401, {"error": "invalid_client", "error_description": "Wrong client credentials"})
            with LOCK:
                c = STATE["codes"].pop(form.get("code", ""), None)
            if not c:
                return self._json(400, {"error": "invalid_grant", "error_description": "Unknown or used code"})
            if form.get("redirect_uri") != c["redirect_uri"]:
                return self._json(400, {"error": "invalid_grant", "error_description": "redirect_uri mismatch"})
            if b64u(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != c["challenge"]:
                return self._json(400, {"error": "invalid_grant", "error_description": "PKCE verification failed"})
            now = int(time.time()); f = STATE["fault"]
            claims = {"iss": ISS, "sub": c["user"]["sub"], "aud": "someone-else" if f == "bad_aud" else CLIENT_ID,
                      "exp": now - 3600 if f == "expired" else now + 300, "iat": now, "nonce": "bad" if f == "bad_nonce" else c["nonce"],
                      "preferred_username": c["user"].get("preferred_username"), "email": c["user"].get("email")}
            if f != "groups_only_userinfo":
                claims["groups"] = c["user"].get("groups", [])
            STATE["last_user"] = c["user"]
            return self._json(200, {"access_token": "at-" + secrets.token_urlsafe(8), "token_type": "Bearer", "expires_in": 300,
                                    "id_token": sign(claims, STATE["alg"], f)})
        self._json(404, {"error": "not found"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    if TLS:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(TLS[0], TLS[1])
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()
