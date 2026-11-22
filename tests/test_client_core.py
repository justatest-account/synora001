import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
import crypto_utils as cu
from vault import Vault, VaultError
import textfix as tf

# --- E2E ---
ap, apub = cu.gen_keypair(); bp, bpub = cu.gen_keypair()
n, c = cu.encrypt_msg(ap, bpub, "alice", "bob", "سلام 👋 hello".encode())
assert cu.decrypt_msg(bp, apub, "alice", "bob", n, c).decode() == "سلام 👋 hello"
for bad in [lambda: cu.decrypt_msg(bp, apub, "mallory", "bob", n, c),
            lambda: cu.decrypt_msg(ap, apub, "alice", "bob", n, c),
            lambda: cu.decrypt_msg(bp, apub, "alice", "bob", n, c[:-4] + "AAAA")]:
    try: bad(); raise SystemExit("should fail")
    except SystemExit: raise
    except Exception: pass
assert cu.safety_code(apub, bpub) == cu.safety_code(bpub, apub) and len(cu.safety_code(apub, bpub)) == 6

# --- vault ---
d = tempfile.mkdtemp(); p = os.path.join(d, "v.bin")
v = Vault.new(p, "secret123", "alice"); v.chat("bob")["msgs"].append({"i": "1", "me": 1, "x": "hi", "ts": 1, "st": 0}); v.save()
raw = open(p, "rb").read(); assert b"bob" not in raw and b"hi" not in raw
v2 = Vault.open(p, "secret123"); assert v2.chats["bob"]["msgs"][0]["x"] == "hi" and v2.pub == v.pub
try: Vault.open(p, "wrong"); raise SystemExit("should fail")
except VaultError: pass

# --- wrapping (fake monospace measure: 10px per char) ---
m = lambda s: 10 * len(s)
t, rtl = tf.layout_text("hello brave new world", m, 110); assert t == "hello brave\nnew world" and not rtl, t
t, _ = tf.layout_text("a" * 25, m, 100); assert t.split("\n") == ["a" * 10, "a" * 10, "a" * 5], t
t, _ = tf.layout_text("x\n\ny", m, 100); assert t == "x\n\ny"
t, _ = tf.layout_text("", m, 100); assert t == ""
assert tf.para_rtl("سلام hello") and not tf.para_rtl("hello سلام") and not tf.para_rtl("123")
print("client core OK (reshaper present:", tf.arabic_reshaper is not None, ")")
