import axios from "axios";
import { logger } from "@/lib/logger";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const MUTATING = new Set(["post", "put", "patch", "delete"]);
const CSRF_COOKIE = "csrf_token";
const CSRF_HEADER = "X-CSRF-Token";
const TOKEN_STORAGE_KEY = "kb_access_token";

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

// --- Bearer access token store -------------------------------------------
// The frontend (kisanbaazar.in) and backend (onrender.com) are different
// sites. Browsers increasingly block cross-site cookies outright (as
// "third-party"), even when SameSite=None; Secure is set correctly. To stay
// working regardless of a browser's third-party-cookie policy, we keep the
// JWT here and send it explicitly via an Authorization header. The httpOnly
// cookie is still set by the backend and used as a fallback where it works.
let _accessToken = null;
try {
  _accessToken = window.localStorage.getItem(TOKEN_STORAGE_KEY) || null;
} catch {
  _accessToken = null;
}

export function setAccessToken(token) {
  _accessToken = token || null;
  try {
    if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // localStorage unavailable (private mode, etc.) — in-memory token still works for this tab session.
  }
}

export function clearAccessToken() {
  setAccessToken(null);
}

export function getAccessToken() {
  return _accessToken;
}

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

/**
 * Convenience wrapper: GET <url> and return response.data directly.
 * Lets call sites use `.then(setter)` without an intermediate Promise-callback
 * variable inside React hooks (keeps useEffect/useCallback bodies dep-clean).
 */
export const getJson = (url, opts) => api.get(url, opts).then((response) => response.data);

// Attach Bearer token (primary auth path) + CSRF header on every mutating request
api.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${_accessToken}`;
  }
  const method = (config.method || "get").toLowerCase();
  if (MUTATING.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) config.headers[CSRF_HEADER] = token;
  }
  return config;
});

// On a 403 CSRF failure, bootstrap a token once and retry
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const cfg = error.config || {};
    const isCsrf =
      error.response?.status === 403 &&
      /csrf/i.test(error.response?.data?.detail || "") &&
      !cfg._csrfRetried;
    if (isCsrf) {
      cfg._csrfRetried = true;
      try {
        await axios.post(`${API}/auth/csrf`, null, { withCredentials: true });
        const token = readCookie(CSRF_COOKIE);
        if (token) cfg.headers = { ...(cfg.headers || {}), [CSRF_HEADER]: token };
        return api(cfg);
      } catch (csrfErr) {
        // CSRF bootstrap failed — log (dev only) and fall through to reject the original 403.
        logger.warn("[api] CSRF token refresh failed, propagating original 403:", csrfErr);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
