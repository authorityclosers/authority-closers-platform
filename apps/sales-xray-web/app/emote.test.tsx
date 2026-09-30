import { render } from "@testing-library/react";
import { expect, it } from "vitest";

import { Emote } from "./emote";

it("holds its space while loading and is decorative unless labelled", () => {
  const { container, rerender } = render(<Emote name="handshake" size={24} />);
  const mark = container.firstElementChild as HTMLElement;
  expect(mark.getAttribute("aria-hidden")).toBe("true");
  expect(mark.style.getPropertyValue("--size")).toBe("24px");
  rerender(<Emote name="handshake" size={24} label="Deal closed" />);
  const labelled = container.firstElementChild as HTMLElement;
  expect(labelled.getAttribute("role")).toBe("img");
  expect(labelled.getAttribute("aria-label")).toBe("Deal closed");
});
