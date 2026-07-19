import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { KeyRound, ArrowLeft } from "lucide-react";

const RULES = [
  { test: (p) => p.length >= 8, label: "At least 8 characters" },
  { test: (p) => /[A-Z]/.test(p), label: "One uppercase letter" },
  { test: (p) => /[a-z]/.test(p), label: "One lowercase letter" },
  { test: (p) => /\d/.test(p), label: "One number" },
  { test: (p) => /[^A-Za-z0-9]/.test(p), label: "One special character" },
];

export default function ChangePassword() {
  const nav = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [logoutOthers, setLogoutOthers] = useState(true);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (next !== confirm) return toast.error("New passwords do not match");
    if (RULES.some((r) => !r.test(next))) return toast.error("Password does not meet all requirements");
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: current, new_password: next, confirm_new_password: confirm,
        logout_other_devices: logoutOthers,
      });
      toast.success(logoutOthers ? "Password changed — other devices logged out" : "Password changed successfully");
      setCurrent(""); setNext(""); setConfirm("");
      nav(-1);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Couldn't change password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-[70vh] flex items-center justify-center p-6 sm:p-12">
      <div className="w-full max-w-md">
        <button onClick={() => nav(-1)} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary mb-6">
          <ArrowLeft size={14} /> Back
        </button>
        <KeyRound className="text-primary mb-4" size={36} />
        <h1 className="font-heading font-bold text-3xl">Change Password</h1>
        <p className="text-muted-foreground mt-2">Keep your account secure with a strong, unique password.</p>

        <form onSubmit={submit} className="mt-8 space-y-4">
          <div>
            <Label className="font-medium">Current password</Label>
            <Input type="password" required value={current} onChange={(e) => setCurrent(e.target.value)} className="h-12 rounded-xl mt-1.5" data-testid="current-password" />
          </div>
          <div>
            <Label className="font-medium">New password</Label>
            <Input type="password" required value={next} onChange={(e) => setNext(e.target.value)} className="h-12 rounded-xl mt-1.5" data-testid="new-password" />
          </div>
          <div>
            <Label className="font-medium">Confirm new password</Label>
            <Input type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} className="h-12 rounded-xl mt-1.5" data-testid="confirm-password" />
          </div>

          {next && (
            <ul className="text-xs space-y-1 pl-1">
              {RULES.map((r) => (
                <li key={r.label} className={r.test(next) ? "text-primary" : "text-muted-foreground"}>
                  {r.test(next) ? "✓" : "○"} {r.label}
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-center justify-between p-4 bg-secondary/40 rounded-xl border-2 border-border">
            <div>
              <p className="text-sm font-medium">Log out other devices</p>
              <p className="text-xs text-muted-foreground">Recommended if you suspect unauthorized access</p>
            </div>
            <Switch checked={logoutOthers} onCheckedChange={setLogoutOthers} />
          </div>

          <Button type="submit" disabled={busy} className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold text-base" data-testid="change-password-submit">
            {busy ? "Updating…" : "Change Password"}
          </Button>
        </form>
      </div>
    </div>
  );
}
