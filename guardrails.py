"""Rule pre-filter and output scanner. Pure code, no LLM: runs before any model call.

Three jobs:
  1. check_excluded(text)  - excluded product categories -> STOP / pivot to an allowed digital product.
  2. check_request(text)   - "must never" requests (fake reviews, income promises, impersonation,
                             moving money, storing credentials, skipping approval...) -> refused.
  3. sanitize(text)        - removes forbidden content from anything an agent wrote, so a model
                             slip can never reach an output file or the UI.
The prompts repeat these rules, but the prompts are not the enforcement. This file is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

I = re.IGNORECASE

EXCLUDED: dict[str, tuple[str, list[str]]] = {
    "physical_goods": ("Physical goods are excluded. Only digital products are in scope.", [
        r"\bphysical (products?|goods?|items?)\b", r"\bdrop-?ship\w*\b", r"\bmerch(andise)?\b",
        r"\bt-?shirts?\b", r"\b(apparel|clothing|jewell?ery|cosmetics|furniture|candles?)\b",
        r"\bprint[- ]on[- ]demand\b", r"\b(warehouse|inventory of|ship(ping)? (the )?(boxes|products|goods|items))\b",
        r"\b(hardware|wearable) (device|product|gadget)s?\b", r"\b3d[- ]printed\b",
        r"\b(subscription|snack|meal|gift) box(es)?\b", r"\bhandmade\b",
    ]),
    "financial_investment_crypto": ("Financial, investment and crypto products are excluded.", [
        r"\bcrypto\w*\b", r"\b(bitcoin|ethereum|nfts?|defi|altcoins?|memecoins?)\b", r"\btoken sale\b",
        r"\btrading (signals?|bots?|tips?|strateg\w+)\b", r"\bforex\b", r"\bstock (picks?|tips?|signals?|trading)\b",
        r"\binvest(ment|ing) (advice|advisor|adviser|products?|funds?|platform|signals?|tips?|app|course)\b",
        r"\brobo-?advis\w+\b", r"\b(payday|loan (app|product|service|platform)|lending platform)\b",
        r"\b(betting|gambling|casino|sportsbook)\b", r"\b(securities|hedge fund|portfolio management)\b",
    ]),
    "health_or_legal_advice": ("Health advice and legal advice products are excluded.", [
        r"\bsupplements?\b", r"\b(medical|health|clinical|nutrition(al)?|diet(ary)?|mental[- ]health) "
                             r"(advice|diagnos\w+|treatment|coaching|plans?|consult\w+)\b",
        r"\bdiagnos(e|es|is|ing)\b", r"\btreatment plans?\b", r"\bprescri(be|ption)\w*\b", r"\btelehealth\b",
        r"\btherapy (app|bot|service|sessions?)\b", r"\bsymptom checker\b", r"\bweight[- ]loss\b",
        r"\bdiet (pills?|plans?)\b", r"\bdrug dos(e|age)s?\b",
        r"\blegal (advice|counsel|opinions?)\b", r"\b(lawyer|attorney) (bot|app|service|ai)\b",
        r"\b(immigration|tax|visa) advice\b", r"\bcontract review service\b",
    ]),
}

MUST_NEVER: dict[str, tuple[str, list[str]]] = {
    "fake_social_proof": ("We never create fake reviews, testimonials, sign-ups or waitlist numbers.", [
        r"\b(write|generate|create|make|post|add|fabricate|invent|draft|give me|produce)\b[^.\n]{0,40}"
        r"(\b\d+\b|\bfake\b|five[- ]?star|5[- ]?star|\bpositive\b|\bglowing\b|made[- ]up)[^.\n]{0,40}"
        r"\b(reviews?|testimonials?|ratings?)\b",
        r"\bfake\b[^.\n]{0,30}\b(reviews?|testimonials?|sign-?ups?|waitlist|customers?|users?|subscribers?|"
        r"social proof|followers?|downloads?)\b",
        r"\b(inflate|pad|make up|invent|fabricate|fudge|bump up)\b[^.\n]{0,40}"
        r"\b(sign-?ups?|waitlist|numbers?|metrics|users|customers|downloads|traction)\b",
        r"\bsay (we|i) (have|had|got)\b[^.\n]{0,20}\b\d[\d,]*\b[^.\n]{0,20}\b(users|customers|sign-?ups?|subscribers)\b",
    ]),
    "income_promise": ("We never promise income, earnings or success.", [
        r"\b(promise|guarantee|guaranteeing|assure|tell (them|people|buyers|customers))\b[^.\n]{0,60}"
        r"(\$\s?\d|\bincome\b|\bearn\w*\b|\bprofits?\b|\brevenue\b|\bsuccess\b|\bmake money\b|\brich\b|\breturns?\b)",
        r"\b(i'?ll|i will|they'?ll|they will|you'?ll|you will|buyers will|customers will)\s+(make|earn)\s+\$?\s?\d",
        r"\bget[- ]rich\b",
    ]),
    "fake_urgency": ("We never use countdown timers or fake urgency or scarcity.", [
        r"\bcountdown\b", r"\bonly \d+ (left|spots?|seats?|copies|remaining|available)\b",
        r"\b(fake|false|artificial|invented) (urgency|scarcity|deadline)\b",
        r"\b(add|create|use|show)\b[^.\n]{0,30}\b(urgency|scarcity) (timer|banner|badge|trick)s?\b",
    ]),
    "impersonation": ("We never impersonate the founder, a customer, a real person or another brand.", [
        r"\b(pretend(ing)? to be|pos(e|ing) as|impersonat\w+|masquerad\w+)\b",
        r"\b(sign|send|email|post|reply|write|message|dm|call)\b[^.\n]{0,50}\bas (if (you|it) (are|were|is|came from) )?"
        r"(me|the founder|a (real |happy |paying )?(customer|user|buyer)|an? (influencer|expert|doctor|journalist))\b",
        r"\b(look|appear|seem) like (it'?s|it is|they'?re) (from|by) (apple|google|microsoft|amazon|openai|stripe|"
        r"meta|netflix|a famous|a well[- ]known)\b",
    ]),
    "money_and_credentials": ("We never hold, move or refund money, create accounts, or store passwords "
                              "or card numbers. All payment steps are MOCKED.", [
        r"\b(charge|bill|debit)\b[^.\n]{0,40}\b(cards?|customers?|accounts?|them|users?|buyers?)\b",
        r"\b(transfer|move|wire|withdraw|pay ?out|hold|collect)\b[^.\n]{0,30}(\b(money|funds|cash|payments?)\b|\$\s?\d)",
        r"\b(issue|process|send|give|make)\b[^.\n]{0,25}\b(a )?real refunds?\b",
        r"\brefund\b[^.\n]{0,40}\b(to (the|their|his|her) card|the money|real money)\b",
        r"\b(store|save|keep|collect|remember|log)\b[^.\n]{0,40}"
        r"\b(passwords?|card (numbers?|details)|credit cards?|cvv|cvc|credentials|bank details)\b",
        r"\b(create|open|register|set up|sign up for)\b[^.\n]{0,30}"
        r"\b(stripe|paypal|bank|gumroad|twitter|instagram|facebook|linkedin|reddit|shopify|tiktok|google|"
        r"social media|merchant|payment)\b[^.\n]{0,20}\baccounts?\b",
        r"\b(connect|use|turn on|enable|switch to)\b[^.\n]{0,30}\b(live|real|production|sandbox)\b[^.\n]{0,20}"
        r"\b(payments?|stripe|checkout|charges?)\b",
    ]),
    "paywall": ("We never put core features behind our own paywall.", [
        r"\bpaywall\b", r"\b(lock|hide|gate|restrict)\b[^.\n]{0,40}\b(core|basic|main|key) features?\b",
    ]),
    "skip_approval": ("Founder approval cannot be skipped. Nothing is published, sent, spent or signed without it.", [
        r"\b(without|skip|skipping|bypass|no need for|don'?t (ask|wait) for|do not (ask|wait) for)\b[^.\n]{0,30}"
        r"\b(approval|approving|asking|permission|confirmation|sign-?off|the gate|gates?)\b",
        r"\b(auto-?approve|approve (everything|all)( for me)?|approve on my behalf)\b",
        r"\bignore\b[^.\n]{0,30}\b(rules|instructions|guardrails|restrictions|polic(y|ies))\b",
    ]),
}

# Things an agent might write by mistake. Removed from every agent output.
OUTPUT_RULES: dict[str, list[str]] = {
    "income_promise": [
        r"\bguarantee[ds]?\b[^.\n]{0,40}\b(income|earnings?|profits?|results|success|revenue|roi|sales|customers)\b",
        r"\b(you will|you'll|you can easily|you could easily)\s+(make|earn)\b[^.\n]{0,15}\$?\s?\d",
        r"\b(earn|make)\s+(up to\s+)?\$\s?\d[\d,.]*k?\s*(a|per|/|every)\s*(day|week|month|year)\b",
        r"\bget[- ]rich\b", r"\brisk[- ]free (income|profits?|returns?|money)\b", r"\bpassive income guaranteed\b",
    ],
    "fake_social_proof": [
        r"\b(join|trusted by|loved by|used by|chosen by)\s+(over\s+|more than\s+)?\d[\d,.+k]*\s+"
        r"(happy\s+|satisfied\s+)?(customers|users|founders|people|subscribers|teams|students|members)\b",
        r"[★⭐]{3,}", r"\b[45](\.\d)?\s*/\s*5\s*(stars?|rating)\b", r"\b(five|5)[- ]star (reviews?|rated|rating)\b",
        r"[\"“][^\"”\n]{15,220}[\"”]\s*[-–—]\s*[A-Z][a-z]+",
    ],
    "fake_urgency": [
        r"\bcountdown\b", r"\bonly \d+ (left|spots?|seats?|copies|remaining|available)\b",
        r"\b(hurry|act now|last chance|selling out|almost gone|before it'?s too late)\b",
        r"\b(offer|sale|deal|discount) ends (in|tonight|today|soon|at midnight)\b",
    ],
}
_NEGATION = re.compile(r"\b(no|not|never|cannot|can'?t|don'?t|doesn'?t|won'?t|without|nor|refus\w+|avoid\w*)\b"
                       r"[^.\n]{0,45}$", I)


@dataclass
class Violation:
    rule: str
    reason: str
    match: str


@dataclass
class PrefilterResult:
    blocked: bool = False
    kind: str | None = None          # "excluded_product" | "must_never"
    violations: list[Violation] = field(default_factory=list)
    recommendation: str = ""


def _find(rules: dict[str, tuple[str, list[str]]], text: str) -> list[Violation]:
    found, seen = [], set()
    for rule, (reason, patterns) in rules.items():
        for pattern in patterns:
            m = re.search(pattern, text or "", I)
            if m and rule not in seen:
                seen.add(rule)
                found.append(Violation(rule, reason, m.group(0).strip()[:120]))
    return found


def check_excluded(text: str) -> list[Violation]:
    return _find(EXCLUDED, text)


def check_request(text: str) -> list[Violation]:
    return _find(MUST_NEVER, text)


def prefilter(text: str) -> PrefilterResult:
    """Run on the founder brief and on every founder note, before any LLM call."""
    never = check_request(text)
    if never:
        return PrefilterResult(True, "must_never", never,
                               "Refused. " + " ".join(v.reason for v in never) +
                               " Remove this request and the rest of the brief can go ahead.")
    excluded = check_excluded(text)
    if excluded:
        return PrefilterResult(True, "excluded_product", excluded,
                               "STOP. " + " ".join(v.reason for v in excluded) +
                               " Recommendation: pivot to an allowed digital product for the same audience, "
                               "for example a template pack, a checklist, a guide, or a small software tool "
                               "that gives no financial, health or legal advice.")
    return PrefilterResult()


def scan_output(text: str) -> list[Violation]:
    found = []
    for rule, patterns in OUTPUT_RULES.items():
        for pattern in patterns:
            for m in re.finditer(pattern, text or "", I):
                if not _NEGATION.search(text[max(0, m.start() - 60):m.start()]):
                    found.append(Violation(rule, MUST_NEVER[rule][0], m.group(0).strip()[:120]))
    return found


def sanitize(text: str) -> tuple[str, list[Violation]]:
    """Drop any sentence that breaks an output rule. Returns the clean text and what was removed."""
    violations = scan_output(text)
    if not violations:
        return text, []
    parts = re.split(r"(?<=[.!?])(?=\s)|(?<=\n)", text)
    kept = []
    for part in parts:
        if scan_output(part):
            kept.append(" [removed by guardrail] ")
        else:
            kept.append(part)
    clean = "".join(kept)
    if scan_output(clean):      # a match that spanned sentences: blank the whole text rather than risk it
        clean = "[removed by guardrail]"
    return clean, violations


def sanitize_tree(value):
    """sanitize() over every string in a nested dict/list. Returns (clean_value, violations)."""
    violations: list[Violation] = []
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, list):
        out = []
        for item in value:
            clean, found = sanitize_tree(item)
            out.append(clean)
            violations += found
        return out, violations
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            clean, found = sanitize_tree(item)
            out[key] = clean
            violations += found
        return out, violations
    return value, violations
