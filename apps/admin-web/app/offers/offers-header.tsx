import Link from "next/link";

import catalogueStyles from "../catalogue/catalogue.module.css";
import styles from "./offers.module.css";

/** The studio's title, with the way back to the catalogue. */
export function OffersHeader() {
  return (
    <header className={catalogueStyles.hero}>
      <p className={catalogueStyles.kicker}>Offer Studio · internal</p>
      <h1>Build offers too good to say no to</h1>
      <p className={catalogueStyles.lede}>
        Bundle features from the{" "}
        <Link href="/catalogue">Feature catalogue</Link>, raise the value
        equation, stack bonuses and a guarantee, write the positioning and price
        it, then export a one-pager.
      </p>
      <p className={styles.saved}>
        Prices here are internal. Sales X-Ray never shows a price.
      </p>
    </header>
  );
}
