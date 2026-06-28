import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, getJson } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useCart } from "@/contexts/CartContext";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { MapPin, Award, Sprout, Gavel, Calendar, Truck, ShieldCheck, Plus, Minus } from "lucide-react";

// Module-scope: fetch + apply in one step so the hook body has zero Promise-callback params.
const fetchAndApplyProduct = (productId, setProduct, setQty) =>
  getJson(`/products/${productId}`).then((product) => {
    setProduct(product);
    setQty(product.moq || 1);
  });

export default function ProductDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [p, setP] = useState(null);
  const [qty, setQty] = useState(1);
  const [bidAmt, setBidAmt] = useState("");
  const { add } = useCart();
  const { user } = useAuth();

  const load = useCallback(
    () => fetchAndApplyProduct(id, setP, setQty),
    [id, setP, setQty],
  );
  useEffect(() => { load(); }, [load]);

  if (!p) return <div className="max-w-7xl mx-auto p-8">Loading…</div>;

  const submitBid = async () => {
    if (!user) { toast.error("Please login to bid"); nav("/login"); return; }
    try {
      const { data } = await api.post(`/products/${id}/bid`, { amount: Number(bidAmt) });
      toast.success(`Bid placed at ₹${data.current_bid}`);
      setBidAmt("");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Bid failed");
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="grid lg:grid-cols-2 gap-10">
        <div>
          <div className="aspect-square bg-muted rounded-3xl overflow-hidden">
            {p.images?.[0] && <img src={p.images[0]} alt={p.title} className="w-full h-full object-cover" />}
          </div>
        </div>

        <div>
          <div className="flex flex-wrap gap-2 mb-3">
            {p.organic && <Badge className="bg-accent text-accent-foreground gap-1"><Sprout size={12} />Organic</Badge>}
            {p.export_ready && <Badge className="bg-primary text-primary-foreground gap-1"><Award size={12} />Export Grade</Badge>}
            {p.auction && <Badge className="bg-amber-500 text-white gap-1"><Gavel size={12} />Live Auction</Badge>}
            <Badge variant="outline">Grade {p.quality_grade}</Badge>
          </div>
          <h1 data-testid="product-title" className="font-heading font-bold text-3xl sm:text-4xl">{p.title}</h1>
          <div className="flex items-center gap-2 text-muted-foreground mt-2">
            <MapPin size={16} /> {p.location}, {p.state}, {p.country}
          </div>
          <div className="mt-2 text-sm">by <span className="font-semibold text-primary">{p.farmer_name}</span></div>

          <div className="mt-6 p-5 bg-secondary/50 dark:bg-card rounded-2xl border-2 border-border">
            <div className="flex items-baseline gap-3">
              <div className="font-heading text-4xl font-bold text-primary">
                ₹{p.auction ? p.current_bid || p.price : p.price}
              </div>
              <div className="text-sm text-muted-foreground">per {p.unit}</div>
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              MOQ: {p.moq} {p.unit} · Available: {p.available_qty} {p.unit}
            </div>

            {p.auction ? (
              <div className="mt-4 space-y-3">
                <div className="text-sm text-muted-foreground">Auction ends: {new Date(p.auction_end).toLocaleString()}</div>
                <div className="flex gap-2">
                  <Input data-testid="bid-amount" value={bidAmt} onChange={(e) => setBidAmt(e.target.value)}
                    type="number" placeholder="Your bid (₹)" className="h-12 rounded-xl" />
                  <Button data-testid="bid-submit" onClick={submitBid} className="h-12 px-6 rounded-xl bg-amber-500 hover:bg-amber-600">
                    Place Bid
                  </Button>
                </div>
              </div>
            ) : (
              <div className="mt-4 flex items-center gap-3">
                <div className="flex items-center gap-1 border-2 border-border rounded-xl p-1">
                  <Button data-testid="qty-minus" size="icon" variant="ghost" className="h-9 w-9 rounded-lg" onClick={() => setQty(Math.max(p.moq, qty - 1))}>
                    <Minus size={16} />
                  </Button>
                  <span data-testid="qty-value" className="w-12 text-center font-semibold">{qty}</span>
                  <Button data-testid="qty-plus" size="icon" variant="ghost" className="h-9 w-9 rounded-lg" onClick={() => setQty(qty + 1)}>
                    <Plus size={16} />
                  </Button>
                </div>
                <Button data-testid="add-to-cart-btn" className="flex-1 h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold"
                  onClick={() => add(p, qty)}>
                  Add to Cart · ₹{(p.price * qty).toLocaleString()}
                </Button>
              </div>
            )}
            {!p.auction && (
              <Button data-testid="buy-now-btn" variant="outline" className="w-full mt-3 h-12 rounded-xl font-semibold"
                onClick={() => { add(p, qty); nav("/checkout"); }}>
                Buy Now
              </Button>
            )}
          </div>

          <div className="mt-6 grid grid-cols-3 gap-3 text-sm">
            <div className="p-3 bg-card border-2 border-border rounded-xl flex flex-col items-center text-center">
              <ShieldCheck className="text-primary mb-1" size={20} /> Verified Farmer
            </div>
            <div className="p-3 bg-card border-2 border-border rounded-xl flex flex-col items-center text-center">
              <Truck className="text-primary mb-1" size={20} /> Pan-India Ship
            </div>
            <div className="p-3 bg-card border-2 border-border rounded-xl flex flex-col items-center text-center">
              <Calendar className="text-primary mb-1" size={20} /> Fresh Harvest
            </div>
          </div>

          <Tabs defaultValue="desc" className="mt-8">
            <TabsList className="rounded-xl">
              <TabsTrigger value="desc" data-testid="tab-desc">Description</TabsTrigger>
              <TabsTrigger value="specs" data-testid="tab-specs">Specifications</TabsTrigger>
              <TabsTrigger value="shipping" data-testid="tab-shipping">Shipping</TabsTrigger>
            </TabsList>
            <TabsContent value="desc" className="mt-4 leading-relaxed text-base">{p.description}</TabsContent>
            <TabsContent value="specs" className="mt-4 text-sm">
              <table className="w-full">
                <tbody>
                  <tr className="border-b border-border"><td className="py-2 text-muted-foreground">Category</td><td className="py-2 font-medium capitalize">{p.category}</td></tr>
                  <tr className="border-b border-border"><td className="py-2 text-muted-foreground">Quality Grade</td><td className="py-2 font-medium">{p.quality_grade}</td></tr>
                  <tr className="border-b border-border"><td className="py-2 text-muted-foreground">Harvest Date</td><td className="py-2 font-medium">{p.harvest_date || "—"}</td></tr>
                  <tr className="border-b border-border"><td className="py-2 text-muted-foreground">Unit</td><td className="py-2 font-medium">{p.unit}</td></tr>
                  <tr><td className="py-2 text-muted-foreground">Origin</td><td className="py-2 font-medium">{p.location}, {p.state}</td></tr>
                </tbody>
              </table>
            </TabsContent>
            <TabsContent value="shipping" className="mt-4 text-sm">
              Standard delivery 3–7 business days. Cold storage available for perishables. Export shipments require additional 5–10 days for customs.
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
