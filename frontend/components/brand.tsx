import { cn } from "@/lib/utils";

/** The product mark: a ruled sheet with one line picked out. */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true">
        <rect width="24" height="24" rx="5" className="fill-brand" />
        <path
          d="M7 8h10M7 12h6M7 16h10"
          className="stroke-on-brand"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <span className="text-lg font-semibold tracking-tight text-ink">Bid Draft Agent</span>
    </span>
  );
}

/** Small uppercase monospace label above a section. */
export function Eyebrow({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <p className={cn("eyebrow text-brand", className)}>{children}</p>;
}

/** "01", "02", ... in the monospace face. */
export function StepNumber({ n, className }: { n: number; className?: string }) {
  return (
    <span className={cn("font-mono text-xs text-subtle tabular-nums", className)}>
      {String(n).padStart(2, "0")}
    </span>
  );
}

/** The page container: one width and gutter for every section. */
export function Container({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("mx-auto w-full max-w-6xl px-4 sm:px-6", className)}>{children}</div>;
}

export function SectionHeading({
  eyebrow,
  title,
  muted,
  children,
}: {
  eyebrow: string;
  title: string;
  /** Second line of the heading, in the muted tone. */
  muted?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="max-w-2xl">
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 className="mt-4 text-3xl leading-[1.1] font-medium sm:text-4xl">
        {title}
        {muted && <span className="block text-subtle">{muted}</span>}
      </h2>
      {children && <p className="mt-4 text-base leading-relaxed text-body">{children}</p>}
    </div>
  );
}
