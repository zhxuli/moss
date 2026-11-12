class Bus:
    def __init__(self):
        self._subs = {}
        self.trace = []

    def on(self, event, fn, name=None, blocking=False):
        self._subs.setdefault(event, []).append((name or getattr(fn, "__name__", "?"), fn, blocking))

    def emit(self, event, payload=None):
        results = []
        for name, fn, blocking in self._subs.get(event, []):
            try:
                results.append((name, fn(payload)))
            except Exception as e:
                results.append((name, "ERROR: %s" % e))
                if blocking:
                    raise
        self.trace.append((event, results))
        return results

BUS = Bus()
