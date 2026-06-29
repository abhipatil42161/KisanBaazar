import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import { imgUrl } from "@/lib/images";
import ProductFormDialog from "@/components/farmer/AddProductDialog";

export default function FarmerListings({ products, cats, onChange }) {
  const remove = async (pid) => {
    if (!window.confirm("Delete this listing? Associated photos will also be removed.")) return;
    try {
      await api.delete(`/products/${pid}`);
      toast.success("Removed");
      onChange();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <section>
      <h2 className="font-heading font-semibold text-xl mb-3">My Listings</h2>
      <div className="space-y-3">
        {products.length === 0 && <p className="text-muted-foreground">No listings yet. Add your first product!</p>}
        {products.map((p) => (
          <div key={p.product_id} data-testid={`listing-${p.product_id}`}
            className="bg-card border-2 border-border rounded-xl p-4 flex gap-3 items-center">
            <div className="w-16 h-16 rounded-lg bg-muted overflow-hidden shrink-0">
              {p.images?.[0] && <img src={imgUrl(p.images[0])} alt="" className="w-full h-full object-cover" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold truncate">{p.title}</div>
              <div className="text-xs text-muted-foreground">₹{p.price}/{p.unit} · {p.available_qty} available · {(p.images || []).length} photo{(p.images || []).length === 1 ? "" : "s"}</div>
            </div>
            <ProductFormDialog cats={cats} existing={p} onSaved={onChange} />
            <Button data-testid={`del-${p.product_id}`} size="icon" variant="ghost" onClick={() => remove(p.product_id)} className="text-destructive">
              <Trash2 size={18} />
            </Button>
          </div>
        ))}
      </div>
    </section>
  );
}
