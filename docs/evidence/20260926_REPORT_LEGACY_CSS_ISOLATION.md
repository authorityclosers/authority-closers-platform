# Report CSS isolation and real-shell verification

Source baseline: `43402408684a91cca9b6ff3f3a6a6cd7a28b5ccb` plus this patch.

The deployed `6d16f057` report exposed two legacy-style collisions. Global
`.studio-report article` rules removed the new takeaway's left inset and capped
it at 850 px. Global `details` margins added 50 px around the compact source
disclosure. These styles now belong only to the legacy findings renderer and
its legacy detail control; redesigned components retain their CSS Modules.

The full-shell development fixture previously omitted the production
`xray-app simple-app`, `studio-report panel`, report stage and acquisition
module classes. It now includes those same style owners. Its synthetic data,
read-only profile fallback and lack of recording/provider remain explicit.

That faithful fixture exposed a second defect: the generic panel's `appear`
animation retained `transform: translateY(0)`, creating a containing block for
the fixed Back shortcut. The shortcut rendered thousands of pixels below the
viewport. Reports now use an opacity-only entry animation. Individual overview
blocks also inherit the measured scroll margin; the final verdict previously
landed at viewport top behind navigation.

## Browser evidence

Supported browser inspection used the development shell with fictional data;
these checks do not claim this follow-up is already deployed.

- At **1440 × 900**, takeaway computed padding is `4px 0px 4px 20px`,
  `max-width: none`; its heading starts 22.4 px inside the article's left edge
  including its border. The source disclosure margin is 0. Document width is
  1425 px including a 15 px scrollbar allocation: no horizontal overflow.
- At **720 × 640**, the shell bar occupies 0–56 px; report navigation occupies
  56–149.8 px. Transcript heading begins at 157.8 px. After the final-verdict
  jump, the target begins at 158.1 px, below navigation.
- In that same viewport the visible Back-to-Overview button occupies
  448.41–490.41 px; the audio dock starts at 503.2 px. The report's computed
  transform is `none`. The Back action returns focus to its originating
  Read-the-final-verdict button.

## Verification

- Combined CallStudio, ReportModes and real-shell fixture suite: 51 passed.
- Real-shell fixture after adding acquisition style owners: 2 passed.
- Web typecheck passed.
- See the companion scroll-offset evidence for the delegate's focused
  navigation, overview and moment suites. Actual browser verification caught
  the additional CSS transform and individual-block margin defects above.

Staging's earlier `6d16f057` release was separately verified to load the saved
fictional long report and start/pause an inline excerpt without restarting it.
This follow-up still requires exact-source CI and a new verified web artifact
before staging or production activation.
