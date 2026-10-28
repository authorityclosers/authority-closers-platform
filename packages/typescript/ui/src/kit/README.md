# Shared kit

`@ac/ui/kit` is Sales X-Ray's design system v2: its phone-first tokens,
page pieces, sheets, loading outlines, scrolling, haptics and alerts.
It is shared so Reflex and, later, Pulse look and feel the same.

Runtime imports use only React and React DOM. Icons use inline Lucide paths
(ISC) from `../sx/icons`; never add an icon dependency. Router-aware pieces
accept `link?: KitLink` from `../sx/link`, with a plain anchor as the fallback.
Apps pass their own router link, such as Next's `Link`, through a small adapter.

Import the token styles once, in this order, then use the components:

```tsx
import "@ac/ui/kit/tokens/palette.css";
import "@ac/ui/kit/tokens/screen.css";
import { Panel, Sheet } from "@ac/ui/kit";
```

For client components, keep the app's client boundary. Pass `link={Link}` to
`PageHeader`, `Panel`, `Kpi`, `Empty`, `QueryTabs`, `Row`, `ActionRow` and
`AlertHost` when adopting an app router. CSS modules ship with each component.
The original Sales X-Ray import paths remain adapters to this kit.

The colour ratchet runs in Sales X-Ray's Vitest setup:
`app/ui/kit-raw-colour-ratchet.test.ts`. Its baseline lives beside this file;
only `tokens/palette.css` is exempt from the raw-colour limit.
