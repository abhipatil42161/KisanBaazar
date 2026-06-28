import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";

export default function FarmerListings({ products, onChange }) {
  const remove = async (pid) => {
    if (!window.confirm("Delete this listing?")) return;
    await api.delete(`/products/${pid}`);
    toast.success("Removed");
    onChange();
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
  );
}
