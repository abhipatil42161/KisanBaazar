import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Plus, Sparkles } from "lucide-react";

const EMPTY = {
  title: "", description: "", category: "vegetables", price: "", unit: "kg", moq: 1, available_qty: 100,
  quality_grade: "A", organic: false, export_ready: false, images: "", location: "", state: "",
  harvest_date: "", auction: false,
};

export default function AddProductDialog({ cats, onCreated }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [predicting, setPredicting] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const aiPredict = async () => {
    if (!form.title || !form.location) { toast.error("Add title & location first"); return; }
    setPredicting(true);
    try {
      const { data } = await api.post("/ai/price-predict", {
        message: `Crop: ${form.title}. Location: ${form.location}, ${form.state}. Quality: ${form.quality_grade}. Organic: ${form.organic}. Unit: ${form.unit}. Estimate fair Indian market price.`
      });
      toast.success(data.prediction, { duration: 12000 });
    } catch { toast.error("AI unavailable"); }
    finally { setPredicting(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/products", {
        ...form,
        price: Number(form.price), moq: Number(form.moq), available_qty: Number(form.available_qty),
        images: form.images.split(",").map((s) => s.trim()).filter(Boolean),
      });
      toast.success("Product listed!");
      setOpen(false); setForm(EMPTY); onCreated();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="add-product-btn" className="h-12 px-6 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
          <Plus size={18} className="mr-1" /> List Product
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-heading">List a new product</DialogTitle>
          <DialogDescription>Add a new crop or product listing to your storefront. Buyers will see it instantly.</DialogDescription>
        </DialogHeader>
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
            <div><Label>Unit</Label><Input data-testid="form-unit" value={form.unit} onChange={(e) => set("unit", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div><Label>MOQ</Label><Input data-testid="form-moq" type="number" value={form.moq} onChange={(e) => set("moq", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div><Label>Available qty</Label><Input data-testid="form-qty" type="number" value={form.available_qty} onChange={(e) => set("available_qty", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div><Label>Location</Label><Input data-testid="form-location" required value={form.location} onChange={(e) => set("location", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div><Label>State</Label><Input data-testid="form-state" required value={form.state} onChange={(e) => set("state", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div className="sm:col-span-2"><Label>Image URLs (comma-separated)</Label><Input data-testid="form-images" value={form.images} onChange={(e) => set("images", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div><Label>Harvest date</Label><Input data-testid="form-harvest" type="date" value={form.harvest_date} onChange={(e) => set("harvest_date", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div className="flex flex-col gap-2 justify-end pb-1">
              <label className="flex items-center gap-2 cursor-pointer text-sm"><Checkbox data-testid="form-organic" checked={form.organic} onCheckedChange={(v) => set("organic", v)} /> Organic certified</label>
              <label className="flex items-center gap-2 cursor-pointer text-sm"><Checkbox data-testid="form-export" checked={form.export_ready} onCheckedChange={(v) => set("export_ready", v)} /> Export ready</label>
            </div>
          </div>
          <Button data-testid="form-submit" type="submit" disabled={busy} className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
            {busy ? "Listing…" : "List Product"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
