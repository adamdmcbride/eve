import math
import unittest
from eve_drive_arbiter import DriveArbiter


class DriveArbiterTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.a = DriveArbiter(['a', 'b'], clock=lambda: self.now)
        self.sequence = 0

    def send(self, channels, source='mind', owner='process-1', command=None, ttl=10, epoch=None):
        self.sequence += 1
        return self.a.submit(channels, source=source, source_epoch=owner,
                             command_id=command or str(self.sequence), ttl_s=ttl,
                             expected_epoch=epoch or self.a.epoch)

    def test_sources_do_not_erase_each_other(self):
        self.send({'a': .8})
        self.send({'a': .4, 'b': .7}, source='body')
        self.send({})
        self.assertEqual({'a': .4, 'b': .7}, self.a.snapshot()['inputs'])

    def test_new_intention_replaces_own_old_channels(self):
        self.send({'a': .8})
        self.send({'b': .4})
        self.assertEqual({'b': .4}, self.a.snapshot()['inputs'])

    def test_wall_clock_expiry_does_not_depend_on_neural_ticks(self):
        self.send({'a': .8})
        self.now += 11
        self.assertEqual({}, self.a.snapshot()['inputs'])

    def test_retry_does_not_extend_or_replay(self):
        self.send({'a': .8}, command='same')
        self.now += 11
        self.assertTrue(self.send({'a': .8}, command='same')['replayed'])
        self.assertEqual({}, self.a.snapshot()['inputs'])
        with self.assertRaises(ValueError):
            self.send({'a': .7}, command='same')

    def test_bad_batch_cannot_partially_mutate(self):
        self.send({'a': .8})
        for values in ({'a': .1, 'bad': .4}, {'a': math.nan}, {'a': True}, {'a': 2}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.send(values)
            self.assertEqual({'a': .8}, self.a.snapshot()['inputs'])

    def test_owner_lease_rejects_competing_process_until_expiry(self):
        self.send({'a': .8})
        with self.assertRaises(ValueError):
            self.send({'b': .2}, owner='process-2')
        self.now += 11
        self.send({'b': .2}, owner='process-2')
        self.assertEqual({'b': .2}, self.a.snapshot()['inputs'])

    def test_reset_rejects_late_commands_and_empties_drives(self):
        epoch = self.a.epoch
        self.send({'a': .8})
        self.a.reset()
        self.assertNotEqual(epoch, self.a.epoch)
        with self.assertRaises(ValueError):
            self.send({'a': .8}, epoch=epoch)
        self.assertEqual({}, self.a.snapshot()['inputs'])

    def test_provenance_is_not_causal_learning(self):
        self.send({'a': .8}, source='legacy')
        snapshot = self.a.snapshot()
        self.assertFalse(snapshot['attribution_complete'])
        self.assertEqual('not_established', snapshot['causal_credit'])
        self.assertEqual('process-1', snapshot['contributors']['legacy']['source_epoch'])

    def test_ttl_bounded_and_finite(self):
        for ttl in (0, -1, 181, math.nan, True):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                self.send({'a': .8}, ttl=ttl)
