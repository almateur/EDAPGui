export interface AssistsState {
  fsd: boolean;
  sc: boolean;
  waypoint: boolean;
  robigo: boolean;
  dss: boolean;
  single_waypoint: boolean;
  afk_combat: boolean;
  [key: string]: boolean;
}

export interface TelemetryData {
  status: string;
  system: string;
  ship: string;
  fuel: number;
  jump_info: string;
  assists: AssistsState;
  flight?: FlightInfo;
}

export interface FlightInfo {
  mode: 'normal' | 'supercruise' | 'unknown';
  pips: { system: number; engine: number; weapons: number } | null;
  cargo: number | null;
  fuel: { FuelMain?: number; FuelReservoir?: number } | null;
  flight_assist_off: boolean | null;
  flags: number | null;
  flags2: number | null;
  timestamp?: string | null;
  stale: boolean;
}

export interface ShipModule {
  Slot: string;
  Item: string;
  Item_Localised?: string;
  On?: boolean;
  Priority?: number;
  Health?: number;
  Engineering?: {
    Engineer?: string;
    BlueprintName?: string;
    Level?: number;
    Quality?: number;
    ExperimentalEffect?: string;
    ExperimentalEffect_Localised?: string;
    Modifiers?: Array<{ Label: string; Value?: unknown; ValueStr?: string; OriginalValue?: unknown; LessIsGood?: boolean }>;
    [field: string]: unknown;
  };
  [field: string]: unknown;
}

export interface ShipInfoMessage {
  type: 'ship_info';
  available: boolean;
  mock: boolean;
  message?: string;
  ship_type?: string | null;
  ship_type_name?: string | null;
  ship_size?: string | null;
  equipment?: Record<string, boolean | null>;
  ship_id?: number | null;
  ship_name?: string;
  ship_ident?: string;
  identity_known?: boolean;
  build_signature?: string | null;
  stale?: boolean;
  reason?: string;
  loadout?: { Modules?: ShipModule[]; timestamp?: string; [field: string]: unknown } | null;
  events?: Record<string, unknown>;
  raw_status?: Record<string, unknown> | null;
  profile?: {
    key: string | null;
    seed_source: string;
    pending: boolean;
    saved_at: string | null;
    dirty: boolean;
    save_error: string | null;
    measured_points: number;
    measured: Record<string, Record<string, Record<string, unknown>>>;
    curves: Record<string, Record<string, Record<string, number>>>;
    rates: { RollRate: number; PitchRate: number; YawRate: number };
    mode: string | null;
    auto_tune: boolean;
    auto_tune_requested: boolean;
    can_tune: boolean;
  };
}

export interface ShipActionResult {
  type: 'ship_action_result';
  command: string;
  request_id?: string;
  success: boolean;
  message: string;
}

export interface EngineStatusMessage {
  type: 'engine_status';
  connected: boolean;
  message: string;
}

export interface TelemetryMessage {
  type: 'telemetry';
  data: TelemetryData;
}

export interface LogMessage {
  type: 'log';
  timestamp: string;
  message: string;
}

export interface ScreenshotMessage {
  type: 'screenshot';
  image: string;
}

export interface PongMessage {
  type: 'pong';
  request_id?: string;
  capabilities?: string[];
}

export interface WaypointLoadResult {
  type: 'waypoint_load_result';
  request_id: string;
  success: boolean;
  message: string;
}

export interface ProcessStatusMessage {
  type: 'process_status';
  building: boolean;
  running: boolean;
  managed: boolean;
  connected: boolean;
  pid?: number;
  message?: string;
}

export interface CalibrationStatusMessage {
  type: 'calibration_status';
  state: 'missing' | 'invalid' | 'incomplete' | 'ready' | 'restart_required';
  message: string;
  issues: string[];
  blocked_assists: string[];
  restart_required: boolean;
  mock: boolean;
  file: string;
  help: string;
}

export interface CommandErrorMessage {
  type: 'command_error';
  command: string;
  message: string;
}

export type ServerToClientMessage =
  | EngineStatusMessage
  | TelemetryMessage
  | LogMessage
  | ScreenshotMessage
  | PongMessage
  | WaypointLoadResult
  | CalibrationStatusMessage
  | CommandErrorMessage
  | ShipInfoMessage
  | ShipActionResult
  | ProcessStatusMessage;

export interface CommandMessage {
  command: string;
  filepath?: string;
  request_id?: string;
  enabled?: boolean;
}
