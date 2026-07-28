"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { t } from "../../i18n";

export type ViewMode = "essential" | "expert";

type ViewModeContextValue = {
  mode: ViewMode;
  setMode: (mode: ViewMode) => void;
  isExpert: boolean;
};

const ViewModeContext = createContext<ViewModeContextValue>({
  mode: "essential",
  setMode: () => undefined,
  isExpert: false,
});

const storageKey = "robin-experience-view-mode";
const storageEvent = "robin-experience-view-mode-change";

function subscribeMode(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(storageEvent, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(storageEvent, onStoreChange);
  };
}

function readMode(): ViewMode {
  return window.localStorage.getItem(storageKey) === "expert"
    ? "expert"
    : "essential";
}

export function ViewModeProvider({ children }: { children: ReactNode }) {
  const mode = useSyncExternalStore<ViewMode>(
    subscribeMode,
    readMode,
    () => "essential",
  );

  useEffect(() => {
    document.documentElement.dataset.robinHydrated = "true";
    return () => {
      delete document.documentElement.dataset.robinHydrated;
    };
  }, []);

  const setMode = (nextMode: ViewMode) => {
    window.localStorage.setItem(storageKey, nextMode);
    window.dispatchEvent(new Event(storageEvent));
  };

  const value = useMemo<ViewModeContextValue>(
    () => ({ mode, setMode, isExpert: mode === "expert" }),
    [mode],
  );

  return (
    <ViewModeContext.Provider value={value}>
      {children}
    </ViewModeContext.Provider>
  );
}

export function useViewMode() {
  return useContext(ViewModeContext);
}

export function ViewModeSwitch() {
  const { mode, setMode } = useViewMode();
  return (
    <div
      className="view-switch"
      role="group"
      aria-label="Niveau de détail"
      title={
        mode === "essential"
          ? t("view.essentialHint")
          : t("view.expertHint")
      }
    >
      <button
        aria-pressed={mode === "essential"}
        className={mode === "essential" ? "active" : ""}
        onClick={() => setMode("essential")}
        type="button"
      >
        {t("view.essential")}
      </button>
      <button
        aria-pressed={mode === "expert"}
        className={mode === "expert" ? "active" : ""}
        onClick={() => setMode("expert")}
        type="button"
      >
        {t("view.expert")}
      </button>
    </div>
  );
}

export function ExpertOnly({ children }: { children: ReactNode }) {
  const { isExpert } = useViewMode();
  if (!isExpert) return null;
  return <>{children}</>;
}
