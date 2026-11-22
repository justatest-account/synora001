import asyncio, base64, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import server as S


class FakeWS:
    def __init__(self): self.sent = []
    async def send(self, s): self.sent.append(json.loads(s))
    def last(self): return self.sent[-1]


PK = base64.b64encode(os.urandom(32)).decode()


async def say(hub, conn, **m):
    await hub.handle(conn, json.dumps(m))


async def run():
    hub = S.Hub(S.Store(":memory:"))
    a, b, c = (S.Conn(FakeWS(), "1.1.1.1") for _ in range(3))

    await say(hub, a, t="msg", to="bob")
    assert a.ws.last()["code"] == "auth_required"
    await say(hub, a, t="register", u="Al", p="password1", pk=PK)
    assert a.ws.last()["code"] == "bad_username"
    await say(hub, a, t="register", u="alice", p="short", pk=PK)
    assert a.ws.last()["code"] == "weak_password"
    await say(hub, a, t="register", u="Alice", p="password1", pk=PK)
    assert a.ws.last() == {"t": "ok", "u": "alice"}
    await say(hub, b, t="register", u="alice", p="password1", pk=PK)
    assert b.ws.last()["code"] == "username_taken"
    await say(hub, b, t="register", u="bob", p="password2", pk=PK)
    assert b.ws.last()["t"] == "ok"
    # bob goes offline
    hub.drop(b)

    await say(hub, a, t="msg", to="bob", cid="c1", n="bm9uY2U=", c="Y2lwaGVy")
    assert a.ws.last()["t"] == "sent"
    await say(hub, a, t="msg", to="bob", cid="c1", n="bm9uY2U=", c="Y2lwaGVy")   # duplicate
    await say(hub, a, t="msg", to="ghost", cid="c2", n="x", c="y")
    assert a.ws.last()["code"] == "no_such_user"

    # bob logs in on a new connection -> receives pending message
    b2 = S.Conn(FakeWS(), "2.2.2.2")
    await say(hub, b2, t="login", u="bob", p="wrong", pk=PK)
    assert b2.ws.last()["code"] == "bad_credentials"
    await say(hub, b2, t="login", u="BOB", p="password2", pk=PK)
    kinds = [x["t"] for x in b2.ws.sent]
    assert kinds == ["err", "ok", "msg"], kinds
    mid = b2.ws.sent[-1]["id"]
    assert b2.ws.sent[-1]["from"] == "alice"
    await say(hub, b2, t="ack", id=mid)
    assert a.ws.last() == {"t": "delivered", "cid": "c1", "to": "bob"}
    assert hub.store.pending("bob") == []

    # live push
    await say(hub, a, t="msg", to="bob", cid="c3", n="bm9uY2U=", c="Y2lwaGVy")
    assert b2.ws.last()["t"] == "msg" and b2.ws.last()["from"] == "alice"

    # keys / presence
    await say(hub, b2, t="get_key", u="alice")
    assert b2.ws.last() == {"t": "key", "u": "alice", "pk": PK}
    await say(hub, b2, t="get_key", u="nobody")
    assert b2.ws.last()["pk"] is None
    await say(hub, b2, t="who", u=["alice", "bob", "zed"])
    assert sorted(b2.ws.last()["on"]) == ["alice", "bob"]

    # key rotation on login from a new device
    PK2 = base64.b64encode(os.urandom(32)).decode()
    a2 = S.Conn(FakeWS(), "3.3.3.3")
    await say(hub, a2, t="login", u="alice", p="password1", pk=PK2)
    assert hub.store.get_pk("alice") == PK2

    # brute-force limiter
    for _ in range(5):
        x = S.Conn(FakeWS(), "9.9.9.9")
        await say(hub, x, t="login", u="alice", p="nope", pk=PK)
    x = S.Conn(FakeWS(), "9.9.9.9")
    await say(hub, x, t="login", u="alice", p="password1", pk=PK)
    assert x.ws.last()["code"] == "rate_limited"

    # garbage
    await hub.handle(c, "not json")
    assert c.ws.last()["code"] == "bad_request"
    print("server logic OK")

asyncio.run(run())
