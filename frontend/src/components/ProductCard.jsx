import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MapPin, Award, Sprout, Gavel } from "lucide-react";
import { useCart } from "@/contexts/CartContext";
import { useLanguage } from "@/contexts/LanguageContext";
import { imgUrl } from "@/lib/images";

export default function ProductCard({ p, index = 0 }) {
  const { add } = useCart();
  const { t } = useLanguage();
  return (
    <div data-testid={`product-card-${p.product_id}`}
      className="group bg-card border-2 border-border rounded-2xl overflow-hidden card-hover fade-up"
      style={{ animationDelay: `${index * 40}ms` }}>
      <Link to={`/products/${p.product_id}`} className="block relative aspect-[4/3] overflow-hidden bg-muted">
        {p.images?.[0] && (
          <img src={imgUrl(p.images[0])} alt={p.title}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
        )}
        <div className="absolute top-3 left-3 flex gap-1.5 flex-wrap">
          {p.organic && <Badge className="bg-accent text-accent-foreground gap-1 shadow"><Sprout size={12} />{t("organic")}</Badge>}
          {p.export_ready && <Badge className="bg-primary text-primary-foreground gap-1 shadow"><Award size={12} />Export</Badge>}
          {p.auction && <Badge className="bg-amber-500 text-white gap-1 shadow"><Gavel size={12} />{t("auction")}</Badge>}
        </div>
      </Link>
      <div className="p-5">
        <Link to={`/products/${p.product_id}`}>
          <h3 className="font-heading font-semibold text-lg line-clamp-1 hover:text-primary">{p.title}</h3>
        </Link>
        <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
          <MapPin size={12} /> {p.location}, {p.state}
        </div>
        <div className="text-xs text-muted-foreground mt-1">by {p.farmer_name}</div>
        <div className="flex items-end justify-between mt-4">
          <div>
            <div className="font-heading text-2xl font-bold text-primary">₹{p.auction ? p.current_bid || p.price : p.price}</div>
            <div className="text-xs text-muted-foreground">{t("per")} {p.unit} · {t("moq")} {p.moq}</div>
          </div>
          <Button data-testid={`add-cart-${p.product_id}`} size="sm" onClick={() => add(p)}
            className="rounded-xl h-10 bg-primary hover:bg-primary/90">
            {p.auction ? "Bid" : "Add"}
          </Button>
        </div>
      </div>
    </div>
  );
}
