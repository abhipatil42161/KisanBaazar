import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider } from "@/contexts/AuthContext";
import { CartProvider } from "@/contexts/CartContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { LanguageProvider } from "@/contexts/LanguageContext";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import AIChat from "@/components/AIChat";
import Home from "@/pages/Home";
import Products from "@/pages/Products";
import ProductDetail from "@/pages/ProductDetail";
import Cart from "@/pages/Cart";
import Checkout from "@/pages/Checkout";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import FarmerDashboard from "@/pages/FarmerDashboard";
import BuyerDashboard from "@/pages/BuyerDashboard";
import AdminDashboard from "@/pages/AdminDashboard";
import ExporterDashboard from "@/pages/ExporterDashboard";
import AuthCallback from "@/pages/AuthCallback";
import ProtectedRoute from "@/components/ProtectedRoute";

function AppRouter() {
  const location = useLocation();
  // Handle Emergent Google OAuth session_id in URL fragment
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <Header />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/products" element={<Products />} />
          <Route path="/products/:id" element={<ProductDetail />} />
          <Route path="/cart" element={<Cart />} />
          <Route path="/checkout" element={<ProtectedRoute><Checkout /></ProtectedRoute>} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/dashboard/farmer" element={<ProtectedRoute role="farmer"><FarmerDashboard /></ProtectedRoute>} />
          <Route path="/dashboard/buyer" element={<ProtectedRoute><BuyerDashboard /></ProtectedRoute>} />
          <Route path="/dashboard/exporter" element={<ProtectedRoute role="exporter"><ExporterDashboard /></ProtectedRoute>} />
          <Route path="/dashboard/admin" element={<ProtectedRoute role="admin"><AdminDashboard /></ProtectedRoute>} />
        </Routes>
      </main>
      <Footer />
      <AIChat />
      <Toaster position="top-right" richColors />
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <AuthProvider>
          <CartProvider>
            <BrowserRouter>
              <AppRouter />
            </BrowserRouter>
          </CartProvider>
        </AuthProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
}
