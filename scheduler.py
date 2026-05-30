"""
Background scheduler — distributes 2% daily profit to all active investments.
Called once from app.py on startup (gunicorn safe: only starts in main worker).
"""
import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
_scheduler = None


def distribute_daily_profits():
    """
    Pays 2% daily profit for every active investment whose last_profit_date
    is either NULL or older than 24 hours. Prevents duplicate payments.
    """
    try:
        from utils.supabase_client import get_admin_supabase
        db  = get_admin_supabase()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        result = db.table('investments').select('*').eq('status', 'active').execute()
        investments = result.data or []

        paid = 0
        for inv in investments:
            last_paid = inv.get('last_profit_date')
            if last_paid:
                last_paid_dt = datetime.fromisoformat(last_paid.replace('Z', '+00:00'))
                if last_paid_dt > cutoff:
                    continue  # Already paid within 24h — skip

            profit  = round(inv['amount'] * 0.02, 2)
            user_id = inv['user_id']

            profile_res = db.table('profiles').select('balance').eq('id', user_id).single().execute()
            if not profile_res.data:
                continue

            new_balance = round(profile_res.data['balance'] + profit, 2)

            db.table('profiles').update({'balance': new_balance}).eq('id', user_id).execute()
            db.table('investments').update({
                'last_profit_date': now.isoformat(),
                'total_earned': round((inv.get('total_earned') or 0) + profit, 2)
            }).eq('id', inv['id']).execute()
            db.table('transactions').insert({
                'user_id':     user_id,
                'type':        'daily_profit',
                'amount':      profit,
                'description': f"Daily 2% profit on ${inv['amount']} ({inv.get('plan_name','Plan')})",
                'status':      'completed',
                'created_at':  now.isoformat()
            }).execute()

            paid += 1

        logger.info(f"[Scheduler] Daily profits distributed to {paid} investment(s).")

    except Exception as e:
        logger.error(f"[Scheduler] Error in daily profit job: {e}")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return  # Already running (avoid double-start in reload)

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        distribute_daily_profits,
        trigger='interval',
        hours=24,
        id='daily_profits',
        replace_existing=True,
        next_run_time=datetime.now()
    )
    _scheduler.start()
    logger.info("[Scheduler] Daily profit scheduler started.")
