import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Run history — AWS Instance Advisor",
  description:
    "Latency, retry counts, grounding results, and estimated monthly cost across completed advisor runs.",
};

export default function HistoryLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}