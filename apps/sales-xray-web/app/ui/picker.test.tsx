// @vitest-environment happy-dom
import { act, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { Picker } from "./picker";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The one picker (owner, 31 Oct 2026): rows with a colour dot, a name, a live
// count and a check; the row that clears the choice first; a listbox the
// keyboard drives.
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const OPTIONS = [
  { key: "new", label: "New Lead", tone: "var(--lx-closing)", count: 12 },
  {
    key: "open_leads",
    label: "Open Leads",
    tone: "var(--lx-teal)",
    count: 1234,
  },
  { key: "lost", label: "Closed / Lost", tone: "var(--lx-danger)" },
];

const button = () =>
  host.querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')!;
const options = () => [
  ...host.querySelectorAll<HTMLElement>('[role="option"]'),
];
const press = (target: Element, key: string) =>
  act(async () => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });

it("shows the choice, then a listbox with All first, live counts and a check on the chosen row", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <Picker
        title="Pipeline stage"
        label="Pipeline stage:"
        value="open_leads"
        options={OPTIONS}
        all={{ label: "All stages", count: 1246 }}
        onChange={onChange}
      />,
    ),
  );
  expect(button().textContent).toBe("Pipeline stage:Open Leads");
  expect(button().getAttribute("aria-expanded")).toBe("false");
  expect(options()).toHaveLength(0);
  await act(async () => button().click());
  expect(button().getAttribute("aria-expanded")).toBe("true");
  const list = host.querySelector('[role="listbox"]')!;
  expect(list.getAttribute("aria-label")).toBe("Pipeline stage");
  expect(button().getAttribute("aria-controls")).toBe(list.id);
  expect(
    options().map((row) => [
      row.textContent,
      row.getAttribute("aria-selected"),
    ]),
  ).toEqual([
    ["All stages1,246", "false"],
    ["New Lead12", "false"],
    ["Open Leads1,234", "true"],
    ["Closed / Lost", "false"],
  ]);
  // Picking the choice already on changes nothing.
  await act(async () => options()[2].click());
  expect(onChange).not.toHaveBeenCalled();
  expect(options()).toHaveLength(0);
  await act(async () => button().click());
  await act(async () => options()[1].click());
  expect(onChange).toHaveBeenCalledWith("new");
  expect(options()).toHaveLength(0);
});

it("moves with the arrows, picks with Enter, and Escape closes without picking", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <Picker
        title="Pipeline stage"
        value={null}
        options={OPTIONS}
        all={{ label: "All stages" }}
        onChange={onChange}
      />,
    ),
  );
  await press(button(), "ArrowDown");
  expect(options()).toHaveLength(4);
  const list = () => host.querySelector('[role="listbox"]')!;
  await press(list(), "ArrowDown");
  await press(list(), "ArrowDown");
  expect(document.activeElement?.textContent).toBe("Open Leads1,234");
  await press(list(), "End");
  expect(document.activeElement?.textContent).toBe("Closed / Lost");
  await press(list(), "Enter");
  expect(onChange).toHaveBeenCalledWith("lost");
  expect(document.activeElement).toBe(button());

  await act(async () => button().click());
  await press(list(), "Escape");
  expect(options()).toHaveLength(0);
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(button());
});

it("closes a popover on a click elsewhere", async () => {
  await act(async () =>
    root.render(
      <Picker
        title="Stage"
        value={null}
        options={OPTIONS}
        onChange={vi.fn()}
      />,
    ),
  );
  await act(async () => button().click());
  expect(options()).toHaveLength(3);
  await act(async () => {
    document.body.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true }),
    );
  });
  expect(options()).toHaveLength(0);
});

it("inside a sheet opens in place, and its rows can't be reached while closed", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <Picker
        mode="inline"
        title="Lead source"
        label="Lead source"
        value={null}
        options={[
          { key: "meta", label: "Meta Ads" },
          { key: "google", label: "Google Ads" },
        ]}
        all={{ label: "Every source" }}
        onChange={onChange}
      />,
    ),
  );
  const drawer = () =>
    host.querySelector('[role="listbox"]')!.closest("[inert], [data-open]")!;
  expect(button().textContent).toBe("Lead sourceEvery source");
  expect(drawer().hasAttribute("inert")).toBe(true);
  // Rows without colours draw no dots.
  expect(
    host.querySelector('[role="listbox"]')!.hasAttribute("data-plain"),
  ).toBe(true);
  await act(async () => button().click());
  expect(drawer().hasAttribute("inert")).toBe(false);
  expect(drawer().hasAttribute("data-open")).toBe(true);
  await act(async () => options()[2].click());
  expect(onChange).toHaveBeenCalledWith("google");
  expect(drawer().hasAttribute("inert")).toBe(true);
});

it("stands in for a form's select: its name, a placeholder, a form value, and shut while disabled", async () => {
  const onChange = vi.fn();
  const ref = createRef<HTMLButtonElement | null>();
  const draw = (value: string | null, disabled = false) =>
    act(async () =>
      root.render(
        <form>
          <Picker
            id="country"
            title="Country or region"
            ariaLabel="Country or region"
            placeholder="Choose a country"
            name="country"
            value={value}
            options={[
              { key: "IN", label: "India (+91)" },
              { key: "GB", label: "United Kingdom (+44)" },
            ]}
            describedBy="country-help"
            invalid={!value}
            disabled={disabled}
            buttonRef={ref}
            onChange={onChange}
          />
        </form>,
      ),
    );
  const field = () => new FormData(host.querySelector("form")!).get("country");
  await draw(null);
  expect(button().textContent).toBe("Country or region Choose a country");
  expect(button().id).toBe("country");
  expect(ref.current).toBe(button());
  expect(button().getAttribute("aria-describedby")).toBe("country-help");
  expect(button().hasAttribute("data-invalid")).toBe(true);
  expect(field()).toBe("");
  // The placeholder is not a row.
  await act(async () => button().click());
  expect(options().map((row) => row.textContent)).toEqual([
    "India (+91)",
    "United Kingdom (+44)",
  ]);
  await act(async () => options()[1].click());
  expect(onChange).toHaveBeenCalledWith("GB");

  await draw("GB", true);
  expect(button().textContent).toBe("Country or region United Kingdom (+44)");
  expect(button().hasAttribute("data-invalid")).toBe(false);
  expect(field()).toBe("GB");
  expect(button().disabled).toBe(true);
  await act(async () => button().click());
  expect(options()).toHaveLength(0);
});

it("inside a label, a tap on a row stops there, so the label can't reopen the list", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <label>
        <span>Theme</span>
        <Picker
          title="Theme"
          value="light"
          options={[
            { key: "light", label: "Light" },
            { key: "dark", label: "Dark" },
          ]}
          onChange={onChange}
        />
      </label>,
    ),
  );
  await act(async () => button().click());
  const tap = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => {
    options()[1].dispatchEvent(tap);
  });
  expect(tap.defaultPrevented).toBe(true);
  expect(onChange).toHaveBeenCalledWith("dark");
  expect(options()).toHaveLength(0);
});
