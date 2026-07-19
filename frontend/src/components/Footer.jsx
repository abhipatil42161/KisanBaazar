import { Sprout, Mail, Phone, MapPin, Facebook, Instagram, Twitter, Youtube, MessageCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { useSiteContent } from "@/hooks/useSiteContent";

const SOCIAL_ICONS = { facebook: Facebook, instagram: Instagram, twitter: Twitter, youtube: Youtube, whatsapp: MessageCircle };

export default function Footer() {
  const site = useSiteContent();
  const socialEntries = Object.entries(site.social_links || {}).filter(([, url]) => url);

  return (
    <footer className="bg-secondary/40 dark:bg-card border-t border-border mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 grid grid-cols-2 md:grid-cols-4 gap-8">
        <div className="col-span-2 md:col-span-1">
          <div className="flex items-center gap-2 mb-4">
            {site.logo_url ? (
              <img src={site.logo_url} alt={site.site_name} className="w-10 h-10 rounded-2xl object-cover" />
            ) : (
              <div className="w-10 h-10 rounded-2xl bg-primary flex items-center justify-center">
                <Sprout className="text-white" size={22} strokeWidth={2.5} />
              </div>
            )}
            <span className="font-heading font-bold text-xl">{site.site_name}</span>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {site.site_description}
          </p>
          {socialEntries.length > 0 && (
            <div className="flex gap-3 mt-4">
              {socialEntries.map(([key, url]) => {
                const Icon = SOCIAL_ICONS[key];
                return (
                  <a key={key} href={url} target="_blank" rel="noopener noreferrer" className="text-muted-foreground hover:text-primary">
                    {Icon && <Icon size={18} />}
                  </a>
                );
              })}
            </div>
          )}
        </div>

        <div>
          <h4 className="font-heading font-semibold mb-3">Marketplace</h4>
          <ul className="space-y-2 text-sm">
            <li><Link to="/products" className="hover:text-primary">All Products</Link></li>
            <li><Link to="/products?organic=true" className="hover:text-primary">Organic Produce</Link></li>
            <li><Link to="/products?export_ready=true" className="hover:text-primary">Export Quality</Link></li>
            <li><Link to="/products?auction=true" className="hover:text-primary">Live Auctions</Link></li>
          </ul>
        </div>

        <div>
          <h4 className="font-heading font-semibold mb-3">For Farmers</h4>
          <ul className="space-y-2 text-sm">
            <li><Link to="/register" className="hover:text-primary">Become a Seller</Link></li>
            <li><Link to="/dashboard/farmer" className="hover:text-primary">Farmer Dashboard</Link></li>
            <li><a href="#schemes" className="hover:text-primary">Government Schemes</a></li>
            <li><a href="#stories" className="hover:text-primary">Success Stories</a></li>
          </ul>
        </div>

        <div>
          <h4 className="font-heading font-semibold mb-3">Contact</h4>
          <ul className="space-y-2 text-sm text-muted-foreground">
            <li className="flex items-center gap-2"><Mail size={14} /> {site.contact_email}</li>
            <li className="flex items-center gap-2"><Phone size={14} /> {site.contact_phone}</li>
            <li className="flex items-center gap-2"><MapPin size={14} /> {site.contact_address}</li>
          </ul>
        </div>
      </div>
      <div className="border-t border-border py-5 text-center text-sm text-muted-foreground">
        © 2026 {site.site_name} · {site.footer_text} · GST · GDPR · IT Act compliant
      </div>
    </footer>
  );
}
