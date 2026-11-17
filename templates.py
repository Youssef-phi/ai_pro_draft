"""HTML renderers. Agents return structured copy; this code turns it into pages.

Rendering in code (instead of letting a model write raw HTML) means every page is
escaped, carries its MOCKED labels, and cannot contain a countdown timer, a fake
counter or a live payment form, whatever a model writes.
"""
from __future__ import annotations

from html import escape as e

CSS = """
body{font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;color:#1c1917;background:#fafaf9}
main{max-width:720px;margin:0 auto;padding:40px 20px 64px}
h1{font-size:2rem;line-height:1.2;margin:.2em 0}h2{font-size:1.2rem;margin-top:2em}
.sub{font-size:1.15rem;color:#44403c}.card{background:#fff;border:1px solid #e7e5e4;border-radius:12px;padding:16px 20px;margin:14px 0}
.btn{display:inline-block;background:#1d4ed8;color:#fff;border:0;border-radius:8px;padding:12px 20px;font:600 1rem system-ui;cursor:pointer}
.mock{background:#fde68a;color:#111;border-radius:6px;padding:2px 8px;font:700 12px system-ui;letter-spacing:.04em}
.note{color:#57534e;font-size:.9rem}input[type=email]{padding:11px;border:1px solid #a8a29e;border-radius:8px;width:60%;font-size:1rem}
li{margin:.35em 0}label{cursor:pointer}footer{margin-top:48px;color:#78716c;font-size:.85rem}
"""


def _page(title: str, body: str) -> str:
    return (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>'
            f"<style>{CSS}</style></head>\n<body>\n<main>\n{body}\n</main>\n</body></html>\n")


def _ul(items: list) -> str:
    return "<ul>" + "".join(f"<li>{e(str(i))}</li>" for i in items if str(i).strip()) + "</ul>"


def render_landing(s, target: int, days: int) -> str:
    """Demand-test landing page. The waitlist form is MOCKED: it collects nothing."""
    body = f"""<h1>{e(s.landing_headline)}</h1>
<p class="sub">{e(s.landing_subheadline)}</p>
{_ul(s.landing_bullets)}
<div class="card">
  <p><strong>{e(s.landing_cta or "Join the waitlist")}</strong> <span class="mock">MOCKED</span></p>
  <form onsubmit="event.preventDefault();document.getElementById('m').hidden=false">
    <input type="email" placeholder="you@example.com" aria-label="Email address">
    <button class="btn" type="submit">{e(s.landing_cta or "Join the waitlist")}</button>
  </form>
  <p id="m" class="note" hidden>MOCKED: this preview form does not send or store anything.</p>
  <p class="note">This is a demand test for a product that does not exist yet. No payment is taken.</p>
</div>
<footer>Demand-test page. Success target fixed in advance: {int(target)} sign-ups in {int(days)} days.
Only sign-ups the founder really counts are used as evidence.</footer>"""
    return _page(s.landing_headline or "Landing page", body)


def render_mvp(spec) -> str:
    """The MVP: a single-file interactive product (tick-off modules, progress kept in the browser)."""
    modules = []
    for mi, module in enumerate(spec.modules):
        items = module.get("items") or []
        if isinstance(items, str):
            items = [items]
        rows = "".join(
            f'<li><label><input type="checkbox" data-k="m{mi}i{ii}"> {e(str(item))}</label></li>'
            for ii, item in enumerate(items) if str(item).strip())
        modules.append(f'<section class="card"><h2>{e(str(module.get("title", f"Module {mi + 1}")))}</h2>'
                       f'<ul style="list-style:none;padding-left:0">{rows}</ul></section>')
    script = """<script>
(function(){var key='mvp-progress-'+document.title,state={};
try{state=JSON.parse(localStorage.getItem(key)||'{}')}catch(err){}
var boxes=document.querySelectorAll('input[data-k]');
function show(){var n=0;boxes.forEach(function(b){if(b.checked)n++});
document.getElementById('progress').textContent=n+' of '+boxes.length+' done'}
boxes.forEach(function(b){b.checked=!!state[b.dataset.k];b.addEventListener('change',function(){
state[b.dataset.k]=b.checked;try{localStorage.setItem(key,JSON.stringify(state))}catch(err){}show()})});show()})();
</script>"""
    body = f"""<h1>{e(spec.product_name)}</h1>
<p class="sub">{e(spec.summary)}</p>
<p class="note">Progress: <strong id="progress"></strong> (saved in this browser only)</p>
{''.join(modules)}
<h2>How to use this</h2><ol>{''.join(f'<li>{e(str(step))}</li>' for step in spec.user_docs)}</ol>
<footer>MVP generated for founder review. General information only; not financial, health or legal advice.</footer>
{script}"""
    return _page(spec.product_name or "MVP", body)


def render_store(m, price_usd: float, product_name: str) -> str:
    """Store page. Checkout is MOCKED: the button explains that no payment exists."""
    faq = "".join(f"<p><strong>{e(str(f.get('q', '')))}</strong><br>{e(str(f.get('a', '')))}</p>"
                  for f in m.faq if isinstance(f, dict))
    body = f"""<h1>{e(m.store_title or product_name)}</h1>
<p class="sub">{e(m.store_tagline)}</p>
<p>{e(m.store_description)}</p>
<h2>What is included</h2>{_ul(m.store_bullets)}
<div class="card">
  <p><strong>${price_usd:,.2f}</strong> one-time <span class="mock">MOCKED CHECKOUT</span></p>
  <button class="btn" onclick="document.getElementById('m').hidden=false">Buy now</button>
  <p id="m" class="note" hidden>MOCKED: there is no payment provider. No card details are asked for,
  no money moves, and nothing is delivered from this page.</p>
</div>
<h2>Questions</h2>{faq}
<footer>Draft store page. Policies are drafts pending a lawyer's review.</footer>"""
    return _page(m.store_title or product_name or "Store", body)
