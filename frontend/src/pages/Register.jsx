import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Sprout, Users, Globe } from "lucide-react";

const ROLES = [
  { id: "buyer", label: "Buyer", desc: "I want to purchase produce", icon: Users },
  { id: "farmer", label: "Farmer", desc: "I want to sell my crops", icon: Sprout },
  { id: "exporter", label: "Exporter", desc: "I export to global markets", icon: Globe },
];

export default function Register() {
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "buyer", phone: "", location: "" });
  const [busy, setBusy] = useState(false);
  const { register, loginWithGoogle } = useAuth();
  const nav = useNavigate();

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const u = await register(form);
      toast.success(`Welcome ${u.name}!`);
      nav(u.role === "farmer" ? "/dashboard/farmer" : u.role === "exporter" ? "/dashboard/exporter" : "/dashboard/buyer");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Registration failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-12">
      <h1 className="font-heading font-bold text-4xl text-center">Join KisanBaazar</h1>
      <p className="text-center text-muted-foreground mt-2">Zero registration fee for farmers · Verified network · Global reach</p>

      <Button type="button" data-testid="google-signup-btn" variant="outline" onClick={loginWithGoogle}
        className="w-full h-12 rounded-xl mt-8 font-medium border-2">
        <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
        Continue with Google
      </Button>

      <div className="my-6 flex items-center gap-3 text-sm text-muted-foreground">
        <div className="flex-1 border-t border-border" /> or sign up with email <div className="flex-1 border-t border-border" />
      </div>

      <form onSubmit={submit} className="space-y-5">
        <div>
          <Label className="font-medium">I want to register as</Label>
          <RadioGroup value={form.role} onValueChange={(v) => set("role", v)} className="grid grid-cols-3 gap-3 mt-2">
            {ROLES.map((r) => (
              <Label key={r.id} htmlFor={`r-${r.id}`} data-testid={`role-${r.id}`}
                className={`p-4 border-2 rounded-xl cursor-pointer text-center ${form.role === r.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"}`}>
                <RadioGroupItem value={r.id} id={`r-${r.id}`} className="sr-only" />
                <r.icon className="mx-auto mb-1 text-primary" size={24} />
                <div className="font-semibold">{r.label}</div>
                <div className="text-xs text-muted-foreground mt-1">{r.desc}</div>
              </Label>
            ))}
          </RadioGroup>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <Label className="font-medium">Full name</Label>
            <Input data-testid="reg-name" required value={form.name} onChange={(e) => set("name", e.target.value)}
              className="h-12 rounded-xl mt-1.5" placeholder="Ramesh Patil" />
          </div>
          <div>
            <Label className="font-medium">Phone</Label>
            <Input data-testid="reg-phone" value={form.phone} onChange={(e) => set("phone", e.target.value)}
              className="h-12 rounded-xl mt-1.5" placeholder="+91 98765 43210" />
          </div>
          <div>
            <Label className="font-medium">Email</Label>
            <Input data-testid="reg-email" type="email" required value={form.email} onChange={(e) => set("email", e.target.value)}
              className="h-12 rounded-xl mt-1.5" placeholder="you@example.com" />
          </div>
          <div>
            <Label className="font-medium">Password</Label>
            <Input data-testid="reg-password" type="password" required minLength={6} value={form.password} onChange={(e) => set("password", e.target.value)}
              className="h-12 rounded-xl mt-1.5" placeholder="Min 6 characters" />
          </div>
        </div>
        <div>
          <Label className="font-medium">Location</Label>
          <Input data-testid="reg-location" value={form.location} onChange={(e) => set("location", e.target.value)}
            className="h-12 rounded-xl mt-1.5" placeholder="Village, District, State" />
        </div>

        <Button data-testid="reg-submit" type="submit" disabled={busy}
          className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold text-base">
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>

      <p className="text-sm text-center mt-6">
        Already a member? <Link to="/login" className="text-primary font-semibold">Sign in</Link>
      </p>
    </div>
  );
}
