"use client";

import { type FormEvent, useEffect, useState } from "react";

import { useAuth } from "./auth-provider";
import { Icon, Logo } from "./ui";

export function AuthDialog({
  open,
  initialMode,
  onClose,
}: {
  open: boolean;
  initialMode: "login" | "register";
  onClose: () => void;
}) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password);
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось войти");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        aria-labelledby="auth-title"
        aria-modal="true"
        className="auth-dialog"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="icon-button modal-close" aria-label="Закрыть" onClick={onClose}>
          <Icon name="x" />
        </button>
        <Logo />
        <div className="auth-copy">
          <span className="eyebrow">Добро пожаловать</span>
          <h2 id="auth-title">{mode === "login" ? "Войдите в аккаунт" : "Создайте аккаунт"}</h2>
          <p>
            {mode === "login"
              ? "Продолжите работу с заказами и аналитикой."
              : "Регистрация создаёт безопасный аккаунт покупателя."}
          </p>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>
            Email
            <input
              autoComplete="email"
              placeholder="you@example.com"
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Пароль
            <input
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              minLength={mode === "register" ? 8 : 1}
              placeholder="Не менее 8 символов"
              required
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <button className="button button-primary button-full" disabled={submitting} type="submit">
            {submitting ? "Подождите…" : mode === "login" ? "Войти" : "Зарегистрироваться"}
          </button>
        </form>
        <p className="auth-switch">
          {mode === "login" ? "Ещё нет аккаунта?" : "Уже зарегистрированы?"}{" "}
          <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Создать" : "Войти"}
          </button>
        </p>
      </section>
    </div>
  );
}
