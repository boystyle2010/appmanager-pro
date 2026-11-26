"""
AES thuần Python (FIPS-197) cho mã hoá nội dung thông báo — không thêm thư viện (cryptography không có sẵn cho armv7).
Chỉ dùng cho tin ngắn (vài KB), tốc độ không quan trọng.

- cbc_encrypt / cbc_decrypt: AES-CBC + PKCS#7 (Bark: app iPhone tự giải mã; khoá 16/24/32 ký tự, IV 16 ký tự)
- gcm_encrypt / gcm_decrypt: AES-GCM (Webhook: nonce 12 byte + bản mã + tag 16 byte)
Đã đối chiếu với thư viện cryptography và véc-tơ chuẩn NIST trong tests/docker/t_notify3.py.
"""
from __future__ import annotations

import hmac

_SBOX = [0] * 256
_INV = [0] * 256


def _init() -> None:
    p = q = 1
    while True:  # sinh S-box theo trường GF(2^8)
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        x = (x ^ 0x63) & 0xFF
        _SBOX[p] = x
        _INV[x] = p
        if p == 1:
            break
    _SBOX[0] = 0x63
    _INV[0x63] = 0


_init()


def _xt(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _expand(key: bytes) -> list[list[int]]:
    nk = len(key) // 4
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16, 24 or 32 bytes")
    nr = nk + 6
    w = [list(key[i * 4:i * 4 + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(nr + 1)]


def _encrypt_block(rk: list[list[int]], block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, rk[0])]
    nr = len(rk) - 1
    for rnd in range(1, nr + 1):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]  # ShiftRows (cột chính)
        if rnd != nr:
            m = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                m += [_xt(a[0]) ^ _xt(a[1]) ^ a[1] ^ a[2] ^ a[3], a[0] ^ _xt(a[1]) ^ _xt(a[2]) ^ a[2] ^ a[3],
                      a[0] ^ a[1] ^ _xt(a[2]) ^ _xt(a[3]) ^ a[3], _xt(a[0]) ^ a[0] ^ a[1] ^ a[2] ^ _xt(a[3])]
            s = m
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return bytes(s)


def _decrypt_block(rk: list[list[int]], block: bytes) -> bytes:
    nr = len(rk) - 1
    s = [b ^ k for b, k in zip(block, rk[nr])]
    for rnd in range(nr - 1, -1, -1):
        s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]  # InvShiftRows
        s = [_INV[b] for b in s]
        s = [b ^ k for b, k in zip(s, rk[rnd])]
        if rnd:
            m = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                m += [_mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9),
                      _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13),
                      _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11),
                      _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)]
            s = m
    return bytes(s)


# ---------------------------------------------------------------- CBC + PKCS#7
def cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(iv) != 16:
        raise ValueError("IV must be 16 bytes")
    rk = _expand(key)
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        prev = _encrypt_block(rk, bytes(a ^ b for a, b in zip(data[i:i + 16], prev)))
        out += prev
    return out


def cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    rk = _expand(key)
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(rk, blk), prev))
        prev = blk
    pad = out[-1] if out else 0
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ValueError("Bad padding")
    return out[:-pad]


# ---------------------------------------------------------------- GCM
def _gmul(x: int, y: int) -> int:
    r, R = 0, 0xE1 << 120
    for i in range(127, -1, -1):
        if (y >> i) & 1:
            r ^= x
        x = (x >> 1) ^ R if x & 1 else x >> 1
    return r


def _ghash(h: int, aad: bytes, ct: bytes) -> int:
    def blocks(b: bytes):
        b += b"\0" * (-len(b) % 16)
        for i in range(0, len(b), 16):
            yield int.from_bytes(b[i:i + 16], "big")
    y = 0
    for blk in list(blocks(aad)) + list(blocks(ct)):
        y = _gmul(y ^ blk, h)
    lens = ((len(aad) * 8) << 64) | (len(ct) * 8)
    return _gmul(y ^ lens, h)


def _ctr(rk, j0: int, data: bytes) -> bytes:
    out = b""
    for n, i in enumerate(range(0, len(data), 16)):
        ctr = (j0 & ~0xFFFFFFFF) | ((j0 + 1 + n) & 0xFFFFFFFF)
        ks = _encrypt_block(rk, ctr.to_bytes(16, "big"))
        out += bytes(a ^ b for a, b in zip(data[i:i + 16], ks))
    return out


def gcm_encrypt(key: bytes, nonce: bytes, data: bytes, aad: bytes = b"") -> bytes:
    """Trả bản mã + tag (16 byte). nonce 12 byte."""
    if len(nonce) != 12:
        raise ValueError("GCM nonce must be 12 bytes")
    rk = _expand(key)
    h = int.from_bytes(_encrypt_block(rk, b"\0" * 16), "big")
    j0 = int.from_bytes(nonce + b"\0\0\0\1", "big")
    ct = _ctr(rk, j0, data)
    tag = int.from_bytes(_encrypt_block(rk, j0.to_bytes(16, "big")), "big") ^ _ghash(h, aad, ct)
    return ct + tag.to_bytes(16, "big")


def gcm_decrypt(key: bytes, nonce: bytes, data: bytes, aad: bytes = b"") -> bytes:
    rk = _expand(key)
    ct, tag = data[:-16], data[-16:]
    h = int.from_bytes(_encrypt_block(rk, b"\0" * 16), "big")
    j0 = int.from_bytes(nonce + b"\0\0\0\1", "big")
    exp = int.from_bytes(_encrypt_block(rk, j0.to_bytes(16, "big")), "big") ^ _ghash(h, aad, ct)
    if not hmac.compare_digest(exp.to_bytes(16, "big"), tag):
        raise ValueError("Authentication failed")
    return _ctr(rk, j0, ct)
