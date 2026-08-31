import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website } from "@/lib/api";
import { HeatmapClient } from "@/components/heatmap-client";

export default async function HeatmapPage() {
  const token = await getAccessToken();
  const websitesResult = await api
    .getAll<Website>("/api/v1/websites/", token ?? "")
    .catch(() => [] as Website[]);
  const websites = websitesResult.filter((w) => w.domain);

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Heatmap</h1>
        <p className="text-muted-foreground mt-1">
          Visualize where visitors click and move across your sites.
        </p>
      </div>

      {websites.length === 0 ? (
        <div className="mt-10 flex flex-col items-center justify-center text-center rounded-xl border border-dashed py-20 px-6">
          <p className="text-xl font-semibold">No monitored sites yet</p>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">
            Add a website to start receiving heatmap data from the tracking snippet.
          </p>
        </div>
      ) : (
        <HeatmapClient websites={websites} />
      )}
    </div>
  );
}
