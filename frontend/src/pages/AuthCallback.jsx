import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

export default function AuthCallback() {
  const nav = useNavigate();
  const { refresh } = useAuth();
  const [error, setError] = useState(null);

  useEffect(() => {
    const hash = window.location.hash;
    const m = hash.match(/session_id=([^&]+)/);
    if (!m) { setError("Missing session"); return; }
    const sessionId = m[1];
    api.post("/auth/google/session", null, { headers: { "X-Session-ID": sessionId } })
      .then(async ({ data }) => {
        localStorage.setItem("kb_token", data.token);
        await refresh();
        nav("/dashboard/buyer", { replace: true });
      })
      .catch((e) => setError(e.response?.data?.detail || "Auth failed"));
  }, []);

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      {error ? <div className="text-destructive">{error}</div> : <div className="animate-pulse">Signing you in…</div>}
    </div>
  );
}
