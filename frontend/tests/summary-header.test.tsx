import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SummaryHeader } from "@/components/review/summary-header";

import { estimate, flag, line } from "./fixtures";

const blocked = estimate([
  line("L001", { flags: [flag("warning", "HIGH_IMPACT_LINE")] }),
  line("L002", {
    rate_basis: "assumed",
    flags: [flag("blocker", "ASSUMED_PRODUCTION_RATE"), flag("warning", "HIGH_IMPACT_LINE")],
  }),
]);

const clear = estimate([
  line("L001", { flags: [flag("warning", "HIGH_IMPACT_LINE")] }),
  line("L002", { flags: [flag("blocker", "ASSUMED_PRODUCTION_RATE", { resolved: true })] }),
]);

function renderHeader(props: Partial<Parameters<typeof SummaryHeader>[0]> = {}) {
  const onApprove = vi.fn();
  const onExport = vi.fn();
  render(
    <SummaryHeader
      estimate={blocked}
      approvedAt={null}
      onApprove={onApprove}
      onExport={onExport}
      {...props}
    />,
  );
  return { onApprove, onExport };
}

describe("SummaryHeader", () => {
  it("shows the grand total, the standard-rate share and the flag counts from the backend", () => {
    renderHeader();

    expect(screen.getByTestId("grand-total")).toHaveTextContent("$3,449.84");
    expect(screen.getByTestId("standard-rate-pct")).toHaveTextContent("60.7%");
    expect(screen.getByTestId("blocker-count")).toHaveTextContent("1");
    expect(screen.getByTestId("warning-count")).toHaveTextContent("2");
    expect(screen.getByText(/39.3% assumed by the LLM/)).toBeInTheDocument();
  });

  it("keeps approval disabled while a blocker is unresolved", async () => {
    const { onApprove } = renderHeader();

    const approve = screen.getByRole("button", { name: "Approve estimate" });
    expect(approve).toBeDisabled();
    expect(screen.getByTestId("approve-status")).toHaveTextContent(
      "Not ready to approve: 1 unresolved blocker",
    );
    await userEvent.click(approve);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("enables approval once no blocker is unresolved", async () => {
    const { onApprove } = renderHeader({ estimate: clear });

    expect(screen.getByTestId("approve-status")).toHaveTextContent("Ready to approve");
    expect(screen.getByTestId("blocker-count")).toHaveTextContent("0");
    await userEvent.click(screen.getByRole("button", { name: "Approve estimate" }));
    expect(onApprove).toHaveBeenCalledOnce();
  });

  it("disables approval while a reprice is in flight", () => {
    renderHeader({ estimate: clear, busy: true });

    expect(screen.getByRole("button", { name: "Approve estimate" })).toBeDisabled();
  });

  it("shows the approved state and cannot be approved twice", () => {
    renderHeader({ estimate: clear, approvedAt: "2026-10-04T10:15:00.000Z" });

    expect(screen.getByTestId("approve-status")).toHaveTextContent("Approved by Estimator");
    expect(screen.getByRole("button", { name: "Approved" })).toBeDisabled();
  });

  it("can always be exported", async () => {
    const { onExport } = renderHeader();

    await userEvent.click(screen.getByRole("button", { name: /Export/ }));
    expect(onExport).toHaveBeenCalledOnce();
  });
});
