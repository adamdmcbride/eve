"""One source-owned, expiring input merge inside the existing simulated fly organ.

Source labels are provenance, not authentication. Max aggregation prevents one
producer from erasing another; it is an interface policy, not a biology claim.
The caller holds its organ lock around submit/snapshot/reset and the neural step.
"""
from collections import OrderedDict
import hashlib
import json
import math
import re
import time
import uuid


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
        raise ValueError("Invalid source, epoch or command identifier")
    return value


class DriveArbiter:
    def __init__(self, channels, *, clock=time.monotonic, max_ttl=180.0):
        self.allowed = frozenset(channels)
        self.clock, self.max_ttl = clock, max_ttl
        self.epoch = str(uuid.uuid4())
        self.revision = 0
        self.sources = {}
        self.receipts = OrderedDict()

    def reset(self):
        self.sources.clear()
        self.receipts.clear()
        self.epoch = str(uuid.uuid4())
        self.revision += 1

    def _expire(self, now):
        expired = [name for name, row in self.sources.items() if row['expires'] <= now]
        for name in expired:
            del self.sources[name]
        if expired:
            self.revision += 1

    def submit(self, channels, *, source, source_epoch, command_id, ttl_s,
               expected_epoch=None):
        # Validate the entire request before changing any drive.
        source, source_epoch, command_id = map(_id, (source, source_epoch, command_id))
        if not isinstance(channels, dict) or len(channels) > len(self.allowed):
            raise ValueError("Expected a bounded channel mapping")
        values = {}
        for name, value in channels.items():
            if name not in self.allowed:
                raise ValueError("Unknown channel: " + str(name))
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Drive must be finite and between zero and one")
            values[name] = float(value)
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)) or not math.isfinite(ttl_s) or not 0 < ttl_s <= self.max_ttl:
            raise ValueError("TTL outside the bounded lease")
        if expected_epoch != self.epoch:
            raise ValueError("Organ epoch changed; observe before sending a new command")
        digest = hashlib.sha256(json.dumps([values, ttl_s], sort_keys=True).encode()).hexdigest()
        key = (source, source_epoch, command_id)
        now = self.clock()
        self._expire(now)
        if key in self.receipts:
            old_digest, receipt = self.receipts[key]
            if old_digest != digest:
                raise ValueError("Command id reused with different input")
            # A retry does not renew a lease or replay an expired command.
            return {**receipt, 'replayed': True}
        current = self.sources.get(source)
        if current and current['source_epoch'] != source_epoch:
            raise ValueError("Source already has an active owner lease")
        if source not in self.sources and values and len(self.sources) >= 32:
            raise ValueError("Too many drive sources")
        self.revision += 1
        if values:
            self.sources[source] = {'source_epoch': source_epoch, 'command_id': command_id,
                                    'channels': values, 'expires': now + ttl_s}
        else:
            self.sources.pop(source, None)  # Release only this source.
        receipt = {'organ_epoch': self.epoch, 'revision': self.revision, 'source': source,
                   'source_epoch': source_epoch, 'command_id': command_id,
                   'channels': values, 'ttl_s': float(ttl_s), 'replayed': False}
        self.receipts[key] = (digest, receipt)
        while len(self.receipts) > 2048:
            self.receipts.popitem(last=False)
        return dict(receipt)

    def snapshot(self):
        now = self.clock()
        self._expire(now)
        effective, sources = {}, {}
        for name, row in sorted(self.sources.items()):
            sources[name] = {k: v for k, v in row.items() if k != 'expires'}
            sources[name]['remaining_s'] = max(0.0, row['expires'] - now)
            for channel, value in row['channels'].items():
                effective[channel] = max(effective.get(channel, 0.0), value)
        return {'epoch': self.epoch, 'revision': self.revision, 'merge': 'max',
                'inputs': effective, 'contributors': sources,
                'attribution_complete': 'legacy' not in sources,
                'causal_credit': 'not_established'}
