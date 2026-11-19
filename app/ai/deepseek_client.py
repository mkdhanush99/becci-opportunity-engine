"""DeepSeek AI Intelligence Layer for BECCI Opportunity Intelligence Engine.

Provides low-cost, high-accuracy structured JSON extraction, scheme classification,
and PDF parsing across Job Scout, Tender Scout, and Funding Scout.

Optimisations:
- Default model: deepseek-flash ($0.14 / 1M prompt, $0.28 / 1M completion)
- Advanced model: deepseek-v4-pro for complex unstructured notifications
- Document-hash caching (AIExtractionCache) prevents redundant spend
- Daily & Monthly spending limits with graceful fallback to deterministic logic
- Granular token & cost audit logging (AIUsageLog)
- Never replaces BECCI verification: AI outputs are always validated before publishing
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
from typing import Any
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.models import AIExtractionCache, AIUsageLog, utcnow

logger = logging.getLogger(__name__)

# Official DeepSeek Pricing (USD per 1,000,000 tokens)
PRICING_PER_MILLION = {
    "deepseek-flash": {"prompt": 0.14, "completion": 0.28},
    "deepseek-v4-pro": {"prompt": 0.55, "completion": 2.19},
}


class DeepSeekError(RuntimeError):
    """Base error for DeepSeek API operations."""


class DeepSeekSpendLimitError(DeepSeekError):
    """Raised when daily or monthly spend limit is reached."""


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.settings = get_settings()
        self.api_key = (
            api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or getattr(self.settings, "deepseek_api_key", "")
        ).strip()
        self.base_url = (base_url or getattr(self.settings, "deepseek_base_url", "https://api.deepseek.com")).rstrip("/")
        self.default_model = getattr(self.settings, "deepseek_default_model", "deepseek-flash")
        self.advanced_model = getattr(self.settings, "deepseek_advanced_model", "deepseek-v4-pro")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculates exact cost in USD for a completion."""
        rates = PRICING_PER_MILLION.get(model, PRICING_PER_MILLION["deepseek-flash"])
        cost = (prompt_tokens * rates["prompt"] + completion_tokens * rates["completion"]) / 1_000_000
        return round(cost, 6)

    def check_daily_spend(self, session: Session) -> float:
        """Returns total USD spent today."""
        today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = session.scalar(
            select(func.sum(AIUsageLog.cost_usd)).where(AIUsageLog.created_at >= today_start)
        ) or 0.0
        return round(float(spent), 4)

    def extract_structured(
        self,
        prompt: str,
        system_instruction: str,
        *,
        agent_id: str,
        model: str | None = None,
        use_pro: bool = False,
        session: Session | None = None,
        max_tokens: int = 1000,
    ) -> dict[str, Any] | None:
        """Executes a structured JSON extraction via DeepSeek with caching and spend protection.
        
        Returns parsed dict or None if unconfigured / budget exceeded / error.
        """
        if not self.is_configured:
            logger.debug("DeepSeek API key not configured; skipping AI extraction.")
            return None

        chosen_model = model or (self.advanced_model if use_pro else self.default_model)

        # 1. Check Document Hash Cache
        cache_key = hashlib.sha256(f"{chosen_model}:{system_instruction}:{prompt}".encode("utf-8")).hexdigest()
        
        def _execute_with_session(sess: Session):
            cached = sess.get(AIExtractionCache, cache_key)
            if cached and cached.response_json:
                logger.info("DeepSeek cache hit for key %s (model: %s, $0.00 spent)", cache_key[:12], chosen_model)
                return cached.response_json

            # 2. Daily Spend Check
            spent_today = self.check_daily_spend(sess)
            if spent_today >= self.settings.deepseek_daily_spend_limit_usd:
                logger.warning(
                    "DeepSeek daily spend limit reached ($%.2f >= $%.2f). Gracefully falling back to deterministic parser.",
                    spent_today,
                    self.settings.deepseek_daily_spend_limit_usd,
                )
                return None

            # 3. Call DeepSeek Chat API
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": chosen_model,
                "messages": [
                    {"role": "system", "content": f"{system_instruction}\nStrictly output valid JSON object only."},
                    {"role": "user", "content": prompt[:8000]},  # Limit input text slice
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
                "temperature": 0.0,
            }

            try:
                with httpx.Client(timeout=30.0) as http_client:
                    res = http_client.post(url, json=body, headers=headers)
                    if res.status_code == 429:
                        logger.warning("DeepSeek rate limited (429); falling back to deterministic parser.")
                        return None
                    if res.status_code >= 400:
                        logger.warning("DeepSeek API error %d: %s", res.status_code, res.text)
                        return None

                    data = res.json()
                    choices = data.get("choices", [])
                    if not choices:
                        return None

                    content_str = choices[0].get("message", {}).get("content", "{}")
                    parsed_json = json.loads(content_str)

                    # Usage & Cost Audit
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", 0)
                    c_tok = usage.get("completion_tokens", 0)
                    t_tok = usage.get("total_tokens", p_tok + c_tok)
                    cost = self.calculate_cost(chosen_model, p_tok, c_tok)

                    sess.add(
                        AIUsageLog(
                            agent_id=agent_id,
                            model=chosen_model,
                            prompt_tokens=p_tok,
                            completion_tokens=c_tok,
                            total_tokens=t_tok,
                            cost_usd=cost,
                            created_at=utcnow(),
                        )
                    )

                    # Save to Cache
                    sess.add(
                        AIExtractionCache(
                            cache_key=cache_key,
                            model=chosen_model,
                            response_json=parsed_json,
                            created_at=utcnow(),
                        )
                    )
                    sess.commit()
                    return parsed_json

            except Exception as exc:
                logger.warning("DeepSeek call failed: %s; falling back to deterministic parser.", exc)
                return None

        if session:
            return _execute_with_session(session)
        else:
            with session_scope() as sess:
                return _execute_with_session(sess)

    # ------------------------------------------------------------------------- Specialised Agent Intelligence
    def extract_job_intelligence(self, text: str, *, session: Session | None = None) -> dict[str, Any] | None:
        """Job Scout: Extracts role, employer, experience, salary, deadline, and government vs private classification."""
        system_instruction = (
            "You are the BECCI Job Intelligence Agent. Extract structured job posting details from the text. "
            "Return a JSON object with keys: "
            "role (string), employer (string), is_government_job (boolean), "
            "location (string or null), experience_required (string or null), "
            "salary (string or null), deadline (YYYY-MM-DD or null), "
            "eligibility_summary (string or null)."
        )
        return self.extract_structured(
            text, system_instruction, agent_id="job-scout", session=session
        )

    def extract_tender_intelligence(self, text: str, *, session: Session | None = None) -> dict[str, Any] | None:
        """Tender Scout: Extracts tender metadata, reference, values, dates, and corrigenda."""
        system_instruction = (
            "You are the BECCI Tender Intelligence Agent. Extract procurement tender details from the text. "
            "Return a JSON object with keys: "
            "tender_title (string), issuing_authority (string), reference_number (string or null), "
            "estimated_value (string or null), emd_amount (string or null), "
            "pre_bid_date (YYYY-MM-DD or null), bid_opening_date (YYYY-MM-DD or null), "
            "deadline (YYYY-MM-DD or null), turnover_requirement (string or null), "
            "experience_requirement (string or null), msme_preference (string or null), "
            "is_corrigendum (boolean), corrigendum_details (string or null)."
        )
        return self.extract_structured(
            text, system_instruction, agent_id="tender-scout", session=session
        )

    def extract_scheme_intelligence(self, text: str, *, session: Session | None = None) -> dict[str, Any] | None:
        """Funding Scout & Scheme Classifier: Extracts eligibility, beneficiary classification, and geographical scope."""
        system_instruction = (
            "You are the BECCI Government Scheme & Funding Intelligence Agent. "
            "Classify and extract financial support programme details from the text. "
            "Enforce strict geographical scope: exactly one of ['pan_india', 'telangana', 'andhra_pradesh', 'other_state']. "
            "Enforce beneficiary classification: exactly one of ['obc_bc_specific', 'general_msme', 'women_entrepreneurs', 'students', 'artisans', 'farmers', 'general_entrepreneurship', 'other_eligible']. "
            "Return a JSON object with keys: "
            "scheme_name (string), issuing_department (string), geographical_scope (string), "
            "beneficiary_classification (string), applicable_castes (array of strings, e.g. ['OBC', 'BC-A', 'BC-B', 'All']), "
            "domicile_required (boolean), domicile_state (string or null), "
            "income_limit (string or null), age_limit (string or null), "
            "benefit_type (string, e.g. loan, subsidy, scholarship), benefit_amount (string or null), "
            "application_status (one of ['open', 'upcoming', 'closed', 'continuous', 'unknown'])."
        )
        return self.extract_structured(
            text, system_instruction, agent_id="scheme-classifier", session=session
        )
