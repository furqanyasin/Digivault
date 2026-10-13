"use client";

import { History, Puzzle, Layers, Globe, Rocket, Pencil, Mail, Users, FileText, ShoppingCart, HardDrive, Search, Shield } from "lucide-react";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { SiteEvent } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Props {
  events: SiteEvent[];
}

const EVENT_ICON: Record<string, React.ReactNode> = {
  plugin_updated: <Puzzle className="h-3.5 w-3.5" />,
  plugin_installed: <Puzzle className="h-3.5 w-3.5" />,
  plugin_removed: <Puzzle className="h-3.5 w-3.5" />,
  theme_changed: <Layers className="h-3.5 w-3.5" />,
  core_updated: <Globe className="h-3.5 w-3.5" />,
  deployment: <Rocket className="h-3.5 w-3.5" />,
  manual: <Pencil className="h-3.5 w-3.5" />,
  form_recipients_changed: <Mail className="h-3.5 w-3.5" />,
  wp_login: <Users className="h-3.5 w-3.5" />,
  wp_login_failed: <Shield className="h-3.5 w-3.5" />,
  wp_user_created: <Users className="h-3.5 w-3.5" />,
  wp_user_updated: <Users className="h-3.5 w-3.5" />,
  wp_user_role_changed: <Shield className="h-3.5 w-3.5" />,
  wp_user_deleted: <Users className="h-3.5 w-3.5" />,
  wp_password_reset: <Shield className="h-3.5 w-3.5" />,
  wp_plugin_activated: <Puzzle className="h-3.5 w-3.5" />,
  wp_plugin_deactivated: <Puzzle className="h-3.5 w-3.5" />,
  wp_plugin_updated: <Puzzle className="h-3.5 w-3.5" />,
  wp_plugin_deleted: <Puzzle className="h-3.5 w-3.5" />,
  wp_theme_switched: <Layers className="h-3.5 w-3.5" />,
  wp_theme_updated: <Layers className="h-3.5 w-3.5" />,
  wp_theme_deleted: <Layers className="h-3.5 w-3.5" />,
  wp_core_updated: <Globe className="h-3.5 w-3.5" />,
  wp_post_published: <FileText className="h-3.5 w-3.5" />,
  wp_post_updated: <FileText className="h-3.5 w-3.5" />,
  wp_post_trashed: <FileText className="h-3.5 w-3.5" />,
  wp_post_deleted: <FileText className="h-3.5 w-3.5" />,
  wp_order_status_changed: <ShoppingCart className="h-3.5 w-3.5" />,
  wp_product_updated: <ShoppingCart className="h-3.5 w-3.5" />,
  wp_order_refunded: <ShoppingCart className="h-3.5 w-3.5" />,
  wp_buffer_overflow: <Shield className="h-3.5 w-3.5" />,
  wp_file_changed: <HardDrive className="h-3.5 w-3.5" />,
  page_discovered: <Search className="h-3.5 w-3.5" />,
  seo_noindex_detected: <Search className="h-3.5 w-3.5" />,
  seo_robots_block: <Search className="h-3.5 w-3.5" />,
  seo_sitemap_missing: <Search className="h-3.5 w-3.5" />,
  seo_meta_changed: <Search className="h-3.5 w-3.5" />,
};

const SEVERITY_CLASS: Record<string, string> = {
  info: "bg-blue-50 text-blue-700 border-blue-200",
  warning: "bg-amber-50 text-amber-700 border-amber-200",
  critical: "bg-red-50 text-red-700 border-red-200",
};

const EVENT_LABEL: Record<string, string> = {
  plugin_updated: "Plugin Updated",
  plugin_installed: "Plugin Installed",
  plugin_removed: "Plugin Removed",
  theme_changed: "Theme Changed",
  core_updated: "Core Updated",
  deployment: "Deployment",
  manual: "Manual Entry",
  form_recipients_changed: "Form Recipients Changed",
  wp_login: "User Login",
  wp_login_failed: "Login Failed",
  wp_user_created: "User Created",
  wp_user_updated: "User Updated",
  wp_user_role_changed: "User Role Changed",
  wp_user_deleted: "User Deleted",
  wp_password_reset: "Password Reset",
  wp_plugin_activated: "Plugin Activated",
  wp_plugin_deactivated: "Plugin Deactivated",
  wp_plugin_updated: "Plugin Updated (WordPress)",
  wp_plugin_deleted: "Plugin Deleted",
  wp_theme_switched: "Theme Switched",
  wp_theme_updated: "Theme Updated",
  wp_theme_deleted: "Theme Deleted",
  wp_core_updated: "WordPress Core Updated",
  wp_post_published: "Post or Page Published",
  wp_post_updated: "Post or Page Updated",
  wp_post_trashed: "Post or Page Trashed",
  wp_post_deleted: "Post or Page Deleted",
  wp_order_status_changed: "Order Status Changed",
  wp_product_updated: "Product Updated",
  wp_order_refunded: "Order Refunded",
  wp_buffer_overflow: "Activity Buffer Overflow",
  wp_file_changed: "File Changed",
  page_discovered: "New Page Discovered",
  seo_noindex_detected: "SEO: Noindex Detected",
  seo_robots_block: "SEO: Robots Block",
  seo_sitemap_missing: "SEO: Sitemap Missing",
  seo_meta_changed: "SEO: Metadata Changed",
};

export function SiteEventsTab({ events }: Props) {
  if (events.length === 0) {
    return (
      <div className="py-16 flex flex-col items-center gap-3 text-center">
        <History className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No change log entries yet</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Site events such as plugin updates, theme changes, and deployments will appear here automatically.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{events.length} event{events.length !== 1 ? "s" : ""}</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Event</TableHead>
            <TableHead>Summary</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead className="whitespace-nowrap">Occurred</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.map((ev) => (
            <TableRow key={ev.id}>
              <TableCell>
                <div className="flex items-center gap-1.5 text-sm">
                  <span className="text-muted-foreground">{EVENT_ICON[ev.event_type] ?? <Pencil className="h-3.5 w-3.5" />}</span>
                  <span className="font-medium whitespace-nowrap">{EVENT_LABEL[ev.event_type] ?? ev.event_type}</span>
                </div>
              </TableCell>
              <TableCell className="max-w-xs">
                <p className="text-sm">{ev.summary}</p>
                {Object.keys(ev.details ?? {}).length > 0 && (
                  <p className="text-xs text-muted-foreground font-mono mt-0.5">
                    {Object.entries(ev.details).slice(0, 3).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                  </p>
                )}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {ev.actor || "—"}
              </TableCell>
              <TableCell>
                <span className={`inline-block px-2 py-0.5 rounded-full border text-xs font-medium capitalize ${SEVERITY_CLASS[ev.severity] ?? SEVERITY_CLASS.info}`}>
                  {ev.severity}
                </span>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                {fmtDateTime(ev.occurred_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
