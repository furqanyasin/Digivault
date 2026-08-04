import Link from "next/link";
import { CheckCircle2, Circle, ArrowRight, Rocket } from "lucide-react";

export interface SetupStep {
  label: string;
  hint: string;
  done: boolean;
  href: string;
}

/** Onboarding progress, shown only while something is still missing.
 *
 *  A fresh team's dashboard is otherwise a wall of zeroes with no indication of
 *  what to do about it. Every step is derived from data the dashboard already
 *  loads, and the whole card disappears once the last one is ticked — a
 *  permanently complete checklist is just clutter.
 */
export function SetupChecklist({ steps }: { steps: SetupStep[] }) {
  const done = steps.filter((s) => s.done).length;
  if (done === steps.length) return null;

  const next = steps.find((s) => !s.done);

  return (
    <section className="rounded-xl border bg-card p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Rocket className="h-4 w-4 text-primary" aria-hidden />
          <h2 className="text-sm font-semibold">Finish setting up</h2>
          <span className="text-xs text-muted-foreground">
            {done} of {steps.length} done
          </span>
        </div>
        {next && (
          <Link
            href={next.href}
            className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            {next.label}
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
        )}
      </div>

      {/* Progress reads as a proportion, so a nearly-done team can see it. */}
      <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${Math.round((done / steps.length) * 100)}%` }}
        />
      </div>

      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {steps.map((s) => (
          <li key={s.label}>
            <Link
              href={s.href}
              className={`flex items-start gap-2 rounded-lg border p-2.5 transition-colors hover:border-foreground/20 ${
                s.done ? "opacity-60" : ""
              }`}
            >
              {s.done ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
              ) : (
                <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              )}
              <span className="min-w-0">
                <span className={`block text-xs font-medium ${s.done ? "line-through" : ""}`}>
                  {s.label}
                </span>
                <span className="block text-[11px] text-muted-foreground">{s.hint}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
