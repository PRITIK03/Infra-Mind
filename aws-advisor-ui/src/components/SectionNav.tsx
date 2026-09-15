"use client";

import { useEffect, useState } from "react";
import type { SystemDesignRecommendation, TechnicalNeeds } from "@/lib/types";

interface Section {
  id: string;
  label: string;
  visible: boolean;
}

interface Props {
  sdr: SystemDesignRecommendation;
  technicalNeeds?: TechnicalNeeds | null;
  hasTerraform?: boolean;
}

export function SectionNav({ sdr, technicalNeeds, hasTerraform = false }: Props) {
  const [sections, setSections] = useState<Section[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const all: Section[] = [
      { id: "cost", label: "Cost", visible: !!sdr.estimated_cost },
      { id: "compute", label: "Compute", visible: true },
      { id: "database", label: "Database", visible: true },
      { id: "cache", label: "Cache", visible: true },
      { id: "load-balancer", label: "Load Balancer", visible: true },
      { id: "terraform", label: "Terraform", visible: hasTerraform },
    ];
    setSections(all.filter((s) => s.visible));
  }, [hasTerraform, sdr]);

  useEffect(() => {
    if (!technicalNeeds) return;
    const ids = sections.map((s) => s.id);
    if (!ids.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .map((e) => e.target.id);
        if (visible.length > 0) {
          setActiveId(visible[0]);
        }
      },
      { root: null, rootMargin: "-40% 0px -40% 0px", threshold: 0 },
    );

    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [sections, technicalNeeds]);

  const handleClick = (id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  if (sections.length === 0) return null;

  return (
    <nav className="xl:sticky xl:top-24" aria-label="Section navigation">
      <div className="flex flex-col gap-1">
        {sections.map((s) => (
          <button
            key={s.id}
            onClick={() => handleClick(s.id)}
            className={[
              "font-mono text-xs text-left px-2 py-1",
              "transition-colors duration-150",
              activeId === s.id
                ? "text-amber"
                : "text-ink-dim hover:text-ink-muted hover:bg-white/[0.03]",
            ].join(" ")}
          >
            {s.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
