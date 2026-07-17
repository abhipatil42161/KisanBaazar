import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { api, setAccessToken } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Sprout, Users, Globe, Eye, EyeOff, ShieldCheck, Loader2, Mail, RotateCcw, CheckCircle2 } from "lucide-react";

const ROLES = [
  { id: "buyer", label: "Buyer", desc: "I want to purchase produce", icon: Users },
  { id: "farmer", label: "Farmer", desc: "I want to sell my crops", icon: Sprout },
  { id: "exporter", label: "Exporter", desc: "I export to global markets", icon: Globe },
];

// Bilingual client-side error strings — server returns the authoritative
// version prefixed with the same English/Marathi pair for messages sent
// from validators; we mirror the wording locally for pre-submit checks.
const T = {
  name_len: "Name must be 2–50 characters · नाव 2–50 अक्षरे",
  name_chars: "Only letters, spaces, dots allowed · फक्त अक्षरे, स्पेस, पूर्णविराम",
  email_bad: "Enter a valid email · वैध ईमेल टाका",
  mobile_bad: "Enter a valid 10-digit Indian mobile (6-9…) · वैध 10-अंकी भारतीय मोबाइल",
  pwd_short: "At least 8 characters · किमान 8 अक्षरे",
  pwd_upper: "One UPPERCASE letter · एक कॅपिटल अक्षर",
  pwd_lower: "One lowercase letter · एक लोअरकेस अक्षर",
  pwd_digit: "One digit (0-9) · एक अंक",
  pwd_symbol: "One symbol (@#$! …) · एक चिन्ह",
  pwd_mismatch: "Passwords don't match · पासवर्ड जुळत नाहीत",
  otp_len: "OTP must be 6 digits · OTP 6 अंकांचा असावा",
};
const NAME_RE = /^[A-Za-z\u0900-\u097F .]+$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MOBILE_RE = /^[6-9]\d{9}$/;

function normalisePhone(p) {
  let v = (p || "").replace(/\s|-/g, "");
  if (v.startsWith("+91")) v = v.slice(3);
  if (v.startsWith("91") && v.length === 12) v = v.slice(2);
  return v;
}

function passwordStrength(pw) {
  const rules = [
    { ok: pw.length >= 8, msg: T.pwd_short },
    { ok: /[A-Z]/.test(pw), msg: T.pwd_upper },
    { ok: /[a-z]/.test(pw), msg: T.pwd_lower },
    { ok: /\d/.test(pw), msg: T.pwd_digit },
    { ok: /[^A-Za-z0-9]/.test(pw), msg: T.pwd_symbol },
  ];
  const passed = rules.filter((r) => r.ok).length;
  return { passed, rules, score: passed };
}

export default function Register() {
  const nav = useNavigate();
  const { loginWithGoogle, refresh } = useAuth();

  const [step, setStep] = useState(1); // 1 = details, 2 = OTP
  const [form, setForm] = useState({
    name: "", email: "", phone: "", password: "", confirm_password: "",
    role: "buyer", location: "",
  });
  const [showPw, setShowPw] = useState(false);
  const [showCpw, setShowCpw] = useState(false);
  const [touched, setTouched] = useState({});
  const [busy, setBusy] = useState(false);

  // OTP session state
  const [otp, setOtp] = useState({
    session: null, email: "", digits: "", mock: false, ttl: 600,
  });
  const [cooldown, setCooldown] = useState(0);
  const cooldownRef = useRef();

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const touch = (k) => setTouched((t) => ({ ...t, [k]: true }));

  const pwStrength = useMemo(() => passwordStrength(form.password), [form.password]);
  const normalisedPhone = useMemo(() => normalisePhone(form.phone), [form.phone]);

  // ---- inline validation ----
  const errors = useMemo(() => {
    const e = {};
    const n = form.name.trim();
    if (!(n.length >= 2 && n.length <= 50)) e.name = T.name_len;
    else if (!NAME_RE.test(n)) e.name = T.name_chars;
    if (!EMAIL_RE.test(form.email.trim())) e.email = T.email_bad;
    if (!MOBILE_RE.test(normalisedPhone)) e.phone = T.mobile_bad;
    if (pwStrength.passed < 5) e.password = pwStrength.rules.find((r) => !r.ok)?.msg;
    if (form.confirm_password !== form.password) e.confirm_password = T.pwd_mismatch;
    return e;
  }, [form, normalisedPhone, pwStrength]);

  const canSubmit = Object.keys(errors).length === 0;

  // ---- countdown (resend cooldown + TTL) ----
  useEffect(() => {
    if (cooldown <= 0) return;
    cooldownRef.current = setTimeout(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearTimeout(cooldownRef.current);
  }, [cooldown]);

  // ---- step 1: send OTP ----
  const sendOtp = async (evt) => {
    evt?.preventDefault?.();
    setTouched({ name: 1, email: 1, phone: 1, password: 1, confirm_password: 1 });
    if (!canSubmit) { toast.error("Please fix the errors above"); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/auth/register/init", {
        name: form.name.trim(),
        email: form.email.trim().toLowerCase(),
        phone: normalisedPhone,
        password: form.password,
        confirm_password: form.confirm_password,
        role: form.role,
        location: form.location?.trim() || null,
      });
      setOtp({ session: data.otp_session, email: data.email, digits: "", mock: data.mock_delivery, ttl: data.expires_in_seconds });
      setCooldown(data.resend_cooldown_seconds || 60);
      setStep(2);
      toast.success(
        data.mock_delivery
          ? "Dev mode — check backend logs for your OTP"
          : `OTP sent to ${data.email}`,
      );
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (Array.isArray(detail)) {
        // FastAPI validation error — surface the first message
        const first = detail[0]?.msg?.replace("Value error, ", "") || "Validation failed";
        toast.error(first);
      } else if (err?.response) {
        // Server responded with an explicit error (4xx/5xx)
        toast.error(detail || "Registration failed");
      } else {
        // No response at all — network drop, or backend was cold-starting.
        // The request may still complete server-side even though this
        // client gave up waiting, so don't say "failed" with certainty.
        toast.error(
          "Couldn't confirm the server's response — this can happen when the " +
          "server is waking up. Please wait ~30s and check if you already " +
          "received an OTP before trying again.",
        );
      }
    } finally { setBusy(false); }
  };

  // ---- step 2: verify OTP ----
  const verifyOtp = useCallback(async () => {
    if (!/^\d{6}$/.test(otp.digits)) { toast.error(T.otp_len); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/auth/register/verify-otp", {
        otp_session: otp.session, code: otp.digits,
      });
      if (data.access_token) setAccessToken(data.access_token);
      await refresh?.();
      toast.success(`Welcome ${data.user.name}!`);
      nav(
        data.user.role === "farmer" ? "/dashboard/farmer"
        : data.user.role === "exporter" ? "/dashboard/exporter"
        : "/dashboard/buyer",
      );
    } catch (err) {
      if (err?.response) {
        toast.error(err.response.data?.detail || "Verification failed");
      } else {
        toast.error(
          "Couldn't confirm the server's response — please wait a moment " +
          "and try the code again before requesting a new one.",
        );
      }
    } finally { setBusy(false); }
  }, [otp.digits, otp.session, refresh, nav]);

  const resend = async () => {
    if (cooldown > 0) return;
    setBusy(true);
    try {
      const { data } = await api.post("/auth/register/resend-otp", { otp_session: otp.session });
      setCooldown(60);
      setOtp((o) => ({ ...o, digits: "", mock: data.mock_delivery }));
      toast.success(data.mock_delivery ? "New OTP printed in backend logs" : "New OTP sent");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Resend failed");
    } finally { setBusy(false); }
  };

  // Auto-submit when the user types the 6th digit — a common mobile UX polish.
  useEffect(() => {
    if (step === 2 && /^\d{6}$/.test(otp.digits) && !busy) verifyOtp();
  }, [step, otp.digits, busy, verifyOtp]);

  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
      <h1 className="font-heading font-bold text-3xl sm:text-4xl text-center">
        {step === 1 ? "Join KisanBaazar" : "Verify your email"}
      </h1>
      <p className="text-center text-muted-foreground mt-2 text-sm sm:text-base">
        {step === 1
          ? "Zero registration fee for farmers · Verified network"
          : <>We sent a 6-digit code to <b className="text-foreground">{otp.email}</b></>}
      </p>

      {step === 1 && (
        <>
          <Button type="button" data-testid="google-signup-btn" variant="outline" onClick={loginWithGoogle}
            className="w-full h-12 rounded-xl mt-6 sm:mt-8 font-medium border-2">
            <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            Continue with Google
          </Button>

          <div className="my-6 flex items-center gap-3 text-sm text-muted-foreground">
            <div className="flex-1 border-t border-border" /> or sign up with email <div className="flex-1 border-t border-border" />
          </div>

          <form onSubmit={sendOtp} className="space-y-4" noValidate>
            <div>
              <Label className="font-medium text-sm">I want to register as</Label>
              <RadioGroup value={form.role} onValueChange={(v) => set("role", v)} className="grid grid-cols-3 gap-2 sm:gap-3 mt-2">
                {ROLES.map((r) => (
                  <Label key={r.id} htmlFor={`r-${r.id}`} data-testid={`role-${r.id}`}
                    className={`p-3 sm:p-4 border-2 rounded-xl cursor-pointer text-center transition-colors ${
                      form.role === r.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"
                    }`}>
                    <RadioGroupItem value={r.id} id={`r-${r.id}`} className="sr-only" />
                    <r.icon className="mx-auto mb-1 text-primary" size={22} />
                    <div className="font-semibold text-sm">{r.label}</div>
                    <div className="hidden sm:block text-xs text-muted-foreground mt-1">{r.desc}</div>
                  </Label>
                ))}
              </RadioGroup>
            </div>

            <Field label="Full name" testId="reg-name" error={touched.name && errors.name}>
              <Input data-testid="reg-name" autoComplete="name" value={form.name}
                onChange={(e) => set("name", e.target.value)} onBlur={() => touch("name")}
                className="h-12 rounded-xl" placeholder="Ramesh Patil" maxLength={50} />
            </Field>

            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Email" testId="reg-email" error={touched.email && errors.email}>
                <Input data-testid="reg-email" type="email" autoComplete="email"
                  value={form.email} onChange={(e) => set("email", e.target.value)} onBlur={() => touch("email")}
                  className="h-12 rounded-xl" placeholder="you@example.com" />
              </Field>
              <Field label="Mobile number" testId="reg-phone" error={touched.phone && errors.phone}>
                <div className="flex items-stretch">
                  <span className="inline-flex items-center px-3 rounded-l-xl border-2 border-r-0 border-border bg-muted text-sm text-muted-foreground font-medium">+91</span>
                  <Input data-testid="reg-phone" type="tel" inputMode="numeric" autoComplete="tel-national"
                    value={form.phone} onChange={(e) => set("phone", e.target.value.replace(/\D/g, "").slice(0, 10))}
                    onBlur={() => touch("phone")}
                    className="h-12 rounded-l-none rounded-r-xl border-l-0" placeholder="9876543210" maxLength={10} />
                </div>
              </Field>
            </div>

            <Field label="Password" testId="reg-password" error={touched.password && errors.password}>
              <div className="relative">
                <Input data-testid="reg-password" type={showPw ? "text" : "password"} autoComplete="new-password"
                  value={form.password} onChange={(e) => set("password", e.target.value)} onBlur={() => touch("password")}
                  className="h-12 rounded-xl pr-12" placeholder="Min 8 chars, mixed case, digit, symbol" />
                <button type="button" data-testid="reg-pw-eye" tabIndex={-1}
                  onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <StrengthMeter strength={pwStrength} pw={form.password} />
            </Field>

            <Field label="Confirm password" testId="reg-confirm" error={touched.confirm_password && errors.confirm_password}>
              <div className="relative">
                <Input data-testid="reg-confirm" type={showCpw ? "text" : "password"} autoComplete="new-password"
                  value={form.confirm_password} onChange={(e) => set("confirm_password", e.target.value)}
                  onBlur={() => touch("confirm_password")}
                  className="h-12 rounded-xl pr-12" placeholder="Repeat password" />
                <button type="button" data-testid="reg-cpw-eye" tabIndex={-1}
                  onClick={() => setShowCpw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showCpw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </Field>

            <Field label="Location (optional)" testId="reg-location">
              <Input data-testid="reg-location" value={form.location}
                onChange={(e) => set("location", e.target.value)}
                className="h-12 rounded-xl" placeholder="Village, District, State" />
            </Field>

            <Button data-testid="reg-submit" type="submit" disabled={busy || !canSubmit}
              className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold text-base disabled:opacity-60">
              {busy ? <><Loader2 className="mr-2 animate-spin" size={18} /> Sending OTP…</> : <>Send OTP · Continue</>}
            </Button>
            <p className="text-xs text-muted-foreground text-center inline-flex items-center gap-1 justify-center w-full">
              <ShieldCheck size={12} /> We&apos;ll send a one-time password to verify your email before creating your account.
            </p>
          </form>
        </>
      )}

      {step === 2 && (
        <div className="mt-8 space-y-6" data-testid="otp-step">
          <div className="bg-primary/5 border-2 border-primary/20 rounded-2xl p-5 sm:p-6 text-center">
            <Mail className="mx-auto text-primary mb-2" size={32} />
            <p className="text-sm text-muted-foreground">
              Enter the 6-digit code from your inbox. It expires in 10 minutes.
            </p>
            {otp.mock && (
              <p className="text-[11px] text-amber-600 mt-2" data-testid="otp-mock-warning">
                Dev mode — no Resend key configured. OTP printed to backend logs.
              </p>
            )}
          </div>

          <div>
            <Label className="font-medium text-sm text-center block">One-time password</Label>
            <Input
              data-testid="otp-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={otp.digits}
              onChange={(e) => setOtp((o) => ({ ...o, digits: e.target.value.replace(/\D/g, "").slice(0, 6) }))}
              placeholder="000000"
              maxLength={6}
              className="h-16 rounded-xl mt-2 text-center text-3xl font-mono tracking-[0.5em] font-bold"
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Button data-testid="otp-resend" type="button" variant="outline"
              disabled={busy || cooldown > 0} onClick={resend}
              className="h-12 rounded-xl">
              <RotateCcw size={16} className="mr-2" />
              {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend OTP"}
            </Button>
            <Button data-testid="otp-verify" type="button" disabled={busy || otp.digits.length !== 6}
              onClick={verifyOtp}
              className="h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
              {busy ? <><Loader2 className="mr-2 animate-spin" size={18} /> Verifying…</> : <><CheckCircle2 size={16} className="mr-2" /> Verify & Create</>}
            </Button>
          </div>

          <button type="button" onClick={() => setStep(1)} data-testid="otp-back"
            className="w-full text-sm text-muted-foreground hover:text-foreground underline">
            ← Change email or details
          </button>
        </div>
      )}

      <p className="text-sm text-center mt-6">
        Already a member? <Link to="/login" className="text-primary font-semibold">Sign in</Link>
      </p>
    </div>
  );
}

function Field({ label, testId, error, children }) {
  return (
    <div>
      <Label className="font-medium text-sm">{label}</Label>
      <div className="mt-1.5">{children}</div>
      {error && (
        <p data-testid={`${testId}-err`} className="text-xs text-destructive mt-1 leading-snug">
          {error}
        </p>
      )}
    </div>
  );
}

function StrengthMeter({ strength, pw }) {
  const colors = ["bg-destructive", "bg-destructive", "bg-amber-500", "bg-amber-400", "bg-emerald-500"];
  const labels = ["Very weak", "Weak", "Okay", "Good", "Strong"];
  if (!pw) return null;
  const idx = Math.min(4, Math.max(0, strength.score - 1));
  return (
    <div className="mt-2">
      <div className="flex gap-1" data-testid="reg-pw-strength">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className={`flex-1 h-1.5 rounded-full ${i < strength.score ? colors[idx] : "bg-muted"}`} />
        ))}
      </div>
      <div className="flex justify-between mt-1">
        <span className={`text-[11px] font-medium ${idx >= 3 ? "text-emerald-600" : idx >= 2 ? "text-amber-600" : "text-destructive"}`}>
          {labels[idx]}
        </span>
        <span className="text-[11px] text-muted-foreground">{strength.score}/5 checks</span>
      </div>
    </div>
  );
}
