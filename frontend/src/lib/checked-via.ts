/**
 * Who produced a monitor status when a firewall blocks our own check. Each is
 * evidence our monitoring IP never fetches, so a host blocking that IP cannot
 * stop it (apps/monitors/evidence.py, apps/monitors/second_opinion.py).
 */
const VIA: Record<string, { short: string; title: string; detail: string }> = {
  site: {
    short: "Site heartbeat",
    title: "Checked by the site itself",
    detail:
      "The site's firewall blocks our own checks. WordPress on the site reports in every 5 minutes " +
      "and loads its own homepage, so its heartbeat stands in for our check. If the site's server " +
      "answers its own request with an error, that is reported as down and alerts as usual.",
  },
  visitors: {
    short: "Real visitors",
    title: "Confirmed by real visitors",
    detail:
      "The site's firewall blocks our own checks. A real visitor's browser loaded the site in the " +
      "last 10 minutes, so their traffic stands in for our check. When visitors go quiet, Google " +
      "checks the site instead.",
  },
  google: {
    short: "Google",
    title: "Checked by Google",
    detail:
      "The site's firewall blocks our own checks, so Google loads it for us about every 30 minutes. " +
      "A failure Google sees is reported as down and alerts as usual.",
  },
};

export function checkedVia(via: string | null | undefined) {
  return (via && VIA[via]) || null;
}
