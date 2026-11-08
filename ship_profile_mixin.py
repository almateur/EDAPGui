"""Connect the existing flight controller to extracted ship/build profiles."""
from copy import deepcopy

from EDAP_data import ship_rpy_sc_50, ship_size_map, ship_name_map
from ship_loadout import flight_info, read_status_once
from ship_profiles import ShipProfiles


class ShipProfileMixin:
    def load_ship_configs(self):
        previous = getattr(self, 'ship_profile_manager', None)
        if previous:
            previous.save(force=True)
        self.ship_profile_manager = ShipProfiles(ship_rpy_sc_50)
        self.ship_configs = self.ship_profile_manager.data
        self.current_ship_type = None
        self.current_ship_cfg = None
        self._ship_status_data = None
        self.refresh_ship_profile()

    def refresh_ship_profile(self):
        # Journal reads can invoke GUI callbacks. Keep them, and our own
        # callbacks below, outside the profile lock so Tk can save concurrently.
        state = self.jn.ship_state()
        summary = self.jn.ship_loadout.summary()
        ship = summary.get('ship_type') or state.get('type')
        with self.ship_profile_manager.lock:
            if not ship or ship not in ship_size_map:
                self.ship_profile_manager.save(force=True)
                self.current_ship_type, self.current_ship_cfg = None, None
                self.auto_tune_rpy = False
                return False
            summary['ship_type'] = ship
            changed = self.ship_profile_manager.select(summary)
            hull_changed = self.current_ship_type != ship
            notify = changed or self.current_ship_cfg is not self.ship_profile_manager.profile or hull_changed
            if notify:
                self.current_ship_type = ship
                self.current_ship_cfg = self.ship_profile_manager.profile
                for axis, attribute in [('RollRate', 'rollrate'), ('PitchRate', 'pitchrate'), ('YawRate', 'yawrate'), ('SunPitchUp+Time', 'sunpitchuptime')]:
                    setattr(self, attribute, self.current_ship_cfg[axis])
                self.auto_tune_rpy = bool(self.config.get('AutoTuneRPYRates', False) and self.ship_profile_manager.key)
                source = self.current_ship_cfg['_Meta']['seed_source']
                identified = bool(self.ship_profile_manager.key)
        if notify:
            if hull_changed and getattr(self, 'templ', None) is not None:
                self.templ.reload_templates(self.scr.scaleX, self.scr.scaleY)
            self.ap_ckb('log', f"Loaded {ship} profile: {source}. "
                               + ('Ship and build identified.' if identified else 'Waiting for complete ship/loadout identity; rates are estimates.'))
            for key, equipment in [('has_fuel_scoop', 'Fuel Scoop'), ('has_adv_dock_comp', 'Advanced Docking Computer')]:
                if state.get(key) is False:
                    self.ap_ckb('log', f'WARNING: Your ship is not fitted with a {equipment}.')
            if state.get('has_std_dock_comp') is True:
                self.ap_ckb('log', 'WARNING: Your ship has a Standard Docking Computer, which cannot undock automatically.')
            if getattr(self, 'gui_loaded', False):
                self.ap_ckb('update_ship_cfg')
        return changed

    def update_ship_configs(self):
        with self.ship_profile_manager.lock:
            if self.current_ship_cfg and self.ship_profile_manager.key:
                self.current_ship_cfg.update(RollRate=self.rollrate, PitchRate=self.pitchrate,
                                             YawRate=self.yawrate, **{'SunPitchUp+Time': self.sunpitchuptime})
                self.ship_profile_manager.dirty = True
                self.ship_profile_manager.save(force=True)

    def get_flight_info(self):
        filename = getattr(getattr(self, 'status', None), 'file_path', None)
        data = read_status_once(filename) if filename is not None else None
        if data is not None:
            self._ship_status_data = data
        state = self.jn.ship_state()
        result = flight_info(self._ship_status_data, state)
        result['stale'] = data is None
        return result

    def get_ship_info(self):
        snapshot = self.jn.ship_details()
        state = self.jn.ship_state()
        with self.ship_profile_manager.lock:
            current = self.ship_profile_manager.describe()
            pending = snapshot.get('profile_key') != current['key'] or self.current_ship_cfg is not self.ship_profile_manager.profile
            available = bool(snapshot.get('profile_key') and not pending and self.current_ship_cfg)
            profile = {**current, 'pending': pending,
                       'rates': {axis: getattr(self, attribute) for axis, attribute in [('RollRate', 'rollrate'), ('PitchRate', 'pitchrate'), ('YawRate', 'yawrate')]},
                       'mode': self.speed_demand, 'auto_tune': bool(self.auto_tune_rpy),
                       'auto_tune_requested': bool(self.config.get('AutoTuneRPYRates', False)), 'can_tune': available}
        return {'type': 'ship_info', 'available': bool(snapshot.get('ship_type')), **snapshot,
                'ship_type_name': ship_name_map.get(snapshot.get('ship_type'), snapshot.get('ship_type')),
                'ship_size': snapshot.get('ship_size', state.get('ship_size')),
                'equipment': snapshot.get('equipment', {key: state.get(key) for key in ('has_fuel_scoop', 'has_adv_dock_comp', 'has_std_dock_comp', 'has_sco_fsd', 'has_supercruise_assist')}),
                'profile': profile,
                'raw_status': deepcopy(self._ship_status_data)}

    def record_ship_tuning(self, axis, angle, rate):
        context = self.get_flight_info()
        with self.ship_profile_manager.lock:
            if self.jn.ship_loadout.summary().get('profile_key') != self.ship_profile_manager.key:
                return False
            context['throttle_demand'] = self.speed_demand
            return self.ship_profile_manager.record(self.speed_demand, axis, angle, rate, context)

    def require_current_ship_profile(self):
        self.jn.ship_state()
        if self.jn.ship_loadout.summary().get('profile_key') != self.ship_profile_manager.key:
            raise ValueError('Ship or outfitting changed during the assist. Wait for a fresh loadout/profile, then restart the assist.')

    def set_auto_tune_rpy(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Auto-tuning enabled must be true or false.')
        self.jn.ship_state()
        with self.ship_profile_manager.lock:
            key = self.jn.ship_loadout.summary().get('profile_key')
            if enabled and not (key and key == self.ship_profile_manager.key and self.current_ship_cfg is self.ship_profile_manager.profile):
                raise ValueError('Wait for a complete, current ship loadout before enabling auto-tuning.')
            self.config['AutoTuneRPYRates'] = enabled
            self.auto_tune_rpy = enabled
        self.update_config()

    def save_ship_tuning(self):
        self.jn.ship_state()
        with self.ship_profile_manager.lock:
            key = self.jn.ship_loadout.summary().get('profile_key')
            if not (key and key == self.ship_profile_manager.key and self.current_ship_cfg is self.ship_profile_manager.profile):
                raise ValueError('The ship/build changed. Wait for the new loadout and idle profile update before saving.')
            self.update_ship_configs()
            if self.ship_profile_manager.save_error:
                raise ValueError('Could not save ship tuning: ' + self.ship_profile_manager.save_error)
