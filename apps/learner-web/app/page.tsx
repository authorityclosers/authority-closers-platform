import { ArrowUpRight, CirclePlay } from "lucide-react";
import Link from "next/link";

import { BrandMark } from "@ac/ui";

const sequence = ["Watch", "Reflect", "Implement", "Review", "Improve"];

export default function HomePage() {
  return (
    <main>
      <nav aria-label="Primary navigation" className="nav-shell">
        <a className="brand" href="#top" aria-label="Authority Closers home">
          <BrandMark className="brand-mark" />
          <span>Authority Closers</span>
        </a>
        <div className="nav-actions">
          <Link href="/login">Sign in</Link>
          <Link className="nav-cta" href="/programs/free-course">
            Explore the course <ArrowUpRight size={16} />
          </Link>
        </div>
      </nav>

      <section id="top" className="hero">
        <div className="eyebrow">
          <span /> The practice floor for high-stakes conversations
        </div>
        <h1>
          Stop collecting advice.
          <br />
          <em>Build the instinct.</em>
        </h1>
        <p className="hero-copy">
          A focused learning system where every lesson becomes evidence, every
          attempt becomes feedback, and every next step is unmistakably clear.
        </p>
        <div className="hero-actions">
          <Link className="primary-action" href="/programs/free-course">
            Begin the free course <ArrowUpRight size={19} />
          </Link>
          <a className="text-action" href="#method">
            <CirclePlay size={19} /> See how practice works
          </a>
        </div>

        <div id="method" className="method-card">
          <div>
            <span className="method-label">Your learning loop</span>
            <p>
              One disciplined sequence. No decorative progress. Only work you
              can explain.
            </p>
          </div>
          <ol>
            {sequence.map((step, index) => (
              <li key={step}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      </section>
    </main>
  );
}
