import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/AuthContext";
import { useCart } from "@/contexts/CartContext";
import { useTheme } from "@/contexts/ThemeContext";
import { useLanguage } from "@/contexts/LanguageContext";
import { LANGUAGES } from "@/lib/i18n";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
  DropdownMenuSeparator, DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { ShoppingCart, Sun, Moon, Globe, User as UserIcon, Search, Sprout, LogOut, LayoutDashboard } from "lucide-react";
import { useState } from "react";
import NotificationBell from "@/components/NotificationBell";

export default function Header() {
  const { user, logout } = useAuth();
  const { count } = useCart();
  const { theme, toggle } = useTheme();
  const { lang, setLanguage, t } = useLanguage();
  const nav = useNavigate();
  const [search, setSearch] = useState("");

  const onSearch = (e) => {
    e.preventDefault();
    if (search.trim()) nav(`/products?q=${encodeURIComponent(search.trim())}`);
  };

  const dashLink = user?.role === "farmer" ? "/dashboard/farmer"
    : user?.role === "admin" ? "/dashboard/admin"
    : user?.role === "exporter" ? "/dashboard/exporter"
    : user?.role === "delivery_partner" ? "/dashboard/delivery" : "/dashboard/buyer";

  return (
    <header className="glass sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 sm:h-20 flex items-center gap-3 sm:gap-6">
        <Link to="/" data-testid="logo-link" className="flex items-center gap-2 shrink-0">
          <div className="w-10 h-10 rounded-2xl bg-primary flex items-center justify-center shadow-md">
            <Sprout className="text-white" size={22} strokeWidth={2.5} />
          </div>
          <span className="font-heading font-bold text-xl tracking-tight hidden sm:block">
            Kisan<span className="text-primary">Baazar</span>
          </span>
        </Link>

        <form onSubmit={onSearch} className="flex-1 max-w-2xl hidden md:flex">
          <div className="relative w-full">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" size={18} />
            <Input
              data-testid="header-search-input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("search_placeholder")}
              className="pl-12 h-12 rounded-2xl bg-background/60 border-2 focus-visible:ring-primary"
            />
          </div>
        </form>

        <nav className="flex items-center gap-1 sm:gap-2 ml-auto">
          <Link to="/products" data-testid="nav-products" className="hidden md:block px-4 py-2 rounded-xl hover:bg-muted font-medium">
            {t("products")}
          </Link>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button data-testid="lang-toggle" variant="ghost" size="icon" className="rounded-xl h-11 w-11">
                <Globe size={20} strokeWidth={2.5} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-80 overflow-y-auto">
              <DropdownMenuLabel>Language</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {LANGUAGES.map((l) => (
                <DropdownMenuItem key={l.code} data-testid={`lang-${l.code}`}
                  onClick={() => setLanguage(l.code)}
                  className={lang === l.code ? "bg-muted font-semibold" : ""}>
                  {l.native} <span className="ml-auto text-xs text-muted-foreground">{l.code.toUpperCase()}</span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <Button data-testid="theme-toggle" variant="ghost" size="icon" onClick={toggle} className="rounded-xl h-11 w-11">
            {theme === "dark" ? <Sun size={20} strokeWidth={2.5} /> : <Moon size={20} strokeWidth={2.5} />}
          </Button>

          <NotificationBell />

          <Link to="/cart" data-testid="cart-link" className="relative">
            <Button variant="ghost" size="icon" className="rounded-xl h-11 w-11">
              <ShoppingCart size={20} strokeWidth={2.5} />
              {count > 0 && (
                <span className="absolute -top-1 -right-1 bg-primary text-primary-foreground text-xs rounded-full w-5 h-5 flex items-center justify-center font-bold">
                  {count}
                </span>
              )}
            </Button>
          </Link>

          {user ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button data-testid="user-menu-btn" variant="ghost" className="rounded-xl h-11 gap-2 px-3">
                  <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-semibold text-sm">
                    {user.name?.[0]?.toUpperCase() || "U"}
                  </div>
                  <span className="hidden sm:inline font-medium max-w-[120px] truncate">{user.name}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel className="capitalize">
                  {user.name} · <span className="text-primary">{user.role}</span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => nav(dashLink)} data-testid="menu-dashboard">
                  <LayoutDashboard size={16} className="mr-2" /> {t("dashboard")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={async () => { await logout(); nav("/"); }} data-testid="menu-logout">
                  <LogOut size={16} className="mr-2" /> {t("logout")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <>
              <Link to="/login"><Button data-testid="header-login-btn" variant="ghost" className="rounded-xl h-11">{t("login")}</Button></Link>
              <Link to="/register" className="hidden sm:inline-block">
                <Button data-testid="header-register-btn" className="rounded-xl h-11 bg-primary hover:bg-primary/90">{t("register")}</Button>
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
