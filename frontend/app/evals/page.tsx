import type { Metadata } from "next";

import { EvalsApp } from "@/components/evals/evals-app";

export const metadata: Metadata = {
  title: "Evals - Bid Draft Agent",
  description:
    "How the agent's LLM steps score against hand-checked expected answers, failures included.",
};

export default function EvalsPage() {
  return <EvalsApp />;
}
