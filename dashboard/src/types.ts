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
}

export interface ProcessStatusMessage {
  type: 'process_status';
  building: boolean;
  running: boolean;
  pid?: number;
  message?: string;
}

export type ServerToClientMessage =
  | EngineStatusMessage
  | TelemetryMessage
  | LogMessage
  | ScreenshotMessage
  | PongMessage
  | ProcessStatusMessage;

export interface CommandMessage {
  command: string;
  filepath?: string;
  enabled?: boolean;
}
