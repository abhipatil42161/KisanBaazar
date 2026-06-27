import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Sprout } from "lucide-react";

export default function Login() {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const { login, loginWithGoogle } = useAuth();
  const nav = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const u = await login(email, pw);
      toast.success(`Welcome back, ${u.name}!`);
      nav(u.role === "farmer" ? "/dashboard/farmer" : u.role === "admin" ? "/dashboard/admin" : "/dashboard/buyer");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Login failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-[80vh] grid lg:grid-cols-2">
      <div className="hidden lg:block relative">
        <img src="https://images.pexels.com/photos/36004056/pexels-photo-36004056.jpeg" alt="" className="absolute inset-0 w-full h-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-br from-primary/80 to-emerald-900/70" />
        <div className="relative h-full flex items-end p-12 text-white">
          <div>
            <Sprout size={48} strokeWidth={2} />
            <h2 className="font-heading font-bold text-4xl mt-4">Welcome back, partner.</h2>
            <p className="mt-3 text-white/90 text-lg">Continue building India's largest farm-to-world marketplace.</p>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-center p-6 sm:p-12">
        <form onSubmit={submit} className="w-full max-w-md">
          <h1 className="font-heading font-bold text-3xl">Sign in</h1>
          <p className="text-muted-foreground mt-1">to KisanBaazar</p>

          <Button type="button" data-testid="google-login-btn" variant="outline" onClick={loginWithGoogle}
            className="w-full h-12 rounded-xl mt-6 font-medium border-2">
            <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            Continue with Google
          </Button>

          <div className="my-6 flex items-center gap-3 text-sm text-muted-foreground">
            <div className="flex-1 border-t border-border" /> or <div className="flex-1 border-t border-border" />
          </div>

          <div className="space-y-4">
            <div>
              <Label className="font-medium">Email</Label>
              <Input data-testid="login-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                className="h-12 rounded-xl mt-1.5" placeholder="you@example.com" />
            </div>
            <div>
              <Label className="font-medium">Password</Label>
              <Input data-testid="login-password" type="password" required value={pw} onChange={(e) => setPw(e.target.value)}
                className="h-12 rounded-xl mt-1.5" placeholder="••••••••" />
            </div>
            <Button data-testid="login-submit" type="submit" disabled={busy}
              className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold text-base">
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </div>

          <p className="text-sm text-center mt-6">
            New to KisanBaazar? <Link to="/register" className="text-primary font-semibold">Create an account</Link>
          </p>

          <div className="mt-8 p-4 bg-secondary/50 rounded-xl text-xs space-y-1">
            <div className="font-semibold mb-1">Demo accounts:</div>
            <div>👨‍🌾 Farmer: <code>farmer@kisanbaazar.in / farmer123</code></div>
            <div>🛒 Buyer: <code>buyer@kisanbaazar.in / buyer123</code></div>
            <div>⚙️ Admin: <code>admin@kisanbaazar.in / admin123</code></div>
          </div>
        </form>
      </div>
    </div>
  );
}
