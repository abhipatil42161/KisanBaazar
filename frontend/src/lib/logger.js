/**
 * Tiny dev-only logger. Strips all output when NODE_ENV is "production"
 * so the bundled SPA never leaks diagnostic chatter to end-user consoles.
 *
 * Use:
 *   import { logger } from "@/lib/logger";
 *   logger.warn("[scope] something happened", detail);
 *   logger.error("[scope] fatal", err);
 */
const isDev = process.env.NODE_ENV !== "production";

export const logger = {
  warn: (...args) => {
    if (isDev) {
      console.warn(...args);
    }
  },
  error: (...args) => {
    if (isDev) {
      console.error(...args);
    }
  },
};
