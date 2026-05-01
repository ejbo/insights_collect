"use client";
import { useEffect, useState } from "react";

/**
 * Controlled-feeling number input that lets the user clear the field
 * (returns `null` while empty) and clamps min/max on blur.
 *
 * Why this exists: a plain `<input type="number" value={0} />` re-renders to
 * "0" on every keystroke, so deleting digits feels like the field "sticks".
 */
export function NumberField({
  value,
  min,
  max,
  step,
  placeholder,
  className,
  onChange,
}: {
  value: number | null;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  className?: string;
  onChange: (n: number | null) => void;
}) {
  const [raw, setRaw] = useState(value === null || value === undefined ? "" : String(value));

  useEffect(() => {
    const next = value === null || value === undefined ? "" : String(value);
    setRaw((cur) => (Number(cur) === Number(next) && cur !== "" ? cur : next));
  }, [value]);

  return (
    <input
      type="text"
      inputMode="decimal"
      className={className}
      placeholder={placeholder}
      value={raw}
      onChange={(e) => {
        const v = e.target.value.trim();
        setRaw(v);
        if (v === "" || v === "-" || v === ".") {
          onChange(null);
          return;
        }
        const n = Number(v);
        if (Number.isNaN(n)) return;
        onChange(n);
      }}
      onBlur={() => {
        if (raw === "") {
          onChange(null);
          return;
        }
        let n = Number(raw);
        if (Number.isNaN(n)) {
          setRaw(value === null ? "" : String(value));
          return;
        }
        if (typeof min === "number") n = Math.max(min, n);
        if (typeof max === "number") n = Math.min(max, n);
        if (typeof step === "number" && step > 0) {
          n = Math.round(n / step) * step;
        }
        setRaw(String(n));
        onChange(n);
      }}
    />
  );
}
