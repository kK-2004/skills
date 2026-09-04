---
name: fixed-scroll-layout
description: Implement or repair fixed-height dialogs, panels, sidebars, and split views where headers and footers stay fixed while overflowing content scrolls internally. Use for requests about fixed container height, internal scrolling, independent column scrolling, or content unexpectedly stretching a parent.
---

# Fixed Scroll Layout

Build the smallest layout change that keeps the requested outer container stable while allowing the intended inner content to scroll.

## Determine the scroll boundary

Before editing, identify:

- the outer height owner, such as a dialog or viewport-sized panel;
- fixed regions, usually the header, toolbar, summary, column heading, and footer;
- flexible regions that must consume the remaining height;
- the exact list or content region that should scroll;
- whether split panes should scroll independently or together.

Preserve the existing visual height unless the user requests a new size. Do not solve overflow by making the whole page or dialog scroll when the request calls for an inner scrolling region.

## Implement the height chain

Every ancestor between the height owner and scroll region must permit shrinking. In flex or grid layouts, apply the equivalent of `min-height: 0` to flexible ancestors; otherwise descendants can expand the parent instead of overflowing.

For Vue with Tailwind, the usual structure is:

```html
<div class="flex h-full min-h-0 flex-col">
  <header class="shrink-0">...</header>
  <div class="min-h-0 flex-1 overflow-hidden">
    <div class="h-full overflow-y-auto">...</div>
  </div>
  <footer class="shrink-0">...</footer>
</div>
```

Use `overflow-hidden` on intermediate containers only to establish the boundary. Put `overflow-y-auto` on the nearest element whose content should actually scroll.

For independent split-pane scrolling, make each pane a shrinking flex column. Keep each pane heading `shrink-0`, and give each list `min-h-0 flex-1 overflow-y-auto`.

When responsive layouts switch from columns to rows, define bounded grid rows or another explicit height allocation so one pane cannot consume all available height.

## Preserve behavior

- Do not change data flow, selection behavior, focus handling, or submit actions for a layout-only request.
- Avoid fixed pixel heights on nested lists when an existing parent already owns the height; prefer consuming remaining space.
- Retain accessible labels and semantic regions.
- Keep empty and loading states inside the same fixed region when practical.
- Avoid nested scrollbars unless the panes are intentionally independent.

## Verify

Check the component in these states:

- short content leaves stable empty space without collapsing the container;
- long content scrolls inside the intended region without moving the header or footer;
- each split pane scrolls independently when requested;
- responsive layouts remain usable;
- keyboard focus can reach items that begin outside the visible scroll area.

Run the project's relevant type checks and component tests. If browser inspection is available, confirm actual overflow with enough repeated items to exceed the container height.
