/** Navigation intent only; never deletes or cancels the saved submission. */
export function newCallHref(homeHref = "/") {
  const url = new URL(homeHref, "https://sales-xray.invalid");
  url.searchParams.delete("call");
  url.searchParams.set("new", "1");
  return `${url.pathname}${url.search}${url.hash}`;
}

export function isNewCallRequested() {
  return new URLSearchParams(window.location.search).get("new") === "1";
}

export function setNewCallRequested(requested: boolean) {
  const url = new URL(window.location.href);
  if (requested) {
    url.searchParams.delete("call");
    url.searchParams.set("new", "1");
  } else {
    url.searchParams.delete("new");
  }
  window.history.replaceState(window.history.state, "", url);
}
