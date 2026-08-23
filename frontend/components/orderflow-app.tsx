"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell, type Screen } from "./app-shell";
import { AuthDialog } from "./auth-dialog";
import { useAuth } from "./auth-provider";
import { AuditScreen } from "./screens/audit-screen";
import { CartScreen } from "./screens/cart-screen";
import { CatalogScreen } from "./screens/catalog-screen";
import { DashboardScreen } from "./screens/dashboard-screen";
import { OrdersScreen } from "./screens/orders-screen";
import { WarehouseScreen } from "./screens/warehouse-screen";
import { LoadingBlock } from "./ui";

export function OrderFlowApp() {
  const { user, loading, logout } = useAuth();
  const [screen, setScreen] = useState<Screen>("catalog");
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");

  useEffect(() => {
    const timer = window.setTimeout(
      () => setScreen(user && user.role !== "customer" ? "overview" : "catalog"),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [user]);

  const openAuth = useCallback((mode: "login" | "register") => {
    setAuthMode(mode);
    setAuthOpen(true);
  }, []);

  function navigate(next: Screen) {
    if (!user && next !== "catalog") {
      openAuth("login");
      return;
    }
    setScreen(next);
  }

  let content;
  if (loading) content = <LoadingBlock label="Восстанавливаем сессию" />;
  else if (screen === "overview") content = <DashboardScreen user={user} onNavigate={navigate} />;
  else if (screen === "cart") content = <CartScreen user={user} onNavigate={navigate} />;
  else if (screen === "orders") content = <OrdersScreen user={user} />;
  else if (screen === "warehouse") content = <WarehouseScreen user={user} />;
  else if (screen === "audit") content = <AuditScreen user={user} />;
  else content = <CatalogScreen user={user} requestAuth={() => openAuth("login")} onNavigate={navigate} />;

  return (
    <AppShell
      user={user}
      screen={screen}
      onNavigate={navigate}
      onLogin={() => openAuth("login")}
      onRegister={() => openAuth("register")}
      onLogout={() => void logout()}
    >
      {content}
      <AuthDialog
        key={`${authMode}:${authOpen}`}
        open={authOpen}
        initialMode={authMode}
        onClose={() => setAuthOpen(false)}
      />
    </AppShell>
  );
}
