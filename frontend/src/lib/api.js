import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const MUTATING = new Set(["post", "put", "patch", "delete"]);
const CSRF_COOKIE = "csrf_token";
const CSRF_HEADER = "X-CSRF-Token";

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

// Attach CSRF header on every mutating request
api.interceptors.request.use((config) => {
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
        // CSRF bootstrap failed — log and fall through to reject the original 403.
        console.warn("[api] CSRF token refresh failed, propagating original 403:", csrfErr);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
