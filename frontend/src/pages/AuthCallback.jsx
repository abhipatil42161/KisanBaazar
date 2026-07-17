import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setAccessToken } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

// Module-scope: parses the OAuth hash and exchanges the session token, then
// invokes `refresh` + `nav`. Returns a Promise so the effect can chain `.catch`.
const exchangeGoogleSession = (sessionId, refresh, nav) =>
  api
    .post("/auth/google/session", null, { headers: { "X-Session-ID": sessionId } })
    .then(({ data }) => {
      if (data.access_token) setAccessToken(data.access_token);
      return refresh();
    })
    .then(() => nav("/dashboard/buyer", { replace: true }));

const parseSessionId = () => {
  const match = (window.location.hash || "").match(/session_id=([^&]+)/);
  return match ? match[1] : null;
};

const formatAuthError = (err) => err.response?.data?.detail || "Auth failed";

export default function AuthCallback() {
  const nav = useNavigate();
  const { refresh } = useAuth();
  const [error, setError] = useState(null);
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const sessionId = parseSessionId();
    if (!sessionId) { setError("Missing session"); return; }
    exchangeGoogleSession(sessionId, refresh, nav).catch((err) => setError(formatAuthError(err)));
  }, [nav, refresh, setError]);

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      {error ? <div className="text-destructive">{error}</div> : <div className="animate-pulse">Signing you in…</div>}
    </div>
  );
}
