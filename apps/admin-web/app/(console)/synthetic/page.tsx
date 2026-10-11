import Link from "next/link";
import { FlaskConical } from "lucide-react";

import { clock, languageLabel } from "@/app/calls/call-data";
import { adminRead } from "@/app/lib/server-api";
import { normalizeSyntheticIndex } from "@/app/synthetic/synthetic-data";
import styles from "@/app/synthetic/synthetic.module.css";
import {
  Badge,
  Empty,
  Page,
  PageHeader,
  Panel,
  Table,
  Toolbar,
  Unavailable,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const SAFE = /^[A-Za-z0-9 ._+:-]{1,80}$/;
type Params = Record<string, string | string[] | undefined>;
const one = (value: string | string[] | undefined) => {
  const text = Array.isArray(value) ? value[0] : value;
  return text && SAFE.test(text) ? text : undefined;
};

export default async function SyntheticPage({
  searchParams,
}: {
  searchParams: Promise<Params>;
}) {
  const params = await searchParams;
  const filters = {
    business: one(params.business),
    language: one(params.language),
    outcome: one(params.outcome),
    q: one(params.q),
  };
  const offset = Math.max(
    0,
    Number.parseInt(one(params.offset) ?? "0", 10) || 0,
  );
  const query = new URLSearchParams(
    Object.entries(filters).filter(
      (entry): entry is [string, string] => !!entry[1],
    ),
  );
  const result = await adminRead(
    `/v1/admin/conversation/synthetic?${query.toString() ? `${query}&` : ""}offset=${offset}&limit=50`,
    normalizeSyntheticIndex,
  );
  const data = result.ok ? result.data : null;
  const select = (
    name: "business" | "language" | "outcome",
    label: string,
    options: { value: string; count: number }[],
  ) => (
    <select name={name} aria-label={label} defaultValue={filters[name] ?? ""}>
      <option value="">{label}: all</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {name === "language" ? languageLabel(option.value) : option.value} (
          {option.count})
        </option>
      ))}
    </select>
  );
  return (
    <Page wide>
      <PageHeader
        title="Synthetic data"
        context={[
          "The fictional synthetic-v1 calls, read-only",
          data ? `${data.total} of ${data.datasetTotal}` : null,
        ]}
      />
      <p className={styles.banner}>
        <FlaskConical size={16} aria-hidden="true" />
        {data?.label ??
          "Synthetic test data: fictional people and companies, never a real team."}{" "}
        Nothing here is ever mixed into real organisations.
      </p>
      {!result.ok ? (
        <Unavailable title="The synthetic dataset" reason={result.error} />
      ) : null}
      {data ? (
        <>
          <form method="get" action="/synthetic">
            <Toolbar label="Filter synthetic calls">
              {select("business", "Seller", data.facets.businesses)}
              {select("language", "Language", data.facets.languages)}
              {select("outcome", "Outcome", data.facets.outcomes)}
              <input
                type="search"
                name="q"
                aria-label="Search"
                placeholder="Search id, scenario, stage"
                defaultValue={filters.q ?? ""}
              />
              <button
                type="submit"
                className={kitStyles.button}
                data-variant="primary"
              >
                Apply
              </button>
            </Toolbar>
          </form>
          <Panel
            title="Calls"
            foot={
              data.nextOffset !== null || offset > 0 ? (
                <span>
                  {offset > 0 ? (
                    <Link
                      className={kitStyles.panelAction}
                      href={`/synthetic?${new URLSearchParams([...query, ["offset", String(Math.max(0, offset - 50))]])}`}
                    >
                      Previous
                    </Link>
                  ) : null}{" "}
                  {data.nextOffset !== null ? (
                    <Link
                      className={kitStyles.panelAction}
                      href={`/synthetic?${new URLSearchParams([...query, ["offset", String(data.nextOffset)]])}`}
                    >
                      Next 50
                    </Link>
                  ) : null}
                </span>
              ) : undefined
            }
          >
            {data.items.length ? (
              <Table label="Synthetic calls">
                <thead>
                  <tr>
                    <th scope="col">Call</th>
                    <th scope="col">Seller</th>
                    <th scope="col">Date</th>
                    <th scope="col">Language</th>
                    <th scope="col">Scenario</th>
                    <th scope="col">Outcome</th>
                    <th scope="col" data-num="">
                      Length
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.callId}>
                      <th scope="row">
                        <Link href={`/synthetic/${item.callId}`}>
                          {item.callId}
                        </Link>
                      </th>
                      <td>{item.businessId}</td>
                      <td>{item.at?.slice(0, 10) ?? "–"}</td>
                      <td>{languageLabel(item.language)}</td>
                      <td>{item.scenario?.replace(/_/g, " ") ?? "–"}</td>
                      <td>
                        <Badge
                          tone={
                            item.outcome === "Won"
                              ? "good"
                              : item.outcome === "Lost"
                                ? "bad"
                                : "neutral"
                          }
                        >
                          {item.outcome ?? "–"}
                        </Badge>
                      </td>
                      <td data-num="">{clock(item.durationMs)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <Empty
                icon={FlaskConical}
                title="No synthetic calls match"
                text="Change or clear the filters."
              />
            )}
          </Panel>
        </>
      ) : null}
    </Page>
  );
}
