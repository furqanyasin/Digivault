import {
  Activity, BarChart3, Bell, FileCode2, FileText, Flame, Gauge, Globe2, KeyRound,
  LockKeyhole, MousePointerClick, Puzzle, Radio, Users, type LucideIcon,
} from "lucide-react";
import type { IconKey } from "@/lib/marketing/content";

export const FEATURE_ICONS: Record<IconKey, LucideIcon> = {
  uptime: Activity,
  ssl: LockKeyhole,
  scripts: FileCode2,
  vault: KeyRound,
  status: Radio,
  performance: Gauge,
  heatmap: Flame,
  reports: FileText,
  wordpress: Globe2,
  alerts: Bell,
  extension: Puzzle,
  team: Users,
};

export { BarChart3, MousePointerClick };

export function FeatureIcon({ icon, className = "h-6 w-6" }: { icon: IconKey; className?: string }) {
  const Icon = FEATURE_ICONS[icon];
  return <Icon className={className} aria-hidden />;
}
