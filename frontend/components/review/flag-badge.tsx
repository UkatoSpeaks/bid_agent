import { CheckIcon, InfoIcon, OctagonAlertIcon, TriangleAlertIcon } from "lucide-react";

import { flagLabel } from "@/lib/format";
import type { Flag, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const TONE: Record<Severity, string> = {
  blocker: "bg-blocker-soft text-blocker",
  warning: "bg-warning-soft text-warning",
  info: "bg-info-soft text-info",
};

const ICON = { blocker: OctagonAlertIcon, warning: TriangleAlertIcon, info: InfoIcon };

export const SEVERITY_LABEL: Record<Severity, string> = {
  blocker: "Blocker",
  warning: "Warning",
  info: "Info",
};

export function SeverityIcon({ severity, className }: { severity: Severity; className?: string }) {
  const Icon = ICON[severity];
  return <Icon className={cn("size-3.5 shrink-0", className)} aria-hidden="true" />;
}

/** A pill in a status tone. Always carries an icon and text, never colour alone. */
export function Pill({
  tone,
  children,
  className,
}: {
  tone: Severity | "ok" | "brand" | "neutral";
  children: React.ReactNode;
  className?: string;
}) {
  const tones = {
    ...TONE,
    ok: "bg-ok-soft text-ok",
    brand: "bg-brand-soft text-brand",
    neutral: "border border-line bg-page text-body",
  };
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-sm px-1.5 text-[0.6875rem] font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function FlagBadge({ flag }: { flag: Flag }) {
  if (flag.resolved) {
    return (
      <Pill tone="neutral" className="text-subtle">
        <CheckIcon className="size-3" aria-hidden="true" />
        <span className="sr-only">Resolved: </span>
        {flagLabel(flag.code)}
      </Pill>
    );
  }
  return (
    <Pill tone={flag.severity}>
      <SeverityIcon severity={flag.severity} className="size-3" />
      <span className="sr-only">{SEVERITY_LABEL[flag.severity]}: </span>
      {flagLabel(flag.code)}
    </Pill>
  );
}
