import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { ChartCardHeader } from "./chart-card-header";

export interface ClientPortfolioRow {
  /** Null for sites with no client attached — they still have to go somewhere. */
  id: string | null;
  name: string;
  siteCount: number;
  needsWork: number;
}

const LIMIT = 5;

/** The clients behind the sites this member can actually see.
 *
 *  Members without manager rights never get the Renewal Center, so this card
 *  takes that slot rather than leaving a hole in the grid. Rows are derived
 *  from the website list, which the API already narrows to a member's
 *  assignments — so an assigned viewer sees their own accounts and site counts,
 *  not the whole agency's book.
 */
export function ClientPortfolio({
  rows,
  siteCount,
  canOpenClients,
}: {
  rows: ClientPortfolioRow[];
  siteCount: number;
  canOpenClients: boolean;
}) {
  const shown = rows.slice(0, LIMIT);
  const rest = rows.length - shown.length;

  return (
    <Card className="lg:col-span-2">
      <CardContent>
        <ChartCardHeader
          title="Your clients"
          subtitle="Accounts behind the sites you can see"
          value={rows.length}
          caption={`${siteCount} site${siteCount === 1 ? "" : "s"}`}
          href={canOpenClients ? "/clients" : undefined}
        />

        {rows.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No websites are assigned to you yet.
          </p>
        ) : (
          <ul className="divide-y">
            {shown.map((row) => {
              const body = (
                <>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {row.name}
                  </span>
                  {row.needsWork > 0 && (
                    <span className="shrink-0 text-xs font-semibold text-amber-600">
                      {row.needsWork} need{row.needsWork === 1 ? "s" : ""} work
                    </span>
                  )}
                  <span className="w-14 shrink-0 text-right text-xs text-muted-foreground">
                    {row.siteCount} site{row.siteCount === 1 ? "" : "s"}
                  </span>
                </>
              );
              return (
                <li key={row.id ?? "unassigned"}>
                  {canOpenClients && row.id ? (
                    <Link
                      href={`/clients/${row.id}`}
                      className="flex items-center gap-3 py-2.5 hover:underline"
                    >
                      {body}
                    </Link>
                  ) : (
                    <div className="flex items-center gap-3 py-2.5">{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {rest > 0 && (
          <p className="pt-2 text-xs text-muted-foreground">
            +{rest} more client{rest === 1 ? "" : "s"}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
