from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ship_loadout import ShipLoadout, build_signature, flight_info, read_status_once

FIXTURE = Path(__file__).parent / 'fixtures/engineered-loadout.json'


def loadout():
    return json.loads(FIXTURE.read_text())


def tracker(ship_id=42, account='F12345'):
    result = ShipLoadout()
    result.consume({'event': 'LoadGame', 'FID': account, 'Ship': 'python', 'ShipID': ship_id})
    event = loadout()
    event['ShipID'] = ship_id
    result.consume(event)
    return result


class ShipExtractionTests(unittest.TestCase):
    def test_full_loadout_engineering_and_unknown_fields_are_preserved_without_exposing_fid(self):
        source = loadout()
        ship = tracker()
        snap = ship.snapshot()
        self.assertEqual(snap['loadout'], source)
        self.assertEqual(snap['ship_name'], 'Test Explorer')
        self.assertEqual(snap['ship_ident'], 'TEST42')
        self.assertEqual(len(snap['build_signature']), 64)
        self.assertTrue(snap['identity_known'])
        self.assertIsNotNone(snap['profile_key'])
        self.assertNotIn('F12345', json.dumps(snap))
        snap['loadout']['Modules'][0]['Item'] = 'mutated'
        self.assertEqual(ship.snapshot()['loadout']['Modules'][0]['Item'], source['Modules'][0]['Item'])

    def test_build_identity_ignores_live_state_order_cosmetics_and_names(self):
        original = loadout()
        modified = deepcopy(original)
        modified.update(timestamp='later', ShipName='Renamed', ShipIdent='OTHER', HullHealth=.2, Rebuy=2)
        for module in modified['Modules']:
            module.update(Health=.1, On=False, Priority=5, AmmoInClip=2, AmmoInHopper=10, Value=1)
        modified['Modules'][0]['Engineering']['Engineer'] = 'Other engineer'
        modified['Modules'][0]['Engineering']['EngineerID'] = 111
        modified['Modules'][0]['Engineering']['ExperimentalEffect_Localised'] = 'Translated effect'
        modified['Modules'][0]['Engineering']['Modifiers'][0]['Label_Localised'] = 'Translated modifier'
        modified['Modules'][0]['Engineering']['Modifiers'].reverse()
        modified['Modules'].reverse()
        modified['Modules'].append({'Slot': 'PaintJob', 'Item': 'paintjob_python_01'})
        self.assertEqual(build_signature(original), build_signature(modified))
        ship = tracker()
        key = ship.summary()['profile_key']
        ship.consume({'event': 'Cargo', 'Vessel': 'Ship', 'Count': 12, 'Inventory': [{'Name': 'gold', 'Count': 12}]})
        ship.consume({'event': 'HullDamage', 'Health': .3})
        ship.consume({'event': 'SetUserShipName', 'ShipID': 42, 'UserShipName': 'Renamed', 'UserShipId': 'NEW'})
        self.assertEqual(ship.summary()['profile_key'], key)
        self.assertEqual(ship.snapshot()['events']['Cargo']['Inventory'][0]['Count'], 12)

    def test_same_hull_different_ships_accounts_or_engineering_never_share_a_profile(self):
        base = tracker()
        key = base.summary()['profile_key']
        self.assertNotEqual(key, tracker(ship_id=43).summary()['profile_key'])
        self.assertNotEqual(key, tracker(account='F999').summary()['profile_key'])
        for mutate in [
            lambda data: data['Modules'][0]['Engineering'].update(Level=4),
            lambda data: data['Modules'][0]['Engineering']['Modifiers'][0].update(Value=1.43),
            lambda data: data['Modules'][0].update(Item='int_engine_size6_class4'),
            lambda data: data.update(UnladenMass=510),
            lambda data: data['Modules'][0].pop('Engineering')
        ]:
            data = loadout()
            mutate(data)
            base.consume(data)
            self.assertNotEqual(key, base.summary()['profile_key'])

    def test_outfitting_invalidation_requires_a_complete_loadout_and_other_ship_events_are_ignored(self):
        ship = tracker()
        original = ship.summary()['profile_key']
        ship.consume({'event': 'EngineerCraft', 'ShipID': 43, 'Slot': 'MainEngines'})
        self.assertEqual(ship.summary()['profile_key'], original)
        ship.consume({'event': 'EngineerCraft', 'ShipID': 42, 'Slot': 'MainEngines'})
        self.assertTrue(ship.summary()['stale'])
        self.assertIsNone(ship.summary()['profile_key'])
        ship.consume(loadout())
        self.assertEqual(ship.summary()['profile_key'], original)

    def test_incomplete_data_cannot_claim_a_known_build(self):
        for modules in [None, [], [{}], [{'Slot': 'X', 'Item': 'x'}, {'Slot': 'X', 'Item': 'y'}]]:
            ship = tracker()
            data = loadout()
            data['Modules'] = modules
            ship.consume(data)
            self.assertTrue(ship.summary()['stale'])
            self.assertIsNone(ship.summary()['profile_key'])
        ship = ShipLoadout()
        ship.consume(loadout())
        self.assertFalse(ship.summary()['identity_known'])
        self.assertIsNone(ship.summary()['profile_key'])
        invalid = loadout()
        invalid['UnladenMass'] = float('nan')
        ship.consume(invalid)
        self.assertTrue(ship.summary()['stale'])
        json.dumps(ship.snapshot(), allow_nan=False)

    def test_switching_ship_or_commander_clears_old_module_and_cargo_data(self):
        ship = tracker()
        ship.consume({'event': 'Cargo', 'Count': 2})
        ship.consume({'event': 'ShipyardSwap', 'ShipType': 'python', 'ShipID': 43})
        self.assertIsNone(ship.snapshot()['loadout'])
        self.assertEqual(ship.snapshot()['events'], {})
        ship = tracker()
        ship.consume({'event': 'LoadGame', 'FID': 'FOTHER', 'Ship': 'python', 'ShipID': 42})
        self.assertIsNone(ship.snapshot()['loadout'])
        self.assertEqual(ship.snapshot()['ship_name'], '')

    def test_status_json_extracts_zero_values_pips_flight_mode_and_does_not_block_on_partial_writes(self):
        data = {'timestamp': 'now', 'Flags': 16 | 32, 'Flags2': 1, 'Pips': [0, 8, 4], 'Cargo': 0,
                'Fuel': {'FuelMain': 0, 'FuelReservoir': .5}, 'Heading': 120, 'FutureField': [1, 2]}
        info = flight_info(data)
        self.assertEqual(info['mode'], 'supercruise')
        self.assertEqual(info['pips'], {'system': 0, 'engine': 4, 'weapons': 2})
        self.assertEqual(info['cargo'], 0)
        self.assertTrue(info['flight_assist_off'])
        self.assertIsNone(flight_info({'Pips': [True, 0, 0]})['pips'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Status.json'
            path.write_text(json.dumps(data))
            self.assertEqual(read_status_once(path), data)
            path.write_text('{')
            self.assertIsNone(read_status_once(path))
