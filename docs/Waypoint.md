# Waypoints

Waypoint JSON files define the systems the autopilot visits in order.

## Ready-to-load sample

Use [waypoints/sample-route.json](../waypoints/sample-route.json) as a starting point. It includes the required `GlobalShoppingList` and two travel-only example destinations: **Eravate**, then **Kremainn**. Shopping lists are empty, station names and bookmarks are unset, fleet carrier transfers are disabled, and the route does not repeat.

1. In the web dashboard, click **Load File** and select the sample or your own JSON file. With the backend connected and Waypoint Assist stopped, wait for the backend confirmation. The dashboard imports a copy; your selected original is unchanged.
2. Select destinations in the route timeline and edit their **System** fields to choose your destinations. Use **Apply changes** to load your edits into the backend, and **Download JSON** to save your own route file.
3. Loading or applying a file does not start travel. Enable **Waypoint Assist** separately when ready to follow the route.

Each numbered entry starts with `Skip: false` and `Completed: false`. Set `Skip` to `true` to disable an entry. For another run, use a fresh copy or reset the completion flags.

For each destination, the autopilot plots a course to `SystemName` in the Galaxy Map and follows it with FSD Route Assist. An empty `StationName` and disabled bookmarks mean that reaching the system completes the waypoint without docking. After the final waypoint, the autopilot goes idle. Progress updates set each reached waypoint's `Completed` flag to `true` in the active route file.

## Waypoint Editor

The web dashboard opens routes in **Quick edit**, a compact table with inline waypoint names, systems, stations, and skip/completion flags. Edit several rows directly. Press **Enter** to edit the next stop in the same column, or **Shift+Enter** to go back; the next cell's contents are selected for replacement. **Add stop** focuses the new destination immediately. Use **Details** for comments, bookmarks, and trading; **Previous stop** and **Next stop** move through those details without returning to the list.

For bulk changes:

1. Use the checkboxes to select stops. **Shift-click** selects a range; **Select all shown** selects the current search/filter results.
2. Delete, skip, enable, mark completed/pending, or move the selection up/down in one action. The selection count explicitly includes stops outside the current filter; **Clear selection** deselects everything.
3. **Undo removal** restores the last deletion in travel order while preserving edits made to surviving stops. If you reused a deleted waypoint name, the restored name gets a unique ` (restored)` suffix. **Undo edits** restores the entire last opened/applied version.

Search by system, station, waypoint name, or comment, and filter by status. A row stays visible while you edit it even if its new value no longer matches the search. On small screens, scroll the table horizontally. The save/download controls stay available at the bottom while scrolling the editor.

Switch to **Route view** for the connected timeline showing travel order, systems, stations, trading stops, and saved skipped/completed flags. It supports the same bulk selection controls. **Reset completion** clears all completion flags for another run. **Repeat route** adds a final `REPEAT` entry; move it back to the end if validation flags its position.

Each stop has editable buy/sell commodity rows and bookmark settings. Commodity quantities must be nonnegative whole numbers; the `All` commodity with quantity `0` remains supported. Expand **Global shopping list** to edit the shared purchases and count updates. The engine ignores the global list's `Skip` field; the editor retains it for file compatibility. Unknown extra JSON fields are retained when saving.

**Apply changes** validates the draft and loads a new working copy after Python confirms it. Stop Waypoint Assist first. **Download JSON** exports the draft in its displayed order. **Undo edits** restores the last opened or applied version. Opening another file or leaving the page warns when you have edits that have not been applied or downloaded. Offline opening, editing, and downloading also work.

The timeline's flags are the state from the opened file and your edits. To inspect progress written by the autopilot, reopen its saved route file. The current-system badge follows live telemetry.

The standalone C# [EDAP-Waypoint-Editor](https://github.com/Stumpii/EDAP-Waypoint-Editor) is also available.

## Repeating Waypoints
A set of waypoints can be endlessly repeated by using a special row at the end of the waypoint file with the system name as **'REPEAT'**. When hitting this record and as long as **Skip** is not ture, the Waypoint Assist will start from the top jumping through the defined Systems until the user ends the Waypoint Assist.

## Docking with a Station
When entering a System via Waypoint Assist, if the **StationName** is not '' and a **GalaxyMapBookmark** or 
**SystemMapBookmark** is defined, the Waypoint Assist will go to the Galaxy Map or System Map and select the 
Station by bookmark. The position of the bookmark in the station list of the **System Map** from top to bottom and 
starting at '1' for the first bookmark. A bookmark of '0' is disabled. 
Upon arriving at the station, the SC Assist (which is acting on behalf of the Waypoint Assist), will drop your ship
out of Supercruise and attempt docking.  Once docked, the fuel and repair will automatically be commanded and Trade wil execute if necessary.

## Docking with a System Colonisation Ship and Orbital Construction Site (Odyssey only)
Refer to *Docking with a Station* above. The only difference from a regular station is that the only trade option is to sell all commodities to the ship. Refer to Trading.
<br>
_Note: Colonisation Ships and Construction Ships can only be bookmarked at the Galaxy Map level._

## Docking with a Fleet Carrier
Refer to *Docking with a Station* above. In addition to Trading (Buy/Sell), Fleet Carriers include the option to Transfer (to/from) the Fleet Carrier using the **FleetCarrierTransfer** option. Transfer will attempt to transfer all commodities on the ship/Fleet Carrier, so transfer from a Fleet Carrier is not particularly useful.
<br>
_Note: There appears to be a bug that sometimes prevents bookmarking a Fleet Carrier in the System Map. If this occurs, it is still possible to bookmark the FC through the Navigation Panel. Once bookmarked, it will be accessible through the System Map._

## Trading
The **SellCommodities** and **BuyCommodities** lists are associated with auto-trading and each waypoint will have both lists and either or both may be empty. If either of the lists are not empty, the trade executor kicks in, brings up Commodities Screen and will perform the Selling and then Buying of each listed commodity if it can be traded. The commodities will be processed in the order defined, so place the important items first. There is also an option to update the item counts as the items are bought and sold.

In addition to the **SellCommodities** and **BuyCommodities** lists defined in each waypoint, a **GlobalShoppingList** exists which is a **BuyCommodities** list common to all waypoints. These are items that will be purchased at every waypoint if they are available **after** the waypoint's **BuyCommodities** has been processed. There is also an option to update the item counts as the items are bought and sold.

# Common Actions
A simple reference for common actions:
### Travel to distant System
* Enter system data, leave station data blank.
### Travel to Station
* Enter system and station data, leave commodity data blank. For travel within the current system, leave system data blank. 
### Trade between station(s) and/or fleet carrier(s)
* Enter system (options) and station data.
* Complete Buy/Sell lists.
### Transfer to/from Fleet Carrier
* Enter system (options) and station data.
* Enter commodity 'All' with a quantity of '0' in the Buy/Sell lists to trigger a transfer.
### System Colonisation Ship / Orbital Construction Site
* Enter system (options) and station data.
* Enter commodity 'All' with a quantity of '0' in the Sell lists to trigger a sale of all commodities.

A complete example with notes:
```py
{
    "GlobalShoppingList": {                 # The Global shopping list. Will attempt to buy these items at every station
                                            #    before buying the waypoint defined items. Do not change this name.
        "BuyCommodities": {                 # The dictionary of commodities to buy. There are no global sell commodities.
            "Ceramic Composites": 14,       # Enter commodity name and quantity
            "CMM Composite": 3029,
            "Insulating Membrane": 324
        },
        "UpdateCommodityCount": true,       # Update the counts above when good purchased (not sold).
        "Skip": true,                       # Ignored for shopping list
        "Completed": false                  # Ignored for shopping list
    },
    "1": {                                  # System key. May be changed to something useful, but must be unique.
        "SystemName": "Hillaunges",         # The target system name used to find the system in the Galaxy Map. If the system
                                            # name is blank, then the current system is assumed to be the target.
        "StationName": "",                  # The destination name (station name, FC name etc). 
                                            #   If blank and no bookmark is set, then the waypoint is complete when reaching
                                            #   the system.
        "GalaxyBookmarkType": "Sys",        # The Galaxy Map bookmark type. May be:
                                            #   'Fav' or '' - Favorites
                                            #   'Sys' - System
                                            #   'Bod' - Body
                                            #   'Sta' - Station
                                            #   'Set' - Settlement
                                            # Note: System Colonisation Ships are bookmarked at the Gal Map level, so would
                                            #   be 'Sta' above.
        "GalaxyBookmarkNumber": 6,          # The bookmark index within the type specified above.
                                            #   Set to 0 or -1 if bookmarks are not used.
        "SystemBookmarkType": "Fav",        # The System Map bookmark type. May be:
                                            #   'Fav' or '' - Favorites
                                            #   'Bod' - Body
                                            #   'Sta' - Station
                                            #   'Set' - Settlement
                                            #   'Nav' - This is a special case that uses the Navigation Panel (Panel #1) to
                                            #      select the bookmark.
                                            #      This is primarily for system targets that do not show up in system map,
                                            #      like Mega Ships.
                                            #      Note that the Nav Panel list is highly variable due to what is in system
                                            #      and where you drop into a system, so filter your Nav Panel first. So use
                                            #      with caution.
                                            #   Note: System Colonisation Ships can only be bookmarked at the Gal Map level, 
                                            #       so this is not applicable to Col Ships.
        "SystemBookmarkNumber": 1,          # The bookmark index within the type specified above.
                                            #   Set to 0 or -1 if bookmarks are not used.
        "SellCommodities": {},              # The dictionary of commodities to sell. Same format as the Global shopping list
                                            #   above. Additionally, for Colonisation Ships and Fleet Carriers in 'Transfer'
                                            #   mode, as all commodities must be transferred, it is okay to put '"All": 0'
                                            #   as the sell good to trigger a sell/transfer all. 
        "BuyCommodities": {},               # The dictionary of commodities to buy. Same format as the Global shopping list
                                            #   above. If you define global and waypoint buy shopping lists, the waypoint
                                            #   shopping list will be processed first. Additionally, for Colonisation
                                            #   Ships and Fleet Carriers in 'Transfer' mode, as all commodities must be
                                            #   transferred, it is okay to put '"All": 0' as the buy good to trigger a
                                            #   transfer all.
        "UpdateCommodityCount": true,       # Update the buy counts above when goods are purchased (not sold). Sell counts
                                            #   are never updated.
        "FleetCarrierTransfer": false,      # If this 'station' is a Fleet Carrier allows option to TRANSFER goods rather
                                            #   than BUY/SELL, set to False to Buy/sell, True to Transfer. Transfer is by
                                            #   default everything you have.
        "Skip": true,                       # Skip this waypoint. EDAP will not change this value, so a good way to disable
                                            #   a waypoint without deleting it.
        "Completed": false                  # If false, process this waypoint. One complete EDAP will switch to True. Once
                                            #   all waypoints are complete, EDAP will switch to False.
    },
    "2": {
        "SystemName": "Synuefe ZX-M b54-1",
        "StationName": "System Colonisation Ship",
        "GalaxyBookmarkType": "Sys",
        "GalaxyBookmarkNumber": 1,
        "SystemBookmarkType": "",
        "SystemBookmarkNumber": -1,
        "SellCommodities": {
            "ALL": 0
        },
        "BuyCommodities": {},
        "FleetCarrierTransfer": false,
        "UpdateCommodityCount": true,
        "Skip": false,
        "Completed": false
    },
    "rep": {
        "SystemName": "REPEAT",             # System name of REPEAT causes the waypoints to be repeated.
                                            # Only the 'Skip' field below is used to 'disable' the repeat function
                                            # without deleting the row. 
        "StationName": "",
        "GalaxyBookmarkType": "",
        "GalaxyBookmarkNumber": -1,
        "SystemBookmarkType": "",
        "SystemBookmarkNumber": -1,
        "SellCommodities": {},
        "BuyCommodities": {},
        "FleetCarrierTransfer": false,
        "UpdateCommodityCount": false,
        "Skip": false,                      # Skip (disables) the REPEAT.
        "Completed": false
    }
}
```

