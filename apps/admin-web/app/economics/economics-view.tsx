/**
 * Admin → Economics (owner, 23 Oct 2026): what each plan earns after GST and the payment
 * fee, what its minutes cost on each analysis route, margins at 25%, 50% and 100% use, how
 * many plans cover the fixed costs, top-ups and the free trial. Read only; list-price
 * estimates for Admin, never shown to a customer.
 */
import { Badge, Card, Kpi, Panel, Table, Tiles, Why } from "../ui/kit";
import {
  WARNING_WORDS,
  marginTone,
  rate,
  routeName,
  rupees,
  share,
  type Economics,
  type Offer,
} from "./economics-data";
import styles from "./economics.module.css";
import { FixedCostsEditor } from "./fixed-costs-editor";

const ENVIRONMENT_WORDS: Record<string, string> = {
  production: "production",
  staging: "staging",
  development: "dev",
};

function Margin({
  value,
  ratio,
  target,
}: {
  value: number;
  ratio: number | null;
  target: number;
}) {
  return (
    <span className={styles.margin} data-tone={marginTone(ratio, target)}>
      {rupees(value)} <small>{share(ratio)}</small>
    </span>
  );
}

function NetLine({ offer }: { offer: Offer }) {
  return (
    <small className={styles.muted}>
      {rupees(offer.gross)} charged ·{" "}
      {offer.channel === "play" ? "Play" : "Razorpay"} {rupees(offer.fee)}
    </small>
  );
}

function OfferTable({ economics }: { economics: Economics }) {
  const base = economics.breakEvenRoute;
  const others = economics.routes.filter((route) => route.id !== base);
  const target = economics.targetMargin;
  const cells = (offer: Offer) => offer.margins[base] ?? [];
  const full = (offer: Offer, route: string) =>
    (offer.margins[route] ?? []).find((item) => item.use === 1);
  return (
    <Table
      label="Margin a month per plan"
      cards={economics.offers.map((offer) => (
        <Card key={offer.id}>
          <strong>{offer.label}</strong>
          <span>
            {rupees(offer.net)} net a {offer.unit} · {offer.minutes} min
          </span>
          <span>
            {cells(offer).map((item) => (
              <span key={item.use} className={styles.cardCell}>
                {Math.round(item.use * 100)}%{" "}
                <Margin
                  value={item.margin}
                  ratio={item.share}
                  target={target}
                />
              </span>
            ))}
          </span>
          <NetLine offer={offer} />
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Plan</th>
          <th scope="col" data-num="">
            Net a month
          </th>
          <th scope="col" data-num="">
            25% use
          </th>
          <th scope="col" data-num="">
            50% use
          </th>
          <th scope="col" data-num="">
            100% use
          </th>
          {others.map((route) => (
            <th key={route.id} scope="col" data-num="">
              100% · {routeName(route.id)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {economics.offers.map((offer) => (
          <tr key={offer.id}>
            <th scope="row" className={styles.planCell}>
              <span className={styles.name}>
                <strong>{offer.label}</strong>
                <NetLine offer={offer} />
              </span>
            </th>
            <td data-num="">
              {rupees(offer.net)}
              <small className={styles.muted}> · {offer.minutes} min</small>
            </td>
            {cells(offer).map((item) => (
              <td key={item.use} data-num="">
                <Margin
                  value={item.margin}
                  ratio={item.share}
                  target={target}
                />
              </td>
            ))}
            {others.map((route) => {
              const item = full(offer, route.id);
              return (
                <td key={route.id} data-num="">
                  {item ? (
                    <Margin
                      value={item.margin}
                      ratio={item.share}
                      target={target}
                    />
                  ) : (
                    "–"
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function RouteTable({ economics }: { economics: Economics }) {
  return (
    <Table
      label="Cost per minute by analysis route"
      cards={economics.routes.map((route) => (
        <Card key={route.id}>
          <strong>{route.label}</strong>
          <span>
            {rate(route.perPlanMinute)} a plan minute ·{" "}
            {rate(route.perAudioMinute)} an audio minute
          </span>
          <small className={styles.muted}>
            <code>{route.id}</code> · {route.source}
          </small>
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Route</th>
          <th scope="col">Basis</th>
          <th scope="col" data-num="">
            ₹ an audio minute
          </th>
          <th scope="col" data-num="">
            ₹ a plan minute
          </th>
        </tr>
      </thead>
      <tbody>
        {economics.routes.map((route) => (
          <tr
            key={route.id}
            data-current={
              route.id === economics.breakEvenRoute ? "" : undefined
            }
          >
            <th scope="row">
              <span className={styles.name}>
                <strong>{route.label}</strong>
                <small>
                  <code>{route.id}</code>
                  {route.id === economics.breakEvenRoute
                    ? " · used for break-even"
                    : ""}
                </small>
              </span>
            </th>
            <td>
              <Badge tone={route.source === "measured" ? "good" : "info"}>
                {route.source === "measured" ? "Measured" : "Projection"}
              </Badge>
            </td>
            <td data-num="">{rate(route.perAudioMinute)}</td>
            <td data-num="">{rate(route.perPlanMinute)}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function BreakEvenTable({ economics }: { economics: Economics }) {
  const plans = (value: number | null) =>
    value === null ? "never" : `${value}`;
  return (
    <Table
      label="Plans needed to cover the fixed costs"
      cards={economics.offers.map((offer) => (
        <Card key={offer.id}>
          <strong>{offer.label}</strong>
          {["0.5", "1"].map((use) => {
            const row = offer.breakEven[use] ?? offer.breakEven[`${use}.0`];
            return row ? (
              <span key={use}>
                {use === "0.5" ? "50%" : "100%"} use: {plans(row.running)} for
                running costs, {plans(row.total)} with the agents
              </span>
            ) : null;
          })}
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Plan</th>
          <th scope="col" data-num="">
            Contribution at 50%
          </th>
          <th scope="col" data-num="">
            Running, 50%
          </th>
          <th scope="col" data-num="">
            With agents, 50%
          </th>
          <th scope="col" data-num="">
            Running, 100%
          </th>
          <th scope="col" data-num="">
            With agents, 100%
          </th>
        </tr>
      </thead>
      <tbody>
        {economics.offers.map((offer) => {
          const half = offer.breakEven["0.5"];
          const whole = offer.breakEven["1.0"] ?? offer.breakEven["1"];
          return (
            <tr key={offer.id}>
              <th scope="row">{offer.label}</th>
              <td data-num="">{rupees(half?.contribution ?? null)}</td>
              <td data-num="">{plans(half?.running ?? null)}</td>
              <td data-num="">{plans(half?.total ?? null)}</td>
              <td data-num="">{plans(whole?.running ?? null)}</td>
              <td data-num="">{plans(whole?.total ?? null)}</td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function FixedList({ economics }: { economics: Economics }) {
  return (
    <ul className={styles.fixed}>
      {economics.fixed.items.map((item) => (
        <li key={item.key}>
          <span className={styles.name}>
            <strong>{item.label}</strong>
            <small>
              {item.kind === "building" ? "Building" : "Running"} ·{" "}
              {item.source === "measured"
                ? "measured"
                : item.source === "invoice"
                  ? "from the invoice"
                  : "estimate"}
            </small>
          </span>
          <b data-source={item.source}>{rupees(item.rupees)}</b>
        </li>
      ))}
      <li className={styles.total}>
        <strong>Running</strong>
        <b>{rupees(economics.fixed.running)}</b>
      </li>
      <li className={styles.total}>
        <strong>With the agents</strong>
        <b>{rupees(economics.fixed.total)}</b>
      </li>
    </ul>
  );
}

export function EconomicsView({ economics }: { economics: Economics }) {
  const where =
    ENVIRONMENT_WORDS[economics.environment] ?? economics.environment;
  const base = economics.routes.find(
    (route) => route.id === economics.breakEvenRoute,
  );
  const find = (id: string) =>
    economics.offers.find((offer) => offer.id === id);
  const personal = find("personal.monthly.web");
  const seat = find("organisation.monthly.web");
  const whole = (offer: Offer | undefined) =>
    offer?.breakEven["1.0"] ?? offer?.breakEven["1"];
  const uncharged = economics.measured.uncharged;
  const offerLabel = (id: string) => find(id)?.label ?? id;
  return (
    <>
      {economics.warnings.length ? (
        <div className={styles.warnings} role="status">
          {economics.warnings.map((item) => (
            <p key={`${item.offer}-${item.route}-${item.kind}`}>
              {offerLabel(item.offer)} on {routeName(item.route)}{" "}
              {WARNING_WORDS[item.kind] ?? item.kind}.
            </p>
          ))}
        </div>
      ) : null}
      <Tiles label="Economics">
        <Kpi
          label="Cost a plan minute"
          value={rate(base?.perPlanMinute ?? null)}
          note={base ? base.label : "No route"}
        />
        <Kpi
          label="Fixed costs a month"
          value={rupees(economics.fixed.total)}
          note={`${rupees(economics.fixed.running)} running · ${rupees(economics.fixed.building)} agents`}
        />
        <Kpi
          label="Break-even at full use"
          value={`${whole(personal)?.total ?? "–"} Personal`}
          note={`or ${whole(seat)?.total ?? "–"} Organisation seats, agents included`}
        />
        <Kpi
          label="AI on calls never charged"
          value={rupees(uncharged?.month ?? null)}
          tone={uncharged && uncharged.month > 0 ? "warn" : "good"}
          note={
            uncharged
              ? `${uncharged.calls} calls · ${uncharged.audioMinutes} min in ${economics.days} days, a month at this pace`
              : "No export yet"
          }
        />
      </Tiles>
      <Panel
        title="Margin a month per plan"
        sub={`After GST and the payment fee, at 25%, 50% and 100% of the plan's minutes on ${routeName(economics.breakEvenRoute).toLowerCase()}'s route`}
        tools={
          <Why
            detail={`Prices are the plans table's, as sold. GST is passed through: a GST-inclusive price is divided by 1 + the GST rate. Razorpay takes its rate of the charge plus GST on its fee; Play Billing takes its rate of the price without tax. A yearly price is shown a month. Minutes cost the route's rupees an audio minute times the audio-to-billed ratio of charged calls (plans count billed minutes). Green is at or above the ${share(economics.targetMargin)} target margin, amber below it, red a loss. List-price estimates, never a bill.`}
          />
        }
      >
        <OfferTable economics={economics} />
      </Panel>
      <Panel
        title="Cost per minute by analysis route"
        sub={`Measured: ${where}'s last ${economics.days} days (${economics.measured.calls} calls, ${economics.measured.audioMinutes} min). Projections: the analysis engine registry on production's measured mix`}
        tools={
          <Why detail="The measured route is the metrics store's list price for real calls (canary, QA and synthetic never count) over their audio minutes; the store does not record the separate Brain 4.0 read, so it is not in that line. Projections are the registry's plans priced from measured fits, the Brain 4.0 read included." />
        }
      >
        <RouteTable economics={economics} />
      </Panel>
      <Panel
        title="Break-even"
        sub="How many of one plan cover the fixed costs a month, on the break-even route"
      >
        <BreakEvenTable economics={economics} />
      </Panel>
      <div className={styles.columns}>
        <Panel
          title="Fixed costs a month"
          sub={
            economics.settingsRevision === null
              ? "Estimates until invoices are entered"
              : `Saved revision ${economics.settingsRevision}`
          }
        >
          <FixedList economics={economics} />
          {economics.settingsConfig ? (
            <details className={styles.edit}>
              <summary>Edit fixed costs</summary>
              <FixedCostsEditor
                revision={economics.settingsRevision}
                config={economics.settingsConfig}
                items={economics.fixed.items}
              />
            </details>
          ) : null}
        </Panel>
        <Panel title="Top-ups and the free trial">
          <ul className={styles.fixed}>
            {economics.topUps.map((pack) => (
              <li key={`${pack.plan}-${pack.key}`}>
                <span className={styles.name}>
                  <strong>
                    {pack.plan.charAt(0).toUpperCase() + pack.plan.slice(1)} ·{" "}
                    {pack.minutes} min
                  </strong>
                  <small>
                    {rupees(pack.gross)} charged · {rate(pack.netPerMinute)} a
                    minute net
                  </small>
                </span>
                <b>
                  {share(pack.marginShare[economics.breakEvenRoute] ?? null)}
                </b>
              </li>
            ))}
            <li>
              <span className={styles.name}>
                <strong>Free trial · {economics.trial.minutes} min</strong>
                <small>
                  {share(economics.trial.conversion)} of trials paying:{" "}
                  {rupees(economics.trial.perPayingUser)} to win each paying
                  user
                </small>
              </span>
              <b>{rupees(economics.trial.cost)}</b>
            </li>
          </ul>
        </Panel>
      </div>
    </>
  );
}
