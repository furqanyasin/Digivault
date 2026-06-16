import { CheckCircle2, XCircle, Radio } from "lucide-react";
import type { Script } from "@/lib/api";

// Categories that represent "tracking codes" the agency cares about verifying.
const TRACKING_CATEGORIES = new Set([
  "analytics",
  "advertising",
  "tag_management",
  "session_recording",
  "call_tracking",
]);

const CATEGORY_LABEL: Record<string, string> = {
  analytics: "Analytics",
  advertising: "Advertising",
  tag_management: "Tag Management",
  session_recording: "Session Recording",
  call_tracking: "Call & Conversion Tracking",
};

export function TrackingTab({ scripts }: { scripts: Script[] }) {
  const tracking = scripts.filter((s) => TRACKING_CATEGORIES.has(s.category));

  if (tracking.length === 0) {
    return (
      <div className="py-16 flex flex-col items-center gap-3 text-center">
        <Radio className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No tracking codes detected yet</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Analytics, advertising, and tag-manager scripts appear here once the snippet
          sees them load in a real browser. A code shown as <span className="text-emerald-600">Active</span> is
          live; one that drops to <span className="text-red-600">Inactive</span> is no longer loading.
        </p>
      </div>
    );
  }

  const firing = tracking.filter((s) => s.is_active);
  const stopped = tracking.filter((s) => !s.is_active);

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {firing.length} tracking code{firing.length !== 1 ? "s" : ""} active
        {stopped.length > 0 && `, ${stopped.length} inactive`}
      </p>
      <div className="border rounded-lg divide-y">
        {[...firing, ...stopped].map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                {s.is_active
                  ? <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                  : <XCircle className="h-4 w-4 text-red-500 shrink-0" />}
                <span className="font-medium text-sm truncate">
                  {s.provider && s.provider !== "unknown" ? s.provider : "Unknown tracker"}
                </span>
                <span className="text-xs text-muted-foreground border rounded px-1.5 py-0.5 shrink-0">
                  {CATEGORY_LABEL[s.category] ?? s.category}
                </span>
              </div>
              <div className="font-mono text-xs text-muted-foreground truncate mt-0.5" title={s.src_url}>
                {s.src_url}
              </div>
            </div>
            <span className={`text-xs font-medium shrink-0 ${s.is_active ? "text-emerald-600" : "text-red-600"}`}>
              {s.is_active ? "Active" : "Inactive"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
