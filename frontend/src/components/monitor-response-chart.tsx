"use client";

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import type { MonitorCheck } from "@/lib/api";

interface Props {
  checks: MonitorCheck[];
}

export function MonitorResponseChart({ checks }: Props) {
  const data = [...checks]
    .reverse()
    .filter((c) => c.response_time_ms !== null)
    .slice(-60)
    .map((c) => ({
      time: new Date(c.checked_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
      ms: c.response_time_ms,
      status: c.status,
    }));

  if (data.length < 2) {
    return (
      <p className="text-xs text-muted-foreground text-center py-8">
        Not enough data yet — run a few checks to see the response time trend.
      </p>
    );
  }

  const avg = Math.round(data.reduce((s, d) => s + (d.ms ?? 0), 0) / data.length);

  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="time" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
        <YAxis tick={{ fontSize: 10 }} unit="ms" />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 6 }}
          formatter={(v) => [`${v} ms`, "Response time"]}
        />
        <ReferenceLine y={avg} stroke="#94a3b8" strokeDasharray="4 2" label={{ value: `avg ${avg}ms`, fontSize: 10, fill: "#94a3b8" }} />
        <Line
          type="monotone"
          dataKey="ms"
          stroke="#6366f1"
          strokeWidth={2}
          dot={(props) => {
            const { cx, cy, payload } = props;
            const color = payload.status === "down" ? "#ef4444" : payload.status === "degraded" ? "#f59e0b" : "#22c55e";
            return <circle key={`dot-${payload.time}`} cx={cx} cy={cy} r={3} fill={color} stroke="none" />;
          }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
