import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy and data sources · Along",
  description:
    "What Along does with a journey you plan, and where its places and routes come from.",
};

/* Written to match the code, and kept that way: an earlier version described
 * an analytics identifier and event log that the page never sent. */
export default function PrivacyPage() {
  return (
    <main className="privacy-page">
      <Link href="/">← Back to Along</Link>
      <h1>Privacy and data sources</h1>
      <section>
        <h2>Your journey</h2>
        <p>
          The start, destination and what you type are sent to Along’s server to find places and
          work out the route. They are used for that one request and are not saved. Your current
          location is read only when you tap Current, once, and never in the background.
        </p>
        <h2>What is not collected</h2>
        <p>
          There is no account, no analytics, no tracking identifier and no advertising. The only
          thing kept in your browser is your light or dark theme choice. The hosting platform keeps
          short-lived server logs, as any website’s host does; Along does not use them to build a
          history of trips.
        </p>
        <h2>Links to Google Maps</h2>
        <p>
          The directions buttons open Google Maps only when you tap them. The coordinates of that
          leg go to Google in the link, under Google’s own privacy terms.
        </p>
        <h2>Where the data comes from</h2>
        <p>
          Places, shop categories and opening hours come from{" "}
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noopener noreferrer"
          >
            © OpenStreetMap contributors
          </a>
          , under the Open Database Licence. Pharmacies are checked against the Health Sciences
          Authority’s register of retail pharmacies on{" "}
          <a href="https://data.gov.sg/" target="_blank" rel="noopener noreferrer">
            data.gov.sg
          </a>
          , under the Singapore Open Data Licence. The base map and place search come from{" "}
          <a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener noreferrer">
            OneMap
          </a>{" "}
          and the Singapore Land Authority, and the rail network from the Land Transport Authority’s
          station codes. Brand logos are loaded by your browser from{" "}
          <a href="https://commons.wikimedia.org/" target="_blank" rel="noopener noreferrer">
            Wikimedia Commons
          </a>
          , each under its own licence; where there is none, a symbol is drawn instead.
        </p>
        <h2 id="demo">Travel times in this demo</h2>
        <p>
          This public demo plans over Singapore’s real rail network with estimated times, so it
          works without any account or key. Lines, stations, interchanges and stop counts are real;
          the minutes are estimates, and buses are shown only as unnamed feeder legs. It is a
          portfolio project, not a timetable: check a live service before you travel.
        </p>
      </section>
    </main>
  );
}
