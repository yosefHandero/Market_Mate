"use client";

import { JournalDecision } from "@/lib/types";

const filters: Array<"all" | JournalDecision> = [
  "all",
  "took",
  "skipped",
  "watching",
];

type JournalFilterBarProps = {
  filter: "all" | JournalDecision;
  onChange: (value: "all" | JournalDecision) => void;
};

export function JournalFilterBar({ filter, onChange }: JournalFilterBarProps) {
  return (
    <div className="form-actions" style={{ marginBottom: 4, flexWrap: "wrap" }}>
      {filters.map((item) => (
        <button
          key={item}
          type="button"
          className={`button journal-filter ${filter === item ? "active" : ""}`}
          onClick={() => onChange(item)}
        >
          {item === "all" ? "All" : item}
        </button>
      ))}
    </div>
  );
}
