"use client";

import {
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export type AccessibleTab<TabId extends string = string> = {
  id: TabId;
  label: ReactNode;
  panel: ReactNode;
  disabled?: boolean;
};

export type TabNavigationKey =
  | "ArrowLeft"
  | "ArrowRight"
  | "ArrowUp"
  | "ArrowDown"
  | "Home"
  | "End";

function enabledIndexes<TabId extends string>(
  tabs: readonly AccessibleTab<TabId>[],
) {
  return tabs
    .map((tab, index) => (tab.disabled ? null : index))
    .filter((index): index is number => index != null);
}

export function nextEnabledTabIndex<TabId extends string>(
  tabs: readonly AccessibleTab<TabId>[],
  currentIndex: number,
  key: TabNavigationKey,
  orientation: "horizontal" | "vertical" = "horizontal",
) {
  const enabled = enabledIndexes(tabs);
  if (!enabled.length) return -1;
  if (key === "Home") return enabled[0];
  if (key === "End") return enabled[enabled.length - 1];

  const backwards =
    key === "ArrowLeft" ||
    key === "ArrowUp";
  const isRelevant =
    orientation === "horizontal"
      ? key === "ArrowLeft" || key === "ArrowRight"
      : key === "ArrowUp" || key === "ArrowDown";
  if (!isRelevant) return currentIndex;

  const currentPosition = enabled.indexOf(currentIndex);
  const startingPosition = currentPosition < 0 ? 0 : currentPosition;
  const offset = backwards ? -1 : 1;
  return enabled[
    (startingPosition + offset + enabled.length) % enabled.length
  ];
}

function safeId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/gu, "-");
}

export function AccessibleTabs<TabId extends string>({
  activationMode = "automatic",
  ariaLabel,
  idBase,
  onChange,
  orientation = "horizontal",
  tabs,
  value,
}: {
  activationMode?: "automatic" | "manual";
  ariaLabel: string;
  idBase?: string;
  onChange: (tabId: TabId) => void;
  orientation?: "horizontal" | "vertical";
  tabs: readonly AccessibleTab<TabId>[];
  value: TabId;
}) {
  const generatedId = useId();
  const resolvedIdBase = safeId(idBase ?? `tabs-${generatedId}`);
  const tabListRef = useRef<HTMLDivElement>(null);
  const firstEnabled = tabs.find((tab) => !tab.disabled);
  const selected =
    tabs.find((tab) => tab.id === value && !tab.disabled) ??
    firstEnabled;
  const selectedId = selected?.id;

  const focusTab = (index: number, activate: boolean) => {
    const tab = tabs[index];
    if (!tab || tab.disabled) return;
    const target =
      tabListRef.current?.querySelector<HTMLButtonElement>(
        `[data-tab-index="${index}"]`,
      );
    target?.focus();
    if (activate) onChange(tab.id);
  };

  const onTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    const key = event.key as TabNavigationKey;
    if (
      ![
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
        "Home",
        "End",
      ].includes(key)
    ) {
      if (
        activationMode === "manual" &&
        (event.key === "Enter" || event.key === " ")
      ) {
        event.preventDefault();
        const tab = tabs[index];
        if (tab && !tab.disabled) onChange(tab.id);
      }
      return;
    }

    const nextIndex = nextEnabledTabIndex(
      tabs,
      index,
      key,
      orientation,
    );
    if (nextIndex === index || nextIndex < 0) return;
    event.preventDefault();
    focusTab(nextIndex, activationMode === "automatic");
  };

  if (!selected) return null;

  return (
    <div className="accessible-tabs">
      <div
        aria-label={ariaLabel}
        aria-orientation={orientation}
        className="tabs"
        ref={tabListRef}
        role="tablist"
      >
        {tabs.map((tab, index) => {
          const tabId = `${resolvedIdBase}-tab-${safeId(tab.id)}`;
          const panelId = `${resolvedIdBase}-panel-${safeId(tab.id)}`;
          const isSelected = tab.id === selectedId;
          return (
            <button
              aria-controls={panelId}
              aria-selected={isSelected}
              className={isSelected ? "active" : ""}
              data-tab-index={index}
              disabled={tab.disabled}
              id={tabId}
              key={tab.id}
              onClick={() => onChange(tab.id)}
              onKeyDown={(event) => onTabKeyDown(event, index)}
              role="tab"
              tabIndex={isSelected ? 0 : -1}
              type="button"
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {tabs.map((tab) => {
        const tabId = `${resolvedIdBase}-tab-${safeId(tab.id)}`;
        const panelId = `${resolvedIdBase}-panel-${safeId(tab.id)}`;
        const isSelected = tab.id === selectedId;
        return (
          <div
            aria-labelledby={tabId}
            className="tab-panel"
            hidden={!isSelected}
            id={panelId}
            key={tab.id}
            role="tabpanel"
            tabIndex={0}
          >
            {tab.panel}
          </div>
        );
      })}
    </div>
  );
}
