import Link from "next/link";

export default function PrivacyPage() {
  return (
    <main className="privacy-page">
      <Link href="/">← Back to Along the Way</Link>
      <p className="eyebrow">Private beta privacy</p>
      <h1>What the beta uses and keeps</h1>
      <section>
        <h2>Journey locations</h2>
        <p>Origin and destination are sent to the journey backend and OneMap to calculate the requested route. Current location is used only after you tap the button. The app does not track location in the background and does not copy exact coordinates into analytics events.</p>
        <h2>Anonymous analytics</h2>
        <p>Your browser creates a random identifier stored locally. It is not based on a fingerprint, account, device information or personal details. We record workflow events, recommendation choice, broad feedback, parse method and timing so the beta can measure comprehension and usefulness.</p>
        <h2>What is not collected</h2>
        <p>No account, name, email, advertising identifier, continuous location trail or permanent exact-location history is required. Natural-language request text is used to interpret the current search but is not stored in the general analytics event table.</p>
        <h2>Retention and access</h2>
        <p>Anonymous beta events are retained for 90 days by default, then deleted during analytics-store initialization. Access to aggregate reporting requires a server-side admin token. Backups, if enabled by the beta operator, follow the same retention window.</p>
        <h2>External navigation</h2>
        <p>Navigation opens only after you choose it. The selected stop coordinates are then sent to the external map service in the navigation link and are subject to that service’s privacy terms.</p>
      </section>
    </main>
  );
}
