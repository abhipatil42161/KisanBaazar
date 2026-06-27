import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useCart } from "@/contexts/CartContext";
import { Trash2, Plus, Minus, ShoppingCart } from "lucide-react";

export default function Cart() {
  const { items, total, remove, updateQty } = useCart();
  const nav = useNavigate();

  if (items.length === 0) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-20 text-center">
        <ShoppingCart className="mx-auto text-muted-foreground mb-4" size={64} strokeWidth={1.5} />
        <h2 className="font-heading font-bold text-3xl">Your cart is empty</h2>
        <p className="text-muted-foreground mt-2">Browse fresh produce from verified farmers.</p>
        <Link to="/products"><Button data-testid="empty-cart-shop-btn" className="mt-6 h-12 px-8 rounded-xl">Shop Now</Button></Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="font-heading font-bold text-3xl mb-6">Your Cart</h1>
      <div className="grid lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-4">
          {items.map((it) => (
            <div key={it.product_id} data-testid={`cart-item-${it.product_id}`}
              className="bg-card border-2 border-border rounded-2xl p-4 flex gap-4">
              <div className="w-24 h-24 rounded-xl overflow-hidden bg-muted shrink-0">
                {it.image && <img src={it.image} alt={it.title} className="w-full h-full object-cover" />}
              </div>
              <div className="flex-1">
                <Link to={`/products/${it.product_id}`} className="font-heading font-semibold text-lg hover:text-primary">{it.title}</Link>
                <div className="text-xs text-muted-foreground">by {it.farmer_name}</div>
                <div className="mt-2 flex items-center justify-between">
                  <div className="flex items-center gap-1 border-2 border-border rounded-xl p-0.5">
                    <Button size="icon" variant="ghost" className="h-8 w-8 rounded-lg" onClick={() => updateQty(it.product_id, it.qty - 1)}>
                      <Minus size={14} />
                    </Button>
                    <span className="w-10 text-center font-medium text-sm">{it.qty}</span>
                    <Button size="icon" variant="ghost" className="h-8 w-8 rounded-lg" onClick={() => updateQty(it.product_id, it.qty + 1)}>
                      <Plus size={14} />
                    </Button>
                  </div>
                  <div className="font-heading font-bold text-lg">₹{(it.price * it.qty).toLocaleString()}</div>
                </div>
              </div>
              <Button data-testid={`remove-${it.product_id}`} variant="ghost" size="icon"
                onClick={() => remove(it.product_id)} className="text-destructive">
                <Trash2 size={18} />
              </Button>
            </div>
          ))}
        </div>

        <div className="bg-card border-2 border-border rounded-2xl p-6 h-fit lg:sticky lg:top-24">
          <h3 className="font-heading font-semibold text-xl mb-4">Order Summary</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Subtotal</span><span>₹{total.toLocaleString()}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Shipping</span><span className="text-primary">Free</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Platform fee (1%)</span><span>₹{Math.round(total * 0.01)}</span></div>
            <div className="border-t border-border pt-3 mt-3 flex justify-between font-heading font-bold text-xl">
              <span>Total</span><span className="text-primary">₹{Math.round(total * 1.01).toLocaleString()}</span>
            </div>
          </div>
          <Button data-testid="cart-checkout-btn" className="w-full mt-6 h-12 rounded-xl bg-primary hover:bg-primary/90 font-semibold"
            onClick={() => nav("/checkout")}>
            Proceed to Checkout
          </Button>
        </div>
      </div>
    </div>
  );
}
