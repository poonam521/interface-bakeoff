"""Browser interfaces driven by Playwright: accessibility-tree text, or screenshots only."""
from __future__ import annotations

from playwright.sync_api import Error as PWError
from playwright.sync_api import Page

from ..types import Observation
from .base import tool

VIEWPORT = {"width": 1024, "height": 768}

# Walks the page in document order and writes a compact text view. Every interactive element
# gets a fresh ref (e1, e2, ...) stored in data-ref so actions can find it again.
SNAPSHOT_JS = r"""
() => {
  document.querySelectorAll('[data-ref]').forEach(e => e.removeAttribute('data-ref'));
  let n = 0;
  const ref = el => { if (!el.dataset.ref) el.dataset.ref = 'e' + (++n); return el.dataset.ref; };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const labelFor = el => {
    if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) return txt(l); }
    const p = el.closest('label'); return p ? txt(p) : (el.name || '');
  };
  const lines = [`page: ${document.title}  (path ${location.pathname}${location.search})`];
  const sel = 'h1,h2,p,li,[role=status],[role=alert],legend,label,a,button,input[type=text],textarea,tr';
  for (const el of document.querySelectorAll(sel)) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'tr') {
      const cells = [...el.children].map(c => {
        const a = c.querySelector('a');
        return a ? `link "${txt(a)}" [${ref(a)}]` : txt(c);
      });
      lines.push('row: ' + cells.join(' | '));
    } else if (tag === 'a' || tag === 'button') {
      if (el.closest('tr')) continue;
      lines.push(`${tag === 'a' ? 'link' : 'button'} "${txt(el)}" [${ref(el)}]`);
    } else if (tag === 'input' || tag === 'textarea') {
      lines.push(`textbox "${labelFor(el)}" [${ref(el)}] value="${el.value}"`);
    } else if (tag === 'label') {
      const r = el.querySelector('input[type=radio]');
      if (r) lines.push(`  radio "${txt(el)}" [${ref(r)}]${r.checked ? ' (checked)' : ''}`);
    } else if (tag === 'legend') {
      lines.push(`group "${txt(el)}"`);
    } else if (tag === 'h1' || tag === 'h2') {
      lines.push(`heading "${txt(el)}"`);
    } else if (tag === 'p' || tag === 'li') {
      if (el.querySelector('a,button')) continue;
      lines.push(`text: ${txt(el)}`);
    } else {
      lines.push(`${el.getAttribute('role')}: ${txt(el)}`);
    }
  }
  return lines.join('\n');
}
"""

# For the fake agent only: where is an element, and how far must the page scroll to show it.
LOCATE_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
  let dy = 0;
  if (r.top < 0 || r.bottom > window.innerHeight) {
    const want = window.scrollY + r.top - 200;
    dy = Math.round(Math.max(0, Math.min(maxScroll, want)) - window.scrollY);
  }
  return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2 - dy),
          dy: dy, ref: el.dataset.ref || null};
}
""".strip()
SNAPSHOT_JS = SNAPSHOT_JS.strip()  # Playwright only treats the string as a function without leading whitespace


class _BrowserBase:
    def __init__(self, browser, base_url: str):
        self.base_url = base_url
        self.context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.page: Page = self.context.new_page()
        self.page.set_default_timeout(5000)

    def _settle(self) -> None:
        try:
            self.page.wait_for_timeout(120)
            self.page.wait_for_load_state("load")
        except PWError:
            pass

    def start(self) -> Observation:
        self.page.goto(self.base_url + "/")
        return self._observe("Opened the ticket tracker home page.")

    def close(self) -> None:
        self.context.close()

    def _locate(self, selector: str) -> dict:
        found = self.page.evaluate(LOCATE_JS, selector)
        if found is None:
            raise LookupError(f"fake agent: no element for {selector}")
        return found


class A11yInterface(_BrowserBase):
    name = "a11y"
    guidance = (
        "You see the web page as a text snapshot: one line per element, with a ref such as [e7] "
        "on everything you can act on. Act by ref. After every action you get a new snapshot; "
        "refs from older snapshots are not valid."
    )

    def tools(self) -> list[dict]:
        r = {"ref": {"type": "string", "description": "Element ref from the latest snapshot, e.g. e7"}}
        return [
            tool("click", "Click a link, button or radio button.", r, ["ref"]),
            tool("fill", "Replace the text in a text box.", {**r, "text": {"type": "string"}}, ["ref", "text"]),
            tool("press", "Press a key, e.g. Enter.", {"key": {"type": "string"}}, ["key"]),
            tool("goto", "Open a path in this app, e.g. / or /tickets/new.", {"path": {"type": "string"}}, ["path"]),
        ]

    def _observe(self, summary: str, is_error: bool = False) -> Observation:
        return Observation(summary=summary, view=self.page.evaluate(SNAPSHOT_JS), is_error=is_error)

    def act(self, name: str, args: dict) -> Observation:
        try:
            if name in ("click", "fill"):
                loc = self.page.locator(f'[data-ref="{args.get("ref")}"]')
                if loc.count() != 1:
                    return self._observe(f"No element with ref {args.get('ref')!r} in the latest snapshot.", True)
                if name == "click":
                    loc.click()
                else:
                    loc.fill(str(args.get("text", "")))
            elif name == "press":
                self.page.keyboard.press(str(args.get("key", "")))
            elif name == "goto":
                path = str(args.get("path", "/"))
                if not path.startswith("/"):
                    return self._observe("Path must start with /.", True)
                self.page.goto(self.base_url + path)
            else:
                return self._observe(f"Unknown action {name}.", True)
        except PWError as e:
            return self._observe(f"Action failed: {str(e).splitlines()[0]}", True)
        self._settle()
        what = {"click": f"Clicked {args.get('ref')}.", "fill": f"Filled {args.get('ref')}.",
                "press": f"Pressed {args.get('key')}.", "goto": f"Opened {args.get('path')}."}[name]
        return self._observe(what)

    def translate(self, step: tuple) -> list[tuple[str, dict]]:
        ref = self._locate(step[1])["ref"]
        if step[0] == "click":
            return [("click", {"ref": ref})]
        return [("fill", {"ref": ref, "text": step[2]})]


class ScreenshotInterface(_BrowserBase):
    name = "screenshot"
    guidance = (
        f"You see the web page only as a screenshot, {VIEWPORT['width']}x{VIEWPORT['height']} pixels. "
        "Act with mouse and keyboard at pixel coordinates. Typing goes to the focused field and adds "
        "to any text already there; press Control+a first to replace it. Scroll to see more of the page."
    )

    def tools(self) -> list[dict]:
        return [
            tool("click", "Left-click at pixel coordinates.",
                 {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
            tool("type", "Type text into the focused element.", {"text": {"type": "string"}}, ["text"]),
            tool("key", "Press a key or combination, e.g. Enter, Tab, Control+a.", {"key": {"type": "string"}}, ["key"]),
            tool("scroll", "Scroll the page vertically by dy pixels (negative scrolls up).",
                 {"dy": {"type": "integer"}}, ["dy"]),
        ]

    def _observe(self, summary: str, is_error: bool = False) -> Observation:
        return Observation(summary=summary, image=self.page.screenshot(type="png"), is_error=is_error)

    def act(self, name: str, args: dict) -> Observation:
        try:
            if name == "click":
                x, y = int(args.get("x", -1)), int(args.get("y", -1))
                if not (0 <= x < VIEWPORT["width"] and 0 <= y < VIEWPORT["height"]):
                    return self._observe(f"({x}, {y}) is outside the screen.", True)
                self.page.mouse.click(x, y)
                what = f"Clicked at ({x}, {y})."
            elif name == "type":
                self.page.keyboard.type(str(args.get("text", "")))
                what = "Typed text."
            elif name == "key":
                self.page.keyboard.press(str(args.get("key", "")))
                what = f"Pressed {args.get('key')}."
            elif name == "scroll":
                dy = int(args.get("dy", 0))
                self.page.mouse.wheel(0, dy)
                what = f"Scrolled by {dy}."
            else:
                return self._observe(f"Unknown action {name}.", True)
        except (PWError, ValueError, TypeError) as e:
            return self._observe(f"Action failed: {str(e).splitlines()[0]}", True)
        self._settle()
        return self._observe(what)

    def translate(self, step: tuple) -> list[tuple[str, dict]]:
        at = self._locate(step[1])
        calls = [("scroll", {"dy": at["dy"]})] if at["dy"] else []
        calls.append(("click", {"x": at["x"], "y": at["y"]}))
        if step[0] == "fill":
            calls += [("key", {"key": "Control+a"}), ("type", {"text": step[2]})]
        return calls
