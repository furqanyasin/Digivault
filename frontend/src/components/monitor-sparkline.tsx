const STATUS_COLOR: Record<string, string> = {
  up: "#10b981",
  degraded: "#f59e0b",
  down: "#ef4444",
  // Not an outage — a WAF answered instead of the site, so this slot is an
  // observation we never got. Slate, like pending, rather than a warning colour.
  blocked: "#64748b",
  pending: "#94a3b8",
};

interface Props {
  statuses: string[];
  width?: number;
  height?: number;
}

export function MonitorSparkline({ statuses, width = 80, height = 20 }: Props) {
  if (!statuses || statuses.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  const barW = Math.max(2, Math.floor((width - statuses.length) / statuses.length));
  const gap = 1;
  const totalW = statuses.length * (barW + gap) - gap;

  return (
    <svg
      width={totalW}
      height={height}
      viewBox={`0 0 ${totalW} ${height}`}
      aria-label="Response history sparkline"
    >
      {statuses.map((s, i) => (
        <rect
          key={i}
          x={i * (barW + gap)}
          y={0}
          width={barW}
          height={height}
          rx={1}
          fill={STATUS_COLOR[s] ?? "#94a3b8"}
          opacity={0.85}
        />
      ))}
    </svg>
  );
}
