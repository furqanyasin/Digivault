import { Flame } from "lucide-react";

export default function HeatmapPage() {
  return (
    <div className="p-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Heatmap</h1>
        <p className="text-muted-foreground mt-1">
          Visualize where visitors click, scroll, and drop off across your sites.
        </p>
      </div>

      <div className="mt-10 flex flex-col items-center justify-center text-center rounded-xl border border-dashed py-20 px-6">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 shadow-sm">
          <Flame className="h-7 w-7 text-white" />
        </div>
        <p className="mt-5 text-xl font-semibold">Coming soon</p>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">
          Heatmaps are on the way. You&apos;ll soon be able to see click, scroll, and
          attention maps for every monitored website right here.
        </p>
        <span className="mt-5 inline-flex items-center rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          In development
        </span>
      </div>
    </div>
  );
}
