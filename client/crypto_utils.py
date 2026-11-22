"""End-to-end crypto helpers (X25519 + HKDF + ChaCha20-Poly1305) and vault sealing."""
import base64
import hashlib
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

MAGIC = b"SYN1"


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s)


def gen_keypair():
    """-> (private_bytes, public_bytes), both 32 bytes."""
    priv = X25519PrivateKey.generate()
    return (priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()),
            priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def _chat_key(my_priv: bytes, peer_pub: bytes, a: str, b: str) -> bytes:
    shared = X25519PrivateKey.from_private_bytes(my_priv).exchange(
        X25519PublicKey.from_public_bytes(peer_pub))
    info = b"synora-v1|" + "|".join(sorted([a, b])).encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(shared)


def encrypt_msg(my_priv, peer_pub, me, peer, plaintext: bytes):
    """-> (nonce_b64, ciphertext_b64). Sender and receiver names are authenticated (AAD)."""
    key = _chat_key(my_priv, peer_pub, me, peer)
    nonce = os.urandom(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext, f"{me}>{peer}".encode())
    return b64e(nonce), b64e(ct)


def decrypt_msg(my_priv, peer_pub, sender, me, nonce_b64, ct_b64) -> bytes:
    key = _chat_key(my_priv, peer_pub, sender, me)
    return ChaCha20Poly1305(key).decrypt(b64d(nonce_b64), b64d(ct_b64), f"{sender}>{me}".encode())


def safety_code(pub_a: bytes, pub_b: bytes):
    """Six 5-digit groups; identical on both phones if no one is in the middle."""
    lo, hi = sorted([pub_a, pub_b])
    h = hashlib.sha256(b"synora-safety|" + lo + hi).digest()
    return ["%05d" % (int.from_bytes(h[i * 4:i * 4 + 4], "big") % 100000) for i in range(6)]


def fingerprint(pub: bytes) -> str:
    h = hashlib.sha256(pub).hexdigest()[:32]
    return " ".join(h[i:i + 4] for i in range(0, 32, 4))


# ---- local vault sealing (password -> key via scrypt) ----
def derive_key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 14, r=8, p=1).derive(password.encode("utf-8"))


def seal(key: bytes, salt: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + salt + nonce + ChaCha20Poly1305(key).encrypt(nonce, plaintext, MAGIC + salt)


def unseal(key: bytes, blob: bytes) -> bytes:
    salt, nonce, ct = blob[4:20], blob[20:32], blob[32:]
    return ChaCha20Poly1305(key).decrypt(nonce, ct, MAGIC + salt)
