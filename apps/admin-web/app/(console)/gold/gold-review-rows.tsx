import Link from "next/link";
import { z } from "zod";

import { adminRead } from "@/app/lib/server-api";
import { AiValue } from "@/app/reviewer/review/gold-review-workspace";
import { goldRow } from "@/app/reviewer/review/gold-review-api";
import { Panel, Table, Unavailable } from "@/app/ui/kit";

export async function GoldReviewRows() {
  const result = await adminRead("/v1/admin/conversation/gold-rows", (body) =>
    z.object({ items: z.array(goldRow).default([]) }).parse(body),
  );
  if (!result.ok)
    return <Unavailable title="Report line reviews" reason={result.error} />;
  return (
    <Panel
      title="Report line reviews"
      sub="Every save is a new gold row. Earlier versions stay in history until the call is erased."
    >
      {!result.data.items.length ? (
        <p>No report lines have been reviewed yet.</p>
      ) : (
        <Table label="Gold dataset report lines">
          <thead>
            <tr>
              <th>Call</th>
              <th>Line</th>
              <th>Reviewer opinion</th>
              <th>AI value judged</th>
              <th>AI version</th>
              <th>Reviewer</th>
              <th>Saved</th>
            </tr>
          </thead>
          <tbody>
            {result.data.items.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link href={`/calls/${row.call.recording_id}`}>
                    {row.call.recording_id.slice(0, 8)}
                  </Link>
                </td>
                <td>{row.target.replaceAll("_", " ")}</td>
                <td>
                  {row.value === null ? (
                    row.erased ? (
                      "Erased with the call"
                    ) : (
                      "Call access unavailable"
                    )
                  ) : (
                    <>
                      <strong>
                        {row.value?.verdict ?? "Score"}
                        {row.value?.score !== null &&
                        row.value?.score !== undefined
                          ? ` · ${row.value.score}/100`
                          : ""}
                      </strong>
                      <p>{row.value?.opinion}</p>
                      {row.supersedes_id ? (
                        <small>
                          Supersedes {row.supersedes_id.slice(0, 8)}
                        </small>
                      ) : null}
                    </>
                  )}
                </td>
                <td>
                  {row.ai_value ? (
                    <details>
                      <summary>Read AI draft</summary>
                      <AiValue value={row.ai_value} />
                    </details>
                  ) : (
                    "Unavailable"
                  )}
                </td>
                <td title={row.ai_sha256}>
                  {row.review_id.slice(0, 8)}
                  <br />
                  <small>{row.ai_sha256.slice(0, 12)}</small>
                </td>
                <td>{row.reviewer_email ?? row.reviewer_id.slice(0, 8)}</td>
                <td>
                  {new Date(row.created_at).toLocaleString("en-IN", {
                    timeZone: "Asia/Kolkata",
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Panel>
  );
}
