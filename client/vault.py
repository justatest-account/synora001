"""Encrypted on-device storage: private key + all chat history in ONE sealed file."""
import json
import os
import time

import crypto_utils as cu


class VaultError(Exception):
    pass


MAX_MSGS_PER_CHAT = 2000


class Vault:
    def __init__(self, path, key, salt, data):
        self.path, self.key, self.salt, self.data = path, key, salt, data

    # --- construction ---
    @classmethod
    def new(cls, path, password, user):
        priv, pub = cu.gen_keypair()
        salt = os.urandom(16)
        data = {"v": 1, "user": user, "priv": cu.b64e(priv), "pub": cu.b64e(pub), "chats": {}}
        return cls(path, cu.derive_key(password, salt), salt, data)

    @classmethod
    def open(cls, path, password):
        try:
            with open(path, "rb") as f:
                blob = f.read()
            if blob[:4] != cu.MAGIC or len(blob) < 48:
                raise VaultError("bad file")
            salt = blob[4:20]
            key = cu.derive_key(password, salt)
            data = json.loads(cu.unseal(key, blob).decode("utf-8"))
            return cls(path, key, salt, data)
        except VaultError:
            raise
        except Exception as e:
            raise VaultError(str(e))

    # --- keys ---
    @property
    def priv(self):
        return cu.b64d(self.data["priv"])

    @property
    def pub(self):
        return cu.b64d(self.data["pub"])

    # --- chats ---
    @property
    def chats(self):
        return self.data["chats"]

    def chat(self, peer):
        c = self.data["chats"].get(peer)
        if c is None:
            c = {"pk": "", "msgs": [], "unread": 0, "changed": False, "created": int(time.time())}
            self.data["chats"][peer] = c
        if len(c["msgs"]) > MAX_MSGS_PER_CHAT:
            del c["msgs"][:len(c["msgs"]) - MAX_MSGS_PER_CHAT]
        return c

    # --- persistence ---
    def save(self):
        blob = cu.seal(self.key, self.salt, json.dumps(self.data, ensure_ascii=False).encode("utf-8"))
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
