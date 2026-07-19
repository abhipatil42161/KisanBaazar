import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Plus, Sparkles, Pencil } from "lucide-react";
import ImageUploader from "@/components/ImageUploader";

const EMPTY = {
  title: "", description: "", category: "vegetables", price: "", unit: "kg", moq: 1, available_qty: 100,
  quality_grade: "A", organic: false, export_ready: false, images: [], location: "", state: "",
  harvest_date: "", auction: false, pincode: "", weight_per_unit_kg: 1, seller_delivery_charge: "",
};

/**
 * ProductFormDialog handles both Add and Edit. Pass `existing` to enter Edit mode.
 * Add mode triggers via "List Product" button; Edit mode triggers via "Pencil" icon.
 */
export default function ProductFormDialog({ cats, onSaved, existing = null, trigger = null }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [predicting, setPredicting] = useState(false);
  const [busy, setBusy] = useState(false);
  const isEdit = Boolean(existing);
  /**
   * `set` accepts a value OR an updater function (mirrors React's setState
   * signature). This lets children like <ImageUploader/> use functional updates
   * to avoid stale-closure races when multiple async operations land at once.
   */
  const set = (k, v) =>
    setForm((f) => ({ ...f, [k]: typeof v === "function" ? v(f[k]) : v }));

  useEffect(() => {
    if (open) {
      setForm(existing
        ? {
            title: existing.title || "",
            description: existing.description || "",
            category: existing.category || "vegetables",
            price: existing.price ?? "",
            unit: existing.unit || "kg",
            moq: existing.moq ?? 1,
            available_qty: existing.available_qty ?? 100,
            quality_grade: existing.quality_grade || "A",
            organic: !!existing.organic,
            export_ready: !!existing.export_ready,
            images: existing.images || [],
            location: existing.location || "",
            state: existing.state || "",
            harvest_date: existing.harvest_date || "",
            auction: !!existing.auction,
            pincode: existing.pincode || "",
            weight_per_unit_kg: existing.weight_per_unit_kg ?? 1,
            seller_delivery_charge: existing.seller_delivery_charge ?? "",
          }
        : EMPTY);
    }
  }, [open, existing]);

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
      const payload = {
        ...form,
        price: Number(form.price),
        moq: Number(form.moq),
        available_qty: Number(form.available_qty),
        weight_per_unit_kg: Number(form.weight_per_unit_kg) || 1,
        seller_delivery_charge: form.seller_delivery_charge === "" ? null : Number(form.seller_delivery_charge),
      };
      if (isEdit) {
        await api.put(`/products/${existing.product_id}`, payload);
        toast.success("Product updated");
      } else {
        await api.post("/products", payload);
        toast.success("Product listed!");
      }
      setOpen(false);
      setForm(EMPTY);
      onSaved();
    } catch (err) { toast.error(err.response?.data?.detail || "Failed"); }
    finally { setBusy(false); }
  };

  const defaultTrigger = isEdit ? (
    <Button data-testid={`edit-product-${existing?.product_id}`} size="icon" variant="ghost"
      className="text-muted-foreground hover:text-primary">
      <Pencil size={18} />
    </Button>
  ) : (
    <Button data-testid="add-product-btn" className="h-12 px-6 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
      <Plus size={18} className="mr-1" /> List Product
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger || defaultTrigger}</DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-heading">{isEdit ? "Edit product" : "List a new product"}</DialogTitle>
          <DialogDescription>{isEdit ? "Update product details. Removed images are deleted from storage." : "Add a new crop or product listing to your storefront. Buyers will see it instantly."}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label className="mb-1.5 block">Photos</Label>
            <ImageUploader value={form.images} onChange={(imgs) => set("images", imgs)} />
          </div>
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
            <div><Label>Harvest date</Label><Input data-testid="form-harvest" type="date" value={form.harvest_date} onChange={(e) => set("harvest_date", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div><Label>Pincode (for delivery calc)</Label><Input data-testid="form-pincode" value={form.pincode} onChange={(e) => set("pincode", e.target.value)} className="rounded-xl h-11 mt-1" placeholder="e.g. 411001" /></div>
            <div><Label>Weight per unit (kg)</Label><Input data-testid="form-weight" type="number" step="0.1" value={form.weight_per_unit_kg} onChange={(e) => set("weight_per_unit_kg", e.target.value)} className="rounded-xl h-11 mt-1" /></div>
            <div>
              <Label>Self-delivery charge (₹, optional)</Label>
              <Input data-testid="form-seller-delivery" type="number" value={form.seller_delivery_charge} onChange={(e) => set("seller_delivery_charge", e.target.value)} className="rounded-xl h-11 mt-1" placeholder="Leave empty to not offer self-delivery" />
            </div>
            <div className="flex flex-col gap-2 justify-end pb-1">
              <label className="flex items-center gap-2 cursor-pointer text-sm"><Checkbox data-testid="form-organic" checked={form.organic} onCheckedChange={(v) => set("organic", v)} /> Organic certified</label>
              <label className="flex items-center gap-2 cursor-pointer text-sm"><Checkbox data-testid="form-export" checked={form.export_ready} onCheckedChange={(v) => set("export_ready", v)} /> Export ready</label>
            </div>
          </div>
          <Button data-testid="form-submit" type="submit" disabled={busy} className="w-full h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
            {busy ? (isEdit ? "Saving…" : "Listing…") : (isEdit ? "Save changes" : "List Product")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
