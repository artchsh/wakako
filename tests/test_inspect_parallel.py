import threading
import time

from wakako import client
from wakako.errors import QuotaError


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class SlowIndex:
    """Each inspect() sleeps a bit so parallel runs actually overlap."""

    def __init__(self, script, delay=0.05):
        self.script = script
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def inspect(self, body):
        outer = self

        class Req:
            def execute(self):
                with outer.lock:
                    outer.active += 1
                    outer.max_active = max(outer.max_active, outer.active)
                time.sleep(outer.delay)
                with outer.lock:
                    outer.active -= 1
                result = outer.script.get(body["inspectionUrl"], PASS)
                if isinstance(result, Exception):
                    raise result
                return result

        return Req()


def result(verdict):
    return {"inspectionResult": {"indexStatusResult": {"verdict": verdict, "coverageState": "x"}}}


PASS = result("PASS")


class Service:
    def __init__(self, index):
        self._index = index

    def urlInspection(self):
        index = self._index

        class UI:
            def index(self_inner):
                return index

        return UI()


def test_parallel_preserves_input_order_and_uses_a_service_per_thread():
    index = SlowIndex({})
    built = []

    def factory():
        built.append(1)
        return Service(index)

    urls = [f"https://x.com/{i}" for i in range(12)]
    rows = client.inspect_many(None, "s", urls, service_factory=factory, workers=4)
    assert [r["url"] for r in rows] == urls
    assert 1 < index.max_active <= 4  # genuinely concurrent, never above the worker count
    assert 1 < len(built) <= 4  # one service per worker thread


def test_parallel_only_unindexed_and_errors():
    script = {"https://x.com/1": result("NEUTRAL")}
    index = SlowIndex(script)
    urls = [f"https://x.com/{i}" for i in range(4)]
    rows = client.inspect_many(None, "s", urls, only_unindexed=True,
                               service_factory=lambda: Service(index), workers=3)
    assert [r["url"] for r in rows] == ["https://x.com/1"]


def test_parallel_stops_at_first_quota_error_in_input_order():
    script = {"https://x.com/2": QuotaError("Quota exceeded (429).")}
    index = SlowIndex(script, delay=0.02)
    urls = [f"https://x.com/{i}" for i in range(10)]
    rows = client.inspect_many(None, "s", urls, service_factory=lambda: Service(index), workers=4)
    assert [r["url"] for r in rows] == urls[:3]
    assert "Quota" in rows[-1]["error"]
    assert all(r["error"] == "" for r in rows[:-1])


def test_workers_one_ignores_factory_and_uses_given_service():
    index = SlowIndex({})
    rows = client.inspect_many(Service(index), "s", ["https://x.com/a"],
                               service_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
                               workers=1)
    assert rows[0]["verdict"] == "PASS"


def test_progress_called_in_order_in_parallel_mode():
    index = SlowIndex({}, delay=0.01)
    calls = []
    client.inspect_many(None, "s", [f"https://x.com/{i}" for i in range(5)],
                        progress=lambda d, n: calls.append((d, n)),
                        service_factory=lambda: Service(index), workers=3)
    assert calls == [(i, 5) for i in range(1, 6)]


def test_compare_rounds_position_and_ctr():
    class SA:
        def __init__(self, *pages):
            self.pages = list(pages)

        def query(self, siteUrl, body):
            return FakeRequest(self.pages.pop(0))

    class Svc:
        def __init__(self, sa):
            self._sa = sa

        def searchanalytics(self):
            return self._sa

    cur = {"rows": [{"keys": ["a"], "clicks": 1, "impressions": 10, "ctr": 0.123456, "position": 2.453186}]}
    prev = {"rows": [{"keys": ["a"], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 3.04999}]}
    row = client.compare_rows(Svc(SA(cur, prev)), "s", ["query"], "2026-09-01", "2026-09-28", [], "web", 0)[0]
    assert (row["ctr"], row["ctr_prev"], row["ctr_delta"]) == (0.1235, 0.1, 0.0235)
    assert (row["position"], row["position_prev"], row["position_delta"]) == (2.5, 3.0, -0.5)
