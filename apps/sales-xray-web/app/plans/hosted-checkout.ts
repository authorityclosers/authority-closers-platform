/**
 * Takes the buyer to the provider's hosted payment step (contract C1 §1
 * `hosted`). No card data ever touches this app: a redirect or form post
 * leaves the page; a client SDK opens the provider's own window and hands
 * control back with "done" or "dismissed". The server decides the result on
 * its return URL; this file never marks anything paid.
 */
import type { Hosted } from "../billing/contract";

export type HostedResult = "left" | "done" | "dismissed";

type RazorpayWindow = Window & {
  Razorpay?: new (options: Record<string, unknown>) => { open(): void };
};

const RAZORPAY_SDK = "https://checkout.razorpay.com/v1/checkout.js";

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${src}"]`,
    );
    if (existing?.dataset.loaded === "true") return resolve();
    const script = existing ?? document.createElement("script");
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    });
    script.addEventListener("error", () =>
      reject(new Error("provider_script_failed")),
    );
    if (!existing) {
      script.src = src;
      script.async = true;
      document.head.append(script);
    }
  });
}

export async function openHostedCheckout(
  hosted: Hosted,
  orderId: string,
): Promise<HostedResult> {
  if (hosted.kind === "redirect" && hosted.url) {
    window.location.assign(hosted.url);
    return "left";
  }
  if (hosted.kind === "form_post" && hosted.url) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = hosted.url;
    for (const [name, value] of Object.entries(hosted.params)) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      form.append(input);
    }
    document.body.append(form);
    form.submit();
    return "left";
  }
  if (hosted.kind === "client_sdk" && hosted.provider === "razorpay") {
    if (
      !hosted.params.key_id ||
      (!hosted.params.order_ref && !hosted.params.subscription_ref)
    )
      throw new Error("provider_reference_missing");
    await loadScript(RAZORPAY_SDK);
    const Razorpay = (window as RazorpayWindow).Razorpay;
    if (!Razorpay) throw new Error("provider_script_failed");
    return new Promise<HostedResult>((resolve) => {
      const checkout = new Razorpay({
        key: hosted.params.key_id,
        ...(hosted.params.subscription_ref
          ? { subscription_id: hosted.params.subscription_ref }
          : { order_id: hosted.params.order_ref }),
        name: hosted.params.name ?? "Authority Closers",
        description: hosted.params.description ?? "Sales Xray",
        notes: { order_id: orderId },
        handler: () => resolve("done"),
        modal: { ondismiss: () => resolve("dismissed") },
      });
      checkout.open();
    });
  }
  throw new Error("hosted_kind_unsupported");
}
