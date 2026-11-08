# Automatic ship information and tuning

The web dashboard's **Ship details, engineering & tuning** link opens the detected ship's information panel. Ship data is read locally from the game journal and `Status.json`; it requires a live Windows backend. Mock mode explicitly reports that no live ship data is available.

## What is extracted

- Ship type, individual ship ID, custom name and ident, plus all fields reported by the journal's `Loadout` event: mass, cargo/fuel capacity, hull condition, values, rebuy, jump range and any additional fields the game supplies.
- Every fitted module, its slot, item name, power state, priority, health, ammo/value fields when provided, and unknown future fields.
- Complete engineering records: engineer, blueprint, grade, quality, experimental effects, and every modifier's original/engineered values and preference direction when provided.
- Detected fuel scoop, docking computer, SCO FSD and Supercruise Assist equipment.
- Live flight mode, engine/system/weapons pips, cargo, main/reserve fuel and flight-assist state from `Status.json`. The raw status record retains additional reported fields such as heading, location, GUI focus and flags.
- Recent cargo, hull/repair and outfitting/engineering events. These are available in the raw view and exported JSON.

Expand **Reported ship statistics** or **Modules and engineering** to inspect details. Module search includes slots, item names, blueprints, engineers and experimental effects; **Engineered only** filters the list. **Inspect** shows modifiers and all original module fields. **Export ship JSON** downloads the full extracted snapshot, current profile/curves and live flight summary. Unknown values are labelled as unknown, not invented.

**Refresh ship data** rereads available journal data; it cannot force the game to emit a new event. If outfitting has changed, the panel labels the old snapshot and waits for a complete new `Loadout`. Open/close Outfitting or re-enter the game if needed. Commander identity and ship ID must be known before build-specific tuning is saved. The commander identifier is hashed for profile isolation and is not included in dashboard/export snapshots.

## Individual ships and engineered builds

Profiles are selected automatically by commander, individual ship ID and build signature. The signature covers fitted module items, engineering (including actual modifier values) and reported unladen mass. Changes to names, paint, fuel, ammo, damage, power priorities or module order do not create new profiles. Live cargo, fuel and pips are recorded with tuning observations, rather than creating a new build on every change.

Changing a relevant module or engineering creates a separate tuning profile. The old one is retained and restored if that ship returns to the same build. A module change during an assist prevents the next rotation from using the previous build's timing and reports that the assist must be restarted after the current profile is loaded.

Existing type-wide entries in `configs/ship_configs.json` remain intact. Their rates/curves can seed a first profile, labelled **Legacy settings — unverified for this build**. A later changed build starts from ship defaults instead of inheriting the previous build's learned curves. New data lives in the same ignored configuration file under `Build_Profiles`; writes use atomic replacement, including autosaves and shutdown saves.

## Starting estimates and actual measurements

The game journal does **not** report the full rotational response curves the controller needs. Built-in starting values are estimates for 50% supercruise. Engineered thruster bonuses are not multiplied into those values: normal-space thruster performance does not determine supercruise handling. Generic fallback estimates are identified explicitly when ship-specific defaults are unavailable.

Enable **Learn rotation rates during assists** after completing screen calibration. This opts into the existing compass/target feedback tuning during normal assist corrections; it does not start an independent manoeuvre or a calibration flight. Learned points are stored separately for roll/pitch/yaw at 0%, 50% and 100% throttle in normal space and supercruise. The panel shows measured-point counts and marks untouched curve points as estimates. A few observations do not mean every mode/angle has been calibrated.

Learning changes autosave with a short debounce and on idle/profile changes or shutdown. **Save tuning now** flushes the current ship/build immediately; write errors remain visible and unsaved data stays in memory. Disabling learning remains possible when loadout data becomes unavailable. Normal-space response also depends on mass and engine pips, so inspect the recorded conditions and tune under the conditions you intend to use. See [Roll, Pitch, Yaw](RollPitchYaw.md) for the existing control/tuning background.

Restart both the Node dashboard and Python backend after updating to enable the new data messages and controls. Rebuild the dashboard with `npm start`.
