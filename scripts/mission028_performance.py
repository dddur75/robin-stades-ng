"""Worker stage timings and a process-shared local API admission gate."""
import sqlite3
import time
from collections import OrderedDict, defaultdict
from statistics import median

STAGES = ('provider_http', 'day_slots_reserve', 'receipt_for', 'get_object',
          'capture_r2', 'write_parquet', 'r2_put', 'r2_list', 'rate_wait')


class Timings:
    def __init__(self, clock=None):
        self.clock, self.samples = clock or time.perf_counter, defaultdict(list)
    def call(self, stage, function, *args, **kwargs):
        start = self.clock()
        try:
            return function(*args, **kwargs)
        finally:
            self.samples[stage].append(self.clock() - start)
    def wrap(self, target, name, stage):
        function = getattr(target, name)
        setattr(target, name, lambda *a, **kw: self.call(stage, function, *a, **kw))
    def summary(self):
        return {stage: dict(count=len(self.samples[stage]), total_seconds=sum(self.samples[stage]),
            median_seconds=median(self.samples[stage]) if self.samples[stage] else 0.) for stage in STAGES}


class MeasuredStore:
    def __init__(self, store, timings):
        self.store, self.timings = store, timings
        self.data, self.journals = OrderedDict(), OrderedDict()
    @staticmethod
    def keep(cache, key, value):
        cache[key] = value
        if len(cache) > 256:
            cache.popitem(last=False)
    def get_object(self, key):
        if key not in self.data:
            self.keep(self.data, key, self.timings.call('get_object', self.store.get_object, key))
        return self.data[key]
    def put_if_absent(self, key, body):
        created = self.timings.call('r2_put', self.store.put_if_absent, key, body)
        self.data.pop(key, None)  # A lost conditional write must re-read the winner.
        prefix = key.split('/attempts/', 1)[0] + '/attempts/'
        if created:
            self.keep(self.data, key, body)
            if prefix in self.journals:
                self.journals[prefix].append(key)
        else:
            self.journals.pop(prefix, None)
        return created
    def iter_keys(self, prefix):
        if not prefix.endswith('/attempts/'):
            return self.timings.call('r2_list', lambda: tuple(self.store.iter_keys(prefix)))
        if prefix not in self.journals:
            self.keep(self.journals, prefix, self.timings.call('r2_list', lambda: list(self.store.iter_keys(prefix))))
        return tuple(self.journals[prefix])


class RateGate:
    """Serialize admissions across all 16 local processes, without R2 traffic."""
    def __init__(self, path):
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.execute('CREATE TABLE IF NOT EXISTS pace (id INTEGER PRIMARY KEY, next_at REAL)')
    def acquire(self):
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            row = self.connection.execute('SELECT next_at FROM pace WHERE id=1').fetchone()
            delay = max(0., (row[0] if row else 0.) - time.monotonic())
            if delay:
                time.sleep(delay)
            self.connection.execute('INSERT OR REPLACE INTO pace VALUES (1, ?)', (time.monotonic() + .126,))
