import { IncomingMessage, Server } from 'http';
import { RequestHandler } from 'express';

export function createLocalAccess(server: Server): {
  isAllowed(request: IncomingMessage, websocket?: boolean): boolean;
  middleware: RequestHandler;
};
