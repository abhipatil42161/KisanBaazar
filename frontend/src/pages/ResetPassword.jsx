import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Sprout, ArrowLeft } from "lucide-react";

const RULES = [
  { test: (p) => p.length >= 8, label: "At least 8 characters" },
  { test: (p) => /[A-Z]/.test(p), label: "One uppercase letter" },
  { test: (p) => /[a-z]/.test(p), label: "One lowercase letter" },
  { test: (p) => /\d/.test(p), label: "One number" },
  { test: (p) => /[^A-Za-z0-9]/.test(p), label: "One special character" },
];

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = useMemo(() => params.get("token") || "", [params]);
  const nav = useNavigate();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (pw !== pw2) {
      toast.error("Passwords do not match");
      return;
    }
    if (RULES.some((r) => !r.test(pw))) {
      toast.error("Password does not meet all requirements below");
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: pw });
      toast.success("Password updated. Please sign in.");
      nav("/login", { replace: true });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center p-6 sm:p-12">
      <div className="w-full max-w-md">
        <Link to="/login" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary mb-6" data-testid="back-to-login">
          <ArrowLeft size={14} /> Back to sign in
        </Link>
        <Sprout className="text-primary mb-4" size={36} />
        <h1 className="font-heading font-bold text-3xl">Set a new password</h1>
        <p className="text-muted-foreground mt-2">Choose a strong, unique password. This link expires 15 minutes after it was requested.</p>

        {!token ? (
          <div data-testid="reset-no-token" className="mt-8 p-5 border-2 border-destructive/30 bg-destructive/5 rounded-2xl text-sm">
            <p className="font-semibold text-destructive mb-1">Missing reset token</p>
            <p className="text-muted-foreground">Please use the link from your email, or <Link to="/forgot-password" className="text-primary font-medium">request a new one</Link>.</p>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <Label className="font-medium">New password</Label>
              <Input
                data-testid="reset-pw"
                type="password"
                required
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                className="h-12 rounded-xl mt-1.5"
                placeholder="••••••••"
              />
            </div>
            <div>
              <Label className="font-medium">Confirm password</Label>
              <Input
                data-testid="reset-pw-confirm"
                type="password"
                required
                value={pw2}
                onChange={(e) => setPw2(e.target.value)}
                className="h-12 rounded-xl mt-1.5"
                placeholder="••••••••"
              />
            </div>
            {pw && (
              <ul className="text-xs space-y-1 pl-1">
                {RULES.map((r) => (
                  <li key={r.label} className={r.test(pw) ? "text-primary" : "text-muted-foreground"}>
                    {r.test(pw) ? "✓" : "○"} {r.label}
                  </li>
                ))}
              </ul>
            )}
            <Button
              data-testid="reset-submit"
              type="submit"
              disabled={busy}
              className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold text-base"
            >
              {busy ? "Updating…" : "Update password"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
