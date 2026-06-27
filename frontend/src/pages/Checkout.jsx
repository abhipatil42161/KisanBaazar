import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { useCart } from "@/contexts/CartContext";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { CreditCard, Smartphone, Wallet, Building2, CheckCircle2 } from "lucide-react";

const METHODS = [
  { id: "upi", label: "UPI (PhonePe, GPay, Paytm)", icon: Smartphone },
  { id: "card", label: "Credit / Debit Card", icon: CreditCard },
  { id: "netbanking", label: "Net Banking", icon: Building2 },
  { id: "wallet", label: "Wallets", icon: Wallet },
];

export default function Checkout() {
  const nav = useNavigate();
  const { items, total, clear } = useCart();
  const { user } = useAuth();
  const [addr, setAddr] = useState(user?.location || "");
  const [phone, setPhone] = useState(user?.phone || "");
  const [method, setMethod] = useState("upi");
  const [busy, setBusy] = useState(false);
  const [orderId, setOrderId] = useState(null);

  const placeOrder = async () => {
    if (!addr.trim() || !phone.trim()) { toast.error("Please fill address and phone"); return; }
    if (items.length === 0) { toast.error("Cart is empty"); return; }
    setBusy(true);
    try {
      const { data: order } = await api.post("/orders", {
        items: items.map((it) => ({
          product_id: it.product_id, title: it.title, qty: it.qty, price: it.price, image: it.image,
        })),
        delivery_address: `${addr} · Phone: ${phone}`,
        payment_method: method,
      });
      // MOCK Razorpay payment — instantly mark paid
      await api.post(`/orders/${order.order_id}/pay`);
      setOrderId(order.order_id);
      clear();
      toast.success("Payment successful!");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Order failed");
    } finally {
      setBusy(false);
    }
  };

  if (orderId) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <CheckCircle2 className="mx-auto text-primary mb-4" size={72} strokeWidth={1.5} />
        <h1 className="font-heading font-bold text-3xl">Order Confirmed!</h1>
        <p className="text-muted-foreground mt-2">Order ID: <span className="font-mono font-semibold text-foreground">{orderId}</span></p>
        <p className="text-sm text-muted-foreground mt-2">MOCK Razorpay payment processed. Real keys can be added in settings.</p>
        <div className="flex gap-3 justify-center mt-6">
          <Button data-testid="view-orders-btn" onClick={() => nav("/dashboard/buyer")} className="h-12 px-6 rounded-xl">View Orders</Button>
          <Button data-testid="continue-shop-btn" variant="outline" onClick={() => nav("/products")} className="h-12 px-6 rounded-xl">Continue Shopping</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="font-heading font-bold text-3xl mb-6">Checkout</h1>
      <div className="grid lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-card border-2 border-border rounded-2xl p-6">
            <h3 className="font-heading font-semibold text-xl mb-4">Delivery Address</h3>
            <div className="space-y-3">
              <Textarea data-testid="checkout-address" value={addr} onChange={(e) => setAddr(e.target.value)}
                placeholder="Full address with PIN code" rows={3} className="rounded-xl" />
              <Input data-testid="checkout-phone" value={phone} onChange={(e) => setPhone(e.target.value)}
                placeholder="Phone number" className="h-12 rounded-xl" />
            </div>
          </div>

          <div className="bg-card border-2 border-border rounded-2xl p-6">
            <h3 className="font-heading font-semibold text-xl mb-4">Payment Method <span className="text-xs font-normal text-muted-foreground">(MOCK Razorpay)</span></h3>
            <RadioGroup value={method} onValueChange={setMethod} className="space-y-2">
              {METHODS.map((m) => (
                <Label key={m.id} htmlFor={m.id} data-testid={`pay-${m.id}`}
                  className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-colors ${
                    method === m.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"
                  }`}>
                  <RadioGroupItem value={m.id} id={m.id} />
                  <m.icon size={20} className="text-primary" />
                  <span className="font-medium">{m.label}</span>
                </Label>
              ))}
            </RadioGroup>
          </div>
        </div>

        <div className="bg-card border-2 border-border rounded-2xl p-6 h-fit lg:sticky lg:top-24">
          <h3 className="font-heading font-semibold text-xl mb-4">Summary</h3>
          <div className="space-y-2 text-sm max-h-48 overflow-y-auto">
            {items.map((it) => (
              <div key={it.product_id} className="flex justify-between text-sm">
                <span className="line-clamp-1 pr-2">{it.title} × {it.qty}</span>
                <span className="font-medium">₹{(it.price * it.qty).toLocaleString()}</span>
              </div>
            ))}
          </div>
          <div className="border-t border-border pt-3 mt-3 space-y-1.5 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Subtotal</span><span>₹{total.toLocaleString()}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Platform fee</span><span>₹{Math.round(total * 0.01)}</span></div>
            <div className="flex justify-between font-heading font-bold text-xl pt-2">
              <span>Total</span><span className="text-primary">₹{Math.round(total * 1.01).toLocaleString()}</span>
            </div>
          </div>
          <Button data-testid="place-order-btn" onClick={placeOrder} disabled={busy}
            className="w-full mt-6 h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold">
            {busy ? "Processing…" : `Pay ₹${Math.round(total * 1.01).toLocaleString()}`}
          </Button>
        </div>
      </div>
    </div>
  );
}
