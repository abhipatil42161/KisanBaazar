export default function FarmerOrders({ orders }) {
  return (
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
  );
}
