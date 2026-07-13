"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { Flame } from "lucide-react";

interface HeatmapEventPayload {
  page_path: string;
  page_title: string;
  event_type: "click" | "scroll" | "mousemove";
  x: number;
  y: number;
  viewport_width: number;
  viewport_height: number;
  metadata?: Record<string, unknown>;
}

interface HeatmapPoint {
  id: string;
  x: number;
  y: number;
  weight: number;
}

export function HeatmapTracker({ isManager = false }: { isManager?: boolean }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isAdminView, setIsAdminView] = useState(isManager);
  const [points, setPoints] = useState<HeatmapPoint[]>([]);
  const [showOverlay, setShowOverlay] = useState(false);
  const lastScrollRef = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(searchParams?.toString());
    setIsAdminView(params.get("heatmap") === "1" || isManager);
  }, [pathname, searchParams, isManager]);

  useEffect(() => {
    const send = async (payload: HeatmapEventPayload) => {
      try {
        await fetch("/api/heatmaps/events", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } catch {
        // best effort only
      }
    };

    const pagePath = `${pathname}${searchParams?.toString() ? `?${searchParams.toString()}` : ""}`;

    const handleClick = (event: MouseEvent) => {
      const rect = document.documentElement.getBoundingClientRect();
      void send({
        page_path: pagePath,
        page_title: document.title,
        event_type: "click",
        x: Number(((event.clientX - rect.left) / window.innerWidth) * 100),
        y: Number(((event.clientY - rect.top) / window.innerHeight) * 100),
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
      });
    };

    const handleScroll = () => {
      const current = Math.round((window.scrollY / Math.max(document.body.scrollHeight - window.innerHeight, 1)) * 100);
      if (Math.abs(current - lastScrollRef.current) < 5) return;
      lastScrollRef.current = current;
      void send({
        page_path: pagePath,
        page_title: document.title,
        event_type: "scroll",
        x: Number((window.scrollX / Math.max(document.documentElement.scrollWidth - window.innerWidth, 1)) * 100),
        y: Number(current),
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
      });
    };

    const handleMouseMove = (event: MouseEvent) => {
      if (Math.random() > 0.08) return;
      const rect = document.documentElement.getBoundingClientRect();
      void send({
        page_path: pagePath,
        page_title: document.title,
        event_type: "mousemove",
        x: Number(((event.clientX - rect.left) / window.innerWidth) * 100),
        y: Number(((event.clientY - rect.top) / window.innerHeight) * 100),
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
      });
    };

    const loadPoints = async () => {
      try {
        const res = await fetch(`/api/heatmaps/events?page_path=${encodeURIComponent(pagePath)}`);
        if (!res.ok) return;
        const payload = await res.json();
        const data: unknown[] = Array.isArray(payload?.data) ? payload.data : [];
        const next = data.reduce((acc: HeatmapPoint[], raw) => {
          const item = raw as { id: string; x?: number; y?: number; event_type?: string };
          const x = Number(item?.x ?? 0);
          const y = Number(item?.y ?? 0);
          if (item?.event_type === "click") {
            acc.push({ id: item.id, x, y, weight: 3 });
          } else if (item?.event_type === "scroll") {
            acc.push({ id: item.id, x, y, weight: 2 });
          } else if (item?.event_type === "mousemove") {
            acc.push({ id: item.id, x, y, weight: 1 });
          }
          return acc;
        }, [] as HeatmapPoint[]);
        setPoints(next);
      } catch {
        // ignore
      }
    };

    document.addEventListener("click", handleClick);
    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("mousemove", handleMouseMove, { passive: true });
    void loadPoints();

    return () => {
      document.removeEventListener("click", handleClick);
      window.removeEventListener("scroll", handleScroll);
      window.removeEventListener("mousemove", handleMouseMove);
    };
  }, [pathname, searchParams]);

  if (!isAdminView) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setShowOverlay((value) => !value)}
        className="fixed bottom-4 right-4 z-50 inline-flex items-center gap-2 rounded-full border bg-background/95 px-3 py-2 text-sm shadow-lg"
      >
        <Flame className="h-4 w-4 text-orange-500" />
        {showOverlay ? "Hide heatmap" : "Show heatmap"}
      </button>
      {showOverlay && (
        <div className="pointer-events-none fixed inset-0 z-40 bg-transparent">
          {points.map((point) => (
            <span
              key={point.id}
              className="absolute rounded-full bg-orange-500/40 blur-[1px]"
              style={{
                left: `${point.x}%`,
                top: `${point.y}%`,
                width: `${Math.max(10, point.weight * 10)}px`,
                height: `${Math.max(10, point.weight * 10)}px`,
                transform: "translate(-50%, -50%)",
              }}
            />
          ))}
        </div>
      )}
    </>
  );
}
