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

export type ViewMode = "discovery" | "analysis" | "expert";

type ViewModeContextValue = {
  mode: ViewMode;
  setMode: (mode: ViewMode) => void;
  isExpert: boolean;
};

const ViewModeContext = createContext<ViewModeContextValue>({
  mode: "discovery",
  setMode: () => undefined,
  isExpert: false,
});

const storageKey = "robin-experience-view-mode";
const storageEvent = "robin-experience-view-mode-change";
const viewModeOptions: ReadonlyArray<{
  hint: string;
  label: string;
  mode: ViewMode;
}> = [
  {
    mode: "discovery",
    label: t("view.essential"),
    hint: t("view.essentialHint"),
  },
  {
    mode: "analysis",
    label: "Vue Analyse",
    hint: "Affiche les comparaisons, les tendances et les éléments d’interprétation.",
  },
  {
    mode: "expert",
    label: t("view.expert"),
    hint: t("view.expertHint"),
  },
];

function subscribeMode(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(storageEvent, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(storageEvent, onStoreChange);
  };
}

function readMode(): ViewMode {
  const storedMode = window.localStorage.getItem(storageKey);
  if (storedMode === "analysis" || storedMode === "expert") return storedMode;
  return "discovery";
}

export function ViewModeProvider({ children }: { children: ReactNode }) {
  const mode = useSyncExternalStore<ViewMode>(
    subscribeMode,
    readMode,
    () => "discovery",
  );

  useEffect(() => {
    document.documentElement.dataset.robinHydrated = "true";
    if (window.localStorage.getItem(storageKey) === "essential") {
      window.localStorage.setItem(storageKey, "discovery");
    }
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
  const activeOption =
    viewModeOptions.find((option) => option.mode === mode) ?? viewModeOptions[0];

  return (
    <div
      className="view-switch"
      role="group"
      aria-label="Niveau de lecture"
      title={activeOption.hint}
    >
      {viewModeOptions.map((option) => (
        <button
          aria-label={`${option.label}. ${option.hint}`}
          aria-pressed={mode === option.mode}
          className={mode === option.mode ? "active" : ""}
          key={option.mode}
          onClick={() => setMode(option.mode)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ExpertOnly({ children }: { children: ReactNode }) {
  const { isExpert } = useViewMode();
  if (!isExpert) return null;
  return <>{children}</>;
}

export function AnalysisOnly({ children }: { children: ReactNode }) {
  const { mode } = useViewMode();
  if (mode === "discovery") return null;
  return <>{children}</>;
}
