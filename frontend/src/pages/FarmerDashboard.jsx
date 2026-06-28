import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Plus, Sparkles, IndianRupee, Package, ShoppingBag, Trash2 } from "lucide-react";

const empty = {
  title: "", description: "", category: "vegetables", price: "", unit: "kg", moq: 1, available_qty: 100,
  quality_grade: "A", organic: false, export_ready: false, images: "", location: "", state: "",
  harvest_date: "", auction: false,
};

export default function FarmerDashboard() {
  const { user } = useAuth();
  const [stats, setStats] = useState({});
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [cats, setCats] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [predicting, setPredicting] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [s, p, o, c] = await Promise.all([
      api.get("/dashboard/stats"),
      api.get("/products"),
      api.get("/orders"),
      api.get("/categories"),
    ]);
    setStats(s.data);
    setProducts(p.data.filter((x) => x.farmer_id === user.user_id));
    setOrders(o.data);
    setCats(c.data);
  }, [user.user_id]);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const aiPredict = async () => {
    if (!form.title || !form.location) { toast.error("Add title & location first"); return; }
    setPredicting(true);
    try {
      const { data } = await api.post("/ai/price-predict", {
        message: `Crop: ${form.title}. Location: ${form.location}, ${form.state}. Quality: ${form.quality_grade}. Organic: ${form.organic}. Unit: ${form.unit}. Estimate fair Indian market price.`
      });
      toast.success(data.prediction, { duration: 12000 });
    } catch (e) { toast.error("AI unavailable"); }
    finally { setPredicting(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/products", {
        ...form,
        price: Number(form.price),
        moq: Number(form.moq),
        available_qty: Number(form.available_qty),
        images: form.images.split(",").map((s) => s.trim()).filter(Boolean),
      });
      toast.success("Product listed!");
      setOpen(false);
      setForm(empty);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
    finally { setBusy(false); }
  };

  const remove = async (pid) => {
    if (!confirm("Delete this listing?")) return;
    await api.delete(`/products/${pid}`);
    toast.success("Removed");
    load();
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-end justify-between flex-wrap gap-3 mb-8">
        <div>
          <h1 className="font-heading font-bold text-3xl">Farmer Dashboard</h1>
          <p className="text-muted-foreground mt-1">Welcome, {user.name} 🌾</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button data-testid="add-product-btn" className="h-12 px-6 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
              <Plus size={18} className="mr-1" /> List Product
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader><DialogTitle className="font-heading">List a new product</DialogTitle></DialogHeader>
            <form onSubmit={submit} className="space-y-4">
              <div className="grid sm:grid-cols-2 gap-4">
                <div className="sm:col-span-2">
                  <Label>Product title</Label>
                  <Input data-testid="form-title" required value={form.title} onChange={(e) => set("title", e.target.value)} className="rounded-xl h-11 mt-1" />
                </div>
                <div className="sm:col-span-2">
                  <Label>Description</Label>
                  <Textarea data-testid="form-desc" required value={form.description} onChange={(e) => set("description", e.target.value)} rows={2} className="rounded-xl mt-1" />
                </div>
                <div>
                  <Label>Category</Label>
                  <Select value={form.category} onValueChange={(v) => set("category", v)}>
                    <SelectTrigger data-testid="form-category" className="rounded-xl h-11 mt-1"><SelectValue /></SelectTrigger>
                    <SelectContent>{cats.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Quality grade</Label>
                  <Select value={form.quality_grade} onValueChange={(v) => set("quality_grade", v)}>
                    <SelectTrigger data-testid="form-grade" className="rounded-xl h-11 mt-1"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="A">A (Premium)</SelectItem>
                      <SelectItem value="B">B (Standard)</SelectItem>
                      <SelectItem value="C">C (Economy)</SelectItem>
                      <SelectItem value="Export">Export Grade</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Price (₹)</Label>
                  <div className="flex gap-2 mt-1">
                    <Input data-testid="form-price" type="number" required value={form.price} onChange={(e) => set("price", e.target.value)} className="rounded-xl h-11" />
                    <Button type="button" data-testid="ai-predict-btn" variant="outline" onClick={aiPredict} disabled={predicting} className="rounded-xl h-11 shrink-0">
                      <Sparkles size={16} className="mr-1" /> {predicting ? "…" : "AI"}
                    </Button>
                  </div>
                </div>
                <div>
                  <Label>Unit</Label>
                  <Input data-testid="form-unit" value={form.unit} onChange={(e) => set("unit", e.target.value)} className="rounded-xl h-11 mt-1" placeholder="kg, dozen, quintal" />
                </div>
                <div>
                  <Label>MOQ</Label>
                  <Input data-testid="form-moq" type="number" value={form.moq} onChange={(e) => set("moq", e.target.value)} className="rounded-xl h-11 mt-1" />
                </div>
                <div>
                  <Label>Available qty</Label>
                  <Input data-testid="form-qty" type="number" value={form.available_qty} onChange={(e) => set("available_qty", e.target.value)} className="rounded-xl h-11 mt-1" />
                </div>
                <div>
                  <Label>Location</Label>
                  <Input data-testid="form-location" required value={form.location} onChange={(e) => set("location", e.target.value)} className="rounded-xl h-11 mt-1" placeholder="District" />
                </div>
                <div>
                  <Label>State</Label>
                  <Input data-testid="form-state" required value={form.state} onChange={(e) => set("state", e.target.value)} className="rounded-xl h-11 mt-1" />
                </div>
                <div className="sm:col-span-2">
                  <Label>Image URLs (comma-separated)</Label>
                  <Input data-testid="form-images" value={form.images} onChange={(e) => set("images", e.target.value)} className="rounded-xl h-11 mt-1" placeholder="https://..." />
                </div>
                <div>
                  <Label>Harvest date</Label>
                  <Input data-testid="form-harvest" type="date" value={form.harvest_date} onChange={(e) => set("harvest_date", e.target.value)} className="rounded-xl h-11 mt-1" />
                </div>
                <div className="flex flex-col gap-2 justify-end pb-1">
                  <label className="flex items-center gap-2 cursor-pointer text-sm">
                    <Checkbox data-testid="form-organic" checked={form.organic} onCheckedChange={(v) => set("organic", v)} /> Organic certified
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer text-sm">
                    <Checkbox data-testid="form-export" checked={form.export_ready} onCheckedChange={(v) => set("export_ready", v)} /> Export ready
                  </label>
                </div>
              </div>
              <Button data-testid="form-submit" type="submit" disabled={busy} className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
                {busy ? "Listing…" : "List Product"}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <StatCard icon={Package} label="Active Listings" value={stats.products || 0} color="bg-emerald-500" />
        <StatCard icon={ShoppingBag} label="Orders Received" value={stats.orders || 0} color="bg-amber-500" />
        <StatCard icon={IndianRupee} label="Total Revenue" value={`₹${(stats.revenue || 0).toLocaleString()}`} color="bg-primary" />
      </div>

      <div className="grid lg:grid-cols-2 gap-8">
        <section>
          <h2 className="font-heading font-semibold text-xl mb-3">My Listings</h2>
          <div className="space-y-3">
            {products.length === 0 && <p className="text-muted-foreground">No listings yet. Add your first product!</p>}
            {products.map((p) => (
              <div key={p.product_id} data-testid={`listing-${p.product_id}`}
                className="bg-card border-2 border-border rounded-xl p-4 flex gap-3 items-center">
                <div className="w-16 h-16 rounded-lg bg-muted overflow-hidden shrink-0">
                  {p.images?.[0] && <img src={p.images[0]} alt="" className="w-full h-full object-cover" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">{p.title}</div>
                  <div className="text-xs text-muted-foreground">₹{p.price}/{p.unit} · {p.available_qty} available</div>
                </div>
                <Button data-testid={`del-${p.product_id}`} size="icon" variant="ghost" onClick={() => remove(p.product_id)} className="text-destructive">
                  <Trash2 size={18} />
                </Button>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="font-heading font-semibold text-xl mb-3">Recent Orders</h2>
          <div className="space-y-3">
            {orders.length === 0 && <p className="text-muted-foreground">No orders yet.</p>}
            {orders.slice(0, 8).map((o) => (
              <div key={o.order_id} className="bg-card border-2 border-border rounded-xl p-4">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-semibold text-sm">Order #{o.order_id.slice(-8)}</div>
                    <div className="text-xs text-muted-foreground">{o.buyer_name} · {new Date(o.created_at).toLocaleDateString()}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-heading font-bold text-primary">₹{o.total.toLocaleString()}</div>
                    <div className="text-xs capitalize">{o.status}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-card border-2 border-border rounded-2xl p-5 flex items-center gap-4">
      <div className={`w-12 h-12 rounded-xl ${color} flex items-center justify-center text-white`}>
        <Icon size={22} strokeWidth={2.5} />
      </div>
      <div>
        <div className="text-xs text-muted-foreground font-medium">{label}</div>
        <div className="font-heading font-bold text-2xl">{value}</div>
      </div>
    </div>
  );
}
