import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Sprout, ArrowLeft } from "lucide-react";

export default function ForgotPassword() {
  const nav = useNavigate();
  const [mode, setMode] = useState("link"); // link | otp
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [otpSession, setOtpSession] = useState(null);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "link") {
        const { data } = await api.post("/auth/forgot-password", { email });
        setSent(true);
        toast.success(data.message || "Reset link sent");
      } else {
        const { data } = await api.post("/auth/forgot-password/otp", { email });
        setOtpSession(data.otp_session);
        setSent(true);
        toast.success(data.message || "Code sent");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const verifyOtp = async (e) => {
    e.preventDefault();
    if (pw !== pw2) return toast.error("Passwords do not match");
    setBusy(true);
    try {
      await api.post("/auth/reset-password/otp/verify", { otp_session: otpSession, code, new_password: pw });
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
        <h1 className="font-heading font-bold text-3xl">Forgot your password?</h1>
        <p className="text-muted-foreground mt-2">
          Enter the email associated with your KisanBaazar account.
        </p>

        {!sent && (
          <div className="flex gap-2 mt-6">
            <button type="button" onClick={() => setMode("link")}
              className={`flex-1 h-10 rounded-xl text-sm font-medium border-2 ${mode === "link" ? "border-primary bg-primary/5" : "border-border"}`}>
              Email Reset Link
            </button>
            <button type="button" onClick={() => setMode("otp")}
              className={`flex-1 h-10 rounded-xl text-sm font-medium border-2 ${mode === "otp" ? "border-primary bg-primary/5" : "border-border"}`}>
              Email OTP Code
            </button>
          </div>
        )}

        {!sent ? (
          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <Label className="font-medium">Email</Label>
              <Input
                data-testid="forgot-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-12 rounded-xl mt-1.5"
                placeholder="you@example.com"
              />
            </div>
            <Button
              data-testid="forgot-submit"
              type="submit"
              disabled={busy}
              className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold text-base"
            >
              {busy ? "Sending…" : mode === "link" ? "Send reset link" : "Send OTP code"}
            </Button>
          </form>
        ) : mode === "link" ? (
          <div data-testid="forgot-sent" className="mt-8 p-5 bg-secondary/60 border-2 border-border rounded-2xl text-sm">
            <p className="font-semibold mb-1">Check your inbox</p>
            <p className="text-muted-foreground">If an account exists for <span className="font-medium text-foreground">{email}</span>, a reset link is on its way. The link expires in 15 minutes.</p>
          </div>
        ) : (
          <form onSubmit={verifyOtp} className="mt-6 space-y-4">
            <p className="text-sm text-muted-foreground">Enter the 6-digit code sent to {email}, and your new password.</p>
            <div>
              <Label className="font-medium">OTP Code</Label>
              <Input required maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} className="h-12 rounded-xl mt-1.5 tracking-widest text-center" placeholder="000000" />
            </div>
            <div>
              <Label className="font-medium">New password</Label>
              <Input type="password" required value={pw} onChange={(e) => setPw(e.target.value)} className="h-12 rounded-xl mt-1.5" placeholder="••••••••" />
            </div>
            <div>
              <Label className="font-medium">Confirm password</Label>
              <Input type="password" required value={pw2} onChange={(e) => setPw2(e.target.value)} className="h-12 rounded-xl mt-1.5" placeholder="••••••••" />
            </div>
            <p className="text-xs text-muted-foreground">Min 8 characters, with uppercase, lowercase, a number, and a special character.</p>
            <Button type="submit" disabled={busy} className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold text-base">
              {busy ? "Updating…" : "Reset Password"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
