"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatMoney, formatQuantity } from "@/lib/format";
import type { RateCard } from "@/lib/types";

function RateTable({ head, rows }: { head: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="max-h-[55vh] overflow-auto rounded-md border border-line">
      <table className="w-full min-w-[30rem] text-sm">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-line">
            {head.map((title, index) => (
              <th
                key={title}
                scope="col"
                className={`eyebrow px-3 py-2 text-subtle ${index === head.length - 1 ? "text-right" : "text-left"}`}
              >
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="align-top">
              {row.map((cell, index) => (
                <td
                  key={index}
                  className={
                    index === 0
                      ? "px-3 py-2 font-mono text-xs whitespace-nowrap text-ink"
                      : index === row.length - 1
                        ? "num px-3 py-2 whitespace-nowrap text-ink"
                        : "px-3 py-2"
                  }
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RateCardDialog({ rateCard }: { rateCard: RateCard }) {
  const { currency, markups } = rateCard;
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="lg">
          View rate card
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="text-xl font-medium">
            {rateCard.company_name} rate card
          </DialogTitle>
          <DialogDescription>
            {rateCard.trade}, amounts in {currency}. Every price and production rate in an estimate
            comes from here.
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="production" className="min-w-0">
          <TabsList className="max-w-full overflow-x-auto">
            <TabsTrigger value="production">
              Production rates ({rateCard.production_rates.length})
            </TabsTrigger>
            <TabsTrigger value="labor">Labor ({rateCard.labor_rates.length})</TabsTrigger>
            <TabsTrigger value="materials">Materials ({rateCard.materials.length})</TabsTrigger>
            <TabsTrigger value="equipment">Equipment ({rateCard.equipment.length})</TabsTrigger>
            <TabsTrigger value="markups">Markups</TabsTrigger>
          </TabsList>
          <TabsContent value="production" className="space-y-2">
            {rateCard.production_rates_note && (
              <p className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">
                {rateCard.production_rates_note}
              </p>
            )}
            <RateTable
              head={["Code", "Work, per unit", "Components per unit", "Unit"]}
              rows={rateCard.production_rates.map((rate) => [
                rate.code,
                rate.description,
                <ul key={rate.code} className="space-y-0.5 text-xs text-body">
                  {rate.components.map((component) => (
                    <li key={component.rate_card_code}>
                      {formatQuantity(component.quantity_per_unit)} ×{" "}
                      <span className="font-mono">{component.rate_card_code}</span>
                    </li>
                  ))}
                </ul>,
                rate.unit,
              ])}
            />
          </TabsContent>
          <TabsContent value="labor">
            <RateTable
              head={["Code", "Role", "Per hour"]}
              rows={rateCard.labor_rates.map((rate) => [
                rate.code,
                rate.role,
                formatMoney(rate.hourly_rate, currency),
              ])}
            />
          </TabsContent>
          <TabsContent value="materials">
            <RateTable
              head={["Code", "Material", "Unit", "Unit cost"]}
              rows={rateCard.materials.map((material) => [
                material.code,
                material.name,
                material.unit,
                formatMoney(material.unit_cost, currency),
              ])}
            />
          </TabsContent>
          <TabsContent value="equipment">
            <RateTable
              head={["Code", "Equipment", "Per", "Rate"]}
              rows={rateCard.equipment.map((item) => [
                item.code,
                item.name,
                item.unit,
                formatMoney(item.rate, currency),
              ])}
            />
          </TabsContent>
          <TabsContent value="markups">
            <RateTable
              head={["Markup", "Applies to", "Percent"]}
              rows={[
                ["Material markup", "Direct material", `${markups.material_markup_pct}%`],
                [
                  "Sales tax",
                  "Material with its markup",
                  `${markups.sales_tax_pct_on_materials}%`,
                ],
                ["Overhead", "Subtotal", `${markups.overhead_pct}%`],
                ["Profit", "Subtotal plus overhead", `${markups.profit_pct}%`],
              ]}
            />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
