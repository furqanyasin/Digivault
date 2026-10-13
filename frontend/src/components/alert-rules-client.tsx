"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Bell, ChevronDown } from "lucide-react";
import type { AlertRule } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const CHANNEL_LABEL: Record<string, string> = {
  in_app: "In-app",
  email: "Email",
  clickup: "ClickUp",
  slack: "Slack",
};

// min_severity is the *floor* a change must clear, and these labels now use the
// same words the backend does. They used to rename the scale — "high" was shown
// as "Critical" — which was survivable only while `critical` was unreachable.
// It is a real minimum now, so a table showing two different rules both called
// "Critical" would be worse than no label at all.
const SEVERITY_LABEL: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

const SEVERITY_VARIANT: Record<string, "destructive" | "warning" | "secondary"> = {
  critical: "destructive",
  high: "destructive",
  medium: "warning",
  low: "secondary",
};

const ALL = "__all__";

/** Rules predate the `name` field, so fall back to something readable. */
function ruleLabel(rule: AlertRule): string {
  if (rule.name) return rule.name;
  const severity = SEVERITY_LABEL[rule.min_severity] ?? rule.min_severity;
  const channel = CHANNEL_LABEL[rule.channel] ?? rule.channel;
  return `${severity} changes → ${channel}`;
}

function FilterMenu({
  value,
  onChange,
  allLabel,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  allLabel: string;
  options: { value: string; label: string }[];
}) {
  const current = options.find((o) => o.value === value);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-48 items-center justify-between rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring">
        <span>{current?.label ?? allLabel}</span>
        <ChevronDown className="h-4 w-4 opacity-50" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-48">
        <DropdownMenuCheckboxItem checked={value === ALL} onCheckedChange={() => onChange(ALL)}>
          {allLabel}
        </DropdownMenuCheckboxItem>
        {options.map((o) => (
          <DropdownMenuCheckboxItem
            key={o.value}
            checked={value === o.value}
            onCheckedChange={() => onChange(o.value)}
          >
            {o.label}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AlertRulesClient({ rules }: { rules: AlertRule[] }) {
  const [channel, setChannel] = useState(ALL);
  const [severity, setSeverity] = useState(ALL);

  // Only offer channels that actually appear, so the filter can never select
  // its way into an empty table.
  const channelOptions = useMemo(() => {
    const seen = Array.from(new Set(rules.map((r) => r.channel)));
    return seen.map((c) => ({ value: c, label: CHANNEL_LABEL[c] ?? c }));
  }, [rules]);

  const severityOptions = useMemo(() => {
    const order: AlertRule["min_severity"][] = ["critical", "high", "medium", "low"];
    const seen = Array.from(new Set(rules.map((r) => r.min_severity)));
    return order
      .filter((s) => seen.includes(s))
      .map((s) => ({ value: s, label: SEVERITY_LABEL[s] ?? s }));
  }, [rules]);

  const visible = rules.filter(
    (r) =>
      (channel === ALL || r.channel === channel) &&
      (severity === ALL || r.min_severity === severity)
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <FilterMenu
          value={channel}
          onChange={setChannel}
          allLabel="All channels"
          options={channelOptions}
        />
        <FilterMenu
          value={severity}
          onChange={setSeverity}
          allLabel="All severities"
          options={severityOptions}
        />
      </div>

      <div className="rounded-lg border bg-card">
        {visible.length === 0 ? (
          <div className="p-10 text-center space-y-1">
            <p className="font-medium">
              {rules.length === 0 ? "No alert rules configured" : "No rules match these filters"}
            </p>
            <p className="text-sm text-muted-foreground">
              {rules.length === 0
                ? "Create a rule to receive notifications via in-app, email, or ClickUp."
                : "Try widening the channel or severity filter."}
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule</TableHead>
                <TableHead>Website</TableHead>
                <TableHead>Channel</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell className="font-medium">
                    <span className="flex items-center gap-2">
                      <Bell className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                      {ruleLabel(rule)}
                    </span>
                  </TableCell>
                  <TableCell className="text-sm">
                    {rule.website ? (
                      <Link
                        href={`/websites/${rule.website}`}
                        className="text-primary hover:underline"
                      >
                        {rule.website_domain || "View site"}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">All websites</span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {CHANNEL_LABEL[rule.channel] ?? rule.channel}
                  </TableCell>
                  <TableCell>
                    <Badge variant={SEVERITY_VARIANT[rule.min_severity] ?? "secondary"}>
                      {SEVERITY_LABEL[rule.min_severity] ?? rule.min_severity}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={rule.is_active ? "default" : "outline"}>
                      {rule.is_active ? "Active" : "Paused"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
