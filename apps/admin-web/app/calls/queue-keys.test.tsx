// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { QueueKeys } from "./queue-keys";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let opened: string[];

beforeEach(async () => {
  opened = [];
  host = document.createElement("div");
  host.innerHTML = `
    <table><tbody>
      <tr><th><a data-call-link href="/calls/one">Asha</a></th>
          <td id="cell">Sharma Realty</td>
          <td><button id="control" type="button">Act</button></td></tr>
    </tbody></table>`;
  document.body.append(host);
  host.querySelector("a")!.addEventListener("click", (event) => {
    event.preventDefault();
    opened.push((event.currentTarget as HTMLAnchorElement).pathname);
  });
  const mount = document.createElement("div");
  host.append(mount);
  root = createRoot(mount);
  await act(async () => root.render(<QueueKeys />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

const click = (id: string, init: MouseEventInit = {}) =>
  host
    .querySelector(`#${id}`)!
    .dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true, ...init }),
    );

it("opens a call from anywhere on its row", () => {
  click("cell");
  expect(opened).toEqual(["/calls/one"]);
});

it("leaves the row's own controls alone", () => {
  click("control");
  expect(opened).toEqual([]);
});

it("opens in a new tab with Ctrl or Cmd", () => {
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  click("cell", { ctrlKey: true });
  expect(opened).toEqual([]);
  expect(open).toHaveBeenCalledWith(
    expect.stringContaining("/calls/one"),
    "_blank",
    "noopener",
  );
});
