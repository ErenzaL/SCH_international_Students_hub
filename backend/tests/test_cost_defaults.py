"""Final release: the default AI caps fit a small Gemini budget (about US$0.012 per generated answer)."""
from app.core.config import Settings


def test_default_daily_caps_stay_small() -> None:
    s = Settings(_env_file=None)
    assert s.ai_daily_limit_global <= 60          # ≈ US$0.70 / day at most at the standard 3.6 Flash price
    assert s.ai_daily_limit_per_user <= 20 and s.ai_daily_limit_per_client <= 10
    assert s.llm_max_attempts_per_model <= 2      # bounded retries, no unbounded escalation
    assert s.auto_translate_announcements is False and s.agent_schedules_enabled is False and s.gpu_worker_enabled is False
