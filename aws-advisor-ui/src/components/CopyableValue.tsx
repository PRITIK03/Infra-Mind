"use client";

import { useState } from "react";

interface Props {
  value: string;
  children: React.ReactNode;
  className?: string;
}

export function CopyableValue({ value, children, className = "" }: Props) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <span
      role="button"
      tabIndex={0}
      aria-label={`Copy ${value}`}
      title="click to copy"
      onClick={() => void copy()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          void copy();
        }
      }}
      className={`cursor-copy transition-colors duration-150 hover:text-amber focus-visible:outline focus-visible:outline-1 focus-visible:outline-amber/60 focus-visible:outline-offset-2 ${className}`}
    >
      {copied ? "copied" : children}
    </span>
  );
}
