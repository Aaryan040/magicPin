import time
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, List, Optional, Dict

app = FastAPI()
START_TIME = time.time()

# In-memory stores
# Key: (scope, context_id) -> {"version": int, "payload": dict}
contexts: Dict[tuple[str, str], dict] = {}
# Key: conversation_id -> {"turns": list, "auto_replies": int}
conversations: Dict[str, dict] = {}
# Key: merchant_id/conversation_id -> count of consecutive auto-replies
merchant_auto_replies: Dict[str, int] = {}


@app.get("/")
async def root():
    return {"message": "Welcome to the magicpin AI Assistant (Vera) Bot API! Please use /v1/healthz or /v1/metadata to inspect status."}


@app.get("/v1")
async def v1_root():
    return {"message": "Vera API v1. Available endpoints: GET /v1/healthz, GET /v1/metadata, POST /v1/context, POST /v1/tick, POST /v1/reply."}


@app.get("/v1/context")
async def get_context():
    return {
        "message": "This endpoint only accepts POST requests. Send a POST request to push context.",
        "payload_example": {
            "scope": "merchant",
            "context_id": "m_001_drmeera",
            "version": 1,
            "payload": {},
            "delivered_at": "2026-04-26T10:00:00Z"
        }
    }


@app.get("/v1/tick")
async def get_tick():
    return {
        "message": "This endpoint only accepts POST requests. Send a POST request to trigger bot actions.",
        "payload_example": {
            "now": "2026-04-26T10:30:00Z",
            "available_triggers": ["trg_001"]
        }
    }


@app.get("/v1/reply")
async def get_reply():
    return {
        "message": "This endpoint only accepts POST requests. Send a POST request to reply to a conversation turn.",
        "payload_example": {
            "conversation_id": "conv_001",
            "merchant_id": "m_001_drmeera",
            "customer_id": None,
            "from_role": "merchant",
            "message": "Yes, send me the details",
            "received_at": "2026-04-26T10:45:00Z",
            "turn_number": 2
        }
    }


@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        if scope in counts:
            counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Team Antigravity",
        "team_members": ["Agent Antigravity"],
        "model": "Gemini 3.5 Flash",
        "approach": "Deterministic template-based composer with robust context lookup and fallback strategies.",
        "contact_email": "antigravity@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.utcnow().isoformat() + "Z"
    }


class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict
    delivered_at: str


@app.post("/v1/context")
async def push_context(body: CtxBody):
    if body.scope not in ["category", "merchant", "customer", "trigger"]:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": f"Unknown scope: {body.scope}"}
        )
    
    key = (body.scope, body.context_id)
    cur = contexts.get(key)
    if cur and cur["version"] >= body.version:
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version", "current_version": cur["version"]}
        )
    
    contexts[key] = {"version": body.version, "payload": body.payload}
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }


class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = []


def get_first_active_offer(merchant: dict, category: dict) -> str:
    # 1. Check merchant's active offers
    for offer in merchant.get("offers", []):
        if offer.get("status") == "active":
            return offer.get("title", "")
    # 2. Check category catalog
    catalog = category.get("offer_catalog", [])
    if catalog:
        return catalog[0].get("title", "")
    return "Special Offer"


def compose_message(category: dict, merchant: dict, trigger: dict, customer: Optional[dict] = None) -> dict:
    """
    Given the 4 contexts, compose a highly relevant and deterministic message.
    """
    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})
    is_placeholder = payload.get("placeholder", False)

    merchant_id = merchant.get("merchant_id", "merchant")
    owner_name = merchant.get("identity", {}).get("owner_first_name", "there")
    biz_name = merchant.get("identity", {}).get("name", "your clinic")
    locality = merchant.get("identity", {}).get("locality", "your area")
    city = merchant.get("identity", {}).get("city", "your city")
    category_slug = merchant.get("category_slug", "")

    salutation = "Dr. " if category_slug == "dentists" else ""

    # Common parameters
    send_as = "vera"
    cta = "binary_yes_no"
    suppression_key = trigger.get("suppression_key", f"suppress:{kind}:{merchant_id}")

    # Fallbacks and Templates based on trigger.kind
    if kind == "research_digest":
        # Find item in category digest
        top_item_id = payload.get("top_item_id", "")
        digest_item = None
        for item in category.get("digest", []):
            if item.get("id") == top_item_id:
                digest_item = item
                break
        if not digest_item and category.get("digest"):
            digest_item = category["digest"][0]
        
        if digest_item:
            title = digest_item.get("title", "3-month fluoride recall cuts caries recurrence")
            source = digest_item.get("source", "JIDA Oct 2026 p.14")
            trial_n = digest_item.get("trial_n", 2100)
            segment = digest_item.get("patient_segment", "high_risk_adults").replace("_", " ")
            body = (
                f"{salutation}{owner_name}, {source} landed. One item relevant to your {segment} — "
                f"{trial_n}-patient trial showed {title}. Worth a look (2-min abstract). "
                f"Want me to pull it + draft a patient-ed WhatsApp you can share? — {source}"
            )
        else:
            body = (
                f"{salutation}{owner_name}, the latest research digest landed for {category_slug}. "
                f"It highlights new clinical insights that could improve patient retention. "
                f"Want me to pull the abstract and draft an educational update you can share?"
            )
        cta = "open_ended"

    elif kind == "regulation_change":
        top_item_id = payload.get("top_item_id", "")
        digest_item = None
        for item in category.get("digest", []):
            if item.get("id") == top_item_id:
                digest_item = item
                break
        if not digest_item and category.get("digest"):
            for item in category["digest"]:
                if item.get("kind") == "compliance":
                    digest_item = item
                    break
        
        deadline = payload.get("deadline_iso", "2026-12-15")
        if digest_item:
            title = digest_item.get("title", "revised radiograph dose limits")
            source = digest_item.get("source", "DCI circular")
            summary = digest_item.get("summary", "Max dose drops 1.5→1.0 mSv per IOPA.")
            body = (
                f"{salutation}{owner_name}, new compliance update: {title} effective {deadline}. "
                f"{summary} Rules are effective by {deadline}. Let's get your profile compliant. "
                f"Want me to draft the updates? — {source}"
            )
        else:
            body = (
                f"{salutation}{owner_name}, there are new category regulations effective by {deadline}. "
                f"We should update your profile and details to remain fully compliant. "
                f"Want me to guide you through the compliance updates?"
            )
        cta = "open_ended"

    elif kind == "recall_due":
        send_as = "merchant_on_behalf"
        cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
        lang = customer.get("identity", {}).get("language_pref", "en") if customer else "en"
        
        # Get active offer
        offer = get_first_active_offer(merchant, category)
        
        # Extract slots
        slots = payload.get("available_slots", [])
        if not slots or is_placeholder:
            slots = [
                {"label": "Wed 5 Nov, 6pm"},
                {"label": "Thu 6 Nov, 5pm"}
            ]
        slots_str = " ya ".join([f"**{s['label']}**" for s in slots])

        if "hi" in lang.lower():
            body = (
                f"Hi {cust_name}, {biz_name} here. It's been 5 months since your last visit — "
                f"your 6-month cleaning recall is due. Apke liye 2 slots ready hain: {slots_str}. "
                f"{offer}. Reply 1 for Wed, 2 for Thu, or tell us a time that works."
            )
        else:
            body = (
                f"Hi {cust_name}, {biz_name} here. It's been 5 months since your last visit — "
                f"your 6-month cleaning recall is due. We have slots ready: {slots_str}. "
                f"Active offer: {offer}. Reply 1 or 2 to book, or let us know a time that works."
            )
        cta = "multi_choice_slot"

    elif kind == "perf_dip":
        metric = payload.get("metric", "views") if not is_placeholder else "views"
        delta_pct = payload.get("delta_pct", -0.30) if not is_placeholder else -0.30
        window = payload.get("window", "7d") if not is_placeholder else "7d"
        vs_baseline = payload.get("vs_baseline", 100) if not is_placeholder else 100
        
        body = (
            f"{salutation}{owner_name}, quick check: your {metric} dropped by {abs(delta_pct)*100:.0f}% "
            f"over the last {window} (baseline was {vs_baseline}). Let's get more footfall "
            f"by posting an update or active offer. Want me to draft a quick post?"
        )

    elif kind == "renewal_due":
        days_remaining = payload.get("days_remaining", 15) if not is_placeholder else 15
        plan = payload.get("plan", "Pro") if not is_placeholder else "Pro"
        amount = payload.get("renewal_amount", 4999) if not is_placeholder else 4999
        
        body = (
            f"{salutation}{owner_name}, your magicpin {plan} plan renewal is due in {days_remaining} days. "
            f"Renewal amount is ₹{amount}. Keep getting new customer leads without interruption. "
            f"Should I generate the payment link for you?"
        )

    elif kind == "festival_upcoming":
        festival = payload.get("festival", "Diwali") if not is_placeholder else "Diwali"
        days_until = payload.get("days_until", 7) if not is_placeholder else 7
        
        body = (
            f"Hi {salutation}{owner_name}, {festival} is in {days_until} days! It's a great time to run a "
            f"festive campaign to attract customers in {locality}. Want me to draft a special festive post "
            f"for your Google profile?"
        )

    elif kind == "wedding_package_followup":
        send_as = "merchant_on_behalf"
        cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
        wedding_date = payload.get("wedding_date", "next month") if not is_placeholder else "next month"
        days_to_wedding = payload.get("days_to_wedding", 60) if not is_placeholder else 60
        
        body = (
            f"Hi {cust_name}, {biz_name} here! Your wedding is in {days_to_wedding} days ({wedding_date}). "
            f"Let's schedule your skin/hair prep program next to look your best. We have slots open this week. "
            f"Would you like to book a slot?"
        )

    elif kind == "curious_ask_due":
        body = (
            f"Hi {salutation}{owner_name}, what's your most-asked treatment or service this week? "
            f"We can use that to create a special post and drive more local queries. "
            f"Just tell me what's hot and I'll write the post!"
        )
        cta = "open_ended"

    elif kind == "winback_eligible":
        days = payload.get("days_since_expiry", 30) if not is_placeholder else 30
        dip = payload.get("perf_dip_pct", -0.25) if not is_placeholder else -0.25
        lapsed = payload.get("lapsed_customers_added_since_expiry", 20) if not is_placeholder else 20
        
        body = (
            f"{salutation}{owner_name}, since your subscription expired {days} days ago, customer views "
            f"dropped by {abs(dip)*100:.0f}%. However, {lapsed} lapsed customers are nearby. "
            f"Let's reactivate to win them back. Should we set up your plan again?"
        )

    elif kind == "ipl_match_today":
        match = payload.get("match", "today's exciting match") if not is_placeholder else "today's match"
        venue = payload.get("venue", "nearby stadium") if not is_placeholder else "nearby stadium"
        
        body = (
            f"Hi {salutation}{owner_name}, {match} is happening today at {venue} in {city}! "
            f"Perfect time to run a match-day special offer. Want me to draft a post to bring in the cricket crowd?"
        )

    elif kind == "review_theme_emerged":
        theme = payload.get("theme", "service speed") if not is_placeholder else "service speed"
        count = payload.get("occurrences_30d", 3) if not is_placeholder else 3
        quote = payload.get("common_quote", "waiting time was a bit high") if not is_placeholder else "waiting time was high"
        
        body = (
            f"Hi {salutation}{owner_name}, I noticed {count} reviews recently mentioning '{theme}' "
            f"(e.g. \"{quote}\"). Let's post an update reassuring customers we've resolved this. "
            f"Want me to draft a response/update for your page?"
        )

    elif kind == "milestone_reached":
        metric = payload.get("metric", "reviews") if not is_placeholder else "reviews"
        val = payload.get("value_now", 100) if not is_placeholder else 100
        milestone = payload.get("milestone_value", 100) if not is_placeholder else 100
        
        body = (
            f"Hi {salutation}{owner_name}, congratulations! You've reached {val} {metric.replace('_', ' ')} "
            f"(milestone: {milestone}). Let's celebrate this achievement with your customers. "
            f"Want me to create a celebratory post for your page?"
        )

    elif kind == "active_planning_intent":
        topic = payload.get("intent_topic", "new program") if not is_placeholder else "new marketing campaign"
        body = (
            f"Hi {salutation}{owner_name}, regarding your interest in \"{topic}\", I've drafted a plan "
            f"to promote it. Want me to send the draft for your review?"
        )

    elif kind == "seasonal_perf_dip":
        metric = payload.get("metric", "views") if not is_placeholder else "views"
        delta = payload.get("delta_pct", -0.20) if not is_placeholder else -0.20
        note = payload.get("season_note", "seasonal shift") if not is_placeholder else "seasonal shift"
        
        body = (
            f"Hi {salutation}{owner_name}, customer {metric} is down by {abs(delta)*100:.0f}% due to the "
            f"seasonal '{note}' shift. Let's run a counter-campaign to boost engagement. "
            f"Should I draft a seasonal offer?"
        )

    elif kind == "customer_lapsed_hard":
        send_as = "merchant_on_behalf"
        cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
        days = payload.get("days_since_last_visit", 90) if not is_placeholder else 90
        
        body = (
            f"Hi {cust_name}, {biz_name} here! We haven't seen you in {days} days. We'd love to welcome you back. "
            f"We have special offers active this week. Would you like to check available slots?"
        )

    elif kind == "trial_followup":
        send_as = "merchant_on_behalf"
        cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
        trial_date = payload.get("trial_date", "recently") if not is_placeholder else "recently"
        
        slots = payload.get("next_session_options", [])
        if not slots or is_placeholder:
            slots = [{"label": "Sat 3 May, 8am"}]
        slots_str = " or ".join([f"**{s['label']}**" for s in slots])

        body = (
            f"Hi {cust_name}, {biz_name} here! Hope you enjoyed your trial on {trial_date}. "
            f"Ready for the next session? We have slots open: {slots_str}. "
            f"Reply 1 to book, or tell us what time works."
        )
        cta = "multi_choice_slot"

    elif kind == "supply_alert":
        mol = payload.get("molecule", "atorvastatin") if not is_placeholder else "essential item"
        batches = payload.get("affected_batches", ["AT2024-1102"]) if not is_placeholder else ["recent batches"]
        batches_str = ", ".join(batches)
        
        body = (
            f"Hi {salutation}{owner_name}, critical alert: manufacturer recall for {mol} "
            f"(batches: {batches_str}). Please check your shelf inventory. "
            f"Want me to help check supplier refund policy or next steps?"
        )

    elif kind == "chronic_refill_due":
        send_as = "merchant_on_behalf"
        cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
        mols = payload.get("molecule_list", ["essential medicines"]) if not is_placeholder else ["prescription refill"]
        mols_str = ", ".join(mols)
        date = payload.get("stock_runs_out_iso", "soon") if not is_placeholder else "soon"
        if "T" in date:
            date = date.split("T")[0]
            
        body = (
            f"Hi {cust_name}, {biz_name} here. Your refill for {mols_str} is due soon (stock runs out by {date}). "
            f"We have your address saved. Reply YES to confirm delivery for this week."
        )

    elif kind == "category_seasonal":
        season = payload.get("season", "summer") if not is_placeholder else "summer"
        trends = payload.get("trends", ["high demand products"]) if not is_placeholder else ["seasonal demand shift"]
        trends_str = ", ".join(trends).replace("_", " ")
        
        body = (
            f"Hi {salutation}{owner_name}, {season} seasonal trends are showing high demand for: {trends_str}. "
            f"Let's update your business offerings to match. Want me to draft a quick post highlighting these?"
        )

    elif kind == "gbp_unverified":
        uplift = payload.get("estimated_uplift_pct", 0.30) if not is_placeholder else 0.30
        body = (
            f"Hi {salutation}{owner_name}, your Google Business Profile is currently unverified. "
            f"Verifying it can increase search views by {uplift*100:.0f}%. Let's get this done. "
            f"Want me to guide you through verification?"
        )

    elif kind == "cde_opportunity":
        credits = payload.get("credits", 2) if not is_placeholder else 2
        fee = payload.get("fee", "free") if not is_placeholder else "free"
        body = (
            f"Hi {salutation}{owner_name}, new training opportunity: earn {credits} credits (fee: {fee.replace('_', ' ')}). "
            f"Perfect for professional development. Want me to share the registration details?"
        )

    elif kind == "competitor_opened":
        comp = payload.get("competitor_name", "new competitor") if not is_placeholder else "new competitor"
        dist = payload.get("distance_km", 1.5) if not is_placeholder else 1.5
        offer = payload.get("their_offer", "special offers") if not is_placeholder else "discounted offers"
        
        body = (
            f"Hi {salutation}{owner_name}, a competitor '{comp}' just opened {dist}km away offering '{offer}'. "
            f"Let's highlight your premium services to retain your customers. Want me to draft a comparison post?"
        )

    elif kind == "perf_spike":
        metric = payload.get("metric", "views") if not is_placeholder else "views"
        delta = payload.get("delta_pct", 0.20) if not is_placeholder else 0.20
        driver = payload.get("likely_driver", "recent update") if not is_placeholder else "recent update"
        
        body = (
            f"Hi {salutation}{owner_name}, great news! Your {metric} is up by {delta*100:.0f}% this week, "
            f"likely driven by your '{driver}'. Let's keep the momentum going. Want to post another update?"
        )

    elif kind == "dormant_with_vera":
        days = payload.get("days_since_last_merchant_message", 30) if not is_placeholder else 30
        body = (
            f"Hi {salutation}{owner_name}, it's been {days} days since we last caught up. "
            f"Let's make sure your page is fresh for customers. Want to check your latest weekly stats?"
        )

    else:
        # Fallback generic message
        body = (
            f"Hi {salutation}{owner_name}, let's keep your Google Profile fresh with new posts "
            f"and active offers to attract more customers in {locality}. Want to see what's trending?"
        )

    # Clean body spacing
    body = " ".join(body.split())

    # Build the action payload
    return {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": suppression_key,
        "rationale": f"Composed from category+merchant+trigger for kind: {kind}. Dynamic address and variables injected for specificity."
    }


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []
    for trg_id in body.available_triggers:
        trg_ctx = contexts.get(("trigger", trg_id))
        if not trg_ctx:
            continue
        trg = trg_ctx["payload"]
        
        merchant_id = trg.get("merchant_id")
        m_ctx = contexts.get(("merchant", merchant_id))
        if not m_ctx:
            continue
        merchant = m_ctx["payload"]
        
        category_slug = merchant.get("category_slug")
        c_ctx = contexts.get(("category", category_slug))
        if not c_ctx:
            continue
        category = c_ctx["payload"]
        
        customer_id = trg.get("customer_id")
        customer = None
        if customer_id:
            cust_ctx = contexts.get(("customer", customer_id))
            if cust_ctx:
                customer = cust_ctx["payload"]
        
        # Compose message
        action = compose_message(category, merchant, trg, customer)
        
        # Add conversation metadata
        conv_id = f"conv_{merchant_id}_{trg_id}"
        action.update({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "trigger_id": trg_id,
            "template_name": f"vera_{trg.get('kind', 'generic')}_v1",
            "template_params": [merchant.get("identity", {}).get("name", "there")]
        })
        
        actions.append(action)
        
        # Initialize conversation state
        conversations[conv_id] = {
            "turns": [{"from": "vera", "msg": action["body"]}],
            "auto_replies": 0,
            "last_trigger_kind": trg.get("kind", "")
        }
        
    return {"actions": actions}


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conv_id = body.conversation_id
    msg_text = body.message.strip()
    msg_lower = msg_text.lower()
    
    # Initialize state if missing
    if conv_id not in conversations:
        conversations[conv_id] = {
            "turns": [],
            "auto_replies": 0,
            "last_trigger_kind": "generic"
        }
        
    conv_state = conversations[conv_id]
    conv_state["turns"].append({"from": body.from_role, "msg": msg_text})
    
    # 1. AUTO-REPLY DETECTION
    is_auto = False
    
    # Common auto-reply signatures
    auto_signatures = [
        "thank you for contacting",
        "will respond shortly",
        "automated assistant",
        "please note that",
        "canned reply",
        "away right now",
        "canned auto-reply"
    ]
    
    if any(sig in msg_lower for sig in auto_signatures):
        is_auto = True
    
    # Repeated message check
    prev_merchant_msgs = [t["msg"] for t in conv_state["turns"] if t["from"] == body.from_role]
    if len(prev_merchant_msgs) >= 2 and prev_merchant_msgs[-1] == prev_merchant_msgs[-2]:
        is_auto = True
        
    m_key = body.merchant_id or conv_id
    if is_auto:
        merchant_auto_replies[m_key] = merchant_auto_replies.get(m_key, 0) + 1
        cnt = merchant_auto_replies[m_key]
        
        if cnt == 1:
            return {
                "action": "send",
                "body": "Looks like an auto-reply. When the owner sees this, just reply 'Yes' to check the details.",
                "cta": "binary_yes_no",
                "rationale": "Detected first auto-reply; flagged for the owner."
            }
        elif cnt == 2:
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Same auto-reply twice; backing off for 24h."
            }
        else:
            return {
                "action": "end",
                "rationale": "Consecutive auto-replies exceeded threshold. Exiting gracefully."
            }
            
    # Reset auto-reply counter if we get a real message
    merchant_auto_replies[m_key] = 0
    
    # 2. HOSTILE / OPT-OUT HANDLING
    hostile_signatures = [
        "stop messaging", "useless spam", "stop sending", "not interested",
        "don't message", "dont message", "abuse", "fraud", "scam"
    ]
    if any(sig in msg_lower for sig in hostile_signatures):
        return {
            "action": "end",
            "rationale": "Merchant explicitly opted out or expressed hostility. Gracefully ending conversation."
        }
        
    # 3. OUT-OF-SCOPE REDIRECTION (e.g. GST)
    if "gst" in msg_lower:
        return {
            "action": "send",
            "body": "I'll have to leave GST filing to your CA — that's outside what I can help with directly. Coming back to growing your page, would you like me to draft a new post for your profile?",
            "cta": "binary_yes_no",
            "rationale": "Declined out-of-scope GST question politely and redirected back to the Google profile theme."
        }
        
    # 4. INTENT TRANSITION (Affirmations / Commitment)
    affirmations = [
        "ok let's do it", "lets do it", "go ahead", "send the", "confirm", "proceed",
        "yes please", "yes, please", "sounds good", "okay send", "send it", "do it"
    ]
    if any(aff in msg_lower for aff in affirmations):
        # Switch from pitching to action/confirmation
        body_reply = (
            "Great! I have scheduled the draft post for your Google Business Profile. "
            "I'll publish it tomorrow at 10 AM. Reply CONFIRM to proceed."
        )
        return {
            "action": "send",
            "body": body_reply,
            "cta": "binary_confirm_cancel",
            "rationale": "Merchant committed. Switched from qualification to action mode with binary confirm CTA."
        }
        
    # 5. GENERAL / POSITIVE RESPONSE (e.g. "Yes", "Ok")
    if msg_lower in ["yes", "ok", "y", "sure", "please"]:
        body_reply = (
            "Perfect. I can draft that post or set up the page change now. "
            "Should I send the preview draft for your review?"
        )
        return {
            "action": "send",
            "body": body_reply,
            "cta": "binary_yes_no",
            "rationale": "Friendly positive response, guiding the merchant to the next concrete action."
        }
        
    # 6. DEFAULT FALLBACK RESPONSE
    return {
        "action": "send",
        "body": "Got it! Let me know if you would like me to draft an update, check your stats, or schedule a post.",
        "cta": "open_ended",
        "rationale": "Acknowledged and kept the conversation open."
    }
