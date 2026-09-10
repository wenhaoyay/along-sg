import Link from "next/link";

export default function PrivacyPage() {
  return (
    <main className="privacy-page">
      <Link href="/">← Back to Along the Way</Link>
      <p className="eyebrow">Private beta privacy</p>
      <h1>What the beta uses and keeps</h1>
      <section>
        <h2>Journey locations</h2>
        <p>
          Origin and destination are sent to the journey backend and OneMap to calculate the
          requested route. Current location is used only after you tap the button. The app does not
          track location in the background and does not copy exact coordinates into analytics
          events.
        </p>
        <h2>Anonymous analytics</h2>
        <p>
          Your browser creates a random identifier stored locally. It is not based on a fingerprint,
          account, device information or personal details. We record workflow events, recommendation
          choice, broad feedback, parse method and timing so the beta can measure comprehension and
          usefulness.
        </p>
        <h2>What is not collected</h2>
        <p>
          No account, name, email, advertising identifier, continuous location trail or permanent
          exact-location history is required. Natural-language request text is used to interpret the
          current search but is not stored in the general analytics event table.
        </p>
        <h2>Retention and access</h2>
        <p>
          Anonymous beta events are retained for 90 days by default, then deleted during
          analytics-store initialization. Access to aggregate reporting requires a server-side admin
          token. Backups, if enabled by the beta operator, follow the same retention window.
        </p>
        <h2>Where the data comes from</h2>
        <p>
          Places, opening hours and shop categories come from{" "}
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noopener noreferrer"
          >
            OpenStreetMap
          </a>{" "}
          contributors, under the Open Database Licence. Routing and the base map come from{" "}
          <a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener noreferrer">
            OneMap
          </a>{" "}
          and the Singapore Land Authority. Bus arrival times, stops and timetables come from{" "}
          <a href="https://datamall.lta.gov.sg/" target="_blank" rel="noopener noreferrer">
            LTA DataMall
          </a>{" "}
          under the Singapore Open Data Licence. Brand-logo metadata comes from{" "}
          <a href="https://www.wikidata.org/" target="_blank" rel="noopener noreferrer">
            Wikidata
          </a>
          , and available logo files are loaded directly by your browser from{" "}
          <a href="https://commons.wikimedia.org/" target="_blank" rel="noopener noreferrer">
            Wikimedia Commons
          </a>
          . AlongSG does not locally host those logo image files, so displaying one causes the
          browser to contact Wikimedia in the normal way for an external image request. Each Commons
          file has its own licensing and attribution terms. Where no usable logo is available, or a
          logo fails to load, the app draws a symbol for what the place sells instead.
        </p>
        <h2>External navigation</h2>
        <p>
          Navigation opens only after you choose it. The selected stop coordinates are then sent to
          the external map service in the navigation link and are subject to that service’s privacy
          terms.
        </p>
      </section>
    </main>
  );
}
