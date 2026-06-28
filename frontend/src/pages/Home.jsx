import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import ProductCard from "@/components/ProductCard";
import { useLanguage } from "@/contexts/LanguageContext";
import { useNavigate } from "react-router-dom";
import { Search, ArrowRight, ShieldCheck, Truck, Globe2, IndianRupee, Quote, Sprout, Wheat, Apple, Beef, Fish, Egg, Salad, Flower, Leaf, Milk, Droplet, FlaskConical, Tractor, Bean, Flame } from "lucide-react";

const ICONS = { Salad, Apple, Wheat, Bean, Flame, Flower, Leaf, Sprout, Milk, Droplet, FlaskConical, Tractor, Beef, Fish, Egg };

const CATEGORY_BG = {
  vegetables: "from-emerald-200 to-green-300", fruits: "from-rose-200 to-amber-200",
  grains: "from-amber-200 to-yellow-200", rice: "from-stone-200 to-amber-100",
  pulses: "from-orange-200 to-amber-300", spices: "from-red-200 to-orange-300",
  flowers: "from-pink-200 to-fuchsia-200", medicinal: "from-lime-200 to-emerald-200",
  organic: "from-emerald-300 to-teal-300", dairy: "from-sky-100 to-slate-200",
  honey: "from-yellow-200 to-amber-300", seeds: "from-stone-200 to-yellow-200",
  fertilizers: "from-slate-200 to-zinc-300", equipment: "from-zinc-200 to-slate-300",
  livestock: "from-amber-200 to-orange-300", fishery: "from-cyan-200 to-blue-200",
  poultry: "from-yellow-100 to-amber-200",
};

const SCHEMES = [
  { id: "pm-kisan", title: "PM-KISAN Samman Nidhi", desc: "₹6,000/year direct income support to small & marginal farmers.", tag: "Active" },
  { id: "e-nam", title: "e-NAM Integration", desc: "Trade your produce on India's largest digital agriculture market.", tag: "Live" },
  { id: "pmfby", title: "PMFBY Crop Insurance", desc: "Comprehensive crop insurance against natural calamities.", tag: "Open" },
  { id: "soil-health", title: "Soil Health Card", desc: "Free soil testing and crop-specific nutrient recommendations.", tag: "Free" },
];

const STORIES = [
  { id: "suresh", name: "Suresh Yadav", crop: "Banana Exporter", earnings: "₹18L/yr", quote: "KisanBaazar connected me to Dubai buyers. My income tripled in 2 years.", img: "https://images.pexels.com/photos/36004056/pexels-photo-36004056.jpeg" },
  { id: "lakshmi", name: "Lakshmi Devi", crop: "Organic Spices", earnings: "₹9L/yr", quote: "Direct buyers from Germany. No commission agents. Fair price for my turmeric.", img: "https://images.unsplash.com/photo-1582719508461-905c673771fd?w=600" },
  { id: "karthik", name: "Karthik Reddy", crop: "Pomegranate Auctions", earnings: "₹24L/yr", quote: "Auction system gave me 40% higher prices than mandi rates. Game changer.", img: "https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=600" },
];

const TESTIMONIALS = [
  { id: "rajesh", name: "Rajesh Foods", role: "Food Processing Co.", quote: "Sourcing 50+ tonnes of basmati monthly. Quality consistent, paperwork seamless." },
  { id: "anita", name: "Anita Kapur", role: "Restaurant Chain", quote: "Farm-fresh vegetables direct from Pune. My chefs love the quality." },
  { id: "emirates", name: "Emirates Trading", role: "International Buyer", quote: "Reliable Indian exporters, GST-compliant invoices, on-time shipments." },
];

const HERO_BADGES = [
  { id: "fee", icon: ShieldCheck, txt: "0% Reg. Fee" },
  { id: "ship", icon: Truck, txt: "Pan-India Delivery" },
  { id: "export", icon: Globe2, txt: "Export Ready" },
  { id: "price", icon: IndianRupee, txt: "Transparent Pricing" },
];

export default function Home() {
  const { t } = useLanguage();
  const [products, setProducts] = useState([]);
  const [cats, setCats] = useState([]);
  const [search, setSearch] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    api.get("/products?limit=12").then((res) => setProducts(res.data));
    api.get("/categories").then((res) => setCats(res.data));
    // Intentionally empty deps: this is a one-shot mount fetch. 'api' is a stable
    // axios singleton; 'setProducts'/'setCats' are stable React setters; 'res' is
    // a Promise-callback parameter (not a reactive value).
  }, []);

  const onSearch = (e) => {
    e.preventDefault();
    nav(`/products${search ? `?q=${encodeURIComponent(search)}` : ""}`);
  };

  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0">
          <img src="https://images.pexels.com/photos/16846734/pexels-photo-16846734.jpeg" alt=""
            className="w-full h-full object-cover" />
          <div className="absolute inset-0 bg-gradient-to-r from-black/75 via-black/55 to-black/30" />
        </div>
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 sm:py-28 lg:py-36">
          <div className="max-w-3xl text-white">
            <div className="inline-flex items-center gap-2 bg-white/15 backdrop-blur px-4 py-1.5 rounded-full text-sm font-medium mb-6">
              <Sprout size={16} /> Trusted by 50,000+ Indian farmers
            </div>
            <h1 className="font-heading font-bold text-4xl sm:text-5xl lg:text-7xl tracking-tight leading-[1.05]">
              {t("hero_title")}
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-white/90 max-w-2xl leading-relaxed">
              {t("hero_subtitle")}
            </p>

            <form onSubmit={onSearch} className="mt-8 flex flex-col sm:flex-row gap-3 max-w-xl">
              <div className="relative flex-1">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" size={20} />
                <Input data-testid="hero-search-input" value={search} onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("search_placeholder")}
                  className="pl-12 h-14 rounded-2xl text-base text-foreground bg-white border-0" />
              </div>
              <Button data-testid="hero-search-btn" type="submit" className="h-14 px-8 rounded-2xl bg-primary hover:bg-primary/90 text-base font-semibold">
                {t("explore")} <ArrowRight size={18} className="ml-1" />
              </Button>
            </form>

            <div className="mt-10 grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
              {HERO_BADGES.map((b) => (
                <div key={b.id} className="flex items-center gap-2 bg-white/10 backdrop-blur rounded-xl px-3 py-2">
                  <b.icon size={18} /> <span className="font-medium">{b.txt}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Categories */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="flex items-end justify-between mb-8">
          <div>
            <h2 className="font-heading font-bold text-3xl sm:text-4xl">{t("categories")}</h2>
            <p className="text-muted-foreground mt-2">Direct from the source.</p>
          </div>
          <Link to="/products" className="text-primary font-semibold hidden sm:flex items-center gap-1">
            View all <ArrowRight size={16} />
          </Link>
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-3 sm:gap-4">
          {cats.slice(0, 16).map((c, i) => {
            const Icon = ICONS[c.icon] || Sprout;
            return (
              <Link key={c.id} to={`/products?category=${c.id}`} data-testid={`category-${c.id}`}
                className={`group p-4 sm:p-5 rounded-2xl bg-gradient-to-br ${CATEGORY_BG[c.id] || "from-emerald-100 to-green-200"} dark:from-emerald-900/40 dark:to-green-900/30 card-hover fade-up text-center`}
                style={{ animationDelay: `${i * 30}ms` }}>
                <Icon className="mx-auto mb-2 text-emerald-900 dark:text-emerald-200" size={28} strokeWidth={2.2} />
                <div className="text-xs sm:text-sm font-semibold text-emerald-900 dark:text-emerald-100 leading-tight">{c.name}</div>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Featured products */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="flex items-end justify-between mb-8">
          <div>
            <h2 className="font-heading font-bold text-3xl sm:text-4xl">{t("featured")}</h2>
            <p className="text-muted-foreground mt-2">Hand-picked produce from verified farmers.</p>
          </div>
          <Link to="/products" className="text-primary font-semibold flex items-center gap-1">
            View all <ArrowRight size={16} />
          </Link>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
          {products.slice(0, 8).map((p, i) => <ProductCard key={p.product_id} p={p} index={i} />)}
        </div>
      </section>

      {/* Schemes */}
      <section id="schemes" className="bg-secondary/40 dark:bg-card/50 py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2 className="font-heading font-bold text-3xl sm:text-4xl mb-2">{t("schemes_title")}</h2>
          <p className="text-muted-foreground mb-8">Stay updated on benefits, subsidies, and policies.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
            {SCHEMES.map((s) => (
              <div key={s.id} className="bg-card border-2 border-border rounded-2xl p-6 card-hover">
                <div className="inline-block bg-accent/20 text-accent-foreground text-xs font-semibold px-2.5 py-1 rounded-full mb-3">{s.tag}</div>
                <h3 className="font-heading font-semibold text-lg mb-2">{s.title}</h3>
                <p className="text-sm text-muted-foreground">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Success stories */}
      <section id="stories" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <h2 className="font-heading font-bold text-3xl sm:text-4xl mb-2">{t("stories_title")}</h2>
        <p className="text-muted-foreground mb-8">Real farmers. Real income. Real change.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {STORIES.map((s) => (
            <div key={s.id} className="relative rounded-2xl overflow-hidden card-hover h-80 group">
              <img src={s.img} alt={s.name} className="absolute inset-0 w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
              <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/40 to-transparent" />
              <div className="relative h-full flex flex-col justify-end p-6 text-white">
                <Quote size={22} className="opacity-70 mb-2" />
                <p className="text-sm italic leading-relaxed mb-4">{s.quote}</p>
                <div className="border-t border-white/20 pt-3">
                  <div className="font-heading font-semibold text-lg">{s.name}</div>
                  <div className="text-xs opacity-80">{s.crop} · Earning {s.earnings}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Testimonials */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
        <h2 className="font-heading font-bold text-3xl sm:text-4xl mb-2">{t("testimonials_title")}</h2>
        <p className="text-muted-foreground mb-8">Trusted by global buyers and Indian retailers.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {TESTIMONIALS.map((tm) => (
            <div key={tm.id} className="bg-card border-2 border-border rounded-2xl p-6 card-hover">
              <Quote className="text-primary mb-3" size={22} />
              <p className="leading-relaxed">{tm.quote}</p>
              <div className="mt-4 pt-4 border-t border-border">
                <div className="font-heading font-semibold">{tm.name}</div>
                <div className="text-xs text-muted-foreground">{tm.role}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="bg-primary text-primary-foreground">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 grid md:grid-cols-2 gap-8 items-center">
          <div>
            <h2 className="font-heading font-bold text-3xl sm:text-4xl">Are you a farmer?</h2>
            <p className="mt-3 opacity-90 text-lg">List your produce in minutes. Get paid directly. Reach buyers across the globe.</p>
          </div>
          <div className="flex flex-wrap gap-3 md:justify-end">
            <Link to="/register"><Button data-testid="cta-farmer-btn" className="h-14 px-8 rounded-2xl bg-white text-primary hover:bg-white/90 font-semibold text-base">
              {t("become_farmer")} <ArrowRight size={18} className="ml-1" />
            </Button></Link>
            <Link to="/products"><Button variant="outline" className="h-14 px-8 rounded-2xl border-white text-white hover:bg-white/10 font-semibold text-base">
              {t("explore")}
            </Button></Link>
          </div>
        </div>
      </section>
    </div>
  );
}
