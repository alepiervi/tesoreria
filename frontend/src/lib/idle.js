import { useEffect, useState } from "react";

export const IDLE_MINUTES = 15;
const IDLE_MS = IDLE_MINUTES * 60 * 1000;
const WARN_MS = 60 * 1000;
const KEY = "nureal_last_activity";
const FLAG = "nureal_idle_logout";
const EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "wheel"];

export function markActivity() {
  try {
    localStorage.setItem(KEY, String(Date.now()));
  } catch {
    /* ignora */
  }
}

export function markIdleLogout() {
  try {
    localStorage.setItem(FLAG, "1");
  } catch {
    /* ignora */
  }
}

// true dopo una disconnessione per inattività (si cancella con clearIdleLogout)
export function wasIdleLogout() {
  try {
    return localStorage.getItem(FLAG) === "1";
  } catch {
    return false;
  }
}

export function clearIdleLogout() {
  try {
    localStorage.removeItem(FLAG);
  } catch {
    /* ignora */
  }
}

export function idleExpired() {
  try {
    const last = Number(localStorage.getItem(KEY));
    return Boolean(last) && Date.now() - last > IDLE_MS;
  } catch {
    return false;
  }
}

function remaining() {
  const last = Number(localStorage.getItem(KEY)) || Date.now();
  return IDLE_MS - (Date.now() - last);
}

// Disconnette dopo IDLE_MINUTES senza attività (condiviso tra le schede); restituisce i secondi rimasti nell'ultimo minuto
export function useIdleLogout(active, onTimeout) {
  const [secondsLeft, setSecondsLeft] = useState(null);

  useEffect(() => {
    if (!active) return undefined;
    markActivity();
    let lastWrite = 0;
    const onActivity = () => {
      if (Date.now() - lastWrite > 5000) {
        lastWrite = Date.now();
        markActivity();
      }
    };
    const check = () => {
      const left = remaining();
      if (left <= 0) onTimeout();
      else setSecondsLeft(left <= WARN_MS ? Math.ceil(left / 1000) : null);
    };
    EVENTS.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));
    document.addEventListener("visibilitychange", check);
    const t = setInterval(check, 1000);
    return () => {
      EVENTS.forEach((e) => window.removeEventListener(e, onActivity));
      document.removeEventListener("visibilitychange", check);
      clearInterval(t);
      setSecondsLeft(null);
    };
  }, [active, onTimeout]);

  return secondsLeft;
}
