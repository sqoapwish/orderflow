"use client";

import type { ReactNode } from "react";

import { initials, roleLabel } from "@/lib/format";
import type { User } from "@/lib/types";

import { Icon, type IconName, Logo } from "./ui";

export type Screen = "overview" | "catalog" | "cart" | "orders" | "warehouse" | "audit";

interface NavItem {
  id: Screen;
  label: string;
  icon: IconName;
}

const CUSTOMER_NAV: NavItem[] = [
  { id: "catalog", label: "Товары", icon: "box" },
  { id: "cart", label: "Корзина", icon: "cart" },
  { id: "orders", label: "Заказы", icon: "orders" },
];

const MANAGER_NAV: NavItem[] = [
  { id: "overview", label: "Обзор", icon: "analytics" },
  { id: "orders", label: "Заказы", icon: "orders" },
  { id: "catalog", label: "Товары", icon: "box" },
  { id: "warehouse", label: "Склады", icon: "warehouse" },
];

export function AppShell({
  user,
  screen,
  onNavigate,
  onLogin,
  onRegister,
  onLogout,
  children,
}: {
  user: User | null;
  screen: Screen;
  onNavigate: (screen: Screen) => void;
  onLogin: () => void;
  onRegister: () => void;
  onLogout: () => void;
  children: ReactNode;
}) {
  const nav = user
    ? user.role === "customer"
      ? CUSTOMER_NAV
      : [...MANAGER_NAV, ...(user.role === "admin" ? [{ id: "audit" as const, label: "Аудит", icon: "audit" as const }] : [])]
    : [{ id: "catalog" as const, label: "Товары", icon: "box" as const }];

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand-button" type="button" onClick={() => onNavigate(user && user.role !== "customer" ? "overview" : "catalog")}>
          <Logo />
        </button>
        <nav className="main-nav" aria-label="Основная навигация">
          {nav.map((item) => (
            <button
              className={screen === item.id ? "nav-item nav-item-active" : "nav-item"}
              key={item.id}
              type="button"
              onClick={() => onNavigate(item.id)}
            >
              <Icon name={item.icon} size={17} />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="account-area">
          {user ? (
            <>
              <div className="avatar">{initials(user.email)}</div>
              <div className="account-copy">
                <strong>{user.email.split("@")[0]}</strong>
                <span>{roleLabel(user.role)}</span>
              </div>
              <button className="icon-button" aria-label="Выйти" type="button" onClick={onLogout}>
                <Icon name="logout" />
              </button>
            </>
          ) : (
            <>
              <button className="button button-ghost" type="button" onClick={onLogin}>
                Войти
              </button>
              <button className="button button-primary" type="button" onClick={onRegister}>
                Регистрация
              </button>
            </>
          )}
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
