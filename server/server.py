"""
SYNORA relay server
===================
A tiny WebSocket relay: it stores accounts (scrypt-hashed passwords) and
*encrypted* messages until the receiver picks them up.  It never sees
plaintext: encryption/decryption happens on the clients (X25519 + ChaCha20-Poly1305).

Run:  python server.py        (env: PORT, HOST, SYNORA_DB)
Needs: pip install "websockets>=13"
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from collections import deque
from http import HTTPStatus

log = logging.getLogger("synora")

USER_RE = re.compile(r"^[a-z0-9_]{3,20}$")
MIN_PW, MAX_PW = 8, 128
MAX_CT = 16 * 1024            # max ciphertext length (base64 chars)
RETENTION = 30 * 86400        # undelivered messages are deleted after 30 days
AUTH_TIMEOUT = 30             # seconds to log in after connecting

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    name    TEXT PRIMARY KEY,
    salt    BLOB NOT NULL,
    pwhash  BLOB NOT NULL,
    pk      TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sender    TEXT NOT NULL,
    recipient TEXT NOT NULL,
    cid       TEXT NOT NULL,
    nonce     TEXT NOT NULL,
    ct        TEXT NOT NULL,
    ts        INTEGER NOT NULL,
    UNIQUE(sender, cid)
);
CREATE INDEX IF NOT EXISTS idx_msg_rcpt ON messages(recipient, id);
"""


def now() -> int:
    return int(time.time())


def hash_pw(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def valid_pk(pk) -> bool:
    try:
        return isinstance(pk, str) and len(base64.b64decode(pk, validate=True)) == 32
    except Exception:
        return False


def field(m: dict, key: str, maxlen: int):
    v = m.get(key)
    if isinstance(v, str) and 0 < len(v) <= maxlen:
        return v
    return None


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def get_user(self, name):
        return self.db.execute("SELECT salt, pwhash, pk FROM users WHERE name=?", (name,)).fetchone()

    def user_exists(self, name) -> bool:
        return self.db.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone() is not None

    def create_user(self, name, salt, pwhash, pk) -> bool:
        try:
            self.db.execute("INSERT INTO users(name,salt,pwhash,pk,created) VALUES(?,?,?,?,?)",
                            (name, salt, pwhash, pk, now()))
            return True
        except sqlite3.IntegrityError:
            return False

    def set_pk(self, name, pk):
        self.db.execute("UPDATE users SET pk=? WHERE name=?", (pk, name))

    def get_pk(self, name):
        r = self.db.execute("SELECT pk FROM users WHERE name=?", (name,)).fetchone()
        return r[0] if r else None

    def add_msg(self, sender, rcpt, cid, nonce, ct):
        """-> (id, ts, is_duplicate)"""
        ts = now()
        try:
            cur = self.db.execute(
                "INSERT INTO messages(sender,recipient,cid,nonce,ct,ts) VALUES(?,?,?,?,?,?)",
                (sender, rcpt, cid, nonce, ct, ts))
            return cur.lastrowid, ts, False
        except sqlite3.IntegrityError:
            r = self.db.execute("SELECT id, ts FROM messages WHERE sender=? AND cid=?",
                                (sender, cid)).fetchone()
            return r[0], r[1], True

    def pending(self, rcpt):
        return self.db.execute(
            "SELECT id, sender, nonce, ct, ts FROM messages WHERE recipient=? ORDER BY id LIMIT 500",
            (rcpt,)).fetchall()

    def ack(self, msg_id, rcpt):
        r = self.db.execute("SELECT sender, cid FROM messages WHERE id=? AND recipient=?",
                            (msg_id, rcpt)).fetchone()
        if r:
            self.db.execute("DELETE FROM messages WHERE id=?", (msg_id,))
        return r

    def purge(self, older_than_ts):
        self.db.execute("DELETE FROM messages WHERE ts<?", (older_than_ts,))


class Limiter:
    def __init__(self, limit: int, window: float):
        self.limit, self.window, self.hits = limit, window, {}

    def _prune(self, key):
        t = time.monotonic()
        lst = [x for x in self.hits.get(key, []) if t - x < self.window]
        if lst:
            self.hits[key] = lst
        else:
            self.hits.pop(key, None)
        return lst

    def blocked(self, key) -> bool:
        return len(self._prune(key)) >= self.limit

    def hit(self, key):
        self._prune(key)
        self.hits.setdefault(key, []).append(time.monotonic())

    def reset(self, key):
        self.hits.pop(key, None)

    def sweep(self):
        for k in list(self.hits):
            self._prune(k)


class Conn:
    def __init__(self, ws, ip="?"):
        self.ws, self.ip, self.user = ws, ip, None
        self.times = deque(maxlen=60)

    async def send(self, obj: dict):
        try:
            await self.ws.send(json.dumps(obj, separators=(",", ":")))
        except Exception:
            pass


def err(code: str) -> dict:
    return {"t": "err", "code": code}


class Hub:
    def __init__(self, store: Store):
        self.store = store
        self.online = {}                        # username -> set[Conn]
        self.user_lim = Limiter(5, 300)         # failed logins per username
        self.ip_lim = Limiter(30, 300)          # failed logins per IP
        self.reg_lim = Limiter(10, 3600)        # registrations per IP

    # ---------- helpers ----------
    async def push(self, user: str, obj: dict):
        for c in list(self.online.get(user, ())):
            await c.send(obj)

    def drop(self, conn: Conn):
        if conn.user and conn.user in self.online:
            self.online[conn.user].discard(conn)
            if not self.online[conn.user]:
                del self.online[conn.user]

    async def attach(self, conn: Conn, user: str):
        conn.user = user
        self.online.setdefault(user, set()).add(conn)
        await conn.send({"t": "ok", "u": user})
        for mid, sender, nonce, ct, ts in self.store.pending(user):
            await conn.send({"t": "msg", "id": mid, "from": sender, "n": nonce, "c": ct, "ts": ts})

    # ---------- dispatch ----------
    async def handle(self, conn: Conn, raw: str):
        try:
            m = json.loads(raw)
        except Exception:
            return await conn.send(err("bad_request"))
        if not isinstance(m, dict):
            return await conn.send(err("bad_request"))
        t = m.get("t")

        if conn.user is None:
            if t == "register":
                return await self.register(conn, m)
            if t == "login":
                return await self.login(conn, m)
            return await conn.send(err("auth_required"))

        # flood protection: 60 packets / 10 s per connection
        tm = time.monotonic()
        while conn.times and tm - conn.times[0] > 10:
            conn.times.popleft()
        if len(conn.times) >= 60:
            return await conn.send(err("rate_limited"))
        conn.times.append(tm)

        if t == "msg":
            await self.on_msg(conn, m)
        elif t == "ack":
            await self.on_ack(conn, m)
        elif t == "get_key":
            u = field(m, "u", 32)
            if u:
                u = u.lower()
                await conn.send({"t": "key", "u": u, "pk": self.store.get_pk(u)})
        elif t == "who":
            q = m.get("u")
            if isinstance(q, list):
                q = [x.lower() for x in q[:200] if isinstance(x, str) and len(x) <= 32]
                await conn.send({"t": "presence", "q": q, "on": [x for x in q if x in self.online]})
        else:
            await conn.send(err("bad_request"))

    # ---------- auth ----------
    async def register(self, conn, m):
        u, p, pk = field(m, "u", 32), field(m, "p", MAX_PW + 1), m.get("pk")
        if not u or not p or not valid_pk(pk):
            return await conn.send(err("bad_request"))
        u = u.lower()
        if not USER_RE.match(u):
            return await conn.send(err("bad_username"))
        if not (MIN_PW <= len(p) <= MAX_PW):
            return await conn.send(err("weak_password"))
        if self.reg_lim.blocked(conn.ip):
            return await conn.send(err("rate_limited"))
        self.reg_lim.hit(conn.ip)
        salt = os.urandom(16)
        h = await asyncio.to_thread(hash_pw, p, salt)
        if not self.store.create_user(u, salt, h, pk):
            return await conn.send(err("username_taken"))
        await self.attach(conn, u)

    async def login(self, conn, m):
        u, p, pk = field(m, "u", 32), field(m, "p", MAX_PW + 1), m.get("pk")
        if not u or not p:
            return await conn.send(err("bad_request"))
        u = u.lower()
        if self.user_lim.blocked(u) or self.ip_lim.blocked(conn.ip):
            return await conn.send(err("rate_limited"))
        row = self.store.get_user(u)
        if row is None:
            await asyncio.to_thread(hash_pw, p, b"\0" * 16)   # equalise timing
            good = False
        else:
            salt, pwhash, old_pk = row
            h = await asyncio.to_thread(hash_pw, p, bytes(salt))
            good = hmac.compare_digest(h, bytes(pwhash))
        if not good:
            self.user_lim.hit(u)
            self.ip_lim.hit(conn.ip)
            return await conn.send(err("bad_credentials"))
        self.user_lim.reset(u)
        if valid_pk(pk) and pk != old_pk:
            self.store.set_pk(u, pk)          # new device -> new key
        await self.attach(conn, u)

    # ---------- messaging ----------
    async def on_msg(self, conn, m):
        to, cid = field(m, "to", 32), field(m, "cid", 64)
        n, c = field(m, "n", 64), field(m, "c", MAX_CT)
        if not (to and cid and n and c):
            return await conn.send(err("bad_request"))
        to = to.lower()
        if to == conn.user:
            return await conn.send(err("bad_request"))
        if not self.store.user_exists(to):
            return await conn.send(err("no_such_user"))
        mid, ts, dup = self.store.add_msg(conn.user, to, cid, n, c)
        await conn.send({"t": "sent", "cid": cid, "ts": ts})
        if not dup:
            await self.push(to, {"t": "msg", "id": mid, "from": conn.user, "n": n, "c": c, "ts": ts})

    async def on_ack(self, conn, m):
        mid = m.get("id")
        if not isinstance(mid, int):
            return
        r = self.store.ack(mid, conn.user)
        if r:
            sender, cid = r
            await self.push(sender, {"t": "delivered", "cid": cid, "to": conn.user})


# ------------------------------------------------------------------ network
def client_ip(ws) -> str:
    try:
        xff = ws.request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
    except Exception:
        pass
    try:
        return ws.remote_address[0]
    except Exception:
        return "?"


async def main():
    from websockets.asyncio.server import serve
    from websockets.exceptions import ConnectionClosed

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(os.environ.get("SYNORA_DB", "synora.db"))
    hub = Hub(store)

    async def watchdog(conn):
        await asyncio.sleep(AUTH_TIMEOUT)
        if conn.user is None:
            await conn.ws.close()

    async def handler(ws):
        conn = Conn(ws, client_ip(ws))
        wd = asyncio.create_task(watchdog(conn))
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    await hub.handle(conn, raw)
        except ConnectionClosed:
            pass
        finally:
            wd.cancel()
            hub.drop(conn)

    async def health(connection, request):
        # plain HTTP request (health check / warm-up ping) -> 200 OK
        if request.headers.get("Upgrade", "").lower() != "websocket":
            return connection.respond(HTTPStatus.OK, "SYNORA relay is running\n")
        return None

    async def janitor():
        while True:
            await asyncio.sleep(3600)
            store.purge(now() - RETENTION)
            for lim in (hub.user_lim, hub.ip_lim, hub.reg_lim):
                lim.sweep()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8765"))
    async with serve(handler, host, port, process_request=health, max_size=64 * 1024) as server:
        log.info("SYNORA relay listening on %s:%s", host, port)
        asyncio.create_task(janitor())
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
