/**
 * AC's real month (owner, 30 Oct 2026: "Fixed costs a month ₹52,214 … is not how much AC
 * really spends"): every cost a month by category and cost centre, one-time purchases spread
 * over their life, who each cost serves, and each product's money in, costs and profit or
 * loss with its break-even. From the cost register in Admin until Pulse finance can be read.
 */
import { Badge, Card, Meter, Panel, Table, Why } from "../ui/kit";
import {
  CATEGORY_WORDS,
  CENTRE_WORDS,
  PRODUCT_WORDS,
  RULE_WORDS,
  cadenceLine,
  rupees,
  share,
  type CostItem,
  type ProductLine,
  type RealCosts,
} from "./economics-data";
import styles from "./economics.module.css";

const SOURCE_WORDS: Record<string, string> = {
  invoice: "Invoice",
  pulse: "Pulse",
  estimate: "Estimate",
};

function Bars({
  rows,
  total,
  label,
}: {
  rows: { key: string; label: string; rupees: number }[];
  total: number;
  label: string;
}) {
  return (
    <ul className={styles.bars} aria-label={label}>
      {rows.map((row) => (
        <li key={row.key}>
          <span className={styles.barName}>{row.label}</span>
          <b>{rupees(row.rupees)}</b>
          <Meter value={row.rupees} max={total} />
        </li>
      ))}
    </ul>
  );
}

const split = (item: CostItem) =>
  Object.entries(item.split)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1])
    .map(
      ([product, value]) =>
        `${PRODUCT_WORDS[product] ?? product} ${share(item.monthly > 0 ? value / item.monthly : null)}`,
    )
    .join(" · ");

function Profit({ value }: { value: number }) {
  return (
    <span
      className={styles.margin}
      data-tone={value > 0 ? "good" : value < 0 ? "bad" : "neutral"}
    >
      {value < 0 ? `−${rupees(-value)}` : rupees(value)}
    </span>
  );
}

const plans = (line: {
  breakEvenPersonal: number | null;
  breakEvenSeats: number | null;
}) =>
  line.breakEvenPersonal === null
    ? "–"
    : `${line.breakEvenPersonal} Personal${line.breakEvenSeats === null ? "" : ` or ${line.breakEvenSeats} seats`}`;

function ProductTable({ costs }: { costs: RealCosts }) {
  const rows: ProductLine[] = costs.products;
  return (
    <Table
      label="Profit and loss by product"
      cards={[
        ...rows.map((row) => (
          <Card key={row.key}>
            <strong>{row.label}</strong>
            <span>
              In {rupees(row.moneyIn)} · out {rupees(row.costs)} ·{" "}
              <Profit value={row.profit} />
            </span>
            {row.breakEvenPersonal !== null ? (
              <small className={styles.muted}>Break-even: {plans(row)}</small>
            ) : null}
          </Card>
        )),
        <Card key="overall">
          <strong>AC overall</strong>
          <span>
            In {rupees(costs.overall.moneyIn)} · out{" "}
            {rupees(costs.overall.costs)} ·{" "}
            <Profit value={costs.overall.profit} />
          </span>
          <small className={styles.muted}>
            Break-even: {plans(costs.overall)}
          </small>
        </Card>,
      ]}
    >
      <thead>
        <tr>
          <th scope="col">Product</th>
          <th scope="col" data-num="">
            Money in a month
          </th>
          <th scope="col" data-num="">
            Costs a month
          </th>
          <th scope="col" data-num="">
            Profit or loss
          </th>
          <th scope="col" data-num="">
            Break-even
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key}>
            <th scope="row">{row.label}</th>
            <td data-num="">{rupees(row.moneyIn)}</td>
            <td data-num="">{rupees(row.costs)}</td>
            <td data-num="">
              <Profit value={row.profit} />
            </td>
            <td data-num="">
              {row.breakEvenPersonal === null ? "–" : plans(row)}
            </td>
          </tr>
        ))}
        <tr className={styles.totalRow}>
          <th scope="row">AC overall</th>
          <td data-num="">{rupees(costs.overall.moneyIn)}</td>
          <td data-num="">{rupees(costs.overall.costs)}</td>
          <td data-num="">
            <Profit value={costs.overall.profit} />
          </td>
          <td data-num="">{plans(costs.overall)}</td>
        </tr>
      </tbody>
    </Table>
  );
}

function ItemTable({ costs }: { costs: RealCosts }) {
  const items = [...costs.items].sort((a, b) => b.monthly - a.monthly);
  const from = (item: CostItem) => (
    <Badge tone={item.source === "estimate" ? "warn" : "good"}>
      {SOURCE_WORDS[item.source] ?? item.source}
    </Badge>
  );
  return (
    <Table
      label="Every cost"
      cards={items.map((item) => (
        <Card key={item.key}>
          <strong>
            {item.vendor} · {item.label}
          </strong>
          <span>
            {rupees(item.monthly)} a month · {cadenceLine(item)}
          </span>
          <small className={styles.muted}>
            {CATEGORY_WORDS[item.category] ?? item.category} ·{" "}
            {CENTRE_WORDS[item.centre] ?? item.centre} ·{" "}
            {split(item) || item.basis}
          </small>
          <span>{from(item)}</span>
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Cost</th>
          <th scope="col">Charged</th>
          <th scope="col" data-num="">
            A month
          </th>
          <th scope="col">Category · cost centre</th>
          <th scope="col">Serves</th>
          <th scope="col">From</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr
            key={item.key}
            className={styles.itemRow}
            data-ended={item.active ? undefined : ""}
          >
            <th scope="row">
              <span className={styles.name}>
                <strong>
                  {item.vendor} · {item.label}
                </strong>
                {item.evidence || item.note ? (
                  <small>
                    {[item.evidence, item.note].filter(Boolean).join(" · ")}
                  </small>
                ) : null}
              </span>
            </th>
            <td>
              <span className={styles.name}>
                <span>{cadenceLine(item)}</span>
                {item.monthsLeft !== null ? (
                  <small>{item.monthsLeft} months left to spread</small>
                ) : null}
                {!item.active ? <small>Not counted this month</small> : null}
              </span>
            </td>
            <td data-num="">{rupees(item.monthly)}</td>
            <td>
              <span className={styles.name}>
                <span>{CATEGORY_WORDS[item.category] ?? item.category}</span>
                <small>{CENTRE_WORDS[item.centre] ?? item.centre}</small>
              </span>
            </td>
            <td>
              <span className={styles.name}>
                <span>{split(item) || "–"}</span>
                <small>
                  {RULE_WORDS[String(item.allocation.rule)] ?? item.basis}
                  {/not measured|no money/.test(item.basis)
                    ? ` · ${item.basis}`
                    : ""}
                </small>
              </span>
            </td>
            <td>{from(item)}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function KeysLine({ costs }: { costs: RealCosts }) {
  const tools = Object.entries(costs.keys.tools).map(([tool, shares]) => {
    const parts = Object.entries(shares)
      .sort((a, b) => b[1] - a[1])
      .map(
        ([product, value]) =>
          `${PRODUCT_WORDS[product] ?? product} ${share(value)}`,
      )
      .join(", ");
    return `${tool === "claude" ? "Claude" : "Codex"}: ${parts}`;
  });
  const cpu = costs.keys.cpu;
  return (
    <p className={styles.keys}>
      {costs.keys.generatedAt
        ? `Agent work measured ${costs.keys.generatedAt.slice(0, 10)} over ${costs.keys.windowDays ?? 30} days. ${tools.join(". ")}.`
        : "Agent work not measured yet: costs split by it stay with AC company until the nightly measure runs."}
      {cpu
        ? ` Server time: apps ${share(cpu.apps ?? 0)}, agents ${share(cpu.agents ?? 0)}, other ${share(cpu.other ?? 0)}.`
        : ""}{" "}
      Of the AI bills, calls cost about {rupees(costs.aiCalls.customerMonth)} a
      month for customers and {rupees(costs.aiCalls.testMonth)} for tests.{" "}
      {costs.platformWork === "pro_rata"
        ? "Shared platform work is spread over the products by their own work."
        : "Shared platform work stays a company cost."}
    </p>
  );
}

export function RealCostsView({ costs }: { costs: RealCosts }) {
  const people = costs.items.some((item) => item.category === "people");
  return (
    <>
      <Panel
        title="Real cost a month"
        sub={`${costs.month} · ${rupees(costs.total)} · one-time purchases spread over their life${people ? " · people as one total" : ""}`}
        tools={
          <Why detail="Each cost a month: monthly as charged, quarterly ÷ 3, yearly ÷ 12, usage as the monthly average entered, a one-time purchase spread evenly over its stated life from the month it was bought. Ended costs stop after their last month. Foreign-currency costs show the amount charged and its rupees. Salaries and debt are one total each, never one line per person. Pulse finance becomes the source once it can be read; until then this is the register in Admin." />
        }
      >
        <div className={styles.split}>
          <section aria-label="By category">
            <h3 className={styles.subhead}>By category</h3>
            <Bars
              rows={costs.byCategory}
              total={costs.total}
              label="Cost by category"
            />
          </section>
          <section aria-label="By cost centre">
            <h3 className={styles.subhead}>By cost centre</h3>
            <Bars
              rows={costs.byCentre.filter((row) => row.rupees > 0)}
              total={costs.total}
              label="Cost by cost centre"
            />
          </section>
        </div>
      </Panel>
      <Panel
        title="Profit and loss by product"
        sub="Money in (live invoices, without GST, less the payment fee) against the costs each product is given"
        tools={
          <Why detail="Each cost goes to the products by its rule: all to one product; by agent work (the agents' session logs, by the files each session touched); by server time (the apps against the agents); by money in; or stated shares. Break-even is the Personal plans (or Organisation seats) at 50% use whose contribution covers the costs. AI for the product today also holds the customers' calls, which the plans' margins count again; at today's volume that is a few hundred rupees." />
        }
      >
        <ProductTable costs={costs} />
        <KeysLine costs={costs} />
      </Panel>
      <Panel
        title="Every cost"
        sub="Largest first; estimates are amber until an invoice replaces them"
      >
        <ItemTable costs={costs} />
      </Panel>
    </>
  );
}
