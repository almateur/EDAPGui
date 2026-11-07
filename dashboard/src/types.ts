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
  | ProcessStatusMessage;

export interface CommandMessage {
  command: string;
  filepath?: string;
  request_id?: string;
  enabled?: boolean;
}
