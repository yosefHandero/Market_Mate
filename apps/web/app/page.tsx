import { getLatestDecisions } from "@/lib/api";
import { DecisionPanel } from "@/components/decision-panel";

export default async function HomePage() {
  const decisionsResult = await getLatestDecisions();

  return (
    <main style={{ display: "grid", gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Market Mate Scanner</h1>
        <p className="muted" style={{ marginBottom: 18 }}>
          Automated analysis in the background. Fast decisions in one view.
        </p>
        <DecisionPanel
          rows={decisionsResult.data ?? []}
          errorMessage={decisionsResult.error}
        />
      </section>
    </main>
  );
}
