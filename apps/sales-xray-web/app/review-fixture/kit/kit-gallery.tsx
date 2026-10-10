"use client";

import { Inbox, Phone } from "lucide-react";
import { useState } from "react";

import {
  Avatar,
  Badge,
  Button,
  Card,
  Delta,
  Empty,
  Fact,
  Field,
  InlineEdit,
  Kpi,
  List,
  Meter,
  PageHeader,
  Panel,
  QueryTabs,
  Row,
  Segmented,
  Skeleton,
  Spark,
  Table,
  Tiles,
  Why,
} from "../../ui/kit";
import styles from "./kit-gallery.module.css";

const calls = [
  {
    name: "Discovery · Amit, Pixel Digital",
    rep: "Asha Menon",
    length: "25:20",
    state: "Report ready",
  },
  {
    name: "समीर जोशी · Pune follow-up",
    rep: "Rahul Verma",
    length: "15:40",
    state: "In progress",
  },
  {
    name: "Pricing call · Rohan Mehta",
    rep: "Neha Kulkarni",
    length: "30:35",
    state: "Needs attention",
  },
];
const tone = (state: string) =>
  state === "Report ready"
    ? "good"
    : state === "In progress"
      ? "accent"
      : "warn";

/** Every kit piece in its states, with fictional data, for review at any width. */
export function KitGallery() {
  const [name, setName] = useState("Discovery · Amit, Pixel Digital");
  const [view, setView] = useState<"team" | "mine">("team");
  return (
    <main className={styles.page}>
      <PageHeader
        title="Page kit"
        context={["Fictional data", "app/ui/kit"]}
        back={{ href: "/dashboard", label: "Dashboard" }}
        actions={
          <>
            <Button>Export</Button>
            <Button variant="primary">New analysis</Button>
          </>
        }
      />
      <QueryTabs
        base="/review-fixture/kit"
        current="overview"
        items={[
          { key: "overview", label: "Overview" },
          { key: "members", label: "Members", count: 8 },
          { key: "company", label: "Company" },
        ]}
      />
      <Tiles>
        <Kpi
          label="Calls"
          value={14}
          delta={<Delta value={14} previous={11} />}
          spark={<Spark values={[1, 0, 2, 3, 1, 4, 3]} label="Calls per day" />}
          note="last 30 days"
        />
        <Kpi
          label="Minutes recorded"
          value={362}
          unit="min"
          note="length of those calls"
        />
        <Kpi label="Reports ready" value={12} note="of 14 calls" tone="good" />
        <Kpi
          label="Needs attention"
          value={1}
          note="Review"
          tone="warn"
          href="/analysis/calls"
        />
      </Tiles>
      <div className={styles.columns}>
        <Panel
          title="Team calls"
          sub="3 of 14"
          action={{ href: "/analysis/calls", label: "Open Calls" }}
          tools={
            <Segmented
              label="Whose calls"
              value={view}
              onChange={setView}
              items={[
                { key: "team", label: "Team" },
                { key: "mine", label: "Mine" },
              ]}
            />
          }
        >
          <Table
            label="Team calls"
            cards={calls.map((call) => (
              <Card key={call.name}>
                <strong>{call.name}</strong>
                <span>
                  {call.rep} · {call.length} ·{" "}
                  <Badge tone={tone(call.state)}>{call.state}</Badge>
                </span>
              </Card>
            ))}
          >
            <thead>
              <tr>
                <th scope="col">Call</th>
                <th scope="col">Rep</th>
                <th scope="col" data-num="">
                  Length
                </th>
                <th scope="col">Report</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((call) => (
                <tr key={call.name}>
                  <th scope="row">{call.name}</th>
                  <td>
                    <span className={styles.person}>
                      <Avatar name={call.rep} size={20} />
                      {call.rep}
                    </span>
                  </td>
                  <td data-num="">{call.length}</td>
                  <td>
                    <Badge tone={tone(call.state)}>{call.state}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
        <Panel
          title="Calls by person"
          tools={
            <Why detail="Counted from the calls analysed in this organisation in the last 30 days." />
          }
        >
          <List label="Calls by person">
            {calls.map((call, index) => (
              <Row
                key={call.rep}
                icon={<Avatar name={call.rep} />}
                title={call.rep}
                meta={[
                  `${3 - index} ${3 - index === 1 ? "call" : "calls"}`,
                  `${(3 - index) * 40} min`,
                ]}
                end={<Meter value={3 - index} max={3} />}
              />
            ))}
          </List>
        </Panel>
      </div>
      <div className={styles.columns}>
        <Panel title="Fields and inline editing">
          <div className={styles.form}>
            <Field label="Company name" hint="2 to 80 characters">
              <input defaultValue="Brightline Coaching" />
            </Field>
            <Field label="City" error="Enter a city">
              <input aria-invalid="true" />
            </Field>
            <Field label="Call name (inline)" wide>
              <InlineEdit
                value={name}
                label="Call name"
                onSave={async (next) => {
                  await new Promise((done) => setTimeout(done, 400));
                  setName(next);
                }}
              />
            </Field>
            <Field label="GSTIN">
              <span>
                <Fact value={null} />
              </span>
            </Field>
          </div>
        </Panel>
        <Panel title="States">
          <Empty
            icon={Inbox}
            title="No calls yet"
            text="Analyse a call and it appears here."
            action={{ href: "/analysis/new", label: "Analyse a call" }}
          />
          <div className={styles.skeletons} aria-hidden="true">
            <Skeleton width="60%" height={12} />
            <Skeleton width="40%" height={10} />
          </div>
          <List>
            <Row
              icon={<Phone size={14} />}
              title="Badges"
              end={
                <>
                  <Badge>Neutral</Badge>
                  <Badge tone="accent">Accent</Badge>
                  <Badge tone="good">Good</Badge>
                  <Badge tone="warn">Warn</Badge>
                  <Badge tone="bad">Bad</Badge>
                </>
              }
            />
          </List>
        </Panel>
      </div>
    </main>
  );
}
