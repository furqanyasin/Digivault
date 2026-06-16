// Instant loading UI for every dashboard page. The sidebar (in layout.tsx)
// stays rendered; Next streams this skeleton in immediately while the page's
// server component resolves its data, so navigation feels instant.
export default function DashboardLoading() {
  return (
    <div className="p-8 space-y-6 animate-pulse">
      <div className="space-y-2">
        <div className="h-8 w-64 rounded-md bg-muted" />
        <div className="h-4 w-40 rounded bg-muted/70" />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-20 rounded-lg border bg-muted/40" />
        ))}
      </div>
      <div className="h-9 w-full max-w-xl rounded-md bg-muted/50" />
      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-12 rounded-lg border bg-muted/30" />
        ))}
      </div>
    </div>
  );
}
