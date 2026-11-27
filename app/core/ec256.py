"""
Đường cong elliptic NIST P-256 (secp256r1) thuần Python — cho Web Push (0.25): ECDH (mã hoá nội dung RFC 8291) và
ECDSA P-256 + SHA-256 (chữ ký VAPID / JWT ES256, RFC 8292). Không dùng thư viện `cryptography` (không có cho armv7).

- Toạ độ Jacobian, nhân vô hướng kiểu "Montgomery ladder" (số phép tính không phụ thuộc bit của khoá).
- ECDSA: k sinh tất định theo RFC 6979 (không phụ thuộc chất lượng bộ sinh số ngẫu nhiên), s chuẩn hoá thấp.
- Kiểm tra điểm nhận vào nằm trên đường cong (chống tấn công điểm không hợp lệ khi ECDH).
Đã đối chiếu với thư viện cryptography và véc-tơ thử của RFC 8291 trong tests/docker/t_webpush.py.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
G = (GX, GY)

Point = Optional[tuple[int, int]]  # None = điểm vô cực


def _inv(x: int, m: int = P) -> int:
    return pow(x, m - 2, m)


def on_curve(pt: Point) -> bool:
    if pt is None:
        return False
    x, y = pt
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


# ---------------------------------------------------------------- Jacobian (X, Y, Z) với x = X/Z², y = Y/Z³
def _jdouble(p):
    X, Y, Z = p
    if Y == 0 or Z == 0:
        return (0, 1, 0)
    YY = Y * Y % P
    S = 4 * X * YY % P
    ZZ = Z * Z % P
    M = 3 * (X - ZZ) * (X + ZZ) % P  # a = -3
    X3 = (M * M - 2 * S) % P
    Y3 = (M * (S - X3) - 8 * YY * YY) % P
    Z3 = 2 * Y * Z % P
    return (X3, Y3, Z3)


def _jadd(p, q):
    X1, Y1, Z1 = p
    X2, Y2, Z2 = q
    if Z1 == 0:
        return q
    if Z2 == 0:
        return p
    Z1Z1 = Z1 * Z1 % P
    Z2Z2 = Z2 * Z2 % P
    U1 = X1 * Z2Z2 % P
    U2 = X2 * Z1Z1 % P
    S1 = Y1 * Z2 * Z2Z2 % P
    S2 = Y2 * Z1 * Z1Z1 % P
    if U1 == U2:
        return _jdouble(p) if S1 == S2 else (0, 1, 0)
    H = (U2 - U1) % P
    R = (S2 - S1) % P
    HH = H * H % P
    HHH = H * HH % P
    V = U1 * HH % P
    X3 = (R * R - HHH - 2 * V) % P
    Y3 = (R * (V - X3) - S1 * HHH) % P
    Z3 = H * Z1 * Z2 % P
    return (X3, Y3, Z3)


def _to_affine(p) -> Point:
    X, Y, Z = p
    if Z == 0:
        return None
    zi = _inv(Z)
    zi2 = zi * zi % P
    return (X * zi2 % P, Y * zi2 * zi % P)


def mul(k: int, pt: Point = G) -> Point:
    """k · pt (Montgomery ladder: cùng số phép tính cho mọi bit)."""
    if pt is None or k % N == 0:
        return None
    k %= N
    r0, r1 = (0, 1, 0), (pt[0], pt[1], 1)
    for i in range(N.bit_length() - 1, -1, -1):
        if (k >> i) & 1:
            r0, r1 = _jadd(r0, r1), _jdouble(r1)
        else:
            r1, r0 = _jadd(r0, r1), _jdouble(r0)
    return _to_affine(r0)


def add(p: Point, q: Point) -> Point:
    if p is None:
        return q
    if q is None:
        return p
    return _to_affine(_jadd((p[0], p[1], 1), (q[0], q[1], 1)))


# ---------------------------------------------------------------- khoá
def keypair() -> tuple[int, bytes]:
    """(khoá bí mật, khoá công khai 65 byte không nén 0x04||X||Y)."""
    d = secrets.randbelow(N - 1) + 1
    return d, encode_point(mul(d))


def public_from_private(d: int) -> bytes:
    return encode_point(mul(d))


def encode_point(pt: Point) -> bytes:
    if pt is None:
        raise ValueError("Point at infinity")
    return b"\x04" + pt[0].to_bytes(32, "big") + pt[1].to_bytes(32, "big")


def decode_point(raw: bytes) -> tuple[int, int]:
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError("Expected an uncompressed P-256 point (65 bytes)")
    pt = (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big"))
    if not on_curve(pt):
        raise ValueError("Point is not on the P-256 curve")
    return pt


def ecdh(d: int, peer_public: bytes) -> bytes:
    """Bí mật chung = toạ độ x của d·Q (32 byte)."""
    shared = mul(d, decode_point(peer_public))
    if shared is None:
        raise ValueError("Invalid shared secret")
    return shared[0].to_bytes(32, "big")


# ---------------------------------------------------------------- ECDSA P-256 / SHA-256 (RFC 6979)
def _bits2int(b: bytes) -> int:
    v = int.from_bytes(b, "big")
    extra = len(b) * 8 - N.bit_length()
    return v >> extra if extra > 0 else v


def _rfc6979_k(d: int, h1: bytes):
    x = d.to_bytes(32, "big")
    h = (_bits2int(h1) % N).to_bytes(32, "big")
    V, K = b"\x01" * 32, b"\x00" * 32
    K = hmac.new(K, V + b"\x00" + x + h, hashlib.sha256).digest()
    V = hmac.new(K, V, hashlib.sha256).digest()
    K = hmac.new(K, V + b"\x01" + x + h, hashlib.sha256).digest()
    V = hmac.new(K, V, hashlib.sha256).digest()
    while True:
        V = hmac.new(K, V, hashlib.sha256).digest()
        k = _bits2int(V)
        if 1 <= k < N:
            yield k
        K = hmac.new(K, V + b"\x00", hashlib.sha256).digest()
        V = hmac.new(K, V, hashlib.sha256).digest()


def sign(d: int, message: bytes) -> bytes:
    """Chữ ký ES256 dạng JOSE: r || s (mỗi số 32 byte)."""
    h1 = hashlib.sha256(message).digest()
    e = _bits2int(h1) % N
    for k in _rfc6979_k(d, h1):
        R = mul(k)
        r = R[0] % N if R else 0
        if r == 0:
            continue
        s = _inv(k, N) * (e + r * d) % N
        if s == 0:
            continue
        if s > N // 2:  # dạng "low-s"
            s = N - s
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")
    raise RuntimeError("unreachable")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    try:
        Q = decode_point(public)
    except ValueError:
        return False
    if len(signature) != 64:
        return False
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (1 <= r < N and 1 <= s < N):
        return False
    e = _bits2int(hashlib.sha256(message).digest()) % N
    w = _inv(s, N)
    X = add(mul(e * w % N), mul(r * w % N, Q))
    return X is not None and X[0] % N == r
