import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Sprout, ArrowLeft } from "lucide-react";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/auth/forgot-password", { email });
      setSent(true);
      toast.success(data.message || "Reset link sent");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Request failed");
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
          Enter the email associated with your KisanBaazar account and we&apos;ll send you a reset link.
        </p>

        {sent ? (
          <div data-testid="forgot-sent" className="mt-8 p-5 bg-secondary/60 border-2 border-border rounded-2xl text-sm">
            <p className="font-semibold mb-1">Check your inbox</p>
            <p className="text-muted-foreground">If an account exists for <span className="font-medium text-foreground">{email}</span>, a reset link is on its way. The link expires in 1 hour.</p>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-8 space-y-4">
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
              {busy ? "Sending…" : "Send reset link"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
